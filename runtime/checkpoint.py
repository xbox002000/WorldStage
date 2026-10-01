"""Runtime checkpoints: resume a World Runtime where it was, instead of playing the whole history again.

The runtime is a pure function of the world's recorded history (runtime/world_runtime.py), and playing a month of it
costs minutes (every walk is planned round furniture and people). A checkpoint is the runtime's state after its last
event, written to a file; a runtime built from it plays only the events recorded since. It is only ever a shortcut:

    rt = open_runtime(conn, "out/live/runtime.ckpt")   # resumes if the file is for this very history, else plays it all
                                                       # and writes the file

A checkpoint is used only when everything it stands on still holds, all checked before a byte of it is read:
  - the same runtime code (a hash of the source files that decide how a body moves: any edit invalidates every file),
  - the same world seed and runtime version,
  - the same history up to the checkpoint (a hash of every event and every delta the runtime reads, up to its last
    event): a world that was edited, branched or replaced is never resumed from somebody else's past,
  - the file itself intact (a hash of the payload).
Anything else and the file is ignored and the history is played in full: a checkpoint can make the runtime faster,
never different. `tests/test_runtime_checkpoint.py` plays a world both ways and compares everything.

The file is the runtime's own pickle: load only files this project wrote (the header is checked first).
"""
from __future__ import annotations

import hashlib
import json
import pickle
import sqlite3
import zlib
from pathlib import Path

from runtime.world_runtime import WorldRuntime

MAGIC = b"worldruntime-checkpoint-1\n"
ROOT = Path(__file__).resolve().parent.parent
CODE = ("runtime/nav.py", "runtime/world_runtime.py", "runtime/scheduler.py", "contracts/runtime.py",
        "narrative/layouts.py", "narrative/spatial.py")
STATE_SKIP = ("conn",)


def code_hash() -> str:
    h = hashlib.sha256()
    for rel in CODE:
        h.update(rel.encode())
        h.update((ROOT / rel).read_bytes().replace(b"\r\n", b"\n"))  # the same on every checkout
    return h.hexdigest()


def history_hash(conn: sqlite3.Connection, last_event: int) -> str:
    """The events and the deltas the runtime reads, up to `last_event`."""
    h = hashlib.sha256()
    for row in conn.execute("SELECT event_id, timestamp, type, location_id, truth FROM events WHERE event_id <= ? "
                            "ORDER BY event_id", (last_event,)):
        h.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode())
    for row in conn.execute(
            "SELECT event_id, entity_type, entity_id, field, old_value, new_value FROM event_deltas WHERE event_id <= ? AND "
            "((entity_type = 'person' AND field IN ('location_id', 'status')) OR "
            "(entity_type = 'object' AND field IN ('owner_person_id', 'location_id'))) ORDER BY delta_id", (last_event,)):
        h.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode())
    return h.hexdigest()


def _header(rt: WorldRuntime, payload: bytes) -> dict:
    return {"runtime": rt.VERSION, "seed": rt.seed, "code": code_hash(), "last_event": rt.last_event,
            "history": history_hash(rt.conn, rt.last_event), "payload": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload)}


def save(rt: WorldRuntime, path: str | Path) -> dict:
    """Write the runtime's state after its last event. Returns the header it wrote."""
    state = {k: v for k, v in rt.__dict__.items() if k not in STATE_SKIP}
    payload = zlib.compress(pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL), 1)
    header = _header(rt, payload)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(MAGIC + json.dumps(header, sort_keys=True).encode() + b"\n" + payload)
    tmp.replace(path)  # a half-written file is never left under the real name
    return header


def load(conn: sqlite3.Connection, path: str | Path) -> WorldRuntime | None:
    """A runtime resumed from the file, or None when the file is not for this world's history (see the module note).
    It has not yet played the events recorded since: call `advance()`."""
    path = Path(path)
    if not path.exists():
        return None
    raw = path.read_bytes()
    if not raw.startswith(MAGIC):
        return None
    try:
        head, payload = raw[len(MAGIC):].split(b"\n", 1)
        header = json.loads(head)
    except ValueError:
        return None
    seed = conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
    if (header.get("runtime") != WorldRuntime.VERSION or header.get("seed") != seed or header.get("code") != code_hash()
            or header.get("bytes") != len(payload) or header.get("payload") != hashlib.sha256(payload).hexdigest()):
        return None
    last = header.get("last_event")
    if not isinstance(last, int) or last > conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM events").fetchone()[0]:
        return None
    if header.get("history") != history_hash(conn, last):
        return None
    rt = WorldRuntime.__new__(WorldRuntime)
    rt.__dict__.update(pickle.loads(zlib.decompress(payload)))
    rt.conn = conn
    return rt


def open_runtime(conn: sqlite3.Connection, path: str | Path, *, save_after: bool = True) -> WorldRuntime:
    """The runtime of this world: resumed from the checkpoint when it fits, else played from the start; brought up to
    the world's last event; and (unless `save_after` is False) written back when it moved on."""
    rt = load(conn, path)
    resumed = rt is not None
    if rt is None:
        rt = WorldRuntime(conn)
    played = rt.advance()
    if save_after and (played or not resumed):
        save(rt, path)
    return rt
