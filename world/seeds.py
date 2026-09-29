"""The seed layer: outside events come in at dawn, adapted to this town, and only through apply_event.

Kill rules (tests enforce them):
1. An outside event never decides an outcome. The adapter turns a topic into SeedEffects from a closed vocabulary:
   set a world variable (only SEED_VARS), place a prop, deliver a parcel, change a prop's value, spread news.
2. It enters the world only as one `seed` event per adopted candidate. The event's truth carries the external
   event id, the candidate hash and the feed hash.
3. The feed arrives on its own timetable. It does not look at how dramatic the town is.
4. Seeds use invented places and people only.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from functools import lru_cache
from pathlib import Path

from contracts.base import from_dict
from contracts.seed import AUDIENCES, SEED_VARS, ExternalEvent, SeedCandidate, SeedEffect, SeedFeed
from world.attention import var
from world.events import Change, EventSpec, MemorySpec, apply_event
from world.rng import rng as make_rng

FEEDS = Path(__file__).with_name("feeds")
DAWN_SLOT = 420
MIN_RELEVANCE = 0.5
MIN_CONFIDENCE = 0.5
BASE_VARS = {"price_food": 800.0, "visibility": 1.0, "job_security": 1.0}

# domain -> the location tag that makes it exist in this town (None: exists everywhere)
DOMAIN_TAG = {"food": "food", "work": "work", "social": "social", "home": "home", "transit": "transit",
              "infrastructure": None, "animals": None, "gambling": "food"}


def _news(text: str, audience: str = "everyone") -> SeedEffect:
    return SeedEffect("news", audience=audience, text=text)


def _adapt_topic(ev: ExternalEvent) -> tuple[str, list[str], list[SeedEffect]] | None:
    """Topic -> (seed type, domains, effects). The only place that says what an outside fact can do here."""
    m = max(0.0, min(2.0, ev.magnitude))
    table = {
        "food_prices_up": ("pressure", ["food"], [
            SeedEffect("set_var", key="price_food", value=round(BASE_VARS["price_food"] * (1 + m)), revert_after_days=5),
            _news("聽說食物全面漲價，咖啡店的餐點也貴了")]),
        "power_outage": ("disruption", ["infrastructure"], [
            SeedEffect("set_var", key="visibility", value=0.3, revert_after_days=1),
            _news("停電了，到處都暗暗的")]),
        "sector_layoffs": ("information", ["work"], [
            SeedEffect("set_var", key="job_security", value=round(max(0.0, 1 - 0.4 * m), 2), revert_after_days=7),
            _news("聽說公司要裁員", "workers")]),
        "courier_mixup": ("disruption", ["home"], [SeedEffect("deliver_object", key="package")]),
        "lottery_ticket_lost": ("opportunity", ["gambling"], [SeedEffect("place_object", key="ticket", at="cafe")]),
        "lottery_draw": ("information", ["gambling"], [
            SeedEffect("set_object_value", key="ticket", value=round(300000 * m)),
            _news("頭獎彩券是在咖啡店賣出的，到現在還沒人領獎")]),
        "exotic_pet_escape": ("stimulus", ["animals", "food"], [
            SeedEffect("place_object", key="parrot", at="cafe"),
            _news("咖啡店飛進來一隻鸚鵡，老闆把牠留下了，牠什麼話都學")]),
        "stray_animals": ("opportunity", ["animals", "social"], [SeedEffect("animal_arrives", key="dog", at="park")]),
    }
    return table.get(ev.topic)


@lru_cache(maxsize=None)
def load_feed(name: str) -> SeedFeed:
    data = json.loads((FEEDS / f"{name}.json").read_text(encoding="utf-8"))
    feed = SeedFeed(data["feed_id"], [from_dict(ExternalEvent, e) for e in data["events"]])
    for ev in feed.events:
        adapted = _adapt_topic(ev)
        if adapted is not None:
            check_effects(adapted[2])
    return feed


def feed_hash(name: str) -> str:
    data = (FEEDS / f"{name}.json").read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def check_effects(effects: list[SeedEffect]) -> None:
    """Kill rule 1, checked on every effect before it can touch the world."""
    for e in effects:
        if e.op == "set_var" and e.key not in SEED_VARS:
            raise ValueError(f"a seed may not set {e.key!r}")
        if e.op == "news" and e.audience not in AUDIENCES:
            raise ValueError(f"unknown audience {e.audience!r}")
        if e.op not in ("set_var", "place_object", "deliver_object", "set_object_value", "news", "animal_arrives"):
            raise ValueError(f"op {e.op!r} is not in the closed vocabulary")


def _tags(conn: sqlite3.Connection) -> set[str]:
    return {t for (tags,) in conn.execute("SELECT tags FROM locations") for t in json.loads(tags)}


def adapt(conn: sqlite3.Connection, ev: ExternalEvent) -> SeedCandidate:
    """Take an outside event in, or say why not. Relevance = share of its domains that exist in this town."""
    adapted = _adapt_topic(ev)
    if adapted is None:
        return _finish(SeedCandidate(f"seed-{ev.external_event_id}", ev.external_event_id, "stimulus", 0.0, [], [],
                                     "rejected", f"no adapter for topic {ev.topic!r}"))
    seed_type, domains, effects = adapted
    tags = _tags(conn)
    relevance = round(sum(1 for d in domains if DOMAIN_TAG.get(d) is None or DOMAIN_TAG[d] in tags) / len(domains), 3)
    status, reason = "adopted", ""
    if relevance < MIN_RELEVANCE:
        status, reason = "rejected", "the town has little of what this touches"
    elif ev.confidence < MIN_CONFIDENCE:
        status, reason = "rejected", "too uncertain"
    else:
        for e in effects:
            row = conn.execute("SELECT status FROM objects WHERE id = ?", (e.key,)).fetchone() if e.op in (
                "place_object", "deliver_object", "set_object_value") else None
            if e.op in ("place_object", "deliver_object") and (row is None or row[0] != "offstage"):
                status, reason = "rejected", f"{e.key} is already in the town"
            if e.op == "animal_arrives":
                animal = conn.execute("SELECT status FROM people WHERE id = ?", (e.key,)).fetchone()
                if animal is None or animal[0] != "inactive":
                    status, reason = "rejected", f"{e.key} is already in the town"
            if e.op == "set_object_value" and (row is None or row[0] != "normal"):
                status, reason = "rejected", f"{e.key} is not in the town"
    return _finish(SeedCandidate(f"seed-{ev.external_event_id}", ev.external_event_id, seed_type, relevance, domains,
                                 effects, status, reason))


def _finish(c: SeedCandidate) -> SeedCandidate:
    from dataclasses import replace
    return replace(c, candidate_hash=c.compute_hash())


def _audience(conn: sqlite3.Connection, audience: str) -> list[str]:
    if audience == "workers":
        return [r[0] for r in conn.execute("SELECT id FROM people WHERE schedule LIKE '%\"work\"%' ORDER BY id")]
    if audience.startswith("at_"):
        return [p for p in humans(conn) if conn.execute("SELECT location_id FROM people WHERE id = ?", (p,)).fetchone()[0] == audience[3:]]
    return humans(conn)


def humans(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT p.id FROM people p LEFT JOIN personas s ON s.person_id = p.id "
        "WHERE COALESCE(json_extract(s.traits, '$.species'), 'human') = 'human' ORDER BY p.id")]


def effect_changes(conn: sqlite3.Connection, c: SeedCandidate, day: int, now: int) -> tuple[list[Change], list[MemorySpec], dict]:
    """What the effects do to the world, as ordinary Changes and memories. Nothing else is possible."""
    check_effects(c.effects)
    seed = conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
    rng = make_rng(seed, now, c.seed_id, "seed_effect")
    changes: list[Change] = []
    memories: list[MemorySpec] = []
    picks: dict = {}
    for e in c.effects:
        if e.op == "set_var":
            changes.append(Change("var", e.key, "value", delta=round(e.value - var(conn, e.key, 0.0), 6)))
            if e.revert_after_days:
                changes.append(Change("var", f"revert.{e.key}", "value",
                                      delta=float(day + e.revert_after_days) - var(conn, f"revert.{e.key}", -1.0)))
        elif e.op == "place_object":
            changes += [Change("object", e.key, "status", value="normal"), Change("object", e.key, "location_id", value=e.at)]
        elif e.op == "deliver_object":
            people = humans(conn)
            holder = rng.choice(people)
            rightful = rng.choice([p for p in people if p != holder])
            picks.update(holder=holder, rightful=rightful)
            changes += [Change("object", e.key, "status", value="normal"),
                        Change("object", e.key, "owner_person_id", value=holder),
                        Change("object", e.key, "rightful_owner_id", value=rightful)]
        elif e.op == "animal_arrives":  # a stray turns up; what it does from here is its own affair
            changes += [Change("person", e.key, "status", value="active"), Change("person", e.key, "location_id", value=e.at)]
        elif e.op == "set_object_value":
            cur = conn.execute("SELECT value_cents FROM objects WHERE id = ?", (e.key,)).fetchone()[0]
            if int(e.value) != cur:
                changes.append(Change("object", e.key, "value_cents", delta=int(e.value) - cur))
        elif e.op == "news":
            memories += [MemorySpec(p, e.text, 0.9, source_type="external_rumor", source_id=c.external_event_id)
                         for p in _audience(conn, e.audience)]
    return changes, memories, picks


class SeedLayer:
    """Runs at dawn: first temporary changes that wear off, then today's outside events."""

    def __init__(self, conn: sqlite3.Connection, feed: str) -> None:
        self.conn = conn
        self.feed_name = feed
        self.feed = load_feed(feed)
        self.feed_hash = feed_hash(feed)

    def dawn(self, day: int) -> list[SeedCandidate]:
        now = day * 1440 + DAWN_SLOT
        for key, base in sorted(BASE_VARS.items()):
            if var(self.conn, f"revert.{key}", -1.0) == day:
                apply_event(self.conn, EventSpec(
                    timestamp=now, type="seed_wears_off", trigger_type="rule", importance=0.1,
                    truth={"var": key, "back_to": base},
                    changes=[Change("var", key, "value", delta=round(base - var(self.conn, key, base), 6)),
                             Change("var", f"revert.{key}", "value", delta=-1.0 - day)]))
                now += 1
        out = []
        for ev in sorted((e for e in self.feed.events if e.day == day), key=lambda e: e.external_event_id):
            cand = adapt(self.conn, ev)
            out.append(cand)
            if cand.status != "adopted":
                continue
            changes, memories, picks = effect_changes(self.conn, cand, day, now)
            participants = [(p, r) for r, p in (("receiver", picks.get("holder")), ("addressee", picks.get("rightful"))) if p]
            apply_event(self.conn, EventSpec(
                timestamp=now, type="seed", trigger_type="external", importance=0.3 + 0.3 * ev.salience,
                truth={"external_event_id": ev.external_event_id, "title": ev.title, "topic": ev.topic,
                       "seed_type": cand.seed_type, "candidate_hash": cand.candidate_hash, "feed": self.feed_name,
                       "feed_hash": self.feed_hash, "external_event_hash": ev.hash(), "picks": picks,
                       "object": next((e.key for e in cand.effects if e.op != "set_var" and e.key), None)},
                participants=participants, changes=changes, memories=memories))
            now += 1
        return out
