"""Domain packs: a new genre or area of life enters without the core being edited.

- A magic pack written in this file, registered at run time, runs in a world: its action is chosen, validated and
  resolved, its claim act can be witnessed and believed, its events are answered, staged, captioned and listed.
- A world whose recipe does not name it refuses it.
- The built-in packs: topics (tastes learnt in talk), work (stress, demands, a job search), and their determinism.
- Character profiles: the rosters satisfy the contract, every person has one, and a world never rewrites one.
"""
from __future__ import annotations

import json
import unittest

from agent.volition import VolitionDecider
from contracts.claim import Claim
from contracts.recipe import MechanicPrimitive as P, WorldRecipe
from world.attention import LOUD, noticers, var
from world.db import connect, init_db
from world.domains import ActionSpec, Domain, EventStyle, register, unregister
from world.domains.base import ClaimAct
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.helpers import RelDeltas, person
from world.intent import Intent, validate
from world.recipes import BASE, register_recipe, unregister_recipe
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash
from world.state import WorldError

MANA, COST = 30.0, 10.0


def _validate_cast(conn, it: Intent, actor) -> None:
    other = person(conn, it.target) if it.target else None
    if other is None or other["location_id"] != actor["location_id"] or it.target == it.actor:
        raise WorldError("nobody here to cast at")
    if var(conn, f"mana.{it.actor}", 0.0) < COST:
        raise WorldError("not enough mana")


def _resolve_cast(conn, it: Intent, now: int, trigger: str) -> EventSpec:
    from world.claims import describe_claim, labels
    a, b = it.actor, it.target
    here = person(conn, a)["location_id"]
    seen = noticers(conn, here, now, f"spell:{a}:{b}", LOUD, a, b)
    c = Claim(a, "hex", b)
    text = describe_claim(c, labels(conn))
    d = RelDeltas()
    d.add(b, a, "fear", 0.1)
    d.add(b, a, "trust", -0.2)
    return EventSpec(timestamp=now, type="spell", trigger_type=trigger, location_id=here, importance=0.7,
                     truth={"actor": a, "target": b, "text": text, "reason": it.reason},
                     participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in seen],
                     changes=[Change("var", f"mana.{a}", "value", delta=-COST), Change("person", b, "emotion", value="scared")]
                     + d.changes(conn),
                     memories=[MemorySpec(p, text, 1.0, claim=c) for p in (a, b)] + [MemorySpec(w, text, 0.8, claim=c) for w in seen],
                     claims=[ClaimSpec(c)])


class Magic(Domain):
    id = "magic_test"
    primitives = (P("magic_test", "power", "a toy magic for the test", ["schedule"], cost=0),)
    acts = {"hex": ClaimAct("magic", "person", "對{o}下了咒", "沒有對{o}下咒", belief_effect=-0.3)}
    actions = {"cast": ActionSpec("cast", _validate_cast, _resolve_cast, targets_person=True, conflict=True)}
    styles = {"spell": EventStyle(caption="對{t}施法", lines=("看招！",), social=True, say=2.0, heat=3, opens_scene=True,
                                  first_time=True)}

    def initial_vars(self, pid, profile):
        return {f"mana.{pid}": MANA}

    def options(self, conn, actor, now, ctx):
        if var(conn, f"mana.{actor}", 0.0) < COST:
            return []
        out = []
        for other in ctx["here"]:
            r = conn.execute("SELECT trust FROM relationships WHERE actor_id = ? AND target_id = ?", (actor, other)).fetchone()
            out.append((0.3 - 1.2 * r[0] + 0.4 * ctx["traits"]["temper"], Intent(actor, "cast", other, reason="volition")))
        return out

    def overnight(self, conn, pid, now):
        cur = var(conn, f"mana.{pid}", None)
        return [Change("var", f"mana.{pid}", "value", delta=MANA - cur)] if cur is not None and cur < MANA else []


def _recipe(rid: str, extra: list[str]) -> WorldRecipe:
    return WorldRecipe(recipe_id=rid, title=rid, content="town_v1", core="everyday_life",
                       pillars=["items.ownership", "money.rent", "gossip.drift"],
                       base=BASE + ["psyche", "items.accusation", "money.debt"] + extra)


def _world(recipe: str, seed: int, days: int):
    c = connect()
    init_db(c, seed)
    build_world(c, seed, recipe)
    d = VolitionDecider(seed)
    Simulation(c, d, d, set()).run(days)
    return c


class ANewPackEntersWithoutTouchingTheCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register(Magic)
        register_recipe(_recipe("town_magic_test", ["magic_test", "social.exchange"]))
        cls.c = _world("town_magic_test", 11, 2)
        cls.spells = cls.c.execute("SELECT * FROM events WHERE type = 'spell' ORDER BY event_id").fetchall()

    @classmethod
    def tearDownClass(cls):
        unregister_recipe("town_magic_test")
        unregister(Magic.id)

    def test_people_cast_and_the_rules_resolve_it(self):
        self.assertGreater(len(self.spells), 0)
        for r in self.spells:
            t = json.loads(r["truth"])
            self.assertNotEqual(t["actor"], t["target"])

    def test_its_claim_can_be_witnessed_and_believed(self):
        rows = self.c.execute("SELECT m.belief FROM memories m JOIN claims c USING (claim_id) WHERE c.act = 'hex'").fetchall()
        self.assertTrue(rows)
        self.assertIn("下了咒", rows[0][0])

    def test_a_spell_gets_an_answer(self):
        answered = 0
        for r in self.spells:
            nxt = self.c.execute("SELECT truth FROM events WHERE event_id > ? AND type = 'talk' ORDER BY event_id LIMIT 1",
                                 (r["event_id"],)).fetchone()
            t, s = json.loads(r["truth"]), json.loads(nxt[0]) if nxt else {}
            answered += s.get("reason", "").startswith("reply:") and s.get("actor") == t["target"]
        self.assertGreater(answered, 0)

    def test_the_stage_and_the_read_models_know_it(self):
        from narrative.lines import line
        from narrative.scenes import scenes
        from runtime.godview import caption
        from runtime.world_runtime import WorldRuntime
        r = self.spells[0]
        t = json.loads(r["truth"])
        names = {x[0]: x[1] for x in self.c.execute("SELECT id, name FROM people")}
        self.assertEqual(line(r["event_id"], "spell", t, names)["say"], "看招！")
        self.assertIn("施法", caption("spell", t, r["location_id"], names))
        self.assertIn(r["event_id"], [s["id"] for s in scenes(self.c)])
        rt = WorldRuntime(self.c)
        rt.advance()
        self.assertTrue(any(a.kind == "say" and a.event_id == r["event_id"] for a in rt.actions))

    def test_a_world_without_it_refuses_it(self):
        c = connect()
        init_db(c, 3)
        build_world(c, 3, "town_v1")
        with self.assertRaises(WorldError):
            validate(c, Intent("ming", "cast", "mei"))


class BuiltInPacks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_recipe(_recipe("town_life_test", ["social.exchange", "social.topics", "life.work"]))
        cls.c = _world("town_life_test", 5, 4)

    @classmethod
    def tearDownClass(cls):
        unregister_recipe("town_life_test")

    def test_talk_has_topics_and_people_learn_each_others_tastes(self):
        topics = [json.loads(r[0]).get("topic") for r in self.c.execute("SELECT truth FROM events WHERE type = 'talk'")]
        self.assertGreater(sum(bool(t) for t in topics), 5)
        learnt = self.c.execute("SELECT COUNT(*) FROM memories m JOIN claims c USING (claim_id) WHERE c.act IN ('like', 'dislike')").fetchone()[0]
        self.assertGreater(learnt, 0)

    def test_work_wears_and_the_superior_acts(self):
        stress = [var(self.c, f"work.stress.{p}", 0.0) for p in ("ming", "jun", "hao", "kai", "tao")]
        self.assertTrue(all(s > 0 for s in stress))
        self.assertIsNone(var(self.c, "work.stress.mei", None))  # no job, no work life
        kinds = {r[0] for r in self.c.execute("SELECT type FROM events WHERE type IN ('overtime', 'praise', 'job_search')")}
        self.assertTrue(kinds)

    def test_same_seed_same_world(self):
        self.assertEqual(snapshot_hash(_world("town_life_test", 5, 4)), snapshot_hash(self.c))

    def test_the_same_pack_speaks_a_sect_s_words(self):
        from world.domains.work import superior_person, words
        c = connect()
        init_db(c, 3)
        build_world(c, 3, "jianghu_v1")
        self.assertEqual(words(c, "lu")["overtime"], "加練")
        self.assertEqual(words(c, "lu")["quit"], "離開師門")
        self.assertEqual(superior_person(c, "lu"), "lin")  # a master in the world, not an offstage boss
        self.assertEqual(words(c, "hua")["work"], "招呼客人")


class Profiles(unittest.TestCase):
    def test_every_roster_satisfies_the_contract_and_covers_its_cast(self):
        from contracts.character import check_roster
        from world.content import content_module
        from world.profiles import load_roster
        from world.seed import PEOPLE
        for content, cast in (("town_v1", [p[0] for p in PEOPLE]),
                              ("jianghu_v1", [p[0] for p in content_module("jianghu_v1").PEOPLE])):
            r = load_roster(content)
            self.assertEqual(check_roster(r), [])
            self.assertEqual(sorted(p.id for p in r.people), sorted(cast))

    def test_a_world_never_rewrites_who_someone_is(self):
        import sqlite3
        from world.profiles import profile
        c = connect()
        init_db(c, 3)
        build_world(c, 3, "town_v1")  # the backstory is an event: the world has begun
        self.assertEqual(profile(c, "ming").name, "阿明")
        for sql in ("UPDATE character_profiles SET profile_hash = 'x' WHERE person_id = 'ming'",
                    "DELETE FROM character_profiles WHERE person_id = 'ming'",
                    "INSERT INTO content_topics(topic, label) VALUES ('late', '後來的')"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                c.execute(sql)


if __name__ == "__main__":
    unittest.main()


class PacksAreNotASecondCore(unittest.TestCase):
    """A domain pack declares rules and answers hooks; the core runs the lifecycle. A pack that drives the
    simulation, writes the database, depends on the agents or grows into an engine of its own is refused."""
    LIMIT = 600  # lines: past this, split the pack's rules into their own module (as martial keeps world/jianghu.py)

    def test_packs_only_declare_and_return(self):
        import ast
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent / "world" / "domains"
        bad = []
        for path in sorted(root.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if len(text.splitlines()) > self.LIMIT:
                bad.append(f"{path.name}: {len(text.splitlines())} lines")
            for node in ast.walk(ast.parse(text)):
                mods = [node.module] if isinstance(node, ast.ImportFrom) and node.module else \
                    [a.name for a in node.names] if isinstance(node, ast.Import) else []
                names = [a.name for a in node.names] if isinstance(node, ast.ImportFrom) else []
                for m in mods:
                    if m.startswith("agent") or m in ("world.simulation", "world.db"):
                        bad.append(f"{path.name}: imports {m}")
                if "apply_event" in names or "mutation" in names:
                    bad.append(f"{path.name}: imports {names}")
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    sql = node.value.lstrip().upper()
                    if sql.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP")):
                        bad.append(f"{path.name}: writes SQL: {node.value[:40]!r}")
        self.assertEqual(bad, [])
