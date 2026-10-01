"""Circles, factions and the fight for a seat (world/domains/factions.py)."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from agent.volition import VolitionDecider
from contracts.intervention import InterventionProposal
from producer.intervention import Ledger
from world.db import connect, init_db
from world.domains import active, solidarity
from world.domains import factions as F
from world.events import Change, EventSpec, apply_event
from world.intent import Intent
from world.seed import build_world
from world.simulation import Simulation
from world.state import WorldError


def saga(seed: int = 3):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, "jianghu_saga_v1")
    return conn


def pack(conn):
    return next(d for d in active(conn) if d.id == "factions")


def now(conn):
    return conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]


def setup(conn, *changes):
    apply_event(conn, EventSpec(timestamp=now(conn), type="setup", trigger_type="rule", location_id=None, changes=list(changes)))


def tie(conn, a, b, affection=0.8, trust=0.5, familiarity=0.5):
    for x, y in ((a, b), (b, a)):
        cur = {f: conn.execute(f"SELECT {f} FROM relationships WHERE actor_id = ? AND target_id = ?", (x, y)).fetchone()[0]
               for f in ("affection", "trust", "familiarity")}
        setup(conn, *[Change("relationship", f"{x}:{y}", f, delta=round(v - cur[f], 6))
                      for f, v in (("affection", affection), ("trust", trust), ("familiarity", familiarity))])


def isolate(conn):
    """Everybody a stranger to everybody: no ties, no grudges (the start of a world already has some, from its seed)."""
    ch = []
    for r in conn.execute("SELECT actor_id, target_id, affection, trust, familiarity, resentment FROM relationships").fetchall():
        for f in ("affection", "trust", "familiarity", "resentment"):
            if r[f]:
                ch.append(Change("relationship", f"{r['actor_id']}:{r['target_id']}", f, delta=-r[f]))
    if ch:
        setup(conn, *ch)
    for r in conn.execute("SELECT key, value FROM world_vars WHERE key LIKE 'circle.%' AND value != 0").fetchall():
        setup(conn, Change("var", r["key"], "value", delta=-r["value"]))


def rel_set(conn, a, b, field, value):
    cur = conn.execute(f"SELECT {field} FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]
    setup(conn, Change("relationship", f"{a}:{b}", field, delta=round(value - cur, 6)))


def meet(conn, *people, place="qingyun"):
    ch = [Change("person", p, "location_id", value=place) for p in people
          if conn.execute("SELECT location_id FROM people WHERE id = ?", (p,)).fetchone()[0] != place]
    if ch:
        setup(conn, *ch)


def do(conn, action, a, b=None, roll=0.0):
    it = Intent(a, action, b, reason="volition")
    spec_ = pack(conn).actions[action]
    spec_.validate(conn, it, conn.execute("SELECT * FROM people WHERE id = ?", (a,)).fetchone())
    with mock.patch("world.domains.factions.make_rng") as rng:
        rng.return_value.random.return_value = roll
        spec = spec_.resolve(conn, it, now(conn) + 1, "decision")
    for d in active(conn):
        spec = d.effects(conn, spec, set())
    eid = apply_event(conn, spec)
    return eid, json.loads(conn.execute("SELECT truth FROM events WHERE event_id = ?", (eid,)).fetchone()[0])


def var(conn, key):
    return conn.execute("SELECT value FROM world_vars WHERE key = ?", (key,)).fetchone()[0]


def res(conn, a, b):
    return conn.execute("SELECT resentment FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]


class Circles(unittest.TestCase):
    def setUp(self):
        self.c = saga()
        isolate(self.c)

    def test_people_who_are_tied_keep_company_and_strangers_do_not(self):
        self.assertEqual(F.circles(self.c), [])
        tie(self.c, "lan", "rui")
        tie(self.c, "rui", "yun")
        tie(self.c, "lan", "yun")
        got = F.circles(self.c)
        self.assertIn(["lan", "rui", "yun"], got)
        self.assertFalse(any("ming" in g for g in got))

    def test_a_grudge_pulls_a_pair_out_of_a_circle(self):
        tie(self.c, "lan", "rui")
        self.assertIn(["lan", "rui"], F.circles(self.c))
        rel_set(self.c, "lan", "rui", "resentment", 0.9)
        rel_set(self.c, "rui", "lan", "resentment", 0.9)
        self.assertEqual(F.circles(self.c), [])

    def test_the_night_writes_the_circle_down_and_it_stays_put(self):
        tie(self.c, "lan", "rui")
        specs = pack(self.c).nightly(self.c, 0, 1400)
        self.assertEqual([s.type for s in specs], ["circles"])
        apply_event(self.c, specs[0])
        cid = F.circle_of(self.c, "lan")
        self.assertEqual((cid, F.circle_of(self.c, "rui")), (F.circle_id(self.c, ["lan", "rui"]), cid))
        self.assertEqual(F.circle_of(self.c, "ming"), 0)
        self.assertEqual(pack(self.c).nightly(self.c, 1, 2840), [])  # nothing changed: no event

    def test_one_of_ones_own_is_the_one_to_stand_by(self):
        self.assertEqual(solidarity(self.c, "ming", "kai"), F.SAME_FACTION)      # the sect
        self.assertEqual(solidarity(self.c, "ming", "lan"), 0.0)
        tie(self.c, "lan", "rui")
        apply_event(self.c, pack(self.c).nightly(self.c, 0, 1400)[0])
        self.assertEqual(solidarity(self.c, "lan", "rui"), F.SAME_CIRCLE)
        self.assertEqual(solidarity(self.c, "ming", "mei") <= 0, True)

    def test_a_bystander_takes_the_side_of_their_own(self):
        """agent/reply.py: the same quarrel, and a bystander of the victim's circle is likelier to stand by them."""
        from agent import reply
        isolate(self.c)
        meet(self.c, "ming", "kai", "mei", place="qingyun")
        eid = apply_event(self.c, EventSpec(timestamp=now(self.c), type="accuse", trigger_type="decision", location_id="qingyun", importance=0.6,
                                            truth={"actor": "kai", "target": "ming", "outcome": "false"},
                                            participants=[("kai", "actor"), ("ming", "target"), ("mei", "witness")]))
        row = self.c.execute("SELECT * FROM events WHERE event_id = ?", (eid,)).fetchone()

        def scores():
            seen = []
            with mock.patch.object(reply, "_pick", side_effect=lambda scored, rng: seen.append(list(scored)) or None):
                reply.Replier(3).intervene(self.c, row, now(self.c))
            by = {it.reason: s for s, it in seen[0] if it is not None}
            return by["intervene:comfort"], by["intervene:side"]

        before = scores()
        self.assertEqual(solidarity(self.c, "mei", "ming"), 0.0)
        # mei and ming keep company (a circle: the night writes it down), and nothing else about them changes
        setup(self.c, Change("var", "circle.mei", "value", delta=2.0), Change("var", "circle.ming", "value", delta=2.0))
        self.assertEqual(solidarity(self.c, "mei", "ming"), F.SAME_CIRCLE)
        after = scores()
        self.assertAlmostEqual(after[0] - before[0], 0.5 * F.SAME_CIRCLE, places=6)   # more likely to comfort the victim
        self.assertAlmostEqual(after[1] - before[1], 0.8 * F.SAME_CIRCLE, places=6)   # and to turn on the one who attacked them

    def test_one_believes_one_of_ones_own_more_readily(self):
        from contracts.claim import Claim
        from world.claims import describe_claim, labels
        from world.events import ClaimSpec, MemorySpec
        from world.social import resolve_tell
        isolate(self.c)
        meet(self.c, "kai", "ming", "mei", place="qingyun")
        claim = Claim("tao", "deceive", "jun")
        apply_event(self.c, EventSpec(timestamp=now(self.c), type="setup", trigger_type="rule", location_id="qingyun", importance=0.9,
                                      memories=[MemorySpec("kai", describe_claim(claim, labels(self.c)), 0.9, claim=claim)], claims=[ClaimSpec(claim)]))
        for listener in ("ming", "mei"):
            rel_set(self.c, listener, "kai", "trust", 0.3)
        cid = self.c.execute("SELECT claim_id FROM memories WHERE observer_id = 'kai' AND claim_id IS NOT NULL ORDER BY memory_id DESC LIMIT 1").fetchone()[0]
        got = {}
        for listener in ("ming", "mei"):
            spec = resolve_tell(self.c, Intent("kai", "tell", listener, claim_id=cid, mode="truth"), now(self.c) + 1, "decision")
            told = [m for m in spec.memories if m.observer_id == listener and m.claim is not None and m.claim.act == "deceive"]
            got[listener] = told[0].confidence
        self.assertGreater(got["ming"], got["mei"])  # the same words from the same mouth: one of kai's own, and one who is not


class Founding(unittest.TestCase):
    def setUp(self):
        self.c = saga()
        isolate(self.c)
        for a, b in (("lan", "rui"), ("rui", "yun"), ("lan", "yun")):
            tie(self.c, a, b)
        apply_event(self.c, pack(self.c).nightly(self.c, 0, 1400)[0])

    def test_a_circle_that_has_become_a_following_is_founded_as_a_faction(self):
        specs = pack(self.c).dawn(self.c, 1, 1440)
        found = [s for s in specs if s.type == "found_faction"]
        self.assertEqual(len(found), 1)
        apply_event(self.c, found[0])
        fid = found[0].truth["faction"]
        self.assertEqual(sorted(F.members(self.c, fid)), ["lan", "rui", "yun"])
        lead = F.leader_of(self.c, fid)
        self.assertIn(lead, ("lan", "rui", "yun"))
        self.assertEqual(self.c.execute("SELECT status FROM factions WHERE faction_id = ?", (fid,)).fetchone()[0], "active")
        self.assertEqual(self.c.execute("SELECT role FROM affiliations WHERE person_id = ?", (lead,)).fetchone()[0], "leader")
        self.assertEqual(solidarity(self.c, "lan", "rui"), F.SAME_FACTION + F.SAME_CIRCLE)

    def test_a_circle_of_two_is_not_a_faction_and_a_sect_member_is_not_founding_another(self):
        c = saga()
        isolate(c)
        tie(c, "lan", "rui")
        apply_event(c, pack(c).nightly(c, 0, 1400)[0])
        self.assertEqual([s for s in pack(c).dawn(c, 1, 1440) if s.type == "found_faction"], [])

    def test_no_slot_no_faction(self):
        for fid in ("f1", "f2", "f3", "f4"):
            setup(self.c, Change("faction", fid, "status", value="active"))
        self.assertEqual([s for s in pack(self.c).dawn(self.c, 1, 1440) if s.type == "found_faction"], [])


class Sides(unittest.TestCase):
    def setUp(self):
        self.c = saga()
        isolate(self.c)
        meet(self.c, "ming", "kai", "mei", "lan", "tao")

    def test_a_leader_recruits_and_the_other_decides_by_how_they_feel(self):
        tie(self.c, "mei", "lan")
        rel_set(self.c, "lan", "mei", "respect", 0.6)
        _, t = do(self.c, "recruit", "mei", "lan", roll=0.0)
        self.assertEqual((t["outcome"], t["founded"]), ("joined", True))
        fid = t["faction"]
        self.assertEqual((F.leader_of(self.c, fid), F.faction_of(self.c, "mei"), F.faction_of(self.c, "lan")), ("mei", fid, fid))
        self.assertIn("加入", t["text"])
        _, t2 = do(self.c, "recruit", "mei", "tao", roll=0.999)  # only a leader recruits, and it can be refused
        self.assertEqual(t2["outcome"], "declined")
        self.assertEqual(F.faction_of(self.c, "tao"), "qingyun")  # he stays where he was
        with self.assertRaises(WorldError):
            do(self.c, "recruit", "lan", "mei")  # lan is a member, not a leader

    def test_somebody_in_another_faction_leaves_it_at_a_price(self):
        tie(self.c, "mei", "tao")
        rel_set(self.c, "tao", "mei", "respect", 0.8)
        # tao is of the sect (qingyun, no leader on stage); mei founds her own and recruits him: the sect holds it against him
        tie(self.c, "mei", "lan")
        do(self.c, "recruit", "mei", "lan")
        _, t = do(self.c, "recruit", "mei", "tao", roll=0.0)
        self.assertEqual(t["left_faction"], "qingyun")
        self.assertGreater(res(self.c, "ming", "tao"), 0.05)  # his old side
        self.assertEqual(F.faction_of(self.c, "tao"), t["faction"])

    def test_leaving_costs_the_grudges_of_those_left(self):
        _, t = do(self.c, "defect", "tao")
        self.assertIsNone(F.faction_of(self.c, "tao"))
        self.assertGreater(res(self.c, "ming", "tao"), 0.05)
        self.assertFalse(t["was_leader"])
        with self.assertRaises(WorldError):
            do(self.c, "defect", "tao")  # in no faction now

    def test_a_leader_who_leaves_takes_the_leadership_with_them(self):
        tie(self.c, "mei", "lan")
        do(self.c, "recruit", "mei", "lan")
        fid = F.faction_of(self.c, "mei")
        do(self.c, "defect", "mei")
        self.assertIsNone(F.leader_of(self.c, fid) if self.c.execute("SELECT status FROM factions WHERE faction_id = ?", (fid,)).fetchone()[0] == "active" else None)
        self.assertGreater(res(self.c, "lan", "mei"), 0.2)  # a leader leaving is felt harder

    def test_a_recruiter_needs_room_for_a_faction(self):
        for fid in ("f1", "f2", "f3", "f4"):
            setup(self.c, Change("faction", fid, "status", value="active"))
        with self.assertRaises(WorldError):
            do(self.c, "recruit", "mei", "lan")


class Seats(unittest.TestCase):
    def setUp(self):
        self.c = saga()
        meet(self.c, "ming", "kai", "tao", "jun", "hao")
        v = Ledger().admit(self.c, InterventionProposal("iv", "S", "A", "open_seat", "chief_disciple", {"day": "3"}, 0, 3, "x"), now(self.c) + 1)
        self.assertTrue(v.admitted)

    def test_nobody_campaigns_for_a_seat_that_is_not_open(self):
        c = saga()
        meet(c, "ming", "kai")
        with self.assertRaises(WorldError):
            do(c, "campaign", "kai", "ming")

    def test_a_member_asks_another_for_support_and_is_remembered_as_standing(self):
        rel_set(self.c, "tao", "kai", "respect", 0.6)
        _, t = do(self.c, "campaign", "kai", "tao", roll=0.0)
        self.assertTrue(t["endorsed"])
        self.assertEqual(var(self.c, "cand.kai"), 1.0)
        self.assertEqual(F._pid(self.c, var(self.c, "vote.tao")), "kai")
        rel_set(self.c, "jun", "ming", "respect", 0.3)
        _, t2 = do(self.c, "campaign", "tao", "jun", roll=0.0)  # one who stands does not back a rival... and tao now promised kai
        self.assertTrue(t2["endorsed"])
        _, t3 = do(self.c, "campaign", "ming", "tao", roll=0.0)  # tao has promised kai already: the odds fall (the dice are rigged to say yes)
        self.assertLess(t3["p"], 0.5)
        rel_set(self.c, "kai", "tao", "respect", 0.2)
        _, t4 = do(self.c, "campaign", "tao", "kai", roll=0.0)  # kai is standing: will not back tao
        self.assertFalse(t4["endorsed"])

    def test_the_faction_votes_on_the_day_and_everything_is_recorded(self):
        do(self.c, "campaign", "kai", "tao", roll=0.0)
        do(self.c, "campaign", "ming", "jun", roll=0.0)
        specs = pack(self.c).dawn(self.c, 3, 3 * 1440)
        self.assertEqual([s.type for s in specs], ["succession"])
        eid = apply_event(self.c, specs[0])
        t = specs[0].truth
        self.assertEqual(sorted(t["candidates"]), ["kai", "ming"])
        self.assertEqual(set(t["votes"]), {"ming", "kai", "tao", "jun", "hao"})  # every member of the sect voted
        self.assertEqual(t["votes"]["kai"], "kai")
        self.assertEqual(t["votes"]["ming"], "ming")  # one who stands votes for oneself
        self.assertEqual(t["votes"]["tao"], "kai")    # and what was promised is kept
        self.assertEqual(sum(t["tally"].values()), 5.0)
        seat = self.c.execute("SELECT holder_id, status FROM seats WHERE seat_id = 'chief_disciple'").fetchone()
        self.assertEqual((seat[0], seat[1]), (t["winner"], "held"))
        self.assertEqual(var(self.c, "cand.kai"), 0.0)  # spent
        loser = "ming" if t["winner"] == "kai" else "kai"
        self.assertGreater(res(self.c, loser, t["winner"]), 0.1)  # the loser holds it against the winner
        self.assertEqual(pack(self.c).appraise(self.c, t["winner"], "succession", t)[0][0], "success")
        self.assertEqual(pack(self.c).appraise(self.c, loser, "succession", t)[0][0], "failure")

    def test_a_seat_nobody_stands_for_is_put_off_not_given_away(self):
        specs = pack(self.c).dawn(self.c, 3, 3 * 1440)
        self.assertEqual([s.type for s in specs], ["seat_put_off"])
        apply_event(self.c, specs[0])
        self.assertEqual(tuple(self.c.execute("SELECT status, decide_by, holder_id FROM seats WHERE seat_id = 'chief_disciple'").fetchone()),
                         ("vacant", 3 + F.EXTEND_DAYS, "ming"))

    def test_a_seat_is_not_decided_before_its_day(self):
        do(self.c, "campaign", "kai", "tao")
        self.assertEqual([s for s in pack(self.c).dawn(self.c, 2, 2 * 1440) if s.type == "succession"], [])


class Lives(unittest.TestCase):
    def test_a_month_has_circles_and_a_fight_for_the_seat_the_producer_opened(self):
        c = saga(3)
        ledger = Ledger()

        class Producer:
            def dawn(self, conn, day, at):
                if day == 3:
                    ledger.admit(conn, InterventionProposal("iv", "S", "A", "open_seat", "chief_disciple", {"day": "9"}, day, 3, "x"), at)

        d = VolitionDecider(3)
        Simulation(c, d, d, set(), feed="synthetic_v1", producer=Producer()).run(14)
        self.assertGreaterEqual(c.execute("SELECT COUNT(*) FROM events WHERE type = 'circles'").fetchone()[0], 1)
        self.assertGreaterEqual(c.execute("SELECT COUNT(*) FROM events WHERE type = 'campaign'").fetchone()[0], 2)
        succ = c.execute("SELECT truth FROM events WHERE type = 'succession'").fetchall()
        self.assertEqual(len(succ), 1)
        t = json.loads(succ[0][0])
        self.assertGreaterEqual(len(t["candidates"]), 2)
        self.assertEqual(c.execute("SELECT holder_id FROM seats WHERE seat_id = 'chief_disciple'").fetchone()[0], t["winner"])
        # and what the world heard of the producer is only that the seat was open
        iv = [json.loads(r[0]) for r in c.execute("SELECT truth FROM events WHERE type = 'intervention'")]
        self.assertEqual([x["kind"] for x in iv], ["open_seat"])

    def test_a_world_without_the_pack_has_no_groups_to_speak_of(self):
        c = connect()
        init_db(c, 3)
        build_world(c, 3, "town_in_jianghu_v1")
        self.assertNotIn("factions", {d.id for d in active(c)})
        self.assertEqual(solidarity(c, "ming", "kai"), 0.0)


if __name__ == "__main__":
    unittest.main()
