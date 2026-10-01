"""Producer 2: it reads the story the world is making, finds the one that is closest, and supplies only what it lacks.

Producer 1 (showrunner.py) had a fixed three-step recipe per kind of arc and no view of the world's own state. This one works the
other way round, each morning:

  1. PACING        how much has happened lately? After a peak it keeps still (silence is a decision, kept in the ledger)
  2. OPPORTUNITIES what is the world half-making, and what does each story lack?         (narrative/opportunity.py, read only)
  3. FOCUS         the most worth having, and who has waited longest (rotation); not somebody who has just had their moment,
                   and not the kind of story it has just told (variety)
  4. SHAPE         the least that fills what it lacks, in the closed vocabulary           (shaper.py)
  5. IMAGINE       (lookahead only) run copies of the world a few days under other luck, with and without it, and do it only if the
                   futures say it is worth what it costs                                   (forecast.py, world/rollout.py)
  6. ADMIT         the weekly budget and the world's own rules have the last word         (intervention.py)

It controls the topology of opportunity and nothing else: a tournament is not a win, a part is a lean on choices somebody already
has, and the world still rolls the dice. It never makes an opportunity of a story whose end is already decided (the detector
keeps those out: a hero who is bound to win is no story), and it keeps a record of what it did and of what it chose not to.

Strategies, so that what each part adds can be measured (producer_lab.py):
  greedy      steps 1-4 and 6
  portfolio   greedy with a pattern memory (a story that would repeat what has been told is gated out and the rest weighed by how new
              it is: a hard constraint before the payoff) and arc death (a story nothing has come of in a week is given up, not
              rescued with more)
  lookahead   greedy, with step 5 choosing among the three best stories and silence
  matched     the same pacing, budget and shaper, but the story is drawn at random from those the world is making (is it choosing
              well among real stories, or only doing something at the right time?)
  blind       the same, but the story is a random pair of fighters, whether or not it is a story at all (is the detector worth
              anything?)
  aggressive  greedy without the pacing: it arranges something whenever it can
  unlimited   greedy without the week's budget
"""
from __future__ import annotations

import hashlib
import sqlite3

from contracts.intervention import InterventionProposal
from contracts.opportunity import Opportunity
from narrative import opportunity as O
from narrative import pacing
from producer import shaper
from producer.arcs import Threads, protected
from producer.intervention import WEEK_BUDGET, Ledger
from world.rng import rng as make_rng

STRATEGIES = ("greedy", "portfolio", "lookahead", "matched", "blind", "aggressive", "unlimited")
STRENGTH = {"cast_role": "soft", "deliver_parcel": "soft", "announce_visitor": "soft", "announce_gathering": "medium", "open_seat": "medium"}
NOVELTY_FLOOR = 0.3    # a story that would only repeat what has been told (portfolio) is not taken up, whatever it would pay
RANDOM_AIM = ("matched", "blind")
MAX_PER_DAY = 3
STAGE_GAP = 5          # days between one announced gathering and the next
SEAT_GAP = 9           # ... and between one seat falling vacant and the next (a vote every few days is a farm, not a story)
WAIT_BONUS = 0.10      # per day a person has waited for the focus, as a share of the opportunity's worth
VARIETY = 0.5          # a kind of story taken up lately counts this much less each time (the first version opened a vote every nine days:
VARIETY_DAYS = 14      #   the cheapest payoff on the books, and the same story again and again)
CANDIDATES = 3         # how many stories lookahead imagines


class Director:
    def __init__(self, strategy: str = "greedy", seed: int = 0, ledger: Ledger | None = None) -> None:
        if strategy not in STRATEGIES:
            raise ValueError(f"no strategy {strategy!r}")
        self.strategy, self.seed = strategy, seed
        self.ledger = ledger if ledger is not None else Ledger(week_budget=10 ** 6 if strategy == "unlimited" else WEEK_BUDGET)
        self.threads = Threads()
        self._last_stage = -99
        self._last_seat = -99
        self._taken: list[tuple[int, str]] = []     # (day, kind) of the stories it has taken up
        self._clean: sqlite3.Connection | None = None

    # -- the daily calls (Simulation.producer) -------------------------------------------------------------------------
    def prepare(self, conn: sqlite3.Connection, day: int) -> None:
        """Before anything of the day: keep the clean boundary to imagine from (only lookahead imagines)."""
        if self.strategy == "lookahead":
            from world import rollout
            if self._clean is not None:
                self._clean.close()
            self._clean = rollout.copy_of(conn)

    def dawn(self, conn: sqlite3.Connection, day: int, now: int) -> None:
        self.threads.settle(conn, day)
        phase = pacing.phase(conn, day)
        if phase == "peak" and self.strategy != "aggressive":
            self.ledger.decide(day, "silence", "a great deal has just happened", phase=phase, intensity=pacing.intensity(conn, day))
            return
        ops = O.detect(conn, day) if self.strategy != "blind" else O.detect(conn, day, unfiltered=True)
        prot = protected(ops)
        ranked = self._ranked(conn, ops, day)
        if not ranked:
            self.ledger.decide(day, "silence", "no story is open that could use anything", phase=phase, seen=len(ops))
            return
        if self.strategy in RANDOM_AIM:
            rng = make_rng(self.seed, day, "director", "aim")
            picks = [ranked[rng.randrange(len(ranked))]]
        else:
            picks = ranked[:CANDIDATES if self.strategy == "lookahead" else 1]
        plans = [(op, self._proposals(shaper.candidates(conn, op, day, prot), op, day)) for op in picks]
        plans = [(op, props) for op, props in plans if props]
        if not plans:
            self.threads.take_up(picks[0], day, acted=self.strategy != "portfolio")
            self.ledger.decide(day, "silence", "the world has what this story needs", phase=phase, opportunity=picks[0].opportunity_id,
                               kind=picks[0].kind, arc_phase="hold", arcs_active=len(self.threads.active()))
            return
        pick, props, imagined = plans[0][0], plans[0][1], None
        if self.strategy == "lookahead" and self._clean is not None:
            pick, props, imagined = self._imagine(day, plans, phase)
            if pick is None:
                return
        self._admit(conn, pick, props, day, now, phase, imagined)

    # -- who is the story today ----------------------------------------------------------------------------------------
    def _novelty(self, o: Opportunity) -> float:
        """How new this story would be, told: what has been told in the world (and what is being told now) counts against it."""
        from narrative import novelty
        mem = novelty.PatternMemory.of(self.threads.found)
        for t in self.threads.active():
            mem.mechanics[novelty.MECHANIC_OF_STORY[t.kind]] = mem.mechanics.get(novelty.MECHANIC_OF_STORY[t.kind], 0) + 1
        pair = f"seat:{o.evidence['seat']}" if o.kind == "succession" else "|".join(sorted([o.protagonist, o.evidence.get("object") or o.others[0]]))
        return mem.novelty(novelty.MECHANIC_OF_STORY[o.kind], pair)

    def _worth(self, o: Opportunity, day: int) -> float:
        if self.strategy == "portfolio":
            fresh = self._novelty(o)
        else:
            fresh = VARIETY ** sum(1 for d, k in self._taken if k == o.kind and day - d < VARIETY_DAYS)
        return o.potential * fresh * (1.0 + WAIT_BONUS * self.threads.waited(o.protagonist, day))

    def _ranked(self, conn: sqlite3.Connection, ops: list[Opportunity], day: int) -> list[Opportunity]:
        """The stories that could be tended today. The aimed strategies: the most worth having first, one per protagonist; the
        random ones: all of them, so that a draw from the list is a draw among the stories."""
        from world.domains.roles import role_of
        open_ = [o for o in ops if not any(m.lack == "recovery" for m in o.missing) and not self.threads.resting(o.protagonist, day)
                 and role_of(conn, o.protagonist, day) is None]
        if self.strategy in RANDOM_AIM:
            return open_
        if self.strategy == "portfolio":   # the hard constraints first: not given up lately, and not a repeat
            open_ = [o for o in open_ if not self.threads.blocked(o.opportunity_id, day) and self._novelty(o) >= NOVELTY_FLOOR]
        out, seen = [], set()
        for o in sorted(open_, key=lambda o: (-self._worth(o, day), o.opportunity_id)):
            if o.protagonist not in seen:
                seen.add(o.protagonist)
                out.append(o)
        return out

    # -- from a lack to proposals ----------------------------------------------------------------------------------------
    def _proposals(self, wanted: list[shaper.Candidate], op: Opportunity, day: int) -> list[InterventionProposal]:
        props = []
        for c in wanted[:MAX_PER_DAY]:
            if c.type == "announce_gathering" and day - self._last_stage < STAGE_GAP:
                continue
            if c.type == "open_seat" and day - self._last_seat < SEAT_GAP:
                continue
            opaque = "iv-" + hashlib.sha256(f"{self.seed}:{op.opportunity_id}:{c.type}:{c.target}:{day}".encode()).hexdigest()[:10]
            # the season is the day and the arc is the opportunity: both stay in this ledger, the world is given neither
            props.append(InterventionProposal(opaque, f"day{day}", op.opportunity_id, c.type, c.target, dict(c.params), day, c.cost, c.purpose,
                                              source="director"))
        return props

    def _imagine(self, day: int, plans, phase: str):
        """Run copies of the world a few days ahead with each of the best stories' answers, and with nothing: do the one the futures favour."""
        from producer import forecast
        bundles = {op.opportunity_id: (props, {op.protagonist, *op.others}) for op, props in plans}
        fc = forecast.evaluate(self._clean, day, self.ledger, bundles)
        score = {k: fc[k].gain - forecast.COST_WEIGHT * sum(p.budget_cost for p in bundles[k][0]) for k in bundles}
        best = max(score, key=lambda k: (score[k], k))
        summary = {k: {"gain": v.gain, "p_payoff": v.p_payoff, "p_played": v.p_played, "earned": v.expected_earned} for k, v in fc.items()}
        op, props = next((o, p) for o, p in plans if o.opportunity_id == best)
        if score[best] < forecast.MIN_GAIN:
            self.ledger.decide(day, "silence", "imagined futures come out as well without it", phase=phase, forecast=summary, score=score,
                               opportunity=op.opportunity_id, kind=op.kind)
            return None, None, None
        return op, props, {"chosen": best, "forecast": summary[best], "silence": summary["silence"], "score": round(score[best], 4)}

    def _admit(self, conn: sqlite3.Connection, pick: Opportunity, props: list[InterventionProposal], day: int, now: int, phase: str, imagined) -> None:
        done, refused = [], []
        for prop in props:
            v = self.ledger.admit(conn, prop, now)
            (done if v.admitted else refused).append((prop.type, "" if v.admitted else v.reason))
            if v.admitted and prop.type == "announce_gathering":
                self._last_stage = day
            if v.admitted and prop.type == "open_seat":
                self._last_seat = day
        if done:
            self.threads.take_up(pick, day)
            self._taken.append((day, pick.kind))
        extra = {"imagined": imagined} if imagined else {}
        self.ledger.decide(day, "intervene" if done else "silence", "supplied what the story lacked" if done else "nothing could be admitted",
                           phase=phase, opportunity=pick.opportunity_id, kind=pick.kind, protagonist=pick.protagonist, others=pick.others,
                           potential=pick.potential, p_success=pick.p_success, lacks=[m.lack for m in pick.missing],
                           admitted=[t for t, _ in done], refused=refused, strength=[STRENGTH[t] for t, _ in done], arc_phase="build",
                           arcs_active=len(self.threads.active()), **extra)
