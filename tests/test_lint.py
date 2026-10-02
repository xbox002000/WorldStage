"""Script lint: it finds each kind of fault in a small hand-made episode, says nothing about a clean one, and only reads."""
from __future__ import annotations

import unittest

from narrative import lint as L
from tests.test_opportunity import fingerprint


def event(eid, etype="talk", day=3, caption="阿明和阿凱聊天", speaker="", listener="", say="", answer="", facts=None, mind=None, reactions=None):
    e = {"id": eid, "type": etype, "day": day, "caption": caption, "facts": facts or {}}
    if say:
        e["speech"] = {"say": say, "answer": answer, "subtext": "", "speaker": speaker, "listener": listener, "reactions": reactions or []}
    if mind:
        e["mind"] = mind
    return e


def beat(index, events, who=("阿明", "阿凱"), shoot=True, derived=False, recap=False, story="A", reason=""):
    b = {"index": index, "event_ids": [e["id"] for e in events], "events": events, "who": list(who), "shoot": shoot, "derived": derived, "story": story,
         "reason": reason, "checklist": {"leaves_question": ""}}
    if recap:
        b["recap"] = True
    return b


def episode(beats, day=3, core="阿明和阿凱會和好，還是徹底決裂？", ending="阿明接下來會怎麼做？", people=("阿明", "阿凱"), grammar=(), cold=""):
    return {"day": day, "core_question": core, "ending_question": ending, "people_names": list(people), "beats": beats, "grammar": list(grammar), "cold_open": cold}


NAMES = ["阿明", "阿凱", "小美", "阿蘭", "阿豪", "阿濤"]


def clean():
    return episode([
        beat(0, [event(1, "tell", say="有件事我想讓你知道：我弄丟了錢袋。", speaker="阿明", listener="阿凱", caption="阿明告訴阿凱一件事")]),
        beat(1, [event(2, "duel", caption="阿明和阿凱比武", speaker="阿明", listener="阿凱", say="接招！", facts={"winner": "阿明", "loser": "阿凱"})]),
        beat(2, [event(3, "talk", say="今天算你贏。", speaker="阿凱", listener="阿明")]),
    ])


def kinds(issues):
    return sorted({f"{i.code}.{i.kind}" for i in issues})


class Clean(unittest.TestCase):
    def test_a_clean_episode_has_no_problem(self):
        self.assertEqual(L.lint_episode(clean(), names=NAMES), [])

    def test_a_quiet_day_has_nothing_to_lint(self):
        self.assertEqual(L.lint_season([None, clean(), None], names=NAMES)[0], [])


class Speech(unittest.TestCase):
    def test_l1_somebody_who_speaks_of_themselves_by_name(self):
        ep = episode([beat(0, [event(1, "tell", say="我聽說阿明弄丟了錢袋。", speaker="阿明", listener="阿凱")])])
        self.assertIn("L1.self_third", kinds(L.lint_episode(ep, names=NAMES)))

    def test_l1_a_thing_about_the_listener_told_to_the_listener_as_news(self):
        ep = episode([beat(0, [event(1, "tell", say="你知道嗎？阿凱沒有拿走戒指。", speaker="阿明", listener="阿凱")])])
        self.assertIn("L1.told_about_self", kinds(L.lint_episode(ep, names=NAMES)))

    def test_l1_a_third_person_named_in_a_rumour_is_fine(self):
        ep = episode([beat(0, [event(1, "tell", say="你知道嗎？小美弄丟了戒指。", speaker="阿明", listener="阿凱")])])
        self.assertEqual([i for i in L.lint_episode(ep, names=NAMES) if i.code == "L1"], [])

    def test_l2_a_tone_passed_on_word_for_word(self):
        for say in ("你知道嗎？阿濤冷淡地對阿豪說話。", "我聽說阿濤敵意地質問阿豪。", "你說過「阿豪親切地對小美說話」，是真的嗎？"):
            ep = episode([beat(0, [event(1, "tell", say=say, speaker="阿明", listener="阿凱")])])
            self.assertIn("L2.tone_gossip", kinds(L.lint_episode(ep, names=NAMES)), say)

    def test_l2_the_gist_of_a_tone_is_not_the_tone(self):
        ep = episode([beat(0, [event(1, "tell", say="聽說了嗎？阿濤和阿豪最近不太對勁。", speaker="阿明", listener="阿凱")])])
        self.assertEqual([i for i in L.lint_episode(ep, names=NAMES) if i.code == "L2"], [])

    def test_l8_a_loser_who_speaks_like_a_winner_and_a_winner_who_speaks_like_a_loser(self):
        duel = event(10, "duel", caption="阿豪和阿濤比武", speaker="阿豪", listener="阿濤", say="接招！", facts={"winner": "阿豪", "loser": "阿濤"})
        wrong = episode([beat(0, [duel], ("阿豪", "阿濤")), beat(1, [event(11, "talk", say="你才是！", speaker="阿濤", listener="阿豪")], ("阿濤", "阿豪"))],
                        people=("阿豪", "阿濤"))
        self.assertIn("L8.loser_sounds_like_winner", kinds(L.lint_episode(wrong, names=NAMES)))
        wrong2 = episode([beat(0, [duel], ("阿豪", "阿濤")), beat(1, [event(11, "talk", say="我輸了。", speaker="阿豪", listener="阿濤")], ("阿豪", "阿濤"))],
                         people=("阿豪", "阿濤"))
        self.assertIn("L8.winner_sounds_like_loser", kinds(L.lint_episode(wrong2, names=NAMES)))
        right = episode([beat(0, [duel], ("阿豪", "阿濤")), beat(1, [event(11, "talk", say="技不如人，我認了。", speaker="阿濤", listener="阿豪")], ("阿濤", "阿豪")),
                         beat(2, [event(12, "talk", say="承讓。", speaker="阿豪", listener="阿濤")], ("阿豪", "阿濤"))], people=("阿豪", "阿濤"))
        self.assertEqual([i for i in L.lint_episode(right, names=NAMES) if i.code == "L8"], [])

    def test_l8_a_line_of_somebody_else_after_the_duel_is_not_judged(self):
        duel = event(10, "duel", say="接招！", speaker="阿豪", listener="阿濤", facts={"winner": "阿豪", "loser": "阿濤"})
        ep = episode([beat(0, [duel], ("阿豪", "阿濤")), beat(1, [event(11, "talk", say="你才是！", speaker="小美", listener="阿蘭")], ("小美", "阿蘭"))])
        self.assertEqual([i for i in L.lint_episode(ep, names=NAMES) if i.code == "L8"], [])


class Time(unittest.TestCase):
    def test_l3_an_event_of_another_day_without_a_recap_mark(self):
        ep = episode([beat(0, [event(1, day=0, say="嗯。", speaker="阿明", listener="阿凱")])], day=3)
        self.assertIn("L3.stale_event", kinds(L.lint_episode(ep, names=NAMES)))

    def test_l3_a_marked_recap_is_allowed(self):
        ep = episode([beat(0, [event(1, day=2, say="嗯。", speaker="阿明", listener="阿凱")], recap=True)], day=3)
        self.assertEqual([i for i in L.lint_episode(ep, names=NAMES) if i.code == "L3"], [])

    def test_l3_the_same_event_filmed_twice(self):
        first = episode([beat(0, [event(7, day=2)])], day=2)
        again = episode([beat(0, [event(7, day=2)], recap=True)], day=3)
        self.assertIn("L3.replayed_event", kinds(L.lint_episode(again, prior=[first], names=NAMES)))

    def test_an_event_not_filmed_is_not_counted(self):
        ep = episode([beat(0, [event(1, day=0)], shoot=False), beat(1, [event(2, day=3)])], day=3)
        self.assertEqual([i for i in L.lint_episode(ep, names=NAMES) if i.code == "L3"], [])

    def test_l4_a_caption_that_is_the_systems_word(self):
        for cap in ("intervention", "小雲backstory"):
            ep = episode([beat(0, [event(1, "intervention", caption=cap)])])
            self.assertIn("L4.untranslated_caption", kinds(L.lint_episode(ep, names=NAMES)), cap)
        ep = episode([beat(0, [event(1, "intervention", caption="掌門宣布：悅來客棧將在第2天舉行比武大會")])])
        self.assertEqual([i for i in L.lint_episode(ep, names=NAMES) if i.code == "L4"], [])

    def test_l4_the_set_up_after_the_reversal(self):
        g = [{"step": "belittled", "event_ids": [238], "present": True}, {"step": "reversal", "event_ids": [235], "present": True}]
        ep = episode([beat(0, [event(235, "duel", caption="阿豪和阿濤比武")])], grammar=g)
        self.assertIn("L4.step_out_of_order", kinds(L.lint_episode(ep, names=NAMES)))
        g_ok = [{"step": "belittled", "event_ids": [200], "present": True}, {"step": "reversal", "event_ids": [235], "present": True}]
        ok = episode([beat(0, [event(235, "duel", caption="阿豪和阿濤比武")])], grammar=g_ok)
        self.assertEqual([i for i in L.lint_episode(ok, names=NAMES) if i.code == "L4"], [])

    def test_a_missing_step_is_not_out_of_order(self):
        g = [{"step": "belittled", "event_ids": [], "present": False}, {"step": "reversal", "event_ids": [235], "present": True}]
        self.assertEqual(L.check_grammar_order(episode([], grammar=g)), [])


class Questions(unittest.TestCase):
    def ep(self, day, core="誰拿了戒指？", ending="阿明接下來會怎麼做？"):
        return episode([beat(0, [event(day * 10, day=day)])], day=day, core=core, ending=ending)

    def test_l5_the_same_core_question_within_seven_days_but_not_after(self):
        first = self.ep(2)
        self.assertIn("L5.core_repeated", kinds(L.lint_episode(self.ep(8), prior=[first], names=NAMES)))
        self.assertNotIn("L5.core_repeated", kinds(L.lint_episode(self.ep(9), prior=[first], names=NAMES)))

    def test_l5_the_same_ending_question_in_the_last_three_episodes_but_not_the_fourth_back(self):
        prior = [self.ep(d, core=f"問題{d}") for d in (1, 2, 3, 4)]
        self.assertIn("L5.ending_repeated", kinds(L.lint_episode(self.ep(5, core="新的問題"), prior=prior[1:], names=NAMES)))
        self.assertNotIn("L5.ending_repeated", kinds(L.lint_episode(self.ep(5, core="新的問題"), prior=[prior[0]] + [self.ep(d, core=f"問題{d}", ending="阿凱能守住嗎？") for d in (2, 3, 4)], names=NAMES)))

    def test_l5_an_ending_about_people_who_are_not_in_the_episode_or_not_there_at_all(self):
        self.assertIn("L5.ending_not_here", kinds(L.lint_episode(self.ep(3, ending="小美會發現阿蘭欺騙了她嗎？"), names=NAMES)))
        self.assertIn("L5.no_ending", kinds(L.lint_episode(self.ep(3, ending=""), names=NAMES)))
        self.assertIn("L5.ending_unnamed", kinds(L.lint_episode(self.ep(3, ending="他的實力什麼時候會被看見？"), names=NAMES)))

    def test_l5_a_question_whose_premise_is_false_or_already_answered(self):
        lost_by_owner = {"objects": {"戒指": {"owner": "小美", "other_takes": 0, "found_day": None, "retaken": False}}}
        self.assertIn("L5.false_premise", kinds(L.lint_episode(self.ep(3), names=NAMES, facts=lost_by_owner)))
        taken = {"objects": {"戒指": {"owner": "小美", "other_takes": 1, "found_day": None, "retaken": False}}}
        self.assertNotIn("L5.false_premise", kinds(L.lint_episode(self.ep(3), names=NAMES, facts=taken)))
        found = {"objects": {"戒指": {"owner": "小美", "other_takes": 1, "found_day": 1, "retaken": False}}}
        self.assertIn("L5.already_answered", kinds(L.lint_episode(self.ep(3), names=NAMES, facts=found)))
        again = {"objects": {"戒指": {"owner": "小美", "other_takes": 2, "found_day": 1, "retaken": True}}}
        self.assertNotIn("L5.already_answered", kinds(L.lint_episode(self.ep(3), names=NAMES, facts=again)))


class Modern(unittest.TestCase):
    def test_l6_a_word_of_our_own_time_in_speech_captions_or_the_minds_words(self):
        for e in (event(1, say="我想買新手機。", speaker="阿明", listener="阿凱"), event(1, caption="阿明在喝咖啡"),
                  event(1, say="嗯。", speaker="阿明", listener="阿凱", mind={"reason": "那張新專輯真好聽", "inner": ""})):
            self.assertIn("L6.modern_word", kinds(L.lint_episode(episode([beat(0, [e])]), names=NAMES)))

    def test_l6_also_in_the_cold_open_and_the_questions(self):
        self.assertIn("L6.modern_word", kinds(L.lint_episode(episode([beat(0, [event(1)])], cold="阿明想要「存錢買新手機」"), names=NAMES)))

    def test_a_town_may_say_them(self):
        ep = episode([beat(0, [event(1, say="我想買新手機。", speaker="阿明", listener="阿凱")])])
        self.assertEqual([i for i in L.lint_episode(ep, names=NAMES, jianghu=False) if i.code == "L6"], [])

    def test_the_word_list_can_be_extended(self):
        ep = episode([beat(0, [event(1, say="這把劍是鋼筆做的。", speaker="阿明", listener="阿凱")])])
        self.assertEqual([i for i in L.lint_episode(ep, names=NAMES) if i.code == "L6"], [])
        self.assertTrue([i for i in L.lint_episode(ep, names=NAMES, modern=L.MODERN_WORDS + ("鋼筆",)) if i.code == "L6"])


class Measures(unittest.TestCase):
    def test_a_line_said_twice_the_same_people_in_a_row_and_how_much_is_talk(self):
        ep = episode([beat(0, [event(1, "talk", say="嗯。", speaker="阿明", listener="阿凱")]), beat(1, [event(2, "tell", say="嗯。", speaker="阿凱", listener="阿明")]),
                      beat(2, [event(3, "duel", say="接招！", speaker="阿明", listener="阿凱")]), beat(3, [event(4, "duel")], ("小美", "阿蘭"))])
        m = L.metrics(ep)
        self.assertEqual((m["dup_lines"], m["max_pair_streak"], m["beats"], m["chat_beats"], m["chat_share"]), (1, 3, 4, 2, 0.5))

    def test_the_second_look_at_an_event_is_not_a_second_beat(self):
        d = event(1, "duel", say="接招！", speaker="阿明", listener="阿凱")
        ep = episode([beat(0, [d]), beat(1, [d], derived=True)])
        self.assertEqual(L.metrics(ep)["beats"], 1)
        self.assertEqual(L.metrics(ep)["dup_lines"], 0)

    def test_the_same_two_people_the_same_kind_of_talk_twice_is_a_repeat_and_a_montage_beat_is_one(self):
        two = episode([beat(0, [event(1, "talk")]), beat(1, [event(2, "duel")], ("小美", "阿蘭")), beat(2, [event(3, "talk")])])
        self.assertEqual(L.metrics(two)["pair_kind_repeats"], 1)
        one = episode([beat(0, [event(1, "talk"), event(3, "talk")], reason="montage: 2 rounds")])
        self.assertEqual(L.metrics(one)["pair_kind_repeats"], 0)

    def test_how_many_of_a_days_hard_events_an_episode_took(self):
        ep = episode([beat(0, [event(5, "duel")]), beat(1, [event(6, "talk")], shoot=False)])
        self.assertEqual(L.hard_taken(ep, [{"id": 5}, {"id": 6}, {"id": 9}]), (3, 1))

    def test_what_a_hard_event_is(self):
        for t in ("duel", "shove", "strike", "smash", "break_down", "defect", "found_faction", "succession", "confession", "steal"):
            self.assertTrue(L.is_hard(t, {}), t)
        self.assertTrue(L.is_hard("confront", {"outcome": "lie_exposed"}))
        self.assertTrue(L.is_hard("accuse", {"outcome": "caught"}))
        for t in ("talk", "tell", "eat", "train", "praise"):
            self.assertFalse(L.is_hard(t, {}), t)
        self.assertFalse(L.is_hard("confront", {"outcome": "unfounded"}))


class OnAWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_episode_planner import produced
        cls.c = produced(17, 8)

    def test_the_hard_events_of_a_day_and_what_the_world_settled_about_a_thing_are_read_from_the_world(self):
        total = [h for d in range(8) for h in L.hard_events(self.c, d)]
        self.assertTrue(total)
        for h in total:
            row = self.c.execute("SELECT type FROM events WHERE event_id = ?", (h["id"],)).fetchone()
            self.assertEqual(row[0], h["type"])
        facts = L.object_facts(self.c, 7)["objects"]
        for info in facts.values():
            self.assertTrue({"owner", "other_takes", "found_day", "retaken"} <= set(info))

    def test_the_lint_only_reads(self):
        before = fingerprint(self.c)
        from narrative import episode_planner as P
        from narrative.dramaturgy import analyse
        sit = analyse(self.c)["situations"]
        shown: set[int] = set()
        plans = []
        ledger = P.Ledger()
        for day in range(8):
            p = P.plan_day(self.c, day, shown, sit, (), P.SHOW, ledger)
            if p is not None:
                plans.append(L.resolve(self.c, p))
                shown |= {i for b in p.beats for i in b.event_ids}
        self.assertTrue(plans)
        for ep in plans:
            L.lint_episode(ep, names=[])
            L.metrics(ep)
        self.assertEqual(fingerprint(self.c), before)

    def test_a_season_report_counts_by_kind_and_reads_a_studio_document_only(self):
        ep = clean()
        bad = episode([beat(0, [event(1, "tell", say="我聽說阿明弄丟了錢袋。", speaker="阿明", listener="阿凱")])], day=4)
        doc = {"meta": {"recipe": "jianghu_story_v1"}, "people": [{"name": n} for n in NAMES],
               "days": [{"day": 3, "episode": ep, "hard": [{"id": 2, "type": "duel", "kind": "duel"}]}, {"day": 4, "episode": bad, "hard": [{"id": 99, "type": "duel", "kind": "duel"}]}, {"day": 5, "episode": None}]}
        r = L.season_report(doc)
        self.assertEqual(r["issues"]["by_kind"].get("L1.self_third"), 1)
        self.assertEqual((r["hard_days"], r["hard_days_taken"], r["hard_day_rate"]), (2, 1, 0.5))
        self.assertEqual(r["episodes"], 2)


class Captions(unittest.TestCase):
    def test_no_event_that_a_story_can_hold_is_captioned_in_the_systems_words(self):
        from runtime.godview import caption
        names = {"yun": "小雲", "mei": "小美", "ring": "戒指"}
        got = {
            "backstory": caption("backstory", {"actor": "yun", "text": "很久以前，小雲拿走了小美的戒指"}, "", names),
            "gather": caption("intervention", {"kind": "announce_gathering", "text": "悅來客棧將在第2天舉行比武大會"}, "", names),
            "parcel": caption("intervention", {"kind": "deliver_parcel", "text": "有人送來了一個給小美的戒指"}, "", names),
            "secret": caption("intervention", {"kind": "cast_role", "text": ""}, "", names),
            "prize": caption("cash_prize", {"actor": "yun"}, "", names),
            "breakthrough": caption("breakthrough", {"actor": "yun"}, "", names),
        }
        for k, v in got.items():
            self.assertFalse(L.SYSTEM_WORD.search(v), (k, v))
        self.assertIn("掌門宣布", got["gather"])
        self.assertTrue(got["backstory"].startswith("（前情）"))


if __name__ == "__main__":
    unittest.main()
