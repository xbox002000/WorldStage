"""Topics: what people talk about, as a domain pack (primitive social.topics). Genre-free: the topics are the content
pack's own vocabulary (world/content/profiles/<content>.json), 釣魚 in a town, 劍法 at an inn.

Choosing (the speaker, from what they know):
  - one's own interests, weighted by what one has learnt the other likes (a stranger's taste is a guess);
  - a dislike one knows the other shares;
  - someone both resent ("@person"), if one has reason to think the other resents them too.
  A hostile word is not small talk: it gets no topic.

What follows (the rule, from what is true):
  - the listener likes it: they warm to the speaker; shared passions draw people together;
  - the listener hates it: it grates;
  - the listener is upset: even their favourite topic, pressed on them, irritates;
  - a shared dislike, or a shared grudge against someone: allies (and the grudge hardens);
  - backbiting to someone who likes the person spoken of: it costs the speaker.
  Both learn each other's taste (claims like/dislike): the next conversation can be better aimed.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import replace

from contracts.claim import Claim
from contracts.recipe import MechanicPrimitive as P
from world.domains.base import ActionSpec, ClaimAct, Domain, EventStyle, add_changes  # noqa: F401
from world.events import EventSpec, MemorySpec, ClaimSpec
from world.helpers import RelDeltas, person, rel
from world.intent import Intent
from world.rng import rng as make_rng

PRIOR = 0.25     # what one expects of a topic when one does not know the other's taste
LEARNT = 0.8     # how sure one is of a taste one heard in conversation
GRUDGE = -0.3    # trust below this: someone one resents
PICK_TEMPERATURE = 0.15
UPSET = ("angry", "hurt", "ashamed", "scared")  # too upset for small talk
LOW = ("uneasy", "embarrassed")                    # low, and a friend's favourite topic can lift it
HARMFUL = ("steal", "take", "deceive", "conceal", "speak_hostile", "speak_cold", "threaten", "accuse")


def taste(conn: sqlite3.Connection, pid: str, topic: str) -> float:
    """-1..1: how much someone likes a topic (their profile, plus how life has changed it)."""
    from world.attention import var
    from world.profiles import profile
    p = profile(conn, pid)
    base = (p.interests.get(topic, 0.0) - p.dislikes.get(topic, 0.0)) if p else 0.0
    return max(-1.0, min(1.0, base + var(conn, f"taste.{pid}.{topic}", 0.0)))


def known_taste(conn: sqlite3.Connection, me: str, other: str, topic: str) -> float | None:
    """What `me` has learnt of `other`'s taste for a topic: +confidence (likes), -confidence (dislikes), or None."""
    row = conn.execute(
        "SELECT c.act, m.confidence FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id = ? AND c.subject = ? "
        "AND c.object = ? AND c.act IN ('like', 'dislike') AND c.polarity = 'affirm' ORDER BY m.memory_id DESC LIMIT 1",
        (me, other, topic)).fetchone()
    if row is None:
        return None
    return row[1] if row[0] == "like" else -row[1]


def known_tastes(conn: sqlite3.Connection, me: str, other: str) -> dict[str, float]:
    """`known_taste` for every topic at once: {topic: +confidence (likes) or -confidence (dislikes)}, the latest memory of each."""
    out: dict[str, float] = {}
    for obj, act, conf in conn.execute(
            "SELECT c.object, c.act, m.confidence FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id = ? "
            "AND c.subject = ? AND c.act IN ('like', 'dislike') AND c.polarity = 'affirm' ORDER BY m.memory_id", (me, other)):
        out[obj] = conf if act == "like" else -conf  # a later memory replaces an earlier one
    return out


def knows_grievance(conn: sqlite3.Connection, me: str, other: str, third: str) -> bool:
    """Does `me` have reason to think `other` resents `third`: something `third` did to `other`, or `other`'s own
    cold or hostile words to `third`, that `me` knows of?"""
    marks = ",".join("?" * len(HARMFUL))
    return conn.execute(
        f"SELECT 1 FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id = ? AND c.polarity = 'affirm' "
        f"AND c.act IN ({marks}) AND ((c.subject = ? AND c.object = ?) OR (c.subject = ? AND c.object = ?)) LIMIT 1",
        (me, *HARMFUL, third, other, other, third)).fetchone() is not None


def _learn(conn: sqlite3.Connection, observer: str, subject: str, topic: str, value: float, names: dict) -> list:
    """A memory (and the truth behind it) of someone's taste, when it showed and is not known yet."""
    if abs(value) < 0.3:
        return []
    act = "like" if value > 0 else "dislike"
    if known_taste(conn, observer, subject, topic) is not None:
        return []
    from world.claims import describe_claim
    c = Claim(subject, act, topic)
    return [MemorySpec(observer, describe_claim(c, names), LEARNT, claim=c)]


class Topics(Domain):
    id = "topics"
    title = "話題"
    primitives = (P("social.topics", "social", "what people talk about: shared tastes and shared grudges draw them "
                    "together; a bad moment spoils even a good topic", ["volition"], cost=0),)
    situation_kinds = {"alliance": "結盟（背後說人壞話）"}
    acts = {"like": ClaimAct("taste", "topic", "喜歡{o}", "不喜歡{o}"),
            "dislike": ClaimAct("taste", "topic", "討厭{o}", "不討厭{o}")}

    # -- choosing a topic (the speaker's view) ------------------------------------------------------------------------
    def shape(self, conn: sqlite3.Connection, actor: str, now: int, scored: list) -> list:
        from world.profiles import profile
        prof = profile(conn, actor)
        if prof is None:
            return scored
        out = []
        picked: dict[str, tuple[str, float]] = {}  # one topic per person spoken to, however many tones are weighed
        for score, it in scored:
            if it is None or it.action != "talk" or it.topic or it.tone == "hostile":
                out.append((score, it))
                continue
            if it.target not in picked:
                picked[it.target] = self.pick(conn, actor, it.target, prof, now)
            topic, expect = picked[it.target]
            if topic:
                it = replace(it, topic=topic)
                # a topic shapes what is said, never whether one talks: a score bonus here once crowded out gossip
            out.append((score, it))
        return out

    def pick(self, conn: sqlite3.Connection, me: str, other: str, prof, now: int) -> tuple[str, float]:
        cands: list[tuple[str, float]] = []
        known = known_tastes(conn, me, other)
        for t, w in sorted(prof.interests.items()):
            k = known.get(t)
            cands.append((t, w * (k if k is not None else PRIOR)))
        for t, w in sorted(prof.dislikes.items()):
            k = known.get(t)
            if k is not None and k < 0:
                cands.append((t, w * -k))  # a dislike we share
        for (third, trust) in conn.execute("SELECT target_id, trust FROM relationships WHERE actor_id = ? AND trust < ? "
                                           "ORDER BY target_id", (me, GRUDGE)).fetchall():
            if third not in (me, other) and knows_grievance(conn, me, other, third):
                cands.append(("@" + third, 0.5 * -trust))
        if not cands:
            return "", 0.0
        rng = make_rng(conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0], now, f"{me}:{other}", "topic")
        topic, expect = rng.choices(cands, [math.exp(v / PICK_TEMPERATURE) for _, v in cands])[0]
        return topic, expect

    # -- what it does (world truth) ------------------------------------------------------------------------------------
    def effects(self, conn: sqlite3.Connection, spec: EventSpec, primitives: set[str]) -> EventSpec:
        t = spec.truth
        topic = t.get("topic") or ""
        if spec.type != "talk" or not topic or t.get("tone") == "hostile":
            return spec
        a, b = t["actor"], t["target"]
        from world.claims import labels
        names = labels(conn)
        mood = person(conn, b)["emotion"]
        upset = mood in UPSET
        extra = []
        d = RelDeltas()
        memories, claims = [], []
        if topic.startswith("@"):
            third = topic[1:]
            if rel(conn, b, third, "trust") < -0.2:  # they agree: allies against someone
                effect = "shared_grudge"
                d.add(b, a, "affection", 0.05)
                d.add(a, b, "affection", 0.03)
                d.add(a, third, "rivalry", 0.04)
                d.add(b, third, "rivalry", 0.04)
            else:  # speaking ill of someone they like
                effect = "backbiting_refused"
                d.add(b, a, "trust", -0.05)
                d.add(b, a, "affection", -0.04)
        else:
            ta, tb = taste(conn, a, topic), taste(conn, b, topic)
            if ta < -0.2 and tb < -0.2:
                effect = "shared_dislike"
                g = 0.1 * min(-ta, -tb)
                d.add(b, a, "affection", g)
                d.add(a, b, "affection", g)
            elif upset and ta > 0.3:
                effect = "irritated"  # pressed on someone who is upset, even their favourite topic grates
                d.add(b, a, "affection", -0.03)
            elif tb > 0.3:
                effect = "bonded"
                d.add(b, a, "affection", 0.06 * tb)
                d.add(b, a, "trust", 0.02 * tb)
                if ta > 0.3:
                    d.add(a, b, "affection", 0.04 * min(ta, tb))
                if mood in LOW and tb > 0.5:  # talking about what they love lifts them
                    effect = "cheered_up"
                    from world.events import Change
                    extra.append(Change("person", b, "emotion", value="calm"))
            elif tb < -0.2:
                effect = "grated"
                d.add(b, a, "affection", -0.05 * -tb)
            else:
                effect = "small_talk"
            memories += _learn(conn, a, b, topic, tb, names) + _learn(conn, b, a, topic, ta, names)
            for who, v in ((b, tb), (a, ta)):
                if abs(v) >= 0.3:  # the taste showed: it is now something that happened, and can be passed on
                    claims.append(ClaimSpec(Claim(who, "like" if v > 0 else "dislike", topic)))
        return add_changes(conn, spec, d.changes(conn) + extra, memories=memories, claims=claims, truth={"topic_effect": effect})

    def situations(self, conn: sqlite3.Connection, names: dict) -> list[dict]:
        """Two people talking behind a third one's back: an alliance the third does not know about (yet)."""
        import json
        from world.domains.base import situation
        pacts: dict[tuple, list] = {}
        for eid, ts, truth in conn.execute("SELECT event_id, timestamp, truth FROM events WHERE type = 'talk' AND "
                                           "json_extract(truth, '$.topic_effect') = 'shared_grudge' ORDER BY event_id"):
            t = json.loads(truth)
            key = (*sorted((t["actor"], t["target"])), t["topic"][1:])
            pacts.setdefault(key, []).append((ts // 1440, eid))
        out = []
        n = lambda p: names.get(p, p)  # noqa: E731
        for (a, b, third), talks in sorted(pacts.items()):
            out.append(situation("alliance", 0.45, talks[0][0], [a, b, third],
                                 f"{n(a)}和{n(b)}在背後一起說{n(third)}的壞話（{len(talks)} 次）",
                                 f"{n(third)}會發現他們聯手了嗎？", [e for _, e in talks[:5]], build=len(talks) / 4, stakes=0.5,
                                 lasts=max(3, talks[-1][0] - talks[0][0] + 3)))
        return out

    def describe(self, conn: sqlite3.Connection, pid: str) -> dict:
        from world.profiles import profile, topics
        p = profile(conn, pid)
        if p is None:
            return {}
        label = topics(conn)
        return {"喜歡": "、".join(label.get(t, t) for t, _ in sorted(p.interests.items(), key=lambda x: -x[1])),
                "討厭": "、".join(label.get(t, t) for t, _ in sorted(p.dislikes.items(), key=lambda x: -x[1]))}
