"""First impressions (world/domains/impression.py, primitive social.impression): the three numbers and where they come from,
that they stay out of the genome's hash, that a world without the primitive is untouched, and that every rule of the pack
leaves a trace that can be read back (attention, talk, misread and reveal, gossip, envy, kindness, looks in romance)."""
from __future__ import annotations

import dataclasses
import json
import unittest

from contracts.base import to_dict
from contracts.persona import IMPRESSION_FIELDS, CharacterGenome
from contracts.recipe import WorldRecipe
from world.db import connect, init_db
from world.domains import active, base
from world.domains import impression as I
from world.domains import romance as R
from world.events import ClaimSpec, EventSpec, MemorySpec, apply_event
from world.intent import Intent
from world.personas import PersonaError, extras_override, lift, stored
from world.recipes import load_recipe, register_recipe, unregister_recipe
from world.seed import build_world

CONTROL, TREAT = "jianghu_story_v1", "impression_test_v1"
# genome ids as they were before the three numbers existed (computed with the contract as of HEAD, and checked equal to the
# ids of the stored rows): they must not move, whether the numbers are set or not
GOLDEN_IDS = {"mei": "genome:6dfa1aab9f0af561", "tao": "genome:17d2209a294c4b1f"}
GOLDEN_JIANGHU = {"yan": "genome:d0eaa44d0a6baa10", "hua": "genome:5a432d5ce8704e03"}
GOLDEN_TOWN_EVENTS = "sha256:4245f4fdf236299e17dc85df2840af8f753df6ec66f4e04c36e876aab2fde4ec"  # town_v1, seed 184729, 2 days


def setUpModule():
    base_recipe = load_recipe(CONTROL)
    register_recipe(dataclasses.replace(base_recipe, recipe_id=TREAT, title=TREAT, base=list(base_recipe.base) + ["social.impression"]))


def tearDownModule():
    unregister_recipe(TREAT)


def world(recipe: str = TREAT, seed: int = 3):
    c = connect()
    init_db(c, seed)
    build_world(c, seed, recipe)
    return c


def pack(conn):
    return next(d for d in active(conn) if d.id == "impression")


def now(conn):
    return conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]


def put(conn, pid: str, **fields):
    """Set a relationship value (as an event, like anything in the world): put(c, 'a:b', familiarity=0.4)."""
    from world.events import Change as Ch
    changes = []
    for key, value in fields.items():
        a, b = pid.split(":")
        cur = conn.execute(f"SELECT {key} FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]
        changes.append(Ch("relationship", pid, key, delta=round(value - cur, 6)))
    apply_event(conn, EventSpec(timestamp=now(conn), type="setup", trigger_type="rule", location_id=None, changes=changes))


def gather(conn, *people, place="inn", others="road"):
    """These people at `place`, everybody else at `others` (so a scene has exactly this audience)."""
    from world.events import Change
    everyone = [r[0] for r in conn.execute("SELECT id FROM people ORDER BY id")]
    want = {p: (place if p in people else others) for p in everyone}
    ch = [Change("person", p, "location_id", value=loc) for p, loc in want.items()
          if conn.execute("SELECT location_id FROM people WHERE id = ?", (p,)).fetchone()[0] != loc]
    if ch:
        apply_event(conn, EventSpec(timestamp=now(conn), type="setup", trigger_type="rule", location_id=place, changes=ch))
    return place


def talk(conn, a, b, tone="neutral", place=None, t=None):
    """A talk as the simulation makes it: the event, every active domain's effects, then written."""
    place = place or conn.execute("SELECT location_id FROM people WHERE id = ?", (a,)).fetchone()[0]
    spec = EventSpec(timestamp=now(conn) + 1 if t is None else t, type="talk", trigger_type="decision", location_id=place,
                     truth={"actor": a, "target": b, "tone": tone, "reason": "volition", "source": "test"},
                     participants=[(a, "actor"), (b, "target")])
    for d in active(conn):
        spec = d.effects(conn, spec, set())
    eid = apply_event(conn, spec)
    return eid, json.loads(conn.execute("SELECT truth FROM events WHERE event_id = ?", (eid,)).fetchone()[0])


def deltas(conn, eid, a, b, field):
    r = conn.execute("SELECT delta_value FROM event_deltas WHERE event_id = ? AND entity_type = 'relationship' AND entity_id = ? "
                     "AND field = ?", (eid, f"{a}:{b}", field)).fetchone()
    return r[0] if r else 0.0


class Derivation(unittest.TestCase):
    """warmth and talk, when the genome does not say: fixed formulas, written in impression.derive."""

    def test_the_formulas_with_numbers(self):
        traits = {"honesty": 0.6, "temper": 0.4, "gossip": 0.4, "generosity": 0.4, "curiosity": 0.4}
        warmth, talk = I.derive(traits)
        self.assertAlmostEqual(warmth, 0.15 + 0.40 * 0.4 + 0.20 * 0.6 + 0.15 * 0.6, places=4)   # 0.52
        self.assertAlmostEqual(talk, 0.10 + 0.40 * 0.4 + 0.25 * 0.4 + 0.10 * 0.4, places=4)    # 0.40
        self.assertEqual(I.derive({}), I.derive(I.TEMPERAMENT))                                  # missing traits are the defaults
        self.assertEqual(I.derive({"gossip": 0.9, "unknown": 9}), I.derive({**I.TEMPERAMENT, "gossip": 0.9}))

    def test_the_formulas_stay_in_range_and_follow_the_temperament(self):
        hi = I.derive({"honesty": 1.0, "temper": 0.0, "gossip": 1.0, "generosity": 1.0, "curiosity": 1.0})
        lo = I.derive({"honesty": 0.0, "temper": 1.0, "gossip": 0.0, "generosity": 0.0, "curiosity": 0.0})
        self.assertEqual(hi, (0.9, 0.85))   # 0.15 + 0.40 + 0.20 + 0.15 ; 0.10 + 0.40 + 0.25 + 0.10
        self.assertEqual(lo, (0.15, 0.10))
        from contracts.character import SocialStyle
        warm = SocialStyle(strangers="熱情", friends="熱心", intimate="大方")
        for v in I.derive({"honesty": 1.0, "temper": 0.0, "gossip": 1.0, "generosity": 1.0, "curiosity": 1.0}, warm) +                 I.derive({"honesty": 0.0, "temper": 1.0, "gossip": 0.0, "generosity": 0.0, "curiosity": 0.0},
                         SocialStyle(strangers="冷淡", friends="少", intimate="不願牽絆")):
            self.assertTrue(0.0 <= v <= 1.0)

    def test_style_words_move_warmth_and_talk(self):
        from contracts.character import SocialStyle
        traits = {"honesty": 0.6, "temper": 0.4, "gossip": 0.4, "generosity": 0.4, "curiosity": 0.4}
        plain = I.derive(traits)
        warm_talky = I.derive(traits, SocialStyle(strangers="熱情", friends="話多", intimate="大方"))
        cold_quiet = I.derive(traits, SocialStyle(strangers="冷淡", friends="少", intimate="不願牽絆"))
        self.assertGreater(warm_talky[0], plain[0])
        self.assertGreater(warm_talky[1], plain[1])
        self.assertLess(cold_quiet[0], plain[0])
        self.assertLess(cold_quiet[1], plain[1])
        # a one-character word must be the whole token: 少 in 多少 is not "quiet"
        self.assertEqual(I.derive(traits, SocialStyle(friends="多少人")), plain)

    def test_nothing_set_means_looks_is_the_charm_and_the_rest_is_derived(self):
        with extras_override({"mei": {"charm": 0.85}}):          # a cast whose genome says nothing about the three numbers
            bare = world()
        v = I.values(bare, "mei")
        from world.profiles import profile
        self.assertEqual(v.looks, 0.85)    # the charm
        traits = json.loads(bare.execute("SELECT traits FROM personas WHERE person_id = 'mei'").fetchone()[0])
        self.assertEqual((v.warmth, v.talk), I.derive(traits, profile(bare, "mei").social))
        self.assertEqual(I.values(world(), "mei").looks, 0.90)   # the content says 0.90 (charm 0.85): the genome wins
        # no genome at all (a bare world): the middle, and what the temperament gives
        plain = connect()
        init_db(plain, 1)
        self.assertEqual(I.values(plain, "nobody").looks, 0.5)


class OutsideTheHash(unittest.TestCase):
    """The numbers are not part of a genome's identity: its id is what it was before they existed."""

    def test_genome_ids_are_what_they_were(self):
        for recipe in ("town_v1", TREAT, CONTROL):
            c = world(recipe, seed=1)
            for pid, gid in GOLDEN_IDS.items():
                self.assertEqual(c.execute("SELECT genome_id FROM character_genomes WHERE person_id = ?", (pid,)).fetchone()[0], gid, recipe)
        c = world("jianghu_v1", seed=1)
        for pid, gid in GOLDEN_JIANGHU.items():
            self.assertEqual(c.execute("SELECT genome_id FROM character_genomes WHERE person_id = ?", (pid,)).fetchone()[0], gid)

    def test_setting_the_numbers_does_not_change_the_id_but_other_fields_do(self):
        c = world(CONTROL, seed=1)
        from world.personas import genome
        g = genome(c, "mei")
        self.assertIsNone(g.looks)
        with_numbers = dataclasses.replace(g, looks=0.9, warmth=0.2, talkativeness=0.1)
        self.assertEqual(with_numbers.genome_id, g.genome_id)
        self.assertEqual(with_numbers.hash(), g.hash())
        self.assertNotEqual(dataclasses.replace(g, charm=0.1).genome_id, g.genome_id)

    def test_only_a_recipe_with_the_primitive_stores_them(self):
        old, new = world(CONTROL, seed=1), world(TREAT, seed=1)
        row_old = json.loads(old.execute("SELECT genome FROM character_genomes WHERE person_id = 'mei'").fetchone()[0])
        row_new = json.loads(new.execute("SELECT genome FROM character_genomes WHERE person_id = 'mei'").fetchone()[0])
        for k in IMPRESSION_FIELDS:
            self.assertNotIn(k, row_old)
        self.assertEqual({k: row_new[k] for k in IMPRESSION_FIELDS}, {"looks": 0.9, "warmth": 0.25, "talkativeness": 0.15})
        self.assertEqual({k: v for k, v in row_new.items() if k not in IMPRESSION_FIELDS}, row_old)
        self.assertEqual(stored(CharacterGenome(name="x", profile=None), True), stored(CharacterGenome(name="x", profile=None), False))  # type: ignore[arg-type]

    def test_a_number_out_of_range_is_refused(self):
        for bad in (1.5, -0.1, "high", True):
            with self.assertRaises(PersonaError):
                with extras_override({"mei": {"looks": bad}}):
                    world(TREAT)

    def test_the_numbers_are_in_the_evidence_graph_when_set(self):
        from world import persona_evidence as ev
        from world.personas import genome
        g = genome(world(TREAT), "mei")
        self.assertTrue(set(IMPRESSION_FIELDS) <= set(ev.fields(g)))
        self.assertEqual(ev.check(g, ev.authored(g)), [])
        g0 = genome(world(CONTROL), "mei")
        self.assertFalse(set(IMPRESSION_FIELDS) & set(ev.fields(g0)))

    def test_every_content_pack_with_numbers_has_them_in_range_and_matching_its_people(self):
        from world.personas import _file_extras
        for content, cold, warm in (("town_v1", "mei", "lan"), ("jianghu_v1", "yan", "hua")):
            people = _file_extras(content)
            self.assertEqual(len(people), 10)
            for pid, e in people.items():
                for k in IMPRESSION_FIELDS:
                    self.assertTrue(0.0 <= e[k] <= 1.0, (content, pid, k))
            c, w = people[cold], people[warm]
            self.assertGreater(c["looks"], 0.8)
            self.assertLess(c["talkativeness"], 0.2)
            self.assertLess(c["warmth"], 0.3)   # the cold beauty
            self.assertGreater(w["warmth"], 0.8)


class UntouchedWithoutIt(unittest.TestCase):
    def test_no_trace_in_a_world_that_does_not_switch_it_on(self):
        from agent.volition import VolitionDecider
        from world.simulation import Simulation
        c = world(CONTROL, seed=5)
        d = VolitionDecider(5)
        Simulation(c, d, d, set()).run(2)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM world_vars WHERE key LIKE 'impression.%'").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth, '$.impression') IS NOT NULL").fetchone()[0], 0)
        self.assertFalse([d for d in active(c) if d.id == "impression"])

    def test_the_legacy_town_has_the_history_it_had(self):
        from tests.refactor_baseline import fingerprint
        self.assertEqual(fingerprint("town_v1", 184729, 2, "synthetic_v1")["events"], GOLDEN_TOWN_EVENTS)

    def test_romance_reads_the_charm_there_and_the_looks_here(self):
        old, new = world(CONTROL), world(TREAT)
        self.assertEqual(R.charm(old, "tao"), 0.40)   # the genome's charm
        self.assertEqual(R.charm(new, "tao"), 0.30)   # how he looks
        self.assertEqual(R.charm(new, "mei"), 0.90)
        put(new, "mei:tao", familiarity=0.3)
        put(old, "mei:tao", familiarity=0.3)
        self.assertLess(R.drawn_level(new, "mei", "tao"), R.drawn_level(old, "mei", "tao"))

    def test_the_hook_defaults_leave_the_reply_alone(self):
        from agent.reply import _reticence
        self.assertEqual(base.Domain().reticence(None, "a", "b", 0), 0.0)
        self.assertEqual(_reticence(world(CONTROL), "mei", "ming", 0), 0.0)


class WhoIsNoticed(unittest.TestCase):
    def setUp(self):
        self.c = world()
        self.p = pack(self.c)
        gather(self.c, "ming", "mei", "jun", "lan", "hao", "tao")

    def talk_scores(self, actor, targets):
        scored = [(0.5, Intent(actor, "talk", t, "neutral")) for t in targets]
        return {it.target: round(s, 4) for s, it in self.p.shape(self.c, actor, now(self.c), scored)}

    def test_a_strangers_looks_draw_the_eye_and_fade_with_knowing(self):
        s = self.talk_scores("ming", ["mei", "jun"])
        self.assertAlmostEqual(s["mei"] - s["jun"], I.LOOK_ATT * (0.90 - 0.35), places=3)
        put(self.c, "ming:mei", familiarity=0.5)
        put(self.c, "ming:jun", familiarity=0.5)
        s = self.talk_scores("ming", ["mei", "jun"])
        self.assertLess(s["mei"], s["jun"])  # known now: warmth counts, and jun is warmer than mei

    def test_known_warmth_draws_more_than_known_beauty(self):
        for t in ("mei", "lan"):
            put(self.c, f"ming:{t}", familiarity=0.4)
        s = self.talk_scores("ming", ["mei", "lan"])
        self.assertGreater(s["lan"], s["mei"])  # lan: kind; mei: lovely and cool

    def test_attention_is_a_read_of_what_the_genome_made(self):
        self.assertEqual(I.attention(self.c, "ming", "mei"), round(I.LOOK_ATT * 0.40, 4))   # looks 0.9, known 0
        put(self.c, "ming:lan", familiarity=I.F_KNOWN)
        self.assertEqual(I.attention(self.c, "ming", "lan"), round(I.WARM_ATT * 0.40, 4))   # warmth 0.9, known fully

    def test_the_talkative_speak_up_and_the_quiet_hold_back(self):
        loud, quiet = self.talk_scores("hao", ["tao"])["tao"], self.talk_scores("mei", ["tao"])["tao"]
        self.assertGreater(loud, quiet)
        scored = [(0.5, Intent("hao", "tell", "tao", claim_id=None))]
        self.assertAlmostEqual(self.p.shape(self.c, "hao", 0, scored)[0][0], 0.5 + I.TELL_DRIVE * 0.4, places=3)
        self.assertLess(self.p.shape(self.c, "mei", 0, [(0.5, Intent("mei", "tell", "tao", claim_id=None))])[0][0], 0.5)

    def test_attention_moves_whom_not_how_much(self):
        # it is centred on the people one could talk to: the sum over the room is what it was
        targets = ["mei", "jun", "lan", "hao", "tao"]
        out = self.talk_scores("ming", targets)
        drive = I.TALK_DRIVE * (I.values(self.c, "ming").talk - 0.5)
        self.assertAlmostEqual(sum(out.values()), 0.5 * len(targets) + drive * len(targets), places=3)
        # a single person to talk to gets no lift from their looks
        only = self.talk_scores("ming", ["mei"])
        self.assertAlmostEqual(only["mei"], 0.5 + drive, places=3)

    def test_idle_and_other_actions_are_left_alone(self):
        scored = [(0.35, None), (0.4, Intent("mei", "move", "inn"))]
        self.assertEqual(self.p.shape(self.c, "mei", 0, scored), scored)

    def test_what_is_told_is_likelier_when_it_is_about_a_beauty(self):
        from world.claims import claim_id
        from contracts.claim import Claim
        ids = {}
        for who in ("mei", "jun"):
            apply_event(self.c, EventSpec(timestamp=now(self.c), type="seed", trigger_type="rule", location_id="inn",
                                          truth={"actor": who}, participants=[(who, "actor")],
                                          memories=[MemorySpec("ming", f"{who} did something", 1.0, claim=Claim(who, "take", "ring_mei"), about_self=True)],
                                          claims=[ClaimSpec(Claim(who, "take", "ring_mei"))]))
            ids[who] = self.c.execute("SELECT claim_id FROM claims WHERE subject = ?", (who,)).fetchone()[0]
        scored = [(0.5, Intent("ming", "tell", "tao", claim_id=ids["mei"])), (0.5, Intent("ming", "tell", "tao", claim_id=ids["jun"]))]
        out = self.p.shape(self.c, "ming", 0, scored)
        drive = I.TELL_DRIVE * (I.values(self.c, "ming").talk - 0.5)
        self.assertAlmostEqual(out[0][0], 0.5 + drive + I.GOSSIP_LOOKS * 2 * (0.90 - 0.5), places=3)
        self.assertAlmostEqual(out[1][0], 0.5 + drive + I.GOSSIP_LOOKS * 2 * (0.35 - 0.5), places=3)   # jun is plain: less
        # and nobody gets a lift for telling about themselves or the one they tell it to
        own = [(0.5, Intent("mei", "tell", "tao", claim_id=ids["mei"]))]
        self.assertAlmostEqual(self.p.shape(self.c, "mei", 0, own)[0][0], 0.5 + I.TELL_DRIVE * (0.15 - 0.5), places=3)


class Reticence(unittest.TestCase):
    def test_a_quiet_one_lets_the_word_pass_more_than_a_chatty_one(self):
        c = world()
        p = pack(c)
        self.assertGreater(p.reticence(c, "mei", "ming", 0), 0.0)
        self.assertLess(p.reticence(c, "hao", "ming", 0), 0.0)

    def test_the_replier_reads_it(self):
        from agent.reply import Replier
        a, b = world(TREAT), world(CONTROL)
        out = {}
        for tag, c in (("on", a), ("off", b)):
            gather(c, "ming", "mei", "hao")
            eid, _ = talk(c, "ming", "mei", "neutral")
            row = c.execute("SELECT * FROM events WHERE event_id = ?", (eid,)).fetchone()
            out[tag] = Replier(3).scored(c, row, 1, now(c) + 1)
        silent_on, silent_off = out["on"][0][0], out["off"][0][0]
        self.assertAlmostEqual(silent_on - silent_off, I.RETICENCE * (0.5 - I.talk_level(a, "mei")), places=3)
        self.assertGreater(silent_on, silent_off)           # mei says less
        self.assertEqual([s for s, _ in out["on"][1:]], [s for s, _ in out["off"][1:]])   # the other answers are as they were
        # the chatty one leans the other way
        row_h = None
        for tag, c in (("on", a), ("off", b)):
            eid, _ = talk(c, "ming", "hao", "neutral")
            row_h = c.execute("SELECT * FROM events WHERE event_id = ?", (eid,)).fetchone()
            out[tag] = Replier(3).scored(c, row_h, 1, now(c) + 1)
        self.assertLess(out["on"][0][0], out["off"][0][0])


class Misread(unittest.TestCase):
    """The cold beauty is taken for contemptuous by someone who does not know her yet; once they do, it turns."""

    def setUp(self):
        self.c = world()
        gather(self.c, "ming", "mei", "hao", "lan")

    def test_who_reads_as_cold(self):
        self.assertGreaterEqual(I.values(self.c, "mei").cold(), I.MISREAD_MIN)
        self.assertLess(I.values(self.c, "hao").cold(), I.MISREAD_MIN)   # looks, but talks and is warm
        self.assertLess(I.values(self.c, "tao").cold(), I.MISREAD_MIN)   # plain and kind

    def test_a_stranger_takes_the_reserve_for_contempt_and_it_is_written_down(self):
        eid, truth = talk(self.c, "ming", "mei", "neutral")
        self.assertLess(deltas(self.c, eid, "ming", "mei", "respect"), 0.0)
        self.assertLess(deltas(self.c, eid, "ming", "mei", "affection"), 0.0)
        m = truth["impression"]["misread"][0]
        self.assertEqual((m["reader"], m["of"]), ("ming", "mei"))
        self.assertAlmostEqual(m["cold"], I.values(self.c, "mei").cold(), places=3)

    def test_it_is_a_bias_of_strangers_not_of_everyone(self):
        eid, truth = talk(self.c, "ming", "hao", "neutral")
        self.assertNotIn("misread", truth.get("impression", {}))
        eid, truth = talk(self.c, "ming", "mei", "warm")
        self.assertNotIn("misread", truth.get("impression", {}))     # warm words clear it up
        eid, truth = talk(self.c, "ming", "mei", "hostile")
        self.assertNotIn("misread", truth.get("impression", {}))     # a real insult is not a misreading
        self.assertNotIn("revealed", truth.get("impression", {}))

    def test_the_bias_wears_off_as_they_get_to_know_each_other(self):
        sizes = []
        for fam in (0.0, 0.1, 0.19):
            put(self.c, "ming:mei", familiarity=fam)
            eid, _ = talk(self.c, "ming", "mei", "neutral")
            sizes.append(deltas(self.c, eid, "ming", "mei", "respect"))
        self.assertTrue(sizes[0] < sizes[1] < sizes[2] <= 0.0, sizes)

    def test_once_known_the_same_exchange_lifts_it(self):
        put(self.c, "ming:mei", familiarity=0.35)
        eid, truth = talk(self.c, "ming", "mei", "neutral")
        self.assertGreater(deltas(self.c, eid, "ming", "mei", "respect"), 0.0)
        self.assertGreater(deltas(self.c, eid, "ming", "mei", "affection"), 0.0)
        self.assertEqual(truth["impression"]["revealed"][0]["of"], "mei")
        self.assertNotIn("misread", truth["impression"])

    def test_a_turn_from_low_to_high_is_in_the_history(self):
        early, _ = talk(self.c, "ming", "mei", "neutral")
        put(self.c, "ming:mei", familiarity=0.4)
        late, _ = talk(self.c, "ming", "mei", "neutral")
        from world.state import relationship_history
        steps = [(r["event_id"], r["delta_value"]) for r in relationship_history(self.c, "ming", "mei", "respect")]
        self.assertLess(dict(steps)[early], 0)
        self.assertGreater(dict(steps)[late], 0)
        kinds = {r["event_id"]: json.loads(self.c.execute("SELECT truth FROM events WHERE event_id = ?", (r["event_id"],)).fetchone()[0])
                 for r in relationship_history(self.c, "ming", "mei", "respect")}
        self.assertIn("misread", kinds[early]["impression"])
        self.assertIn("revealed", kinds[late]["impression"])

    def test_the_reveal_stops_when_respect_is_already_high(self):
        put(self.c, "ming:mei", familiarity=0.4, respect=0.2)
        a, _ = talk(self.c, "ming", "mei", "neutral")
        put(self.c, "ming:mei", respect=0.5)
        b, _ = talk(self.c, "ming", "mei", "neutral")
        self.assertGreater(deltas(self.c, a, "ming", "mei", "respect"), deltas(self.c, b, "ming", "mei", "respect"))
        self.assertEqual(deltas(self.c, b, "ming", "mei", "respect"), 0.0)

    def test_it_is_seen_as_a_situation(self):
        names = {"ming": "阿明", "mei": "小美"}
        for _ in range(2):
            talk(self.c, "ming", "mei", "neutral")
        kinds = [s["kind"] for s in pack(self.c).situations(self.c, names)]
        self.assertIn("misread", kinds)
        put(self.c, "ming:mei", familiarity=0.4)
        talk(self.c, "ming", "mei", "neutral")
        self.assertIn("misread_turn", [s["kind"] for s in pack(self.c).situations(self.c, names)])
        self.assertTrue({"misread", "misread_turn", "friend_zone"} <= set(pack(self.c).situation_kinds))


class KindnessAndTheFriendZone(unittest.TestCase):
    def setUp(self):
        self.c = world()
        gather(self.c, "ming", "tao", "mei", "lan", "kai")

    def test_the_warm_are_liked_faster_and_trusted_once_known(self):
        put(self.c, "ming:tao", familiarity=0.3)
        put(self.c, "ming:kai", familiarity=0.3)
        warm, _ = talk(self.c, "ming", "tao", "warm")
        cool, _ = talk(self.c, "ming", "kai", "warm")
        self.assertGreater(deltas(self.c, warm, "ming", "tao", "affection"), deltas(self.c, cool, "ming", "kai", "affection"))
        self.assertGreater(deltas(self.c, warm, "ming", "tao", "trust"), 0.0)
        self.assertEqual(deltas(self.c, cool, "ming", "kai", "trust"), 0.0)   # kai is not warm

    def test_trust_waits_for_knowing_but_liking_does_not(self):
        stranger, _ = talk(self.c, "ming", "tao", "warm")
        self.assertGreater(deltas(self.c, stranger, "ming", "tao", "affection"), 0.0)
        self.assertEqual(deltas(self.c, stranger, "ming", "tao", "trust"), 0.0)

    def test_a_plain_good_soul_is_desired_less_than_the_same_soul_with_a_beauty_face(self):
        cast = {"mei": {"attracted_to": ["male"]}, "tao": {"attracted_to": ["female"], "warmth": 0.8}}
        levels = {}
        for looks in (0.3, 0.9):
            with extras_override({**cast, "tao": {**cast["tao"], "looks": looks}}):
                c = world()
            put(c, "mei:tao", familiarity=0.5)
            levels[looks] = R.drawn_level(c, "mei", "tao")
        # the formula is the one it was: 0.55 x the looks (it used to be the charm), the same warmth either way
        self.assertAlmostEqual(levels[0.9] - levels[0.3], 0.55 * (0.9 - 0.3), places=3)

    def test_the_friend_zone_is_found_when_it_stands_there(self):
        # tao (kind, plain) is drawn to mei; mei likes him a lot and is drawn to him little
        from tests.test_romance import feel
        put(self.c, "tao:mei", familiarity=0.5)
        feel(self.c, "tao", "mei", 0.5)
        put(self.c, "mei:tao", affection=0.6)
        feel(self.c, "mei", "tao", 0.05)
        found = [s for s in pack(self.c).situations(self.c, {}) if s["kind"] == "friend_zone"]
        self.assertEqual([sorted(s["people"]) for s in found], [["mei", "tao"]])
        feel(self.c, "mei", "tao", 0.5)
        self.assertFalse([s for s in pack(self.c).situations(self.c, {}) if s["kind"] == "friend_zone"])


class Envy(unittest.TestCase):
    def setUp(self):
        self.c = world()

    def test_the_outshone_of_the_same_sex_who_are_there_resent_a_little(self):
        gather(self.c, "ming", "mei", "lan", "ning", "rui", "yun", "hao")
        eid, truth = talk(self.c, "ming", "mei", "neutral")
        envious = {e["who"]: e for e in truth["impression"]["envy"]}
        self.assertEqual(set(envious), {"lan", "ning", "rui", "yun"})   # women outshone by mei (0.90) by at least 0.2: 0.65, 0.65, 0.60, 0.55
        self.assertNotIn("hao", envious)                               # a man
        self.assertTrue(all(e["of"] == "mei" for e in envious.values()))
        for w in envious:
            self.assertGreater(deltas(self.c, eid, w, "mei", "resentment"), 0.0)
        # both of them like men and the one who spoke is a man: the scene is contested, and it counts more
        self.assertTrue(envious["lan"]["contested"])
        plain = I.ENVY * envious["lan"]["gap"]
        self.assertAlmostEqual(deltas(self.c, eid, "lan", "mei", "resentment"), 2.5 * plain, places=4)

    def test_an_equal_is_not_envied_and_the_speaker_and_target_are_not_the_audience(self):
        gather(self.c, "ming", "lan", "rui")
        eid, truth = talk(self.c, "ming", "lan", "neutral")            # lan (0.65) is not 0.2 above rui (0.60)
        self.assertNotIn("envy", truth.get("impression", {}))
        gather(self.c, "mei")
        eid, truth = talk(self.c, "lan", "mei", "neutral")
        self.assertNotIn("lan", [e["who"] for e in truth["impression"]["envy"]])

    def test_the_resentment_is_the_worlds_own_field_and_travels_through_the_event(self):
        gather(self.c, "ming", "mei", "yun")
        eid, _ = talk(self.c, "ming", "mei", "neutral")
        row = self.c.execute("SELECT entity_id, field FROM event_deltas WHERE event_id = ? AND field = 'resentment'", (eid,)).fetchall()
        self.assertIn(("yun:mei", "resentment"), [tuple(r) for r in row])

    def test_a_flirt_is_a_scene_too(self):
        gather(self.c, "ming", "mei", "yun")
        spec = EventSpec(timestamp=now(self.c) + 1, type="flirt", trigger_type="decision", location_id="inn",
                         truth={"actor": "ming", "target": "mei"}, participants=[("ming", "actor"), ("mei", "target")])
        out = pack(self.c).effects(self.c, spec, set())
        self.assertIn("yun", [e["who"] for e in out.truth["impression"]["envy"]])
        # a declined confession is not
        spec2 = EventSpec(timestamp=now(self.c) + 1, type="confession", trigger_type="decision", location_id="inn",
                          truth={"actor": "ming", "target": "mei", "outcome": "declined"}, participants=[("ming", "actor"), ("mei", "target")])
        self.assertIs(pack(self.c).effects(self.c, spec2, set()), spec2)


class TalkLevel(unittest.TestCase):
    def test_reply_length_and_the_level(self):
        c = world()
        self.assertEqual(I.reply_length(c, "mei"), "short")
        self.assertEqual(I.reply_length(c, "hao"), "long")
        self.assertEqual(I.reply_length(c, "kai"), "normal")
        from world.events import Change
        apply_event(c, EventSpec(timestamp=0, type="setup", trigger_type="rule", location_id=None,
                                 changes=[Change("person", "hao", "emotion", value="hurt")]))
        self.assertLess(I.talk_level(c, "hao"), I.values(c, "hao").talk)        # upset: says less
        self.assertEqual(I.reply_length(c, "hao"), "normal")

    def test_the_world_var_starts_from_the_style_and_follows_the_nights(self):
        from agent.volition import VolitionDecider
        from world.simulation import Simulation
        c = world()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM world_vars WHERE key LIKE 'impression.talk.%'").fetchone()[0], 10)
        start = c.execute("SELECT value FROM world_vars WHERE key = 'impression.talk.mei'").fetchone()[0]
        d = VolitionDecider(3)
        Simulation(c, d, d, set()).run(2)
        after = c.execute("SELECT value FROM world_vars WHERE key = 'impression.talk.mei'").fetchone()[0]
        self.assertNotEqual(start, after)
        # the change came through an event (the nightly upkeep), not around it
        ev = c.execute("SELECT e.type FROM event_deltas d JOIN events e USING (event_id) WHERE d.entity_id = 'impression.talk.mei'").fetchall()
        self.assertTrue(ev and all(r[0] == "upkeep" for r in ev))
        from world.state import audit
        self.assertEqual(audit(c), [])
        self.assertLess(after, 0.4)
        self.assertGreater(c.execute("SELECT value FROM world_vars WHERE key = 'impression.talk.hao'").fetchone()[0], 0.8)

    def test_describe_and_influences_read_the_numbers(self):
        c = world()
        d = pack(c).describe(c, "mei")
        self.assertEqual((d["外貌"], d["親和"], d["話量"], d["答話"]), (0.9, 0.25, 0.15, "short"))
        self.assertEqual(pack(c).influences(c, "mei", 0)[0]["leans"], "holds back")
        self.assertEqual(pack(c).influences(c, "tao", 0), [])


class WhatStaysTheSame(unittest.TestCase):
    def test_a_minor_is_still_not_drawn_to_anyone_and_nobody_to_them(self):
        from unittest import mock
        from world import profiles
        c = world()
        real = profiles.profile
        minor = dataclasses.replace(real(c, "mei"), age=17)
        with mock.patch("world.profiles.profile", lambda conn, pid: minor if pid == "mei" else real(conn, pid)):
            self.assertFalse(R.drawn_to(c, "ming", "mei"))
            self.assertFalse(R.drawn_to(c, "mei", "ming"))
            self.assertEqual(R.drawn_level(c, "ming", "mei"), 0.0)

    def test_two_days_of_the_test_world_run_and_audit_clean(self):
        from agent.volition import VolitionDecider
        from world.simulation import Simulation
        from world.state import audit
        c = world()
        d = VolitionDecider(3)
        Simulation(c, d, d, set()).run(3)
        self.assertEqual(audit(c), [])
        marks = c.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth, '$.impression') IS NOT NULL").fetchone()[0]
        self.assertGreater(marks, 0)   # the rules did fire

    def test_the_pack_is_a_pack(self):
        self.assertEqual(pack(world()).enabled_by(), {"social.impression"})
        self.assertIn("social.impression", [p.id for d in active(world()) for p in d.primitives])
        self.assertNotIn("social.impression", [p.id for d in active(world(CONTROL)) for p in d.primitives])


if __name__ == "__main__":
    unittest.main()
