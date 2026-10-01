"""The inner chain: body -> arousal -> losing control -> hurt and regret -> experience -> self-model -> behaviour.

- Relationships soften at the ends (soft_delta) and fade a little on nights apart, in worlds with social.exchange.
- Being called a liar when one told the truth is being wronged; hostility one provoked oneself stings less; a day
  without being attacked lets aggression ease.
- A held self-model leans behaviour (self_bias), as the plan's table says.
- Past self-control, and only then, a shove or a blow is possible; it is witnessed, it hurts, and the next night it
  is regretted (and someone one cares about is owed amends). Between fighters, skill decides who is hurt.
"""
from __future__ import annotations

import json
import unittest

from world.db import connect, init_db
from world.events import Change, EventSpec, apply_event
from world.seed import build_world


def _fresh(recipe: str = "town_life_v1", seed: int = 4):
    c = connect()
    init_db(c, seed)
    build_world(c, seed, recipe)
    return c


def _set(c, ts: int, **values: float) -> None:
    """Set world vars by an event (the only way anything changes)."""
    from world.attention import var
    ch = [Change("var", k, "value", delta=round(v - var(c, k, 0.0), 6)) for k, v in values.items() if v != var(c, k, 0.0)]
    apply_event(c, EventSpec(timestamp=ts, type="setup", trigger_type="rule", changes=ch))


class Relationships(unittest.TestCase):
    def test_strong_feelings_move_little_and_a_pull_back_counts_in_full(self):
        from world.helpers import soft_delta
        self.assertAlmostEqual(soft_delta(0.0, 0.15), 0.15)
        self.assertAlmostEqual(soft_delta(0.9, 0.15), 0.15 * 0.01)
        self.assertAlmostEqual(soft_delta(0.9, -0.15), -0.15)
        self.assertAlmostEqual(soft_delta(-0.8, -0.1), -0.1 * 0.04)

    def test_only_worlds_where_people_answer_soften(self):
        from world.helpers import rel_delta
        self.assertAlmostEqual(rel_delta(_fresh("town_v1"), 0.9, 0.15), 0.1)       # clamped only
        self.assertAlmostEqual(rel_delta(_fresh("town_life_v1"), 0.9, 0.15), 0.0015)


class Hurt(unittest.TestCase):
    def test_called_a_liar_for_the_truth_is_being_wronged(self):
        from world.psyche import appraise
        c = _fresh()
        apply_event(c, EventSpec(timestamp=600, type="confront", trigger_type="decision", location_id="cafe", importance=0.7,
                                 truth={"actor": "ming", "target": "kai", "outcome": "unfounded"},
                                 participants=[("ming", "actor"), ("kai", "target")]))
        exp, _ = appraise(c, "kai", 0)
        self.assertAlmostEqual(exp["wronged"], 0.8)

    def test_hostility_one_provoked_stings_less(self):
        from world.psyche import PROVOKED, appraise
        c = _fresh()
        first = apply_event(c, EventSpec(timestamp=600, type="talk", trigger_type="decision", location_id="cafe",
                                         truth={"actor": "ming", "target": "kai", "tone": "hostile"},
                                         participants=[("ming", "actor"), ("kai", "target")]))
        apply_event(c, EventSpec(timestamp=601, type="talk", trigger_type="decision", location_id="cafe", parent_event_id=first,
                                 truth={"actor": "kai", "target": "ming", "tone": "hostile"},
                                 participants=[("kai", "actor"), ("ming", "target")]))
        self.assertAlmostEqual(appraise(c, "ming", 0)[0]["hostility"], PROVOKED)  # he started it
        self.assertAlmostEqual(appraise(c, "kai", 0)[0]["hostility"], 1.0)


class SelfModels(unittest.TestCase):
    def test_a_held_self_model_leans_behaviour(self):
        from world.psyche import self_bias
        c = _fresh()
        self.assertEqual(self_bias(c, "ming"), {})
        _set(c, 10, **{"psy.ming.self.cannot_trust": 1.0, "psy.ming.self.always_blamed": 0.5})
        b = self_bias(c, "ming")
        self.assertAlmostEqual(b["belief"], -0.15)
        self.assertAlmostEqual(b["accuse"], 0.3)
        self.assertAlmostEqual(b["defend"], 0.15)  # softened: half strength

    def test_self_models_form_in_a_month(self):
        from agent.volition import VolitionDecider
        from world.simulation import Simulation
        c = _fresh(seed=260934)
        d = VolitionDecider(260934)
        Simulation(c, d, d, set(), feed="synthetic_v1").run(18)
        held = {k.split(".")[-1] for k, v in c.execute("SELECT key, value FROM world_vars WHERE key LIKE 'psy.%.self.%'") if v >= 0.5}
        self.assertTrue(held & {"world_is_hostile", "always_blamed", "cannot_trust", "on_my_own"}, held)


class Body(unittest.TestCase):
    def test_arousal_ebbs(self):
        from world.domains.body import HALF_LIFE, arousal
        c = _fresh()
        _set(c, 100, **{"body.arousal.ming": 0.8, "body.arousal_at.ming": 100.0})
        self.assertAlmostEqual(arousal(c, "ming", 100), 0.8)
        self.assertAlmostEqual(arousal(c, "ming", 100 + int(HALF_LIFE)), 0.4, places=3)

    def test_no_outburst_within_self_control_and_one_past_it(self):
        from world.domains.body import Body as Pack, control
        c = _fresh()
        here = ["kai"]
        self.assertEqual(Pack()._outbursts(c, "ming", here, 200), [])
        _set(c, 200, **{"body.arousal.ming": min(1.0, control(c, "ming") + 0.4), "body.arousal_at.ming": 200.0})
        kinds = {it.action for _, it in Pack()._outbursts(c, "ming", here, 200)}
        self.assertTrue({"shove", "strike"} <= kinds, kinds)

    def test_a_blow_is_seen_regretted_and_owed(self):
        from world.domains.body import Body as Pack
        from world.intent import Intent, validate
        from world.rules import resolve
        c = _fresh()
        apply_event(c, EventSpec(timestamp=300, type="setup", trigger_type="rule",
                                 changes=[Change("person", p, "location_id", value="cafe") for p in ("ming", "kai", "mei")]
                                 + [Change("relationship", "ming:kai", "affection", delta=0.5)]))
        it = Intent("ming", "strike", "kai", reason="body:lost_control")
        validate(c, it)
        eid = apply_event(c, resolve(c, it, 310, "decision"))
        t = json.loads(c.execute("SELECT truth FROM events WHERE event_id = ?", (eid,)).fetchone()[0])
        self.assertEqual(t["hurt"], "kai")
        night = Pack().nightly(c, 0, 1439)
        self.assertIn("regret", {s.type for s in night})
        self.assertTrue(any(s.type == "goal_change" and s.truth["kind"] == "make_amends" for s in night))
        self.assertEqual(dict(Pack().appraise(c, "ming", "strike", t))["shame"], 0.8)

    def test_between_fighters_skill_decides_who_is_hurt(self):
        from world.intent import Intent
        from world.rules import resolve
        c = _fresh("town_in_jianghu_v1", seed=7)
        apply_event(c, EventSpec(timestamp=300, type="setup", trigger_type="rule",
                                 changes=[Change("person", p, "location_id", value="inn") for p in ("hao", "kai")]
                                 + [Change("var", "skill.kai", "value", delta=0.4)]))  # kai 0.9 against hao 0.3
        spec = resolve(c, Intent("hao", "strike", "kai"), 310, "decision")
        self.assertEqual(spec.truth["hurt"], "hao")  # the weaker one lashed out and came off worse


if __name__ == "__main__":
    unittest.main()
