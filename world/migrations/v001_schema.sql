-- World State Engine V0.
-- Current state tables hold "now"; events / event_deltas / memories are the immutable history.
-- Every write goes through world.db.mutation(), which raises a guard row for the duration of one
-- transaction. Triggers below refuse any write to state or history while the guard is absent.

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mutation_guard (
  id INTEGER PRIMARY KEY CHECK (id = 1)
);

CREATE TABLE IF NOT EXISTS locations (
  id       TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  x        REAL NOT NULL,
  y        REAL NOT NULL,
  capacity INTEGER NOT NULL CHECK (capacity >= 0),
  tags     TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags))
);

CREATE TABLE IF NOT EXISTS location_edges (
  from_location_id TEXT NOT NULL REFERENCES locations(id),
  to_location_id   TEXT NOT NULL REFERENCES locations(id),
  travel_minutes   INTEGER NOT NULL CHECK (travel_minutes >= 0),
  PRIMARY KEY (from_location_id, to_location_id),
  CHECK (from_location_id <> to_location_id)
);

CREATE TABLE IF NOT EXISTS people (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  location_id TEXT NOT NULL REFERENCES locations(id),
  energy      INTEGER NOT NULL CHECK (energy BETWEEN 0 AND 100),
  money_cents INTEGER NOT NULL CHECK (money_cents >= 0),
  hunger      INTEGER NOT NULL CHECK (hunger BETWEEN 0 AND 100),
  goal        TEXT NOT NULL,
  emotion     TEXT NOT NULL,
  schedule    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(schedule)),
  status      TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','resting','working','traveling','inactive'))
);

-- Static character sheet: never changes, so it lives outside the event-sourced state.
CREATE TABLE IF NOT EXISTS personas (
  person_id TEXT PRIMARY KEY REFERENCES people(id),
  text      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS objects (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  owner_person_id TEXT REFERENCES people(id),
  location_id     TEXT REFERENCES locations(id),
  tags            TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags)),
  status          TEXT NOT NULL DEFAULT 'normal',
  CHECK (NOT (owner_person_id IS NOT NULL AND location_id IS NOT NULL))
);

-- Directed: actor's feeling toward target. History lives in event_deltas.
CREATE TABLE IF NOT EXISTS relationships (
  actor_id   TEXT NOT NULL REFERENCES people(id),
  target_id  TEXT NOT NULL REFERENCES people(id),
  trust      REAL NOT NULL DEFAULT 0.0 CHECK (trust     BETWEEN -1.0 AND 1.0),
  affection  REAL NOT NULL DEFAULT 0.0 CHECK (affection BETWEEN -1.0 AND 1.0),
  fear       REAL NOT NULL DEFAULT 0.0 CHECK (fear      BETWEEN -1.0 AND 1.0),
  rivalry    REAL NOT NULL DEFAULT 0.0 CHECK (rivalry   BETWEEN -1.0 AND 1.0),
  debt_cents INTEGER NOT NULL DEFAULT 0 CHECK (debt_cents >= 0),
  PRIMARY KEY (actor_id, target_id),
  CHECK (actor_id <> target_id)
);

-- `truth` is what actually happened (world truth); memories hold what each person believes.
CREATE TABLE IF NOT EXISTS events (
  event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp       INTEGER NOT NULL CHECK (timestamp >= 0),
  type            TEXT NOT NULL,
  location_id     TEXT REFERENCES locations(id),
  parent_event_id INTEGER REFERENCES events(event_id),
  trigger_type    TEXT NOT NULL,
  importance      REAL NOT NULL DEFAULT 0.0 CHECK (importance BETWEEN 0.0 AND 1.0),
  truth           TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(truth))
);

CREATE TABLE IF NOT EXISTS event_participants (
  event_id  INTEGER NOT NULL REFERENCES events(event_id),
  person_id TEXT NOT NULL REFERENCES people(id),
  role      TEXT NOT NULL DEFAULT 'actor',
  PRIMARY KEY (event_id, person_id, role)
);

-- old/new/delta have no declared type on purpose: they keep the type they were inserted with,
-- so the numeric trigger below can tell numbers from text.
CREATE TABLE IF NOT EXISTS event_deltas (
  delta_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id    INTEGER NOT NULL REFERENCES events(event_id),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('person','relationship','object')),
  entity_id   TEXT NOT NULL,
  field       TEXT NOT NULL,
  old_value,
  new_value,
  delta_value,
  value_kind  TEXT NOT NULL CHECK (value_kind IN ('numeric','set')),
  UNIQUE (event_id, entity_type, entity_id, field)
);

CREATE TABLE IF NOT EXISTS memories (
  memory_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  observer_id TEXT NOT NULL REFERENCES people(id),
  event_id    INTEGER NOT NULL REFERENCES events(event_id),
  belief      TEXT NOT NULL,
  confidence  REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
  created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_parent    ON events(parent_event_id);
CREATE INDEX IF NOT EXISTS idx_deltas_entity    ON event_deltas(entity_type, entity_id, field, delta_id);
CREATE INDEX IF NOT EXISTS idx_memories_observer ON memories(observer_id, created_at);

-- Delta invariants -----------------------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS event_deltas_validate
BEFORE INSERT ON event_deltas
BEGIN
  SELECT CASE
    WHEN NEW.value_kind = 'numeric' AND (
           typeof(NEW.old_value)   NOT IN ('integer','real')
        OR typeof(NEW.new_value)   NOT IN ('integer','real')
        OR typeof(NEW.delta_value) NOT IN ('integer','real'))
      THEN RAISE(ABORT, 'numeric delta needs numeric old/new/delta values')
    WHEN NEW.value_kind = 'numeric'
         AND ABS(NEW.new_value - (NEW.old_value + NEW.delta_value)) > 0.000001
      THEN RAISE(ABORT, 'new_value != old_value + delta_value')
    WHEN NEW.value_kind = 'set' AND NEW.delta_value IS NOT NULL
      THEN RAISE(ABORT, 'set delta must not carry delta_value')
  END;
END;

CREATE TRIGGER IF NOT EXISTS events_validate_parent
BEFORE INSERT ON events
WHEN NEW.parent_event_id IS NOT NULL
BEGIN
  SELECT CASE
    WHEN (SELECT timestamp FROM events WHERE event_id = NEW.parent_event_id) IS NULL
      THEN RAISE(ABORT, 'parent event does not exist')
    WHEN (SELECT timestamp FROM events WHERE event_id = NEW.parent_event_id) > NEW.timestamp
      THEN RAISE(ABORT, 'parent event must not be later than child event')
  END;
END;

-- History: insert only inside a mutation, never update or delete -------------------------------

CREATE TRIGGER IF NOT EXISTS events_guard_insert BEFORE INSERT ON events
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'writes require a mutation'); END;
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TRIGGER IF NOT EXISTS event_participants_guard_insert BEFORE INSERT ON event_participants
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'writes require a mutation'); END;
CREATE TRIGGER IF NOT EXISTS event_participants_no_update BEFORE UPDATE ON event_participants
BEGIN SELECT RAISE(ABORT, 'event_participants are append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_participants_no_delete BEFORE DELETE ON event_participants
BEGIN SELECT RAISE(ABORT, 'event_participants are append-only'); END;

CREATE TRIGGER IF NOT EXISTS event_deltas_guard_insert BEFORE INSERT ON event_deltas
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'writes require a mutation'); END;
CREATE TRIGGER IF NOT EXISTS event_deltas_no_update BEFORE UPDATE ON event_deltas
BEGIN SELECT RAISE(ABORT, 'event_deltas are append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_deltas_no_delete BEFORE DELETE ON event_deltas
BEGIN SELECT RAISE(ABORT, 'event_deltas are append-only'); END;

CREATE TRIGGER IF NOT EXISTS memories_guard_insert BEFORE INSERT ON memories
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'writes require a mutation'); END;
CREATE TRIGGER IF NOT EXISTS memories_no_update BEFORE UPDATE ON memories
BEGIN SELECT RAISE(ABORT, 'memories are append-only'); END;
CREATE TRIGGER IF NOT EXISTS memories_no_delete BEFORE DELETE ON memories
BEGIN SELECT RAISE(ABORT, 'memories are append-only'); END;

-- Current state: seedable before the first event, afterwards changed only inside a mutation ----

CREATE TRIGGER IF NOT EXISTS people_guard_insert BEFORE INSERT ON people
WHEN EXISTS (SELECT 1 FROM events) AND NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS people_guard_update BEFORE UPDATE ON people
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS people_no_delete BEFORE DELETE ON people
BEGIN SELECT RAISE(ABORT, 'people cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS relationships_guard_insert BEFORE INSERT ON relationships
WHEN EXISTS (SELECT 1 FROM events) AND NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS relationships_guard_update BEFORE UPDATE ON relationships
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS relationships_no_delete BEFORE DELETE ON relationships
BEGIN SELECT RAISE(ABORT, 'relationships cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS objects_guard_insert BEFORE INSERT ON objects
WHEN EXISTS (SELECT 1 FROM events) AND NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS objects_guard_update BEFORE UPDATE ON objects
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS objects_no_delete BEFORE DELETE ON objects
BEGIN SELECT RAISE(ABORT, 'objects cannot be deleted'); END;
