-- v2 -> v3: World C. Items have a rightful owner and a value, people have static traits, and the world has
-- numeric variables (prices, visibility, arrears, seed state) that only events may change.
ALTER TABLE objects ADD COLUMN rightful_owner_id TEXT REFERENCES people(id);
ALTER TABLE objects ADD COLUMN value_cents INTEGER NOT NULL DEFAULT 0 CHECK (value_cents >= 0);
UPDATE objects SET rightful_owner_id = owner_person_id WHERE rightful_owner_id IS NULL;
ALTER TABLE personas ADD COLUMN traits TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(traits));

CREATE TABLE IF NOT EXISTS world_vars (
  key   TEXT PRIMARY KEY,
  value REAL NOT NULL
);

CREATE TRIGGER IF NOT EXISTS world_vars_guard_insert BEFORE INSERT ON world_vars
WHEN EXISTS (SELECT 1 FROM events) AND NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS world_vars_guard_update BEFORE UPDATE ON world_vars
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS world_vars_no_delete BEFORE DELETE ON world_vars
BEGIN SELECT RAISE(ABORT, 'world variables cannot be deleted'); END;

-- event_deltas learns the 'var' entity type. SQLite cannot alter a CHECK, so the table is rebuilt with its
-- rows, ids and triggers unchanged.
CREATE TABLE event_deltas_v3 (
  delta_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id    INTEGER NOT NULL REFERENCES events(event_id),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('person','relationship','object','var')),
  entity_id   TEXT NOT NULL,
  field       TEXT NOT NULL,
  old_value,
  new_value,
  delta_value,
  value_kind  TEXT NOT NULL CHECK (value_kind IN ('numeric','set')),
  UNIQUE (event_id, entity_type, entity_id, field)
);
INSERT INTO event_deltas_v3 SELECT delta_id, event_id, entity_type, entity_id, field, old_value, new_value,
  delta_value, value_kind FROM event_deltas ORDER BY delta_id;
DROP TABLE event_deltas;
ALTER TABLE event_deltas_v3 RENAME TO event_deltas;
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
