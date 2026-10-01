"""The evidence graph: every field of a genome rests on claims with evidence, disagreements stay, and a fictionalized
genome's evidence gives nobody away."""
from __future__ import annotations

import dataclasses
import unittest

from contracts.base import canonical_json, from_dict, to_dict
from contracts.persona import Evidence, EvidenceSource, PersonaClaim, PersonaEvidence
from tests.test_persona import public_figure, world
from world import persona_evidence as pe
from world import personas


def ming():
    return personas.genome(world(), "ming")


class Authored(unittest.TestCase):
    def test_an_invented_character_is_covered_by_the_authors_word(self):
        for pid in ("ming", "mei", "yun"):
            g = personas.genome(world(), pid)
            ev = pe.authored(g)
            self.assertEqual(pe.check(g, ev), [], pid)
            self.assertEqual(pe.uncovered(g, ev), [])
            self.assertEqual(len(ev.claims), len(pe.fields(g)))
            self.assertTrue(all(c.kind == "authored" and c.confidence == 1.0 for c in ev.claims))

    def test_fields_lists_what_the_genome_says(self):
        g = ming()
        f = pe.fields(g)
        self.assertIn("temperament.temper", f)
        self.assertIn("profile.values.truth", f)
        self.assertTrue(any(x.startswith("profile.habits[") for x in f))
        self.assertTrue(any(x.startswith("profile.core.") for x in f))
        self.assertEqual(len(f), len(set(f)))
        self.assertFalse(any(x.startswith("formative") for x in f))  # it has none

    def test_the_evidence_round_trips(self):
        ev = pe.authored(ming())
        self.assertEqual(from_dict(PersonaEvidence, to_dict(ev)), ev)
        self.assertEqual(ev.hash(), from_dict(PersonaEvidence, to_dict(ev)).hash())


class Checking(unittest.TestCase):
    def setUp(self):
        self.g = public_figure()
        s = [EvidenceSource("talk", "一場公開演講", locator="12:30", period="2015"),
             EvidenceSource("book", "一本傳記", locator="第三章", period="1990-2010", reliability=0.8)]
        self.ev = PersonaEvidence(self.g.genome_id, s, [
            PersonaClaim("c1", "decisions.typical_choices[0]", "做決定先問第一性原理", "stated", 0.9, [Evidence("talk", "我習慣從第一性原理想")]),
            PersonaClaim("c2", "decisions.typical_choices[0]", "有時憑直覺一口氣決定", "inferred", 0.4,
                         [Evidence("book", "他在會議上突然拍板")], contradicts=["c1"]),
            PersonaClaim("c3", "temperament", "整體直接", "inferred", 0.6, [Evidence("book")]),
            PersonaClaim("c4", "formative", "早年的經歷", "stated", 0.8, [Evidence("book")]),
        ])

    def test_a_graph_with_gaps_is_refused_until_they_are_filled(self):
        bad = pe.check(self.g, self.ev)
        self.assertTrue(any(b.startswith("no evidence for profile.values") for b in bad))
        self.assertEqual(pe.check(self.g, self.ev, complete=False), [])

    def test_contradictions_stay_and_are_listed(self):
        self.assertEqual(pe.conflicts(self.ev), [("c1", "c2")])
        both = pe.why(self.ev, "decisions.typical_choices[0]")
        self.assertEqual([c.id for c in both], ["c1", "c2"])  # strongest first, and neither erased the other
        self.assertEqual([c.id for c in pe.why(self.ev, "temperament.temper")], ["c3"])  # a group speaks for its members

    def test_what_is_wrong_is_said(self):
        ev = self.ev
        cases = {
            "nothing behind it": dataclasses.replace(ev, claims=ev.claims + [PersonaClaim("c9", "temperament", "x", "inferred", 0.5)]),
            "unknown source": dataclasses.replace(ev, claims=ev.claims + [PersonaClaim("c9", "temperament", "x", "stated", 0.5, [Evidence("nope")])]),
            "outside 0..1": dataclasses.replace(ev, claims=ev.claims + [PersonaClaim("c9", "temperament", "x", "stated", 1.5, [Evidence("talk")])]),
            "listed twice": dataclasses.replace(ev, claims=ev.claims + [ev.claims[0]]),
            "is not there": dataclasses.replace(ev, claims=ev.claims + [PersonaClaim("c9", "temperament", "x", "stated", 0.5, [Evidence("talk")], contradicts=["zzz"])]),
            "nothing at": dataclasses.replace(ev, claims=ev.claims + [PersonaClaim("c9", "knowledge.knows[7]", "x", "stated", 0.5, [Evidence("talk")])]),
            "evidence is for": dataclasses.replace(ev, genome_id="genome:other"),
        }
        for want, bad_ev in cases.items():
            problems = pe.check(self.g, bad_ev, complete=False)
            self.assertTrue(any(want in p for p in problems), (want, problems))


class Fictionalizing(unittest.TestCase):
    def setUp(self):
        self.raw = public_figure()
        s = [EvidenceSource("talk", "林大偉在宏達電子的演講", locator="12:30"), EvidenceSource("book", "《大偉哥傳》", locator="第三章")]
        self.ev = PersonaEvidence(self.raw.genome_id, s, [
            PersonaClaim("c1", "decisions.risk[0]", "敢賭，但留退路", "stated", 0.9, [Evidence("talk", "林大偉：我總會留一條退路")]),
            PersonaClaim("c2", "formative[0]", "2008 年撐過危機", "stated", 0.8, [Evidence("book", "賣掉房子")]),
            PersonaClaim("c3", "formative[1]", "小時候家裡很窮", "stated", 0.7, [Evidence("book")], contradicts=["c2"]),
            PersonaClaim("c4", "beliefs[0]", "大偉哥說沒有退路才會想出路", "inferred", 0.6, [Evidence("talk")], contradicts=["c1"]),
        ])

    def test_the_evidence_gives_nobody_away(self):
        fake, ev, banned = personas.fictionalize_all(self.raw, self.ev, name="周明遠", replacements={"宏達電子": "遠景科技"},
                                                      remove=["2008 年"])
        text = canonical_json(to_dict(ev))
        for term in ("林大偉", "大偉哥", "宏達電子", "2008", "傳", "12:30", "第三章", "賣掉房子"):
            self.assertNotIn(term, text)
        self.assertEqual(ev.genome_id, fake.genome_id)
        self.assertEqual([s.id for s in ev.sources], ["redacted"])
        self.assertTrue(all(e.source == "redacted" for c in ev.claims for e in c.evidence))
        self.assertEqual(personas.scan([text], banned), [])

    def test_what_was_dropped_takes_its_claims_and_the_rest_move_with_their_fields(self):
        fake, ev, _ = personas.fictionalize_all(self.raw, self.ev, name="周明遠", replacements={"宏達電子": "遠景科技"},
                                                 remove=["2008 年"])
        by = {c.id: c for c in ev.claims}
        self.assertNotIn("c2", by)  # the dated event is gone, so is the claim about it
        self.assertEqual(by["c3"].field, "formative[0]")  # the childhood moved up into its place
        self.assertEqual(fake.formative[0].kind, "childhood")
        self.assertEqual(by["c3"].contradicts, [])  # what it disagreed with is not there any more
        self.assertEqual(by["c4"].contradicts, ["c1"])  # a disagreement that is left stays
        self.assertEqual(by["c4"].statement, "周明遠說沒有退路才會想出路")  # the alias is swapped, not lost
        self.assertEqual(pe.check(fake, ev, complete=False), [])  # every claim still points at something the genome says

    def test_an_alias_in_the_evidence_is_swapped_like_the_name(self):
        leaky = dataclasses.replace(self.ev, claims=self.ev.claims + [
            PersonaClaim("c5", "persona_text", "他的暱稱是阿偉仔", "stated", 0.5, [Evidence("talk")])])
        raw = dataclasses.replace(self.raw, origin=dataclasses.replace(self.raw.origin, real_names=["林大偉", "阿偉仔"]))
        fake, ev, banned = personas.fictionalize_all(raw, dataclasses.replace(leaky, genome_id=raw.genome_id), name="周明遠")
        self.assertNotIn("阿偉仔", canonical_json(to_dict(ev)))  # an alias is swapped like the name


if __name__ == "__main__":
    unittest.main()
