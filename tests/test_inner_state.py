"""Inner state: what somebody shows and what is underneath it. A read model: every reading traces to records of the world,
nothing is said without one, and reading it changes nothing."""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from unittest import mock

from narrative import inner_state as I
from narrative import speech as S
from world.db import connect, init_db, mutation
from world.seed import build_world

SOURCE = Path(I.__file__)


def _speakers(c):
    """(event_id, type, actor, target, truth) of every event somebody could say something at."""
    for r in c.execute("SELECT event_id, type, truth FROM events WHERE type != 'day_end' ORDER BY event_id").fetchall():
        t = json.loads(r["truth"])
        if t.get("actor"):
            yield r["event_id"], r["type"], t["actor"], t.get("target") or t.get("victim") or "", t


class InAWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agent.volition import VolitionDecider
        from producer.director import Director
        from runtime.godview import _names
        from world.simulation import Simulation
        cls.c = connect()
        init_db(cls.c, 612)
        build_world(cls.c, 612, "jianghu_story_v1")
        d = VolitionDecider(612)
        Simulation(cls.c, d, d, set(), feed="synthetic_v1", producer=Director("greedy", 612)).run(14)
        cls.names = _names(cls.c)
        cls.readings = [(eid, who, to, I.inner_state(cls.c, who, eid, cls.names)) for eid, _, who, to, _ in _speakers(cls.c)]
        cls.found = [(eid, who, to, st) for eid, who, to, st in cls.readings if st]

    def test_there_are_readings_to_check(self):
        self.assertGreater(len(self.found), 30)
        self.assertGreater(len({st["rule"] for _, _, _, st in self.found}), 5)

    def test_every_reading_is_in_the_records(self):
        for eid, who, _, st in self.found:
            self.assertEqual(I.verify(self.c, st), [], (eid, who, st["rule"]))

    def test_every_cause_is_a_real_event_before_the_line_that_the_person_took_part_in(self):
        for eid, who, _, st in self.found:
            cause = st["because"]["event_id"]
            self.assertLess(cause, eid)
            self.assertTrue(self.c.execute("SELECT 1 FROM event_participants WHERE event_id = ? AND person_id = ?", (cause, who)).fetchone())
            self.assertTrue(st["because"]["text"])
            self.assertTrue(any(e["kind"] == "event" and e["event_id"] == cause for e in st["evidence"]))

    def test_the_feeling_it_explains_is_the_one_the_person_has(self):
        from narrative.audience import value_at
        for eid, who, _, st in self.found:
            self.assertEqual(value_at(self.c, "person", who, "emotion", eid - 1), st["surface"])
            self.assertEqual(st["surface_zh"], I.EMOTION_ZH[st["surface"]])

    def test_the_lines_it_hangs_on_are_the_lines_speech_always_gives(self):
        self.assertEqual(set(I.ALONE) - set(S.SELF), set())
        self.assertEqual(set(I.SPEECH_TYPES) & set(S.SELF), set())
        self.assertEqual(I.ALONE_EVERY, {k: v for k, v in S.SELF_RARE.items() if k in I.ALONE})     # the lines speech leaves silent

    def test_a_calm_person_has_nothing_underneath(self):
        from narrative.audience import value_at
        calm = [(eid, who) for eid, _, who, _, _ in _speakers(self.c) if value_at(self.c, "person", who, "emotion", eid - 1) == "calm"]
        self.assertTrue(calm)
        for eid, who in calm[:200]:
            self.assertIsNone(I.inner_state(self.c, who, eid, self.names))

    def test_the_same_world_reads_the_same(self):
        again = [(eid, who, to, I.inner_state(self.c, who, eid, self.names)) for eid, _, who, to, _ in _speakers(self.c)]
        self.assertEqual(again, self.readings)

    def test_it_only_reads(self):
        def fingerprint():
            return (self.c.execute("SELECT COUNT(*), SUM(LENGTH(truth)) FROM events").fetchone()[:],
                    self.c.execute("SELECT COUNT(*), SUM(delta_id) FROM event_deltas").fetchone()[:],
                    self.c.execute("SELECT SUM(trust + affection + resentment + fear) FROM relationships").fetchone()[0],
                    self.c.total_changes)
        before = fingerprint()
        for eid, _, who, to, _ in _speakers(self.c):
            I.inner_subtext(self.c, who, eid, to, self.names)
            S.speak(self.c, eid, "talk", {"actor": who, "target": to, "tone": "cold"}, self.names)
        self.assertEqual(fingerprint(), before)

    def test_a_reading_is_said_once_and_again_to_the_person_it_is_about_never_more(self):
        said = {}
        for eid, etype, who, to, _ in _speakers(self.c):
            if etype not in I.VOICED_ON:
                continue
            st = I.inner_subtext(self.c, who, eid, "" if etype in I.ALONE else to, self.names)
            if st:
                said.setdefault((who, st["because"]["event_id"]), []).append((eid, to, st["other"]))
        self.assertTrue(said)
        for key, lines in said.items():
            self.assertLessEqual(len(lines), 2, key)
            if len(lines) == 2:
                self.assertEqual(lines[1][1], lines[1][2], key)       # the second time is to the person it is about

    def test_nothing_unsure_is_said_but_it_is_still_in_the_read_model(self):
        eid, who, to, st = next((e, w, t, s) for e, w, t, s in self.found if I.inner_subtext(self.c, w, e, t, self.names))
        weak = I._r("說不準", "weak", SAY_BELOW, "x", {"kind": "event", "event_id": st["because"]["event_id"], "type": st["because"]["type"]})
        with mock.patch.dict(I.RULES, {st["because"]["type"]: lambda k: weak}):
            self.assertIsNotNone(I.inner_state(self.c, who, eid, self.names))
            self.assertIsNone(I.inner_subtext(self.c, who, eid, to, self.names))

    def test_speech_carries_it_and_changes_nothing_else(self):
        rows = self.c.execute("SELECT event_id, timestamp, type, location_id, truth FROM events WHERE type != 'day_end' ORDER BY event_id").fetchall()

        def lines(on):
            S.INNER_SUBTEXT = on
            try:
                return [S.speak(self.c, r["event_id"], r["type"], r["truth"], self.names, r["timestamp"], r["location_id"] or "") for r in rows]
            finally:
                S.INNER_SUBTEXT = True
        off, on = lines(False), lines(True)
        carried = 0
        for a, b in zip(off, on):
            self.assertEqual(a is None, b is None)
            if a is None:
                continue
            self.assertNotIn("inner", a)
            self.assertEqual({k: v for k, v in a.items() if k != "subtext"}, {k: v for k, v in b.items() if k not in ("subtext", "inner")})
            if a.get("subtext") and a["subtext"] not in S.GENERIC_SUBTEXT:
                self.assertEqual(a["subtext"], b["subtext"])            # what the relationship gave stays
            if "inner" in b:
                carried += 1
                self.assertEqual(b["subtext"], f"表面{I.EMOTION_ZH[b['inner']['surface']]}，底下是{b['inner']['underneath']}")
                self.assertGreaterEqual(b["inner"]["confidence"], I.SAY_AT)
        self.assertGreater(carried, 20)
        self.assertGreater(sum(1 for b in on if b and b.get("subtext")), sum(1 for a in off if a and a.get("subtext")))

    def test_the_same_world_says_the_same_subtext(self):
        rows = self.c.execute("SELECT event_id, timestamp, type, location_id, truth FROM events WHERE type = 'talk' ORDER BY event_id").fetchall()
        one = [S.speak(self.c, r["event_id"], r["type"], r["truth"], self.names, r["timestamp"], r["location_id"] or "") for r in rows]
        two = [S.speak(self.c, r["event_id"], r["type"], r["truth"], self.names, r["timestamp"], r["location_id"] or "") for r in rows]
        self.assertEqual(one, two)


SAY_BELOW = I.SAY_AT - 0.2


class Readings(unittest.TestCase):
    """Hand-made histories on a copy of a real world: what is underneath is exactly what the records support, and nothing else."""

    @classmethod
    def setUpClass(cls):
        base = connect()
        init_db(base, 7)
        build_world(base, 7, "jianghu_story_v1")
        cls.base = base
        cls.p, cls.q, cls.r = [x[0] for x in base.execute("SELECT id FROM people ORDER BY id LIMIT 3")]

    def setUp(self):
        self.c = connect()
        self.base.backup(self.c)
        self.t = (self.c.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0] // 1440 + 1) * 1440 + 600

    def event(self, etype, truth, parts, deltas=(), at=0):
        with mutation(self.c):                                   # (the test makes its own history; the module under test never writes)
            eid = self.c.execute("INSERT INTO events(timestamp, type, location_id, trigger_type, importance, truth) VALUES (?, ?, NULL, 'rule', 0.5, ?)",
                                 (self.t + at, etype, json.dumps(truth))).lastrowid
            for who, role in parts:
                self.c.execute("INSERT INTO event_participants(event_id, person_id, role) VALUES (?, ?, ?)", (eid, who, role))
            for kind, entity, field, old, new in deltas:
                self.c.execute("INSERT INTO event_deltas(event_id, entity_type, entity_id, field, old_value, new_value, delta_value, value_kind) "
                               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (eid, kind, entity, field, old, new, None if isinstance(new, str) else new - old, "set" if isinstance(new, str) else "numeric"))
        return eid

    def relate(self, a, b, field, value):
        return self.event("tell", {"actor": a}, [(a, "actor")], [("relationship", f"{a}:{b}", field, 0.0, value)], at=-300)

    def feel(self, who, emotion, etype="talk", **truth):
        parts = [(truth.get("actor", self.p), "actor"), (who, "target")]
        return self.event(etype, {"actor": truth.pop("actor", self.p), "target": who, **truth}, parts, [("person", who, "emotion", "calm", emotion)])

    def read(self, who=None, upto=None):
        nxt = self.c.execute("SELECT MAX(event_id) FROM events").fetchone()[0] + 1
        return I.inner_state(self.c, who or self.q, upto or nxt, {self.p: "阿甲", self.q: "阿乙", self.r: "阿丙"})

    def test_a_cold_word_from_somebody_loved_is_the_fear_of_being_left(self):
        set_up = self.relate(self.q, self.p, "affection", 0.8)
        cause = self.feel(self.q, "hurt", tone="cold")
        got = self.read()
        self.assertEqual(got["underneath"], "怕被阿甲丟下")
        self.assertEqual((got["surface"], got["because"]["event_id"], got["rule"]), ("hurt", cause, "fond_turned_cold"))
        rel = next(e for e in got["evidence"] if e["kind"] == "relationship")
        self.assertEqual((rel["entity"], rel["field"], rel["value"], rel["set_by"]), (f"{self.q}:{self.p}", "affection", 0.8, set_up))
        self.assertEqual(I.verify(self.c, got), [])

    def test_the_same_word_with_nothing_between_them_has_nothing_underneath(self):
        self.feel(self.q, "hurt", tone="cold")
        self.assertIsNone(self.read())

    def test_what_held_before_counts_not_what_came_after(self):
        self.feel(self.q, "hurt", tone="cold")
        self.relate(self.q, self.p, "affection", 0.9)          # fondness that only came later explains nothing about it
        self.assertIsNone(self.read())

    def test_it_follows_a_feeling_through_the_night_a_little_less_sure(self):
        self.relate(self.q, self.p, "affection", 0.8)
        cause = self.feel(self.q, "angry", tone="hostile")
        direct = self.read()
        self.event("upkeep", {"actor": self.q}, [(self.q, "actor")], [("person", self.q, "emotion", "angry", "uneasy")], at=300)
        got = self.read()
        self.assertEqual((got["surface"], got["felt_then"], got["nights"], got["because"]["event_id"]), ("uneasy", "angry", 1, cause))
        self.assertLess(got["confidence"], direct["confidence"])
        self.assertEqual(I.verify(self.c, got), [])

    def test_a_feeling_that_settled_to_calm_is_not_read(self):
        self.relate(self.q, self.p, "affection", 0.8)
        self.feel(self.q, "hurt", tone="cold")
        self.event("upkeep", {"actor": self.q}, [(self.q, "actor")], [("person", self.q, "emotion", "hurt", "calm")], at=300)
        self.assertIsNone(self.read())

    def test_a_cause_from_days_ago_is_not_read(self):
        self.relate(self.q, self.p, "affection", 0.8)
        self.feel(self.q, "hurt", tone="cold")
        self.event("talk", {"actor": self.r, "target": self.p, "tone": "warm"}, [(self.r, "actor"), (self.p, "target")], at=3 * 1440)
        self.assertIsNone(self.read())

    def test_a_feeling_with_no_event_behind_it_is_not_made_up(self):
        self.assertIsNone(self.read())                          # nobody here has felt anything yet
        self.event("talk", {"actor": self.p, "target": self.q, "tone": "cold"}, [(self.p, "actor"), (self.q, "target")])
        self.assertIsNone(self.read())                          # a cold word that left no feeling explains none

    def test_being_left_is_the_fear_of_being_left(self):
        cause = self.event("break_up", {"actor": self.p, "target": self.q}, [(self.p, "actor"), (self.q, "target")],
                           [("person", self.q, "emotion", "calm", "hurt"), ("person", self.p, "emotion", "angry", "calm")])
        got = self.read()
        self.assertEqual((got["rule"], got["because"]["event_id"]), ("left", cause))
        self.assertIsNone(self.read(self.p))                    # the one who left feels calm: nothing to read

    def test_a_loss_in_front_of_others_and_the_goal_it_started(self):
        cause = self.event("duel", {"actor": self.q, "target": self.p, "winner": self.p, "loser": self.q},
                           [(self.q, "actor"), (self.p, "target"), (self.r, "witness")],
                           [("person", self.q, "emotion", "calm", "ashamed")])
        self.assertIsNone(self.read())                          # one witness is not a crowd
        goal = self.event("goal_change", {"actor": self.q, "target": self.p, "kind": "surpass", "to": "formed", "text": "有一天打贏阿甲", "cause_event": cause},
                          [(self.q, "actor")])
        got = self.read()
        self.assertEqual(got["rule"], "lost_wants_back")
        self.assertIn("有一天打贏阿甲", got["underneath"])
        self.assertIn(goal, [e["event_id"] for e in got["evidence"] if e["kind"] == "event"])
        self.assertEqual(I.verify(self.c, got), [])

    def test_a_suspicion_is_read_from_what_the_owner_believes_not_from_who_really_did_it(self):
        for guilty in (True, False):
            c = connect()
            self.base.backup(c)
            self.c = c
            self.event("notice_missing", {"actor": self.q, "suspect": self.p, "confidence": 0.5, "suspect_guilty": guilty}, [(self.q, "actor"), (self.p, "suspect")],
                       [("person", self.q, "emotion", "calm", "uneasy")])
            got = self.read()
            self.assertEqual((got["rule"], got["underneath"]), ("suspects", "懷疑阿甲，可是不確定"))

    def test_a_forged_reading_does_not_verify(self):
        self.relate(self.q, self.p, "affection", 0.8)
        self.feel(self.q, "hurt", tone="cold")
        good = self.read()
        self.assertEqual(I.verify(self.c, good), [])
        import copy
        wrong_value = copy.deepcopy(good)
        next(e for e in wrong_value["evidence"] if e["kind"] == "relationship")["value"] = 0.2
        self.assertTrue(I.verify(self.c, wrong_value))
        wrong_person = copy.deepcopy(good)
        wrong_person["person"] = self.r                          # somebody who took no part in it
        self.assertTrue(I.verify(self.c, wrong_person))
        wrong_felt = copy.deepcopy(good)
        wrong_felt["felt_then"] = "angry"
        self.assertTrue(I.verify(self.c, wrong_felt))
        future = copy.deepcopy(good)
        future["as_of"] = good["because"]["event_id"] - 1
        self.assertTrue(I.verify(self.c, future))


class Reads(unittest.TestCase):
    def test_it_imports_no_write_path_of_the_world(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertLessEqual(mods - {"__future__"}, {"narrative.audience", "world.psyche"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertEqual(names & {"apply_event", "mutation", "EventSpec", "Change", "Simulation"}, set())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                up = node.value.upper().lstrip()
                self.assertFalse(any(up.startswith(s) for s in ("INSERT ", "UPDATE ", "DELETE ", "REPLACE ")), node.value[:40])

    def test_it_never_looks_at_what_really_happened_behind_a_persons_back(self):
        self.assertNotIn("suspect_guilty", SOURCE.read_text(encoding="utf-8").replace("who really took a thing", ""))


if __name__ == "__main__":
    unittest.main()
