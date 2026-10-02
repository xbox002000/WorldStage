"""Looking at a world whose people have a mind: the control room replays it from the answers already paid for, and nothing else.

What is proved here, with no network and no model (a stub answers while the little world is made; after that only the recorded answers exist):
the replay is the saved world event for event, each mind is paired with the event it decided and no other, an event no mind decided has no
`mind`, and a request the cache lacks is an error, not a call and not a quiet fall-back to the rules."""
from __future__ import annotations

import itertools
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from functools import partial
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import soul_lab
from agent.llm import CacheMiss, LLMClient
from agent.llm_cache import LLMCache
from channel.studio import IDLE, Handler, Hub, MindReplayError, ReplayMind, Studio, mind_info, open_readonly, pair_minds, replay_check

ROOT = Path(__file__).resolve().parent.parent
EVENTS = "SELECT event_id, type, timestamp, location_id, truth FROM events ORDER BY event_id"
NO_NETWORK = mock.patch("socket.socket.connect", side_effect=AssertionError("something tried to open a network connection"))


def make_world(tmp: Path, name: str = "tiny", seed: int = 503, days: int = 3) -> Path:
    """A little soul_lab world made the way soul_lab makes one, with a stub for the model: it asks 'the model' in cache mode, so the
    answers end up in <name>.llm_cache.db, which is all a replay will ever have."""
    cache_conn = soul_lab.open_cache(tmp / f"{name}.llm_cache.db")
    n = itertools.count()

    def backend(prompt, schema, temperature):
        k = next(n)
        return json.dumps({"option": k % 2, "reason": f"理由{k}", "inner": f"心聲{k}" if k % 3 else ""}, ensure_ascii=False)

    client = LLMClient("stub-model", mode="cache", cache=LLMCache(cache_conn), backend=backend, retries=0, min_interval=0)
    a = SimpleNamespace(seed=seed, recipe="jianghu_story_v1", tier="A", budget=20, per_person_day=2, shuffle=True)
    res = soul_lab.run_world(a, tmp / name, client, days, announce=lambda *_: None)
    assert res["days"] == days and res["paused"] is None
    cache_conn.close()
    return tmp / name


class Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="mind_"))
        cls.root = make_world(cls.tmp)
        cls.out = cls.tmp / "studio"
        with NO_NETWORK:                       # the replay must not even try
            cls.studio = Studio(cls.out, mind=cls.root, title="江湖（角色有 LLM）")
        cls.doc = json.loads((cls.out / "studio.json").read_text(encoding="utf-8"))
        cls.minds = cls.doc["minds"]["items"]
        cls.ref = open_readonly(cls.root / "world.db")

    @classmethod
    def tearDownClass(cls):
        cls.ref.close()
        cls.studio.client.cache_conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- the replay is the world --------------------------------------------------------------------------------------------------------
    def test_the_replay_is_the_saved_world_event_for_event(self):
        a = [tuple(r) for r in self.studio.conn.execute(EVENTS)]
        b = [tuple(r) for r in self.ref.execute(EVENTS)]
        self.assertTrue(a)
        self.assertEqual(len(a), len(b))
        for x, y in zip(a, b):                 # id, type, time, place, and the whole truth
            self.assertEqual(x, y)
        rep = self.studio.mind["report"]
        self.assertTrue(rep["equal"])
        self.assertEqual(rep["events"], len(b))
        self.assertEqual(self.doc["meta"]["days"], 3)

    def test_the_replayed_decisions_are_the_recorded_ones(self):
        saved = [json.loads(x) for x in (self.root / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(saved)
        keys = ("person", "t", "wake", "chose", "reason", "inner", "option", "of", "rule_top", "shown_at")
        self.assertEqual([tuple(x[k] for k in keys) for x in self.studio.mind["log"]], [tuple(x[k] for k in keys) for x in saved])
        self.assertEqual(len(self.minds), len(saved))

    def test_nothing_was_asked_of_anyone_and_the_cache_was_not_added_to(self):
        c = self.studio.client
        self.assertEqual(c.misses, [])
        self.assertEqual(self.studio.agent.stats["agent_failed"], 0)
        self.assertTrue(all(cl.calls == 0 and cl._backend is None and cl.mode == "replay" for cl in c.inner.clients))   # no backend was ever even made
        before = self.tmp / "tiny.llm_cache.db"
        rows = sqlite3.connect(before).execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
        self.assertEqual(rows, len(self.minds))                                                       # one recorded answer per mind that woke
        with self.assertRaises(sqlite3.OperationalError):
            c.cache_conn.execute("INSERT INTO llm_cache VALUES ('x','x','x','{}','{}',0)")           # opened read-only

    def test_a_difference_from_the_saved_world_is_an_error_and_names_the_event(self):
        bad = self.tmp / "tampered.db"
        shutil.copyfile(self.root / "world.db", bad)
        c = sqlite3.connect(bad, isolation_level=None)
        for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():   # the world refuses to be rewritten: this copy is only a stand-in
            c.execute(f"DROP TRIGGER {name}")
        eid = c.execute("SELECT event_id FROM events WHERE type = 'talk' ORDER BY event_id LIMIT 1").fetchone()[0]
        c.execute("UPDATE events SET truth = json_set(truth, '$.tone', 'tampered') WHERE event_id = ?", (eid,))
        c.close()
        with self.assertRaises(MindReplayError) as cm:
            replay_check(self.studio.conn, bad, 3)
        self.assertIn("differs", str(cm.exception))
        self.assertTrue(replay_check(self.studio.conn, self.root / "world.db", 3)["equal"])

    # -- each mind is paired with its own event ---------------------------------------------------------------------------------------
    def test_each_mind_is_paired_with_the_event_it_decided_and_no_other(self):
        c = self.studio.conn
        seen: set[int] = set()
        for m in self.minds:
            if m["event"] is None:
                self.assertEqual(m["chose"], IDLE)       # only a mind that chose to do nothing has no event
                continue
            self.assertNotIn(m["event"], seen, "an event was paired with two minds")
            seen.add(m["event"])
            r = c.execute("SELECT timestamp, truth FROM events WHERE event_id = ?", (m["event"],)).fetchone()
            truth = json.loads(r["truth"])
            self.assertEqual(truth["actor"], m["person"])
            self.assertEqual(truth["reason"], "agent:" + m["reason"])
            self.assertEqual(truth["source"], m["model"])
            self.assertEqual(r["timestamp"] * 60, m["t"])
            self.assertEqual(r["timestamp"] // 1440, m["day"])
            self.assertEqual(m["clock"], f"{(r['timestamp'] % 1440) // 60:02d}:{(r['timestamp'] % 1440) % 60:02d}")
        # and no event that a mind decided is left without its mind
        decided = {r[0] for r in c.execute("SELECT event_id, truth FROM events") if str(json.loads(r[1]).get("reason", "")).startswith("agent:")}
        self.assertEqual(decided, seen)
        self.assertEqual(self.doc["meta"]["mind"]["with_event"], len(seen))
        self.assertEqual(self.doc["meta"]["mind"]["idle"], len(self.minds) - len(seen))

    def test_the_mind_on_an_event_is_the_one_in_the_list_of_minds(self):
        by_event = {m["event"]: m for m in self.minds if m["event"] is not None}
        n = 0
        for d in self.doc["days"]:
            for b in (d["episode"] or {"beats": []})["beats"]:
                for e in b["events"]:
                    if "mind" in e:
                        n += 1
                        m = by_event[e["id"]]
                        self.assertEqual(e["mind"], {k: m[k] for k in ("reason", "inner", "wake", "chose", "rank", "of", "rule_top")} | {"model": m["model"]})
                        self.assertIn("beat", m)                                  # the list knows the scene that shows it
                        self.assertEqual(m["day"], e["day"])
                        self.assertIn(e["id"], b["event_ids"])
        for m in self.minds:
            if "beat" in m:
                beat = next(b for b in self.doc["days"][m["day"]]["episode"]["beats"] if b["index"] == m["beat"])
                self.assertTrue(beat["shoot"])
                self.assertIn(m["event"], beat["event_ids"])
        self.assertEqual(n, sum(1 for m in self.minds if "beat" in m))     # every mind the list puts in a scene is on an event of that scene, and the reverse

    def test_an_event_no_mind_decided_has_no_mind_field(self):
        decided = {m["event"] for m in self.minds if m["event"] is not None}
        checked = 0
        for d in self.doc["days"]:
            evs = [e for b in (d["episode"] or {"beats": []})["beats"] for e in b["events"]] + \
                  [e for g in (d["episode"] or {"grammar": []})["grammar"] for e in g["events"]]
            for e in evs:
                checked += 1
                self.assertEqual("mind" in e, e["id"] in decided, e)
        self.assertGreater(checked, 0)
        world = json.loads((self.out / "world.json").read_text(encoding="utf-8"))
        for e in world["events"]:
            self.assertEqual("mind" in e, e["id"] in decided, e["id"])
            if "mind" in e:
                m = next(x for x in self.minds if x["event"] == e["id"])
                self.assertEqual(e["mind"], {"reason": m["reason"], "inner": m["inner"]})

    def test_pairing_does_not_slip_when_a_person_says_the_same_words_twice(self):
        """Same person, same words, three times, in order; an event for each of two; one decision that came to nothing."""
        def log(t, who="kai", reason="哼", chose="不客氣地對阿明說話"):
            return {"person": who, "t": t, "wake": [], "chose": chose, "reason": reason, "inner": "", "option": 1, "of": 4, "rule_top": "x"}
        ev = lambda eid, ts, who="kai", reason="哼": (eid, ts, {"actor": who, "reason": f"agent:{reason}"})  # noqa: E731
        logs = [log(100), log(200), log(300), log(150, "yun", "哼"), log(400, "kai", "想想", IDLE)]
        events = [ev(7, 100), ev(8, 150, "yun"), ev(9, 200), ev(10, 305), ev(11, 50, "kai", "別的"), (12, 90, {"actor": "kai", "reason": "rule:routine"})]
        got = {(x["person"], x["t"]): eid for x, eid in pair_minds(logs, events)}
        self.assertEqual(got, {("kai", 100): 7, ("yun", 150): 8, ("kai", 200): 9, ("kai", 300): 10, ("kai", 400): None})
        # a log's own failure is not a mind; an event can come only after the moment it was decided
        self.assertEqual(pair_minds([{"person": "kai", "t": 100, "wake": [], "error": "X"}], events), [])
        self.assertEqual(pair_minds([log(500)], [ev(1, 100)]), [(log(500), None)])

    def test_the_page_data_only_has_what_a_mind_world_adds(self):
        self.assertEqual(set(self.doc["minds"]), {"version", "items"})
        self.assertEqual(self.doc["meta"]["strategy"], "off")
        for k in ("model", "minds", "with_event", "idle", "answers", "replay_events", "world", "settings"):
            self.assertIn(k, self.doc["meta"]["mind"])
        for d in self.doc["days"]:
            self.assertEqual(set(d), {"day", "state", "pacing", "episode", "producer", "payoffs", "events"})   # the days themselves are unchanged
        self.assertIsNotNone(self.doc["world3d"])          # a soul world has no space of its own: the runtime still stages it
        self.assertTrue((self.out / "site" / "world" / "index.html").exists())

    def test_it_is_read_only_going_on_is_refused(self):
        with self.assertRaises(MindReplayError):
            self.studio.advance(1)


class Misses(unittest.TestCase):
    def test_a_request_the_cache_lacks_is_an_error_and_never_a_call(self):
        tmp = Path(tempfile.mkdtemp(prefix="mind_miss_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        db = tmp / "empty.llm_cache.db"
        soul_lab.open_cache(db).close()
        mind = ReplayMind(db, ["gemini-3.5-flash-lite"])
        self.addCleanup(mind.cache_conn.close)
        with NO_NETWORK:
            with self.assertRaises(CacheMiss):
                mind.generate_json("a question nobody ever asked", {"type": "object"}, 0.7)
        self.assertEqual(len(mind.misses), 1)
        self.assertTrue(all(c._backend is None and c.calls == 0 for c in mind.inner.clients))
        # the client itself, in replay mode, with a backend that would answer: it is not used
        c = LLMClient("m", mode="replay", cache=LLMCache(sqlite3.connect(":memory:")), backend=lambda *a: self.fail("asked"))
        c.cache.conn.execute("CREATE TABLE llm_cache (request_hash TEXT PRIMARY KEY, provider TEXT, model TEXT, request_json TEXT, response_json TEXT, created_at INTEGER)")
        with self.assertRaises(CacheMiss):
            c.generate_json("p", {}, 0.7)

    def test_a_replay_that_needs_an_answer_nobody_recorded_stops_instead_of_letting_the_rules_decide(self):
        tmp = Path(tempfile.mkdtemp(prefix="mind_gap_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        root = make_world(tmp)
        c = sqlite3.connect(tmp / "tiny.llm_cache.db", isolation_level=None)
        gone = c.execute("SELECT request_hash FROM llm_cache ORDER BY created_at, request_hash LIMIT 1").fetchone()[0]
        c.execute("DELETE FROM llm_cache WHERE request_hash = ?", (gone,))
        c.close()
        with NO_NETWORK:
            with self.assertRaises(MindReplayError) as cm:
                Studio(tmp / "studio", mind=root)
        self.assertIn("recorded answers lack", str(cm.exception))
        self.assertFalse((tmp / "studio" / "studio.json").exists())          # nothing was written

    def test_a_folder_without_its_cache_or_world_is_refused(self):
        tmp = Path(tempfile.mkdtemp(prefix="mind_none_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with self.assertRaises(MindReplayError):
            mind_info(tmp / "nowhere")


class Catalog(unittest.TestCase):
    def test_the_world_is_listed_as_something_to_look_at_and_going_on_is_refused(self):
        tmp = Path(tempfile.mkdtemp(prefix="mind_hub_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        root = make_world(tmp, "mini", seed=504, days=2)
        hub = Hub(tmp / "hub")
        with mock.patch.object(Studio, "_world3d", lambda self: None):
            key = hub.make_mind(root)
        self.assertEqual(key, "soul-504")
        row = next(r for r in json.loads((tmp / "hub" / "worlds.json").read_text(encoding="utf-8"))["worlds"] if r["key"] == key)
        self.assertEqual((row["live"], row.get("mind"), row["seed"], row["days"], row["title"]), (False, True, 504, 2, "江湖（角色有 LLM）"))
        self.assertNotIn(key, hub.worlds)
        Handler.hub = hub
        srv = HTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(hub.root)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        h = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        h.request("POST", f"/{key}/advance?n=1")
        r = h.getresponse()
        self.assertEqual(r.status, 409)
        self.assertIn("quota", json.loads(r.read())["error"])
        h.close()


REAL = ROOT / "out" / "soul" / "soul503"


@unittest.skipUnless((REAL / "world.db").exists() and (REAL.parent / "soul503.llm_cache.db").exists() and (REAL / "decisions.jsonl").exists(),
                     "out/soul/soul503 (soul_lab.py's seed 503) is not here")
class RealWorld(unittest.TestCase):
    def test_seed_503_replays_to_the_saved_world_with_every_decision_paired(self):
        tmp = Path(tempfile.mkdtemp(prefix="mind_real_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with NO_NETWORK, mock.patch.object(Studio, "_world3d", lambda self: None):
            s = Studio(tmp, mind=REAL)
        self.addCleanup(s.client.cache_conn.close)
        ref = open_readonly(REAL / "world.db")
        self.addCleanup(ref.close)
        self.assertEqual([tuple(r) for r in s.conn.execute(EVENTS)], [tuple(r) for r in ref.execute(EVENTS)])
        saved = [json.loads(x) for x in (REAL / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(s.minds), len(saved))
        for m, row in zip(s.minds, sorted(saved, key=lambda x: (x["day"], x["t"]))):
            self.assertEqual((m["person"], m["day"] + 1, m["reason"], m["inner"]), (row["person"], row["day"], row["reason"], row["inner"]))
        self.assertEqual(s.mind["report"]["with_event"] + s.mind["report"]["idle"], len(saved))
        self.assertEqual(s.client.misses, [])


if __name__ == "__main__":
    unittest.main()
