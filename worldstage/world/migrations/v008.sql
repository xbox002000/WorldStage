-- v7 -> v8: depth in relationships, and groups. Six more things one person feels about another (what a pair has been
-- through: resentment from being wronged, respect from deeds seen, familiarity from time together, attraction); the
-- groups people form (factions: a leader and a goal, declared by events); who belongs to which (affiliations); and the
-- scarce places a group can fight over (seats: chief disciple, a promotion). Like every state table they change only by
-- events. The rules that move them belong to domain packs (world/domains); worlds that do not enable those packs keep
-- every value at 0 and every faction dormant.
ALTER TABLE relationships ADD COLUMN resentment  REAL NOT NULL DEFAULT 0.0 CHECK (resentment  BETWEEN -1.0 AND 1.0);
ALTER TABLE relationships ADD COLUMN respect     REAL NOT NULL DEFAULT 0.0 CHECK (respect     BETWEEN -1.0 AND 1.0);
ALTER TABLE relationships ADD COLUMN familiarity REAL NOT NULL DEFAULT 0.0 CHECK (familiarity BETWEEN -1.0 AND 1.0);
ALTER TABLE relationships ADD COLUMN attraction  REAL NOT NULL DEFAULT 0.0 CHECK (attraction  BETWEEN -1.0 AND 1.0);
-- what one believes the other can do (0..1, in the units of the ability itself): it lags the truth, because growth is
-- private and only what is seen or heard moves it
ALTER TABLE relationships ADD COLUMN estimate    REAL NOT NULL DEFAULT 0.5 CHECK (estimate    BETWEEN 0.0 AND 1.0);
-- what the two are to each other beyond feeling: '' nothing, 'dating', 'ex', or (on the one who confessed) 'rejected'
ALTER TABLE relationships ADD COLUMN bond        TEXT NOT NULL DEFAULT '' CHECK (bond IN ('', 'dating', 'ex', 'rejected'));

CREATE TABLE IF NOT EXISTS factions (
  faction_id TEXT PRIMARY KEY,
  name       TEXT NOT NULL DEFAULT '',
  leader_id  TEXT REFERENCES people(id),
  goal       TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'dormant' CHECK (status IN ('dormant', 'active', 'dissolved'))
);
CREATE TABLE IF NOT EXISTS affiliations (
  person_id  TEXT PRIMARY KEY REFERENCES people(id),
  faction_id TEXT REFERENCES factions(faction_id),
  role       TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS seats (
  seat_id   TEXT PRIMARY KEY,
  title     TEXT NOT NULL DEFAULT '',
  holder_id TEXT REFERENCES people(id),
  faction_id TEXT REFERENCES factions(faction_id),     -- whose seat it is: only its members may stand for it
  status    TEXT NOT NULL DEFAULT 'held' CHECK (status IN ('held', 'vacant', 'contested')),
  decide_by INTEGER NOT NULL DEFAULT 0 CHECK (decide_by >= 0)
);
CREATE TRIGGER IF NOT EXISTS factions_guard_insert BEFORE INSERT ON factions
WHEN EXISTS (SELECT 1 FROM events) AND NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS factions_guard_update BEFORE UPDATE ON factions
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS factions_no_delete BEFORE DELETE ON factions
BEGIN SELECT RAISE(ABORT, 'factions cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS affiliations_guard_insert BEFORE INSERT ON affiliations
WHEN EXISTS (SELECT 1 FROM events) AND NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS affiliations_guard_update BEFORE UPDATE ON affiliations
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS affiliations_no_delete BEFORE DELETE ON affiliations
BEGIN SELECT RAISE(ABORT, 'affiliations cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS seats_guard_insert BEFORE INSERT ON seats
WHEN EXISTS (SELECT 1 FROM events) AND NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS seats_guard_update BEFORE UPDATE ON seats
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'state changes require an event'); END;
CREATE TRIGGER IF NOT EXISTS seats_no_delete BEFORE DELETE ON seats
BEGIN SELECT RAISE(ABORT, 'seats cannot be deleted'); END;

-- event_deltas learns the entity types of the groups (faction, affiliation, seat). SQLite cannot alter a CHECK, so the
-- table is rebuilt with its rows, ids and triggers unchanged.
CREATE TABLE event_deltas_v8 (
  delta_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id    INTEGER NOT NULL REFERENCES events(event_id),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('person','relationship','object','var','goal','faction','affiliation','seat')),
  entity_id   TEXT NOT NULL,
  field       TEXT NOT NULL,
  old_value,
  new_value,
  delta_value,
  value_kind  TEXT NOT NULL CHECK (value_kind IN ('numeric','set')),
  UNIQUE (event_id, entity_type, entity_id, field)
);
INSERT INTO event_deltas_v8 SELECT delta_id, event_id, entity_type, entity_id, field, old_value, new_value,
  delta_value, value_kind FROM event_deltas ORDER BY delta_id;
DROP TABLE event_deltas;
ALTER TABLE event_deltas_v8 RENAME TO event_deltas;
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
