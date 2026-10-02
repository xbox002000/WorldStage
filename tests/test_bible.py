"""The Bible: a standing, model-neutral description of the cast and the places, made from the world and only read from it."""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from typing import get_args

from contracts import bible as cb
from contracts.base import canonical_json, from_dict, schema_for, to_dict
from contracts.bible import Bible, ReferenceAsset, check_bible, model_words_in
from production import bible as pb
from production.bible import BibleError, build_bible
from tests.provider_conformance.worlds import bible_for_recipe, world_from_recipe
from world.db import connect, init_db, save_to
from world.personas import extras_override, genome

RECIPES = ("jianghu_story_v1", "town_v1", "town_in_jianghu_v1")


class Contract(unittest.TestCase):
    def test_the_committed_schema_is_the_dataclass(self):
        path = Path(cb.__file__).with_name("schemas") / "bible.schema.json"
        self.assertTrue(path.exists(), "run python -m contracts.bible")
        self.assertEqual(path.read_text(encoding="utf-8").replace("\r\n", "\n"), cb.schema_text())
        schema = schema_for(Bible)
        self.assertEqual(set(schema["$defs"]), {"Bible", "CharacterAsset", "SceneAsset", "Look", "VoiceDescription", "ReferenceAsset"})
        asset = schema["$defs"]["CharacterAsset"]
        self.assertEqual(set(asset["required"]), {f.name for f in dataclasses.fields(cb.CharacterAsset)
                                                  if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING})
        self.assertEqual(set(asset["properties"]), {f.name for f in dataclasses.fields(cb.CharacterAsset)})

    def test_the_reference_kinds_listed_are_the_ones_the_type_allows(self):
        self.assertEqual(set(cb.REFERENCE_KINDS), set(get_args(cb.ReferenceKind)))

    def test_it_round_trips_through_json_and_keeps_its_hash(self):
        b = bible_for_recipe("jianghu_story_v1")
        back = from_dict(Bible, json.loads(canonical_json(to_dict(b))))
        self.assertEqual(back, b)
        self.assertTrue(cb.verify(back))

    def test_a_model_word_is_found_whole_word_only(self):
        self.assertEqual(model_words_in(["a cinematic, 8K portrait", "Bokeh"]), ["8k", "bokeh", "cinematic"])
        self.assertEqual(model_words_in(["Glenside", "a lensman", "家具8kg"]), [])
        self.assertEqual(model_words_in(["方正的臉，法令紋深"]), [])

    def test_the_gate_catches_model_words_banned_names_a_stale_hash_and_misfiled_assets(self):
        b = bible_for_recipe("jianghu_story_v1")
        self.assertEqual(check_bible(b), [])
        some = next(iter(b.characters.values()))
        dirty = dataclasses.replace(some, standard_description=some.standard_description + " cinematic 8k")
        bad = check_bible(dataclasses.replace(b, characters={**b.characters, some.asset_id: dirty}))
        self.assertTrue(any("cinematic" in x for x in bad) and any("8k" in x for x in bad))
        found = check_bible(b, banned=[some.costume])
        self.assertTrue(any("banned name" in x for x in found))
        self.assertEqual(check_bible(b, banned=["王大明"]), [])
        self.assertTrue(any("bible_hash" in x for x in check_bible(dataclasses.replace(b, world="elsewhere"))))
        self.assertTrue(any("filed under" in x for x in check_bible(dataclasses.replace(b, characters={"x": some}, bible_hash=""))))
        self.assertTrue(any("unknown kind" in x for x in check_bible(dataclasses.replace(
            b, characters={some.asset_id: dataclasses.replace(some, references=[ReferenceAsset("selfie", "p")])}, bible_hash=""))))

    def test_it_is_registered_with_the_versions(self):
        from contracts.versions import VERSIONS
        self.assertEqual(VERSIONS["bible_contract"], cb.BIBLE_VERSION)
        self.assertEqual(cb.BIBLE_VERSION, "bible_v0.1")


class Building(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = {r: world_from_recipe(r) for r in RECIPES}
        cls.bibles = {r: build_bible(c) for r, c in cls.worlds.items()}

    @classmethod
    def tearDownClass(cls):
        for c in cls.worlds.values():
            c.close()

    def test_the_same_world_gives_the_same_bible_with_the_same_hash(self):
        for r, c in self.worlds.items():
            again = build_bible(c)
            self.assertEqual(again.bible_hash, self.bibles[r].bible_hash, r)
            self.assertEqual(again, self.bibles[r])
        # and a world built again from the recipe, not only the same connection
        self.assertEqual(bible_for_recipe("jianghu_story_v1").bible_hash, self.bibles["jianghu_story_v1"].bible_hash)

    def test_it_only_reads_the_world(self):
        c = world_from_recipe("jianghu_story_v1")
        before = c.total_changes
        rows = [tuple(r) for t in ("character_genomes", "character_profiles", "locations", "meta")
                for r in c.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
        build_bible(c)
        self.assertEqual(c.total_changes, before)
        self.assertEqual(rows, [tuple(r) for t in ("character_genomes", "character_profiles", "locations", "meta")
                                for r in c.execute(f"SELECT * FROM {t} ORDER BY 1, 2")])

    def test_a_path_is_opened_read_only_and_gives_the_same_bible(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_to(self.worlds["jianghu_story_v1"], Path(tmp) / "world.db")
            self.assertEqual(build_bible(path).bible_hash, self.bibles["jianghu_story_v1"].bible_hash)
        with self.assertRaises(BibleError):
            build_bible("jianghu_story_v1")  # a recipe is not a world; tests/provider_conformance/worlds.py makes one

    def test_everyone_and_every_place_is_described(self):
        for r, b in self.bibles.items():
            n_people = self.worlds[r].execute("SELECT COUNT(*) FROM character_genomes").fetchone()[0]
            n_places = self.worlds[r].execute("SELECT COUNT(*) FROM locations").fetchone()[0]
            self.assertEqual((len(b.characters), len(b.scenes)), (n_people, n_places), r)
            self.assertEqual(b.world, r)
            self.assertEqual(b.gaps, [])
            for key, c in b.characters.items():
                self.assertEqual(key, c.asset_id)
                self.assertTrue(c.standard_description and c.identity_lock and c.wardrobe_lock and c.voice.standard_description, c.person_id)
                self.assertEqual(c.lock_asset_id, f"char_{c.person_id}")
                self.assertEqual(c.references, [])  # reserved for a provider to fill
                self.assertNotIn(c.name, c.standard_description)
                self.assertEqual(c.gaps, [], f"{r}:{c.person_id}")
            for key, s in b.scenes.items():
                self.assertEqual(key, f"scene:{s.location_id}")
                self.assertIn(s.name, s.standard_description)
                self.assertTrue(s.layout_id.endswith(".v1") and s.layout_hash.startswith("sha256:") and all(x > 0 for x in s.footprint))

    def test_the_description_is_the_genomes_and_the_castings(self):
        c = self.worlds["jianghu_story_v1"]
        b = self.bibles["jianghu_story_v1"]
        for pid in ("hao", "ming", "mei"):
            g = genome(c, pid)
            a = b.character_for(pid)
            self.assertEqual(a.genome_id, g.genome_id)
            for text in (g.appearance.face, g.appearance.hair, g.appearance.build, g.voice.timbre, *g.appearance.marks):
                self.assertTrue(text in a.standard_description or text in a.voice.standard_description, (pid, text))
            self.assertIn(a.costume, a.standard_description)
            self.assertEqual(a.voice.catchphrases, g.voice.catchphrases)

    def test_one_genome_keeps_its_face_and_changes_its_clothes_between_worlds(self):
        town, story = self.bibles["town_v1"], self.bibles["jianghu_story_v1"]
        t, s = town.character_for("hao"), story.character_for("hao")
        self.assertEqual(t.genome_id, s.genome_id)               # the same person
        self.assertEqual(t.look, s.look)                         # with the same face
        self.assertEqual(t.voice, s.voice)
        self.assertNotEqual(t.costume, s.costume)                # dressed by each world
        self.assertNotEqual(t.asset_id, s.asset_id)              # so the asset is keyed by genome and casting
        self.assertEqual(t.asset_id.split(":")[1], s.asset_id.split(":")[1])
        self.assertNotEqual(town.bible_hash, story.bible_hash)

    def test_no_model_words_and_no_names_anywhere(self):
        for r, b in self.bibles.items():
            self.assertEqual(check_bible(b), [], r)
            self.assertEqual(model_words_in(list(cb._strings(to_dict(b)))), [], r)

    def test_a_banned_name_stops_it_and_so_does_a_real_name_the_genome_carries(self):
        with self.assertRaises(BibleError) as ctx:
            build_bible(self.worlds["jianghu_story_v1"], banned=["阿豪"])
        self.assertIn("阿豪", str(ctx.exception))
        marks = ["像王大明"]
        with extras_override({"hao": {"origin": {"kind": "original_character", "real_names": ["王大明"]},
                                      "appearance": {"face": "笑臉", "marks": marks}}}):
            c = world_from_recipe("jianghu_story_v1")
        with self.assertRaises(BibleError) as ctx:
            build_bible(c)
        self.assertIn("王大明", str(ctx.exception))

    def test_a_world_with_a_real_person_who_was_not_fictionalized_is_refused(self):
        with extras_override({"hao": {"origin": {"kind": "public_person", "real_names": ["王大明"]}}}):
            c = world_from_recipe("jianghu_story_v1")
        with self.assertRaises(BibleError):
            build_bible(c)

    def test_what_the_world_does_not_say_is_reported_not_invented(self):
        with extras_override({"hao": {"appearance": {"face": "笑臉", "hair": "", "build": "高大", "presence": "愛笑"},
                                      "voice": {"pace": "快"}}}):
            c = world_from_recipe("jianghu_story_v1")
        b = build_bible(c)
        a = b.character_for("hao")
        self.assertEqual(set(a.gaps), {"appearance.hair is not written", "appearance.marks is not written", "voice.timbre is not written"})
        self.assertNotIn("頭髮", a.standard_description)
        self.assertFalse(any(x.startswith("頭髮") or x.startswith("特徵") for x in a.identity_lock))
        self.assertTrue(b.character_for("ming").gaps)            # nobody else was written either

    def test_a_world_with_no_genomes_has_places_and_says_so(self):
        c = connect()
        init_db(c, 1)
        c.execute("INSERT INTO locations VALUES ('inn','悅來客棧',0,0,10,'[\"food\"]')")
        b = build_bible(c)
        self.assertEqual((b.characters, list(b.scenes)), ({}, ["scene:inn"]))
        self.assertTrue(b.gaps)

    def test_a_scene_is_described_from_its_layout(self):
        b = self.bibles["jianghu_story_v1"]
        inn = b.scene_for("inn")
        self.assertEqual((inn.name, inn.layout_id, inn.footprint), ("悅來客棧", "cafe.v1", [14.0, 10.0]))
        self.assertIn("5張桌子", inn.standard_description)
        self.assertIn("室內", inn.standard_description)
        self.assertIn("戶外", b.scene_for("road").standard_description)
        town = self.bibles["town_v1"].scene_for("cafe")
        self.assertEqual((town.layout_id, town.layout_hash), (inn.layout_id, inn.layout_hash))   # the same stage, another name


class Caching(unittest.TestCase):
    def test_a_cached_bible_is_read_back_and_a_damaged_one_is_made_again(self):
        c = world_from_recipe("jianghu_story_v1")
        with tempfile.TemporaryDirectory() as tmp:
            first = build_bible(c, cache=tmp)
            files = list(Path(tmp).glob("bible_*.json"))
            self.assertEqual(len(files), 1)
            real = pb._characters
            try:
                pb._characters = lambda conn: (_ for _ in ()).throw(AssertionError("built again"))
                self.assertEqual(build_bible(c, cache=tmp), first)    # a hit does not build
            finally:
                pb._characters = real
            data = json.loads(files[0].read_text(encoding="utf-8"))
            data["world"] = "tampered"
            files[0].write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertIsNone(pb.load_bible(files[0]))
            again = build_bible(c, cache=tmp)
            self.assertEqual(again, first)
            self.assertEqual(pb.load_bible(files[0]), first)       # and the file is repaired

    def test_a_changed_world_is_a_different_key(self):
        a, b = world_from_recipe("jianghu_story_v1"), world_from_recipe("town_v1")
        self.assertNotEqual(pb.world_key(a), pb.world_key(b))
        self.assertEqual(pb.world_key(a), pb.world_key(world_from_recipe("jianghu_story_v1")))
        with extras_override({"hao": {"appearance": {"face": "另一張臉"}}}):
            other = world_from_recipe("jianghu_story_v1")
        self.assertNotEqual(pb.world_key(a), pb.world_key(other))


if __name__ == "__main__":
    unittest.main()
