"""The character forge: same seed, same bytes; locks stick; a cast of 6 or more is dramatically balanced."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from contracts.base import from_dict
from contracts.character import CharacterRoster, check_roster
from narrative.lint import MODERN_WORDS
from tests.test_drama_content import FAMOUS as PACK_FAMOUS
from world.forge import (
    ARCHETYPES, BIRTHPLACES, FAMOUS, GIVEN_FEMALE, GIVEN_MALE, GIVEN_ONE, GIVEN_TWO,
    JIANGHU_JOB_WORDS, JIANGHU_TOPICS, NEMESIS_WHY, SECRET_GENERIC, SECRET_MATCHED, SURNAMES,
    TOWN_GIVEN_FEMALE, TOWN_GIVEN_MALE, TOWN_SURNAMES, cast_text, find_modern, forge_cast,
)
from world.personas import lift

ROOT = Path(__file__).resolve().parent.parent
ATTACHMENTS = {"secure", "anxious", "avoidant"}
CONFLICTS = {"avoid", "bottle_up", "confront", "sulk", "appease"}
GENDERS = {"male", "female"}


def _walk_strings(obj, chunks: list[str]) -> None:
    if isinstance(obj, str):
        chunks.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            _walk_strings(value, chunks)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _walk_strings(value, chunks)


def jianghu_template_text() -> str:
    chunks: list[str] = []
    for spec in ARCHETYPES.values():
        for key in ("cores", "habits", "looks_pool", "family", "education", "roles"):
            _walk_strings(spec[key]["jianghu"], chunks)
        _walk_strings(spec["social"], chunks)
        _walk_strings(spec["voices"], chunks)
    for table in (JIANGHU_TOPICS, JIANGHU_JOB_WORDS, BIRTHPLACES["jianghu"], NEMESIS_WHY["jianghu"],
                  SECRET_MATCHED["jianghu"], SECRET_GENERIC["jianghu"], SURNAMES, GIVEN_ONE, GIVEN_TWO):
        _walk_strings(table, chunks)
    return "\n".join(chunks)


class ForgeTests(unittest.TestCase):
    def test_the_ban_list_matches_the_drama_pack(self):
        self.assertEqual(FAMOUS, PACK_FAMOUS)

    def test_same_seed_is_byte_for_byte_and_another_seed_is_not(self):
        first = forge_cast(7, 10, "jianghu")
        second = forge_cast(7, 10, "jianghu")
        other = forge_cast(8, 10, "jianghu")
        for attr in ("profiles_json", "genomes_json", "relations_json", "summary"):
            self.assertEqual(getattr(first, attr), getattr(second, attr))
            self.assertNotEqual(getattr(first, attr), getattr(other, attr))
        self.assertEqual(first.summary, forge_cast(7, 10, "jianghu", archetypes=None, locks=None).summary)
        self.assertNotEqual(first.profiles_json, forge_cast(7, 10, "town").profiles_json)

    def test_same_bytes_across_processes(self):
        code = (
            "import hashlib\n"
            "from world.forge import forge_cast\n"
            "c = forge_cast(7, 10, 'jianghu')\n"
            "blob = (c.profiles_json + c.genomes_json + c.relations_json + c.summary).encode('utf-8')\n"
            "print(hashlib.sha256(blob).hexdigest())\n"
        )
        outs = set()
        for hash_seed in ("0", "1", "random"):
            env = {**os.environ, "PYTHONHASHSEED": hash_seed}
            run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=ROOT)
            self.assertEqual(run.returncode, 0, run.stderr)
            outs.add(run.stdout.strip())
        self.assertEqual(len(outs), 1, outs)

    def test_a_lock_is_kept_and_the_other_fields_still_come_from_the_seed(self):
        locks = {0: {"name": "白薇", "age": 16}}
        free = forge_cast(4, 8, "jianghu")
        locked = forge_cast(4, 8, "jianghu", locks=locks)
        reroll = forge_cast(5, 8, "jianghu", locks={"0": {"name": "白薇", "age": 16}})
        self.assertEqual(locked.people[0].name, "白薇")
        self.assertEqual(reroll.people[0].name, "白薇")
        self.assertEqual(locked.people[0].age, 16)
        self.assertEqual(reroll.people[0].age, 16)
        self.assertEqual(locked.people[0].looks, free.people[0].looks)
        self.assertEqual(locked.people[0].warmth, free.people[0].warmth)
        self.assertEqual(locked.people[0].talkativeness, free.people[0].talkativeness)
        self.assertEqual(locked.people[0].blurb, free.people[0].blurb)
        self.assertEqual(locked.people[0].temperament, free.people[0].temperament)
        self.assertEqual([p.looks for p in locked.people], [p.looks for p in free.people])
        self.assertNotEqual(locked.profiles_json, reroll.profiles_json)
        self.assertFalse(locked.people[0].romance_eligible)
        self.assertEqual(locked.people[0].attracted_to, ())
        self.assertIn("p0", locked.relations["not_romance"])
        for crush in locked.relations["crushes"]:
            self.assertNotIn("p0", (crush["from"], crush["to"]))

    def test_a_cast_of_ten_is_balanced_adult_and_named(self):
        for seed in (1, 2, 3, 7, 11, 23, 42, 99, 1000, 184729):
            for era in ("jianghu", "town"):
                cast = forge_cast(seed, 10, era)
                self.assert_balanced(cast)
                self.assert_people(cast)
        for seed in range(1, 21):
            self.assert_balanced(forge_cast(seed, 6, "jianghu"))

    def test_jianghu_text_has_no_modern_word_and_the_town_does(self):
        self.assertEqual(find_modern(jianghu_template_text(), MODERN_WORDS), [])
        for seed in (1, 7, 11, 23, 42):
            jianghu = forge_cast(seed, 12, "jianghu")
            town = forge_cast(seed, 12, "town")
            self.assertEqual(find_modern(cast_text(jianghu), MODERN_WORDS), [], seed)
            self.assertTrue(find_modern(cast_text(town), MODERN_WORDS), seed)

    def test_roster_and_lift_accept_the_files(self):
        for era in ("jianghu", "town"):
            cast = forge_cast(7, 10, era)
            roster = from_dict(CharacterRoster, json.loads(cast.profiles_json))
            self.assertEqual(check_roster(roster), [])
            genomes = json.loads(cast.genomes_json)["people"]
            self.assertEqual(set(genomes), {p.id for p in cast.people})
            for profile in roster.people:
                person = next(p for p in cast.people if p.id == profile.id)
                genome = lift(profile, person.temperament, person.blurb, genomes[profile.id])
                self.assertEqual(genome.name, profile.name)
                self.assertEqual(genome.charm, genome.looks)
                self.assertEqual(genome.looks, person.looks)
                self.assertEqual(genome.warmth, person.warmth)
                self.assertEqual(genome.talkativeness, person.talkativeness)
                self.assertEqual(genome.profile.costume, "")
                self.assertTrue(genome.appearance.face and genome.appearance.presence)
                self.assertTrue(genome.voice.timbre and genome.voice.catchphrases)

    def test_a_cold_beauty_is_beautiful_and_quiet_and_a_plain_helper_is_not(self):
        for seed in range(1, 11):
            cold = forge_cast(seed, 6, "jianghu", archetypes=["高冷美人"])
            self.assert_balanced(cold)
            for person in cold.people:
                self.assertEqual(person.archetype, "高冷美人")
                self.assertGreaterEqual(person.looks, 0.75)
                self.assertLessEqual(person.warmth, 0.35)
                self.assertLessEqual(person.talkativeness, 0.30)
                self.assertEqual(person.charm, person.looks)
            plain = forge_cast(seed, 4, "town", archetypes=["其貌不揚的熱心人"])
            for person in plain.people:
                self.assertEqual(person.archetype, "其貌不揚的熱心人")
                self.assertLessEqual(person.looks, 0.45)
                self.assertGreaterEqual(person.warmth, 0.70)
                self.assertEqual(person.charm, person.looks)

    def test_archetype_list_limits_the_cast(self):
        cast = forge_cast(7, 8, "jianghu", archetypes="高冷美人,毒舌")
        self.assertTrue(all(p.archetype in ("高冷美人", "毒舌") for p in cast.people))

    def test_bad_arguments_are_refused(self):
        with self.assertRaises(ValueError):
            forge_cast(1, 0, "jianghu")
        with self.assertRaises(ValueError):
            forge_cast(1, 4, "space")
        with self.assertRaises(ValueError):
            forge_cast(1, 4, "jianghu", archetypes=["不存在"])
        with self.assertRaises(ValueError):
            forge_cast(1, 4, "jianghu", locks={9: {"name": "白薇"}})

    def test_names_follow_gender_given_names_differ_and_blurbs_do_not_repeat(self):
        self.assertFalse(set(GIVEN_MALE) & set(GIVEN_FEMALE))
        self.assertFalse(set(TOWN_GIVEN_MALE) & set(TOWN_GIVEN_FEMALE))
        for name, spec in ARCHETYPES.items():
            for era in ("jianghu", "town"):
                cores = spec["cores"][era]
                self.assertGreaterEqual(len(cores), 3, (name, era))
                blurbs = [core["blurb"] for core in cores]
                self.assertEqual(len(blurbs), len(set(blurbs)), (name, era))
        for seed in range(1, 31):
            for era in ("jianghu", "town"):
                cast = forge_cast(seed, 10, era)
                self.assert_gendered_unique_names(cast)
                self.assert_distinct_sets_when_enough(cast)

    def test_a_small_cast_still_validates(self):
        cast = forge_cast(7, 3, "town")
        self.assertEqual(len(cast.people), 3)
        self.assertEqual(check_roster(from_dict(CharacterRoster, cast.roster)), [])

    def test_the_command_writes_the_four_files(self):
        from character_forge import main

        with tempfile.TemporaryDirectory() as folder:
            code = main(["--seed", "7", "--size", "10", "--era", "jianghu", "--out", folder,
                         "--archetypes", "高冷美人,毒舌"])
            self.assertEqual(code, 0)
            cast = forge_cast(7, 10, "jianghu", archetypes=["高冷美人", "毒舌"])
            for name, text in (
                ("profiles.json", cast.profiles_json),
                ("genomes.json", cast.genomes_json),
                ("relations.json", cast.relations_json),
                ("summary.md", cast.summary),
            ):
                self.assertEqual(Path(folder, name).read_text(encoding="utf-8"), text)
            lock = Path(folder, "locks.json")
            lock.write_text(json.dumps({"0": {"name": "白薇"}}), encoding="utf-8")
            locked_out = Path(folder, "locked")
            code = main(["--seed", "3", "--size", "6", "--era", "jianghu", "--out", str(locked_out),
                         "--lock", str(lock)])
            self.assertEqual(code, 0)
            roster = json.loads((locked_out / "profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(roster["people"][0]["name"], "白薇")

    def assert_balanced(self, cast):
        relations = cast.relations
        by_id = {p.id: p for p in cast.people}
        self.assertGreaterEqual(len(relations["nemeses"]), 1, cast.seed)
        self.assertGreaterEqual(len(relations["secrets"]), 1, cast.seed)
        self.assertGreaterEqual(len(relations["crushes"]), 1, cast.seed)
        self.assertGreaterEqual(len(relations["underestimated"]), 1, cast.seed)
        for pair in relations["nemeses"]:
            self.assertNotEqual(pair["a"], pair["b"])
            self.assertIn(pair["a"], by_id)
            self.assertIn(pair["b"], by_id)
        for secret in relations["secrets"]:
            self.assertNotEqual(secret["holder"], secret["kept_from"])
            self.assertIn(secret["holder"], by_id)
            self.assertIn(secret["kept_from"], by_id)
            self.assertTrue(secret["secret"])
        for crush in relations["crushes"]:
            admirer, other = by_id[crush["from"]], by_id[crush["to"]]
            self.assertNotEqual(admirer.id, other.id)
            self.assertTrue(crush["one_way"])
            self.assertGreaterEqual(admirer.age, 18)
            self.assertGreaterEqual(other.age, 18)
            self.assertIn(other.gender, admirer.attracted_to)
            self.assertNotIn(crush["from"], relations["not_romance"])
            self.assertNotIn(crush["to"], relations["not_romance"])
        for item in relations["underestimated"]:
            self.assertIn(item["id"], by_id)

    def assert_people(self, cast):
        names = [p.name for p in cast.people]
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse(set(names) & set(FAMOUS))
        for person in cast.people:
            self.assertGreaterEqual(person.age, 18)
            self.assertIn(person.gender, GENDERS)
            self.assertIn(person.attachment, ATTACHMENTS)
            self.assertIn(person.conflict, CONFLICTS)
            self.assertTrue(person.romance_eligible)
            self.assertTrue(person.attracted_to)
            self.assertTrue(set(person.attracted_to) <= GENDERS)
            self.assertEqual(person.charm, person.looks)
            self.assertTrue(all(0.0 <= value <= 1.0 for value in person.temperament.values()))
            self.assertEqual(set(person.temperament), set(("honesty", "temper", "gossip", "generosity",
                                                            "absent_minded", "curiosity")))
            if cast.era == "jianghu":
                self.assertGreaterEqual(len(person.name), 2)
                self.assertLessEqual(len(person.name), 3)
                self.assertIn(person.name[0], SURNAMES)
                self.assertNotIn(person.name[0], "阿小老")
                rest = person.name[1:]
                self.assertTrue(rest in GIVEN_ONE or rest in GIVEN_TWO, person.name)
        self.assert_gendered_unique_names(cast)
        self.assert_distinct_sets_when_enough(cast)
        self.assertEqual(cast.relations["not_romance"], [])

    def assert_gendered_unique_names(self, cast):
        if cast.era == "jianghu":
            male, female, surnames = GIVEN_MALE, GIVEN_FEMALE, SURNAMES
        else:
            male, female, surnames = TOWN_GIVEN_MALE, TOWN_GIVEN_FEMALE, TOWN_SURNAMES
        givens = []
        for person in cast.people:
            self.assertIn(person.name[:1], surnames, person.name)
            given = person.name[1:]
            givens.append(given)
            own, other = (female, male) if person.gender == "female" else (male, female)
            self.assertIn(given, own, (cast.seed, cast.era, person.name, person.gender))
            self.assertNotIn(given, other, (cast.seed, cast.era, person.name, person.gender))
        self.assertEqual(len(givens), len(set(givens)), (cast.seed, cast.era, givens))

    def assert_distinct_sets_when_enough(self, cast):
        """Same archetype, same cast: no shared set while unused sets remain. 他/她 does not make a new set."""
        grouped: dict[str, list[tuple]] = {}
        profiles = {p["id"]: p for p in cast.roster["people"]}
        for person in cast.people:
            profile = profiles[person.id]
            parts = [profile["core"][key] for key in ("want", "fear", "wound", "false_belief", "need", "life_question")]
            parts += [profile["life_goal"], profile["season_goal"], person.blurb]
            key = tuple(part.replace("她", "他") for part in parts)
            grouped.setdefault(person.archetype, []).append(key)
        for archetype, keys in grouped.items():
            available = len(ARCHETYPES[archetype]["cores"][cast.era])
            if len(keys) <= available:
                self.assertEqual(len(keys), len(set(keys)), (cast.seed, cast.era, archetype))


if __name__ == "__main__":
    unittest.main()
