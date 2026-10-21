"""Plot engine phase 1: the fact ledger and its knowledge gate, the main-line beats bound to real events, and continuity."""
from __future__ import annotations

import copy
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from worldstage.agent.volition import VolitionDecider
from worldstage.narrative import plot_continuity as PC
from worldstage.narrative.dialogue import NARRATOR, LLMWriter, OfflineWriter
from worldstage.narrative.ledger import FactLedger, KnowledgeGate
from worldstage.producer.director import Director
from worldstage.producer.plot import episodes, write_all
from worldstage.producer.spine import BEATS, EPISODE_DAYS, SpineDirector, fulfil
from worldstage.world.db import connect, init_db
from worldstage.world.seed import build_world
from worldstage.world.simulation import Simulation


def binds(spine):
    return {bid: {"event_id": b.event_id, "episode": b.beat.episode, "must_hit": b.beat.must_hit} for bid, b in spine.bindings.items()}


class PlotEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="plot_p1_"))
        db = cls.tmp / "world.db"
        c = connect(str(db))
        init_db(c, 701)
        build_world(c, 701, "jianghu_drama_v1")
        d = VolitionDecider(701)
        cls.director = SpineDirector("greedy", 701)
        Simulation(c, d, d, set(), feed="synthetic_v1", producer=cls.director).run(3 * EPISODE_DAYS)
        c.close()
        cls.conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cls.ledger = FactLedger(cls.conn)
        cls.gate = KnowledgeGate(cls.ledger)
        cls.spine = fulfil(cls.conn, BEATS, EPISODE_DAYS)
        cls.eps = episodes(cls.ledger, cls.spine, 3, EPISODE_DAYS)
        write_all(cls.ledger, cls.eps, OfflineWriter())

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- the ledger and the gate ---------------------------------------------------------------------------------------
    def test_knowing_is_read_from_the_worlds_memories(self):
        L = self.ledger
        for f in list(L.facts.values())[:300]:
            if f.actor:
                self.assertTrue(L.knows(f.actor, f.fact_id, f.ts))
            for p in L.names:
                if p not in f.participants and L.knows(p, f.fact_id, f.ts + 10 ** 7):
                    row = self.conn.execute("SELECT 1 FROM memories WHERE observer_id = ? AND (event_id = ? OR about_event_id = ?)",
                                            (p, f.fact_id, f.fact_id)).fetchone()
                    self.assertIsNotNone(row, (p, f.fact_id))

    def test_somebody_who_was_not_there_does_not_know_until_told(self):
        L = self.ledger
        cases = 0
        for f in L.facts.values():
            for (p,) in self.conn.execute("SELECT person_id FROM event_participants WHERE event_id = ? AND role = 'victim'", (f.fact_id,)):
                saw = self.conn.execute("SELECT 1 FROM memories WHERE observer_id = ? AND event_id = ?", (p, f.fact_id)).fetchone()
                if saw is None:
                    cases += 1
                    self.assertFalse(L.knows(p, f.fact_id, f.ts))
        people = sorted(L.names.keys() & set(L.knowing))
        # and in general: nobody knows everything
        self.assertTrue(all(len(L.knowing[p]) < len(L.facts) for p in people))
        self.assertGreaterEqual(cases + len(people), 1)

    def test_the_gate_refuses_an_unknown_fact_a_future_one_and_quoted_words(self):
        L, g = self.ledger, self.gate
        f = next(x for x in L.facts.values() if x.claim_text and len(x.claim_text) >= 5 and len(L.who_knows(x.fact_id, x.ts + 1440)) < len(L.names) - 1)
        outsider = next(p for p in sorted(L.names) if p in L.knowing and not L.knows(p, f.fact_id, f.ts + 1440)
                        and f.claim_text not in " ".join(k.belief for k in L.knowing[p].values()))
        at = f.ts + 1440
        self.assertEqual([v.code for v in g.check_line(outsider, "我聽說了。", [f.fact_id], at)], ["K1"])
        self.assertEqual([v.code for v in g.check_line(f.actor, "那件事。", [f.fact_id], f.ts - 1)], ["K2"])
        self.assertIn("K3", [v.code for v in g.check_line(outsider, f"你知道嗎？{f.claim_text}。", [], at)])
        self.assertEqual(g.check_line(f.actor, f"你知道嗎？{f.claim_text}。", [f.fact_id], at), [])

    def test_a_line_cannot_name_a_thing_none_of_its_facts_holds(self):
        L, g = self.ledger, self.gate
        f = next(x for x in L.facts.values() if x.actor and not any(o in x.summary + x.claim_text for o in L.object_names))
        thing = sorted(L.object_names)[0]
        self.assertIn("K6", [v.code for v in g.check_line(f.actor, f"這{thing}你收下。", [f.fact_id], f.ts)])
        holder = next((x for x in L.facts.values() if x.actor and thing in x.summary + x.claim_text), None)
        if holder is not None:
            self.assertNotIn("K6", [v.code for v in g.check_line(holder.actor, f"那{thing}的事。", [holder.fact_id], holder.ts)])

    def test_every_act_of_the_world_stood_on_what_its_actor_knew(self):
        bad = [v for f in self.ledger.facts.values() if f.actor for v in self.gate.check_act(f.actor, f)]
        self.assertEqual(bad, [])

    def test_the_llm_writer_is_gated_before_a_scene_is_accepted(self):
        L = self.ledger
        card = next(c for ep in self.eps for c in ep["scenes"] if len(c.cast) >= 2)
        unknown = next(f for f in L.facts.values() if f.ts <= card.ts and not L.knows(card.pov, f.fact_id, card.ts))
        leak = {"lines": [{"speaker": card.pov, "text": "我知道那件事。", "uses": [unknown.fact_id], "kind": "say"}]}
        good = {"lines": [{"speaker": card.pov, "text": "……", "uses": [card.anchor] if L.knows(card.pov, card.anchor, card.ts) else [],
                           "kind": "say"}]}

        class Fake:
            def __init__(self, answers):
                self.answers, self.calls = list(answers), 0

            def generate_json(self, prompt, schema, temperature=0.8):
                self.calls += 1
                return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

        w = LLMWriter(Fake([leak, good]))
        lines = w.write(L, card, self.gate)
        self.assertEqual(lines[0]["speaker"], NARRATOR)
        self.assertEqual(lines[1:], good["lines"])
        self.assertEqual(len(w.rejected), 1)
        w2 = LLMWriter(Fake([leak]))                       # it never learns: the offline writer takes the scene
        lines2 = w2.write(L, card, self.gate)
        self.assertEqual(len(w2.rejected), 2)
        self.assertEqual(lines2, OfflineWriter().write(L, card, self.gate))
        absent = next(p for p in sorted(L.names) if p in L.knowing and p not in card.cast)
        w3 = LLMWriter(Fake([{"lines": [{"speaker": absent, "text": "我也在。", "uses": [], "kind": "say"}]}]))
        w3.write(L, card, self.gate)
        self.assertIn("不在場", w3.rejected[0]["why"][0])

    # -- the main line -------------------------------------------------------------------------------------------------
    def test_every_beat_maps_to_a_real_event_of_its_episode(self):
        for bid, b in self.spine.bindings.items():
            if b.event_id is None:
                self.assertFalse(b.beat.must_hit, bid)
                continue
            row = self.conn.execute("SELECT type, timestamp FROM events WHERE event_id = ?", (b.event_id,)).fetchone()
            self.assertIsNotNone(row, bid)
            self.assertIn(row[0], b.beat.types)
            self.assertEqual(row[1] // 1440 // EPISODE_DAYS + 1, b.beat.episode, bid)

    def test_a_lines_later_beats_share_its_cast(self):
        first = {}
        for bid, b in sorted(self.spine.bindings.items(), key=lambda kv: kv[1].beat.episode):
            if b.event_id is None:
                continue
            if b.beat.line in first:
                self.assertTrue(set(b.cast) & first[b.beat.line], bid)
                first[b.beat.line] |= set(b.cast)
            else:
                first[b.beat.line] = set(b.cast)

    def test_the_spine_only_reorders_what_the_director_would_weigh(self):
        self.assertTrue(all(p[2] in {b.pull for b in BEATS} for p in self.director.pulls))
        plain = Director("greedy", 701)
        d = SpineDirector("greedy", 701)
        c = connect()
        init_db(c, 3)
        build_world(c, 3, "jianghu_drama_v1")
        from worldstage.narrative import opportunity as O
        ops = O.detect(c, 0)
        self.assertEqual(sorted(o.opportunity_id for o in d._ranked(c, ops, 0)), sorted(o.opportunity_id for o in plain._ranked(c, ops, 0)))

    # -- episodes and continuity ---------------------------------------------------------------------------------------
    def test_three_episodes_two_lines_two_povs_and_no_severe_issue(self):
        self.assertEqual(len(self.eps), 3)
        for ep in self.eps:
            self.assertGreaterEqual(len({c.line for c in ep["scenes"]}), 2)
            self.assertGreaterEqual(len({c.pov for c in ep["scenes"]}), 2)
            for c in ep["scenes"]:
                self.assertTrue(c.question and c.turn["before"] != c.turn["after"])
        issues = PC.check(self.ledger, self.eps, binds(self.spine), EPISODE_DAYS)
        self.assertEqual([i for i in issues if i.severity == "severe"], [])

    def test_continuity_catches_absence_order_knowledge_and_beats(self):
        L = self.ledger
        eps = copy.deepcopy(self.eps)
        ep = eps[1]
        c = ep["scenes"][0]
        absent = next(p for p in sorted(L.names) if p in L.knowing and p not in c.cast)
        c.lines.append({"speaker": absent, "text": "……", "uses": [], "kind": "say"})
        later = max(L.facts.values(), key=lambda f: f.ts)
        c.lines.append({"speaker": c.pov, "text": "……", "uses": [later.fact_id], "kind": "say"})
        ep["scenes"].reverse()
        b = binds(self.spine)
        some = next(k for k, v in b.items() if v["event_id"] is not None and v["must_hit"])
        b[some] = dict(b[some], event_id=None)
        other = next(k for k, v in b.items() if v["event_id"] is not None and k != some)
        b[other] = dict(b[other], episode=b[other]["episode"] % 3 + 1)
        codes = {i.code for i in PC.check(L, eps, b, EPISODE_DAYS) if i.severity == "severe"}
        self.assertLessEqual({"P1", "K2", "T1", "B1", "B2"}, codes)


if __name__ == "__main__":
    unittest.main()
