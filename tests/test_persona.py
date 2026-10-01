"""The Persona layer: genomes in every world, the same person across worlds, branches, formative events, and the rule
that a real public figure is never filmed or published unless fictionalized first."""
from __future__ import annotations

import dataclasses
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from contracts.base import canonical_json, from_dict, to_dict
from contracts.persona import (Belief, BranchOrigin, CharacterGenome, DecisionHabits, Formative, KnowledgeBoundary,
                               Origin, SimulationBranch)
from world import personas
from world.db import connect, init_db, migrate, schema_version
from world.seed import build_world

RECIPES = ("town_v1", "town_life_v1", "town_in_jianghu_v1")


def world(recipe: str = "town_life_v1", seed: int = 7, extras: dict | None = None):
    conn = connect()
    init_db(conn, seed)
    if extras is None:
        build_world(conn, seed, recipe)
    else:
        with personas.extras_override(extras):
            build_world(conn, seed, recipe)
    return conn


def public_figure() -> CharacterGenome:
    """A made-up 'real person', for the tests of the real-person rule."""
    base = personas.genome(world(), "ming")
    return dataclasses.replace(
        base, name="林大偉", persona_text="林大偉，宏達電子創辦人，說話直接", temperament=dict(base.temperament),
        origin=Origin(kind="public_person", label="公開訪談整理", real_names=["林大偉", "Dawei Lin", "大偉哥"]),
        decisions=DecisionHabits(typical_choices=["先問第一性原理", "在宏達電子的會議上總是最後發言"], risk=["敢賭，但留退路"]),
        formative=[Formative(kind="turning_point", text="2008 年在宏達電子差點倒閉，林大偉賣掉房子撐住", age=40, weight=0.9),
                   Formative(kind="childhood", text="小時候家裡很窮，常幫忙看店", age=9, weight=0.6)],
        beliefs=[Belief(kind="world", text="大偉哥說：沒有退路才會想出路", confidence=0.7)])


class Genomes(unittest.TestCase):
    def test_everyone_in_every_recipe_has_a_genome(self):
        for r in RECIPES:
            c = world(r)
            ids = [row[0] for row in c.execute("SELECT id FROM people WHERE status = 'active' ORDER BY id")]
            self.assertEqual([i.person_id for i in personas.instances(c)], ids, r)
            for pid in ids:
                g = personas.genome(c, pid)
                self.assertEqual(g.origin.kind, "original_character")
                self.assertEqual(g.profile.id, pid)
                self.assertTrue(g.temperament and set(g.temperament) <= set(("honesty", "temper", "gossip", "generosity",
                                                                              "absent_minded", "curiosity")))

    def test_one_person_is_one_genome_in_every_world(self):
        """Casting (the job, the season's goal) is the world's; who they are is not."""
        a, b, c = (world(r) for r in RECIPES)
        for pid in ("ming", "mei", "yun"):
            self.assertEqual(personas.genome(a, pid).genome_id, personas.genome(b, pid).genome_id)
            self.assertEqual(personas.genome(a, pid).genome_id, personas.genome(c, pid).genome_id)
        # ...while the jianghu profile the agents read carries the disciple's job
        from world.profiles import profile
        self.assertEqual(profile(c, "ming").occupation.role, "弟子")
        self.assertIsNone(personas.genome(c, "ming").profile.occupation)

    def test_genome_id_is_content(self):
        g = personas.genome(world(), "ming")
        self.assertEqual(g.genome_id, personas.genome(world(seed=99), "ming").genome_id)  # not the seed
        self.assertNotEqual(g.genome_id, dataclasses.replace(g, persona_text="別的").genome_id)
        self.assertEqual(from_dict(CharacterGenome, json.loads(canonical_json(to_dict(g)))).genome_id, g.genome_id)

    def test_a_genome_never_changes(self):
        c = world()
        for sql in ("UPDATE character_genomes SET genome = '{}' WHERE person_id = 'ming'",
                    "DELETE FROM character_genomes WHERE person_id = 'ming'"):
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute(sql)

    def test_schema_upgrade_adds_the_table_and_old_worlds_have_no_genomes(self):
        c = connect()
        init_db(c, 1)
        c.execute("DROP TRIGGER character_genomes_insert")
        c.execute("DROP TRIGGER character_genomes_update")
        c.execute("DROP TRIGGER character_genomes_delete")
        c.execute("DROP TABLE character_genomes")
        c.execute("UPDATE meta SET value = '6' WHERE key = 'schema_version'")
        self.assertIsNone(personas.genome(c, "ming"))
        self.assertEqual((personas.instances(c), personas.problems(c)), ([], []))
        self.assertEqual(migrate(c), 7)
        self.assertEqual(schema_version(c), 7)


class Branches(unittest.TestCase):
    def test_the_branch_says_which_run_it_is(self):
        c = world("town_in_jianghu_v1", seed=11)
        b = personas.branch(c)
        self.assertEqual((b.recipe, b.seed, b.model, b.visibility), ("town_in_jianghu_v1", 11, "rule_agent_v1", "public"))
        self.assertEqual(b.roster_hash, personas.roster_hash(c))
        self.assertTrue(all(i.branch_id == b.branch_id for i in personas.instances(c)))

    def test_same_recipe_and_seed_is_the_same_branch_and_anything_else_is_not(self):
        a = personas.branch(world("town_life_v1", 5)).branch_id
        self.assertEqual(a, personas.branch(world("town_life_v1", 5)).branch_id)
        self.assertNotEqual(a, personas.branch(world("town_life_v1", 6)).branch_id)
        self.assertNotEqual(a, personas.branch(world("town_in_jianghu_v1", 5)).branch_id)

    def test_a_fork_is_a_different_branch_that_remembers_its_parent(self):
        c = world()
        parent = personas.branch(c)
        fork = personas.write_branch(c, "town_life_v1", 7, BranchOrigin(parent.branch_id, 12, "sha256:abc"))
        self.assertNotEqual(fork.branch_id, parent.branch_id)
        self.assertEqual(personas.branch(c).forked_from.day, 12)

    def test_contracts_round_trip(self):
        b = personas.branch(world())
        self.assertEqual(from_dict(SimulationBranch, json.loads(canonical_json(to_dict(b)))), b)


class FormativeEvents(unittest.TestCase):
    def test_what_made_someone_is_world_truth(self):
        extras = {"yun": {"formative": [{"kind": "loss", "text": "十二歲那年，父親離開了家", "age": 12, "weight": 0.9}],
                          "decisions": {"conflict": ["被追問就變冷淡"]},
                          "knowledge": {"unknown": ["戒指的下落"]},
                          "beliefs": [{"kind": "people", "text": "人最後都會離開", "confidence": 0.8}]}}
        c = world(extras=extras)
        g = personas.genome(c, "yun")
        self.assertEqual(g.decisions.conflict, ["被追問就變冷淡"])
        self.assertEqual(g.beliefs[0].text, "人最後都會離開")
        row = c.execute("SELECT event_id, truth, importance FROM events WHERE json_extract(truth,'$.formative') = 'loss'").fetchone()
        self.assertIsNotNone(row)
        self.assertIn("父親離開了家", json.loads(row[1])["text"])
        self.assertGreater(row[2], 0.5)
        mem = c.execute("SELECT belief FROM memories WHERE observer_id = 'yun' AND belief LIKE '%父親%'").fetchone()
        self.assertIsNotNone(mem)
        # it is in the snapshot like any event; and the other people have nothing of the sort
        self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth,'$.formative') IS NOT NULL").fetchone()[0], 1)

    def test_extras_for_somebody_who_is_not_there_are_refused(self):
        with self.assertRaises(personas.PersonaError):
            world(extras={"nobody": {"beliefs": []}})

    def test_the_existing_casts_add_no_events(self):
        for r in RECIPES:
            c = world(r)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1, r)  # the ring, as before


class RealPeople(unittest.TestCase):
    def test_fictionalize_changes_the_name_and_removes_what_identifies(self):
        raw = public_figure()
        fake, banned = personas.fictionalize(raw, name="周明遠", replacements={"宏達電子": "遠景科技"}, remove=["2008 年"])
        text = canonical_json(to_dict(fake))
        for term in ("林大偉", "Dawei Lin", "大偉哥", "2008"):
            self.assertNotIn(term, text)
        self.assertIn("周明遠", text)
        self.assertIn("遠景科技", text)
        self.assertEqual(fake.profile.name, "周明遠")
        self.assertEqual(sorted(banned), sorted({"林大偉", "Dawei Lin", "大偉哥", "2008 年"}))
        # what is kept: the structure of the person
        self.assertEqual(fake.decisions.risk, raw.decisions.risk)
        self.assertEqual(fake.temperament, raw.temperament)
        self.assertEqual([f.kind for f in fake.formative], ["childhood"])  # the dated, identifying one was dropped
        # where it came from is remembered, but not who
        self.assertEqual((fake.origin.kind, fake.origin.fictionalized, fake.origin.derived_from, fake.origin.real_names),
                         ("public_person", True, raw.genome_id, []))
        self.assertNotEqual(fake.genome_id, raw.genome_id)

    def test_fictionalizing_refuses_when_something_still_gives_the_person_away(self):
        raw = dataclasses.replace(public_figure(), beliefs=[Belief(kind="world", text="那位 DAWEI LIN 說過的話", confidence=0.5)])
        # a name in another capitalisation is swapped too
        fake, banned = personas.fictionalize(raw, name="周明遠", replacements={"宏達電子": "遠景科技"})
        self.assertEqual(personas.scan([canonical_json(to_dict(fake))], banned), [])
        self.assertIn("周明遠", fake.beliefs[0].text)
        # a replacement that brings the real name back is caught by the check: nothing is returned
        with self.assertRaises(personas.FictionalizeError):
            personas.fictionalize(raw, name="周明遠", replacements={"宏達電子": "Dawei Lin 科技"})
        # a nickname nobody listed cannot be found, but listing it as a detail to remove makes the result clean
        leaky = dataclasses.replace(raw, beliefs=[Belief(kind="world", text="他的綽號是大偉", confidence=0.5)])
        fake2, _ = personas.fictionalize(leaky, name="周明遠", remove=["大偉"])
        self.assertNotIn("大偉", canonical_json(to_dict(fake2)))

    def test_only_a_raw_public_person_is_fictionalized_once(self):
        c = personas.genome(world(), "ming")
        with self.assertRaises(personas.FictionalizeError):
            personas.fictionalize(c, name="x")
        fake, _ = personas.fictionalize(public_figure(), name="周明遠")
        with self.assertRaises(personas.FictionalizeError):
            personas.fictionalize(fake, name="y")

    def test_a_world_with_a_raw_public_person_is_private_and_is_not_filmed(self):
        raw = public_figure()
        c = world(extras={"ming": {"origin": to_dict(raw.origin)}})
        self.assertEqual(personas.branch(c).visibility, "private")
        self.assertEqual(len(personas.problems(c)), 1)
        with self.assertRaises(personas.NotPublishable):
            personas.assert_publishable(c)

    def test_a_fictionalized_person_may_be_published(self):
        raw = public_figure()
        fake, _ = personas.fictionalize(raw, name="周明遠")
        c = world(extras={"ming": {"origin": to_dict(fake.origin)}})
        self.assertEqual(personas.branch(c).visibility, "public")
        personas.assert_publishable(c)
        self.assertEqual(personas.problems(c), [])

    def test_the_daily_pipeline_refuses_a_world_holding_real_people(self):
        from channel.daily import DailyConfig, run_daily
        raw = public_figure()
        with tempfile.TemporaryDirectory() as d:
            live = Path(d) / "live.db"
            c = world(extras={"ming": {"origin": to_dict(raw.origin)}})
            from world.db import save_to
            save_to(c, live)
            cfg = DailyConfig(world_db=str(live), prod_db=str(Path(d) / "prod.db"), out_dir=str(Path(d) / "out"), days=1)
            with self.assertRaises(personas.NotPublishable):
                run_daily(cfg)

    def test_the_publish_gate_finds_a_banned_name_in_any_text(self):
        banned = ["林大偉", "Dawei Lin"]
        self.assertEqual(personas.scan(["今天林大偉說了一句話", "字幕"], banned), ["林大偉"])
        self.assertEqual(personas.scan(["dawei LIN spoke"], banned), ["Dawei Lin"])
        self.assertEqual(personas.scan(["周明遠說了一句話"], banned), [])


if __name__ == "__main__":
    unittest.main()


class FormativeShaping(unittest.TestCase):
    """A formative experience is not only a line of history: it leaves the marks that living it would."""

    def shaped(self, experience: str, weight: float = 0.9, pid: str = "mei"):
        return world(extras={pid: {"formative": [{"kind": "turning_point", "text": "那一年", "age": 10, "weight": weight,
                                                  "experience": experience}]}})

    def var(self, c, key):
        return c.execute("SELECT value FROM world_vars WHERE key = ?", (key,)).fetchone()[0]

    def test_an_early_betrayal_leaves_a_wary_person_who_holds_the_belief(self):
        control, c = world(), self.shaped("betrayal")
        self.assertGreater(self.var(c, "psy.mei.vigilance"), self.var(control, "psy.mei.vigilance") + 0.2)
        self.assertLess(self.var(c, "psy.mei.trust_default"), self.var(control, "psy.mei.trust_default") - 0.2)
        self.assertEqual(self.var(c, "psy.mei.self.cannot_trust"), 1.0)  # strong enough to be a self-model already
        self.assertEqual(self.var(control, "psy.mei.self.cannot_trust"), 0.0)
        # it is a scar, as a lived betrayal would be: healing stops short of rest
        self.assertEqual(self.var(c, "psy.mei.worst.vigilance"), self.var(c, "psy.mei.vigilance"))
        # and it is world truth: an event that says what it did, which only mei carries
        row = c.execute("SELECT truth FROM events WHERE json_extract(truth,'$.experience') = 'betrayal'").fetchone()
        self.assertIn("vigilance", json.loads(row[0])["shaped"])
        self.assertEqual(self.var(c, "psy.ming.vigilance"), self.var(control, "psy.ming.vigilance"))

    def test_a_weak_memory_moves_the_traits_but_forms_no_belief(self):
        c = self.shaped("betrayal", weight=0.4)
        self.assertGreater(self.var(c, "psy.mei.vigilance"), self.var(world(), "psy.mei.vigilance"))
        self.assertEqual(self.var(c, "psy.mei.self.cannot_trust"), 0.0)

    def test_kindness_and_hostility_push_the_other_way_and_each_experience_has_a_mark(self):
        control = world()
        kind, hostile = self.shaped("kindness"), self.shaped("hostility")
        self.assertGreater(self.var(kind, "psy.mei.trust_default"), self.var(control, "psy.mei.trust_default"))
        self.assertEqual(self.var(kind, "psy.mei.self.some_are_kind"), 1.0)
        self.assertGreater(self.var(hostile, "psy.mei.aggression"), self.var(control, "psy.mei.aggression"))
        from world.psyche import EXPERIENCES, SHAPING
        self.assertEqual(sorted(SHAPING), sorted(EXPERIENCES))

    def test_the_shaping_shows_in_what_they_would_do(self):
        """Persona probe at day 0: someone betrayed early is quicker to accuse than the same person who was not."""
        from persona_probe import probe
        control, c = world(), self.shaped("betrayal")
        base, shaped = probe(control, 7)["mei"]["accuse"], probe(c, 7)["mei"]["accuse"]
        self.assertGreater(shaped, base * 1.2)

    def test_what_cannot_be_applied_is_left_alone(self):
        from world.psyche import shaping_changes
        c = world()
        self.assertEqual(shaping_changes(c, "mei", "boredom", 0.9), ([], {}))      # not an experience the psyche knows
        self.assertEqual(shaping_changes(c, "nobody", "betrayal", 0.9), ([], {}))  # nobody with a psyche here
