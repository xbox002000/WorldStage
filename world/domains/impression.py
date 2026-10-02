"""First impressions, as a domain pack (primitive social.impression): how one looks, how warm one is to be with, and how much
one speaks. Three numbers each person is born with (the genome's `looks`, `warmth`, `talkativeness`, each 0..1; when the genome
does not say, they are derived: looks is the charm, warmth and talk come from the temperament and the social style, `derive`),
and what the world makes of them. The same face is not the same person: a cold beauty, a kind neighbour and a plain good soul
live differently here, and nothing is scripted, it falls out of the rules below. Every rule has a source (what makes it) and a
reader (what it moves).

  attention   Whom one talks to. A stranger's looks draw the eye, and fade as one gets to know them; their warmth draws one in,
              and grows the better one knows them: weight = looks x (1 - known) + warmth x known, centred on 0.5 and taken
              from the mean of the people one could talk to (it moves whom, not how much).   [read in shape]
  talk        One who talks a lot opens their mouth more (talk and tell are likelier); a quiet one answers less (`reticence`,
              read by agent/reply.py). The world var `impression.talk.<pid>` is the level now (the number, dulled when one is
              upset), and `reply_length` turns it into short / normal / long for whoever writes the lines.   [shape; reticence]
  misread     A good-looking, quiet, unwarm person is taken for contemptuous by someone who does not know them yet: in an
              exchange that is not warm, the other's respect and affection for them fall (`truth.impression.misread`); once they
              do know them, the same exchange shows who they really are and both rise (`revealed`). An early bias that the
              event record can show, and that reverses.   [effects on `talk`]
  gossip      What is told: the better-looking the person it is about, the likelier it is passed on.   [shape on `tell`]
  envy        Somebody of the same sex who is clearly outshone, in the room while a person is spoken to, courted or won,
              resents them a little (resentment, `truth.impression.envy`; more when both are drawn to the one who speaks).   [effects]
  kindness    The warm are liked faster (affection) and, once known, trusted (trust); the pull of looks is kept apart: romance
              reads `looks` where it used to read `charm` (world/domains/romance.py), so a warm plain person is liked a lot and
              desired less: the friend one does not fall for.   [effects; romance.charm]

Nothing in a world without this primitive reads any of it.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from contracts.recipe import MechanicPrimitive as P
from world.domains.base import Domain, Scored, add_changes, situation
from world.helpers import RelDeltas

IMPRESSION_VERSION = "impression_v0.1"   # a draft: the constants below are first guesses, never tuned to the acceptance numbers (docs/impression.md)
F_KNOWN = 0.30         # familiarity at which one counts as knowing somebody (a median pair is at ~0.16 after six days)
LOOK_ATT = 1.0          # how strongly a stranger's looks draw the eye (score, centred on 0.5)
WARM_ATT = 0.7          # ... and how strongly a known person's warmth draws one in
TALK_DRIVE = 0.7        # how much more (or less) a talkative (quiet) person opens their mouth: score on a talk
TELL_DRIVE = 0.4        # ... and on passing something on
GOSSIP_LOOKS = 0.5      # a story about somebody good-looking is passed on more (a plain one's less): score x (looks - 0.5) x 2
RETICENCE = 0.6         # how much a quiet person leans to not answering (score on the "say nothing" answer)
MISREAD_MIN = 0.20      # looks x (1 - talk) x (1 - warmth) from which one is taken for cold
MISREAD_RESPECT = 0.05  # what respect falls by per exchange with a stranger, times how cold they seem
MISREAD_AFFECTION = 0.03
MISREAD_BELOW = 0.20    # familiarity below which silence is read as contempt
REVEAL_FROM = 0.20      # familiarity from which the exchange shows who they are ...
REVEAL_SPAN = 0.20      # ... fully by this much further
REVEAL_RESPECT = 0.05
REVEAL_AFFECTION = 0.03
REVEAL_CEIL = 0.5       # it lifts respect only up to about here
WARM_AFFECTION = 0.03   # liked faster: affection per friendly exchange, times how far warmth is above 0.45
WARM_TRUST = 0.02       # trusted once known: trust per friendly exchange, times the same and how well one knows them
ENVY_GAP = 0.20         # outshone by at least this much in looks (same sex) to envy
ENVY = 0.0015           # resentment per scene, times the gap (x 2.5 when both are drawn to the one who speaks)
UPSET = ("angry", "hurt", "ashamed", "scared")
SHORT, LONG = 0.33, 0.67  # a talk level below / above these is a short / a long answer
WARM_WORDS = ("熱情", "親切", "友善", "自來熟", "八面玲瓏", "笑臉", "熱心", "照顧", "寬厚", "豪爽", "大方", "護短")
COOL_WORDS = ("冷淡", "防備", "傲氣", "驕傲", "威嚴", "霸氣", "若即若離", "不願牽絆", "藏得很深")
CHATTY_WORDS = ("話多", "太黏", "黏人", "愛誇大", "愛逞強", "嘴巴壞", "熱情", "自來熟", "八面玲瓏", "熱心", "豪爽")
QUIET_WORDS = ("少", "少言", "安靜", "慢熱", "沉默", "冷淡", "嘴笨", "不善表達")
KEPT = ("talk", "flirt", "date", "confession")   # events that turn some eyes to the one spoken to
TEMPERAMENT = {"honesty": 0.6, "temper": 0.4, "gossip": 0.4, "generosity": 0.4, "absent_minded": 0.3, "curiosity": 0.4}


@dataclass(frozen=True)
class Presence:
    looks: float
    warmth: float
    talk: float

    def cold(self) -> float:
        """0..1: how much one reads as aloof: good-looking, quiet and not warm."""
        return round(self.looks * (1.0 - self.talk) * (1.0 - self.warmth), 4)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _hits(words: tuple[str, ...], tokens: list[str]) -> int:
    """How many of the style tokens say one of the words (a one-character word must be the whole token)."""
    return sum(1 for t in tokens if any((w == t) if len(w) == 1 else (w in t) for w in words))


def derive(traits: dict, social=None) -> tuple[float, float]:
    """(warmth, talk) from a temperament and a social style (strangers / friends / intimate words), when the genome does not
    say. Fixed formulas, nothing hidden:

        style_warm = clamp(0.10 x (warm words - cool words), -0.2, 0.2)       style_talk = ... (chatty words - quiet words)
        warmth = 0.15 + 0.40 generosity + 0.20 (1 - temper) + 0.15 honesty + style_warm
        talk   = 0.10 + 0.40 gossip + 0.25 curiosity + 0.10 generosity + style_talk
    """
    t = {**TEMPERAMENT, **{k: float(v) for k, v in traits.items() if k in TEMPERAMENT}}
    tokens = [x for x in (getattr(social, "strangers", ""), getattr(social, "friends", ""), getattr(social, "intimate", "")) if x]
    sw = _clamp(0.10 * (_hits(WARM_WORDS, tokens) - _hits(COOL_WORDS, tokens)), -0.2, 0.2)
    st = _clamp(0.10 * (_hits(CHATTY_WORDS, tokens) - _hits(QUIET_WORDS, tokens)), -0.2, 0.2)
    warmth = 0.15 + 0.40 * t["generosity"] + 0.20 * (1.0 - t["temper"]) + 0.15 * t["honesty"] + sw
    talk = 0.10 + 0.40 * t["gossip"] + 0.25 * t["curiosity"] + 0.10 * t["generosity"] + st
    return round(_clamp(warmth), 4), round(_clamp(talk), 4)


def values(conn: sqlite3.Connection, pid: str) -> Presence:
    """Somebody's three numbers: the genome's, or what `derive` makes of who they are (looks: the charm)."""
    from world.personas import genome
    from world.profiles import profile
    g = genome(conn, pid)
    row = conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
    try:
        traits = json.loads(row[0]) if row else {}
    except (TypeError, ValueError):
        traits = {}
    warmth, talk = derive(traits, getattr(profile(conn, pid), "social", None))
    if g is None:
        return Presence(0.5, warmth, talk)
    return Presence(_clamp(g.looks if g.looks is not None else g.charm),
                      _clamp(g.warmth if g.warmth is not None else warmth),
                      _clamp(g.talkativeness if g.talkativeness is not None else talk))


def looks(conn: sqlite3.Connection, pid: str) -> float:
    return values(conn, pid).looks


def talk_level(conn: sqlite3.Connection, pid: str) -> float:
    """0..1: how much somebody talks now: their number, dulled when they are upset, and lifted a little when they are happy."""
    base = values(conn, pid).talk
    mood = conn.execute("SELECT emotion FROM people WHERE id = ?", (pid,)).fetchone()
    emotion = mood[0] if mood else ""
    return round(_clamp(base * (0.6 if emotion in UPSET else 1.15 if emotion == "happy" else 1.0)), 4)


def reply_length(conn: sqlite3.Connection, pid: str) -> str:
    """How long somebody's answers are: "short" (a few cold words), "normal" or "long". Read only: for whoever writes the lines
    (narrative/speech.py); the world var `impression.talk.<pid>` carries the same level."""
    level = talk_level(conn, pid)
    return "short" if level < SHORT else "long" if level > LONG else "normal"


def familiarity(conn: sqlite3.Connection, a: str, b: str) -> float | None:
    """What `a` knows `b` (None when the two have no relationship row yet)."""
    r = conn.execute("SELECT familiarity FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()
    return None if r is None else r[0]


def attention(conn: sqlite3.Connection, me: str, other: str) -> float:
    """How much `other` draws `me` to talk to them: a stranger's looks, then as one comes to know them their warmth."""
    fam = familiarity(conn, me, other)
    iv = values(conn, other)
    known = _clamp(max(0.0, fam or 0.0) / F_KNOWN)
    return round(LOOK_ATT * (iv.looks - 0.5) * (1.0 - known) + WARM_ATT * (iv.warmth - 0.5) * known, 4)


def _gender(conn: sqlite3.Connection, pid: str) -> str:
    from world.profiles import profile
    p = profile(conn, pid)
    return p.gender if p else ""


class Impression(Domain):
    id = "impression"
    title = "第一印象"
    primitives = (P("social.impression", "social", "looks, warmth and talkativeness: whom one notices, who is taken for cold, who "
                    "is gossiped about and envied, who is liked and who is desired", ["social.depth"], cost=0),)
    situation_kinds = {"misread": "被誤會的冷淡", "misread_turn": "誤會解開", "friend_zone": "被當成朋友"}

    # -- what it leans: whom one speaks to, and how much ----------------------------------------------------------------
    def shape(self, conn: sqlite3.Connection, actor: str, now: int, scored: Scored) -> Scored:
        me = values(conn, actor)
        drive = me.talk - 0.5
        # attention says WHOM one talks to, not how much: it is taken from the mean over the people one could talk to, so a room
        # full of beauties does not make anyone talk more, only to somebody else (the first draft added it as it was and shifted
        # the world's mix of actions: talk +12%, tell -35%)
        gaze = {it.target: attention(conn, actor, it.target) for _, it in scored if it is not None and it.action == "talk" and it.target}
        centre = sum(gaze.values()) / len(gaze) if gaze else 0.0
        subjects: dict[int, str | None] = {}
        out = []
        for score, it in scored:
            if it is not None and it.action == "talk" and it.target:
                score += TALK_DRIVE * drive + gaze[it.target] - centre
            elif it is not None and it.action == "tell":
                score += TELL_DRIVE * drive
                if it.claim_id is not None:
                    if it.claim_id not in subjects:
                        r = conn.execute("SELECT subject FROM claims WHERE claim_id = ?", (it.claim_id,)).fetchone()
                        subjects[it.claim_id] = r[0] if r else None
                    who = subjects[it.claim_id]
                    if who and who not in (actor, it.target):
                        score += GOSSIP_LOOKS * 2.0 * (looks(conn, who) - 0.5)
            out.append((score, it))
        return out

    def reticence(self, conn: sqlite3.Connection, pid: str, other: str, now: int) -> float:
        """A quiet person leans to not answering; a talkative one to answering (score on saying nothing)."""
        return round(RETICENCE * (0.5 - talk_level(conn, pid)), 4)

    # -- what it does ---------------------------------------------------------------------------------------------------
    def effects(self, conn: sqlite3.Connection, spec, primitives: set[str]):
        t = spec.truth
        if spec.type not in KEPT:
            return spec
        a, b = t.get("actor"), t.get("target")
        if not a or not b or a == b or (spec.type == "confession" and t.get("outcome") != "accepted"):
            return spec
        d = RelDeltas()
        note: dict = {}
        if spec.type == "talk":
            tone = t.get("tone")
            for y, x in ((a, b), (b, a)):  # y is in the exchange with x
                fam = familiarity(conn, y, x)
                if fam is None or tone == "hostile":
                    continue
                self._first_impression(conn, d, note, y, x, max(0.0, fam), tone, values(conn, x))
        self._envy(conn, d, note, spec, a, b)
        if not d._sum:
            return spec
        return add_changes(conn, spec, d.changes(conn), truth={"impression": note} if note else None)

    def _first_impression(self, conn, d: RelDeltas, note: dict, y: str, x: str, fam: float, tone: str, iv: Presence) -> None:
        cold = iv.cold()
        if cold >= MISREAD_MIN:
            if fam < MISREAD_BELOW and tone != "warm":  # silence taken for contempt, by somebody who does not know them
                k = cold * (1.0 - fam / MISREAD_BELOW)
                d.add(y, x, "respect", -MISREAD_RESPECT * k)
                d.add(y, x, "affection", -MISREAD_AFFECTION * k)
                note.setdefault("misread", []).append({"reader": y, "of": x, "cold": cold, "known": round(fam, 3)})
            elif fam >= REVEAL_FROM:  # once they know them, the same reserve is read for what it is
                from world.helpers import rel
                ramp = _clamp((fam - REVEAL_FROM) / REVEAL_SPAN)
                room = _clamp(1.0 - max(0.0, rel(conn, y, x, "respect")) / REVEAL_CEIL)
                d.add(y, x, "respect", REVEAL_RESPECT * cold * ramp * room)
                d.add(y, x, "affection", REVEAL_AFFECTION * cold * ramp * room)
                note.setdefault("revealed", []).append({"reader": y, "of": x, "cold": cold, "known": round(fam, 3)})
        if tone in ("warm", "neutral") and iv.warmth > 0.45:  # the warm are liked faster, and once known, trusted
            lift = iv.warmth - 0.45
            d.add(y, x, "affection", WARM_AFFECTION * lift)
            d.add(y, x, "trust", WARM_TRUST * lift * _clamp(fam / F_KNOWN))

    def _envy(self, conn, d: RelDeltas, note: dict, spec, a: str, b: str) -> None:
        """Those of the same sex who are clearly outshone, in the room while somebody is spoken to, resent them a little."""
        if not spec.location_id:
            return
        from world.attention import present
        from world.domains.romance import drawn_to
        gender, vb = _gender(conn, b), values(conn, b)
        if not gender:
            return
        for w in present(conn, spec.location_id, a, b):
            if _gender(conn, w) != gender or familiarity(conn, w, b) is None:
                continue
            gap = vb.looks - values(conn, w).looks
            if gap < ENVY_GAP:
                continue
            contested = drawn_to(conn, w, a) and drawn_to(conn, b, a)
            d.add(w, b, "resentment", ENVY * gap * (2.5 if contested else 1.0))
            note.setdefault("envy", []).append({"who": w, "of": b, "gap": round(gap, 3), "contested": bool(contested)})

    def overnight(self, conn: sqlite3.Connection, pid: str, now: int) -> list:
        """The world var `impression.talk.<pid>` follows the level of the day (it starts from the style words alone)."""
        from world.events import Change
        key = f"impression.talk.{pid}"
        row = conn.execute("SELECT value FROM world_vars WHERE key = ?", (key,)).fetchone()
        if row is None:
            return []
        want = talk_level(conn, pid)
        return [Change("var", key, "value", delta=round(want - row[0], 6))] if abs(want - row[0]) >= 0.01 else []

    def initial_vars(self, pid: str, profile) -> dict[str, float]:
        """Where the talk level starts, from the style words only (the profile is all that is known here): the first night
        replaces it with the real level."""
        tokens = [x for x in (getattr(getattr(profile, "social", None), "strangers", ""), getattr(getattr(profile, "social", None), "friends", ""),
                              getattr(getattr(profile, "social", None), "intimate", "")) if x]
        return {f"impression.talk.{pid}": round(_clamp(0.5 + 0.1 * (_hits(CHATTY_WORDS, tokens) - _hits(QUIET_WORDS, tokens)), 0.0, 1.0), 4)}

    # -- read models ----------------------------------------------------------------------------------------------------
    def influences(self, conn: sqlite3.Connection, pid: str, now: int) -> list[dict]:
        iv = values(conn, pid)
        if abs(iv.talk - 0.5) < 0.2:
            return []
        return [{"kind": "impression", "talk": round(iv.talk, 2), "leans": "speaks up" if iv.talk > 0.5 else "holds back"}]

    def describe(self, conn: sqlite3.Connection, pid: str) -> dict:
        iv = values(conn, pid)
        return {"外貌": round(iv.looks, 2), "親和": round(iv.warmth, 2), "話量": round(iv.talk, 2), "答話": reply_length(conn, pid)}

    def situations(self, conn: sqlite3.Connection, names: dict) -> list[dict]:
        """A quiet beauty taken for cold by somebody (and the day it turned), and the friend somebody loves who loves them back
        as a friend. Read only, from the events and from how people stand."""
        n = lambda p: names.get(p, p)  # noqa: E731
        out: list[dict] = []
        seen: dict[tuple[str, str], dict] = {}
        for eid, ts, truth in conn.execute("SELECT event_id, timestamp, truth FROM events WHERE type = 'talk' AND "
                                           "json_extract(truth, '$.impression') IS NOT NULL ORDER BY event_id"):
            imp = json.loads(truth).get("impression", {})
            for kind in ("misread", "revealed"):
                for m in imp.get(kind, []):
                    s = seen.setdefault((m["reader"], m["of"]), {"misread": [], "revealed": [], "day": ts // 1440})
                    s[kind].append(eid)
        for (y, x), s in sorted(seen.items()):
            if s["revealed"] and s["misread"]:
                out.append(situation("misread_turn", 0.5, s["day"], [y, x], f"{n(y)}原本以為{n(x)}看不起人，後來才知道只是慢熱",
                                     f"{n(y)}會怎麼對{n(x)}？", s["misread"][:2] + s["revealed"][:2], build=0.5, lasts=4))
            elif len(s["misread"]) >= 2:
                out.append(situation("misread", 0.5, s["day"], [y, x], f"{n(y)}把{n(x)}的冷淡當成看不起人",
                                     f"{n(y)}會發現{n(x)}只是慢熱嗎？", s["misread"][:4], build=min(1.0, len(s["misread"]) / 4), lasts=5))
        from world.domains.romance import drawn_to
        rows = {(r["actor_id"], r["target_id"]): r for r in conn.execute("SELECT actor_id, target_id, attraction, affection FROM relationships")}
        day = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0] // 1440
        for (p, q), r in sorted(rows.items()):
            back = rows.get((q, p))
            if back is not None and r["attraction"] >= 0.22 and back["affection"] >= 0.30 and back["attraction"] < 0.15 \
                    and drawn_to(conn, p, q):
                out.append(situation("friend_zone", 0.55, day, [p, q], f"{n(q)}把{n(p)}當成好朋友，{n(p)}想的卻不只是朋友",
                                     f"{n(p)}要不要說出口？", [], build=min(1.0, r["attraction"]), stakes=0.4, lasts=5))
        return out
