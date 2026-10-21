-- v3 -> v4: goals as world state. Each person has a fixed number of goal slots, created with the world, so a goal
-- that forms later is a Change to an empty slot, never an insert outside apply_event. Every change of kind, target,
-- status or setbacks is an event with deltas, which is the goal's provenance.
CREATE TABLE IF NOT EXISTS goals (
  person_id   TEXT NOT NULL REFERENCES people(id),
  slot        INTEGER NOT NULL CHECK (slot >= 0),
  kind        TEXT NOT NULL DEFAULT '',
  target      TEXT NOT NULL DEFAULT '',
  object      TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'empty'
    CHECK (status IN ('empty','formed','active','blocked','abandoned','revised','completed','transformed')),
  priority    REAL NOT NULL DEFAULT 0.0 CHECK (priority BETWEEN 0.0 AND 1.0),
  since_day   INTEGER NOT NULL DEFAULT 0,
  setbacks    INTEGER NOT NULL DEFAULT 0 CHECK (setbacks >= 0),
  parent      TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (person_id, slot)
);

CREATE TRIGGER IF NOT EXISTS goals_guard_insert BEFORE INSERT ON goals
WHEN EXISTS (SELECT 1 FROM events) AND NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS goals_guard_update BEFORE UPDATE ON goals
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS goals_no_delete BEFORE DELETE ON goals
BEGIN SELECT RAISE(ABORT, 'goals cannot be deleted'); END;

-- event_deltas learns the 'goal' entity type. SQLite cannot alter a CHECK, so the table is rebuilt with its
-- rows, ids and triggers unchanged.
CREATE TABLE event_deltas_v4 (
  delta_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id    INTEGER NOT NULL REFERENCES events(event_id),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('person','relationship','object','var','goal')),
  entity_id   TEXT NOT NULL,
  field       TEXT NOT NULL,
  old_value,
  new_value,
  delta_value,
  value_kind  TEXT NOT NULL CHECK (value_kind IN ('numeric','set')),
  UNIQUE (event_id, entity_type, entity_id, field)
);
INSERT INTO event_deltas_v4 SELECT delta_id, event_id, entity_type, entity_id, field, old_value, new_value,
  delta_value, value_kind FROM event_deltas ORDER BY delta_id;
DROP TABLE event_deltas;
ALTER TABLE event_deltas_v4 RENAME TO event_deltas;
CREATE INDEX IF NOT EXISTS idx_deltas_entity ON event_deltas(entity_type, entity_id, field, delta_id);
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
CREATE TRIGGER IF NOT EXISTS event_deltas_guard_insert BEFORE INSERT ON event_deltas
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'writes require a mutation'); END;
CREATE TRIGGER IF NOT EXISTS event_deltas_no_update BEFORE UPDATE ON event_deltas
BEGIN SELECT RAISE(ABORT, 'event_deltas are append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_deltas_no_delete BEFORE DELETE ON event_deltas
BEGIN SELECT RAISE(ABORT, 'event_deltas are append-only'); END;
