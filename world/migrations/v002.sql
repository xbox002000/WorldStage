-- v1 -> v2: structured claims and typed memory sources.
ALTER TABLE memories ADD COLUMN claim_id INTEGER REFERENCES claims(claim_id);
ALTER TABLE memories ADD COLUMN about_event_id INTEGER REFERENCES events(event_id);
ALTER TABLE memories ADD COLUMN source_type TEXT NOT NULL DEFAULT 'direct_observation'
  CHECK (source_type IN ('direct_observation','told_by','inference','external_rumor'));
ALTER TABLE memories ADD COLUMN source_id TEXT;

-- Claims: propositions. Truth = event_claims(role='truth'); beliefs = memories.claim_id (see contracts/claim.py).
CREATE TABLE IF NOT EXISTS claims (
  claim_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  claim_hash TEXT NOT NULL UNIQUE,
  subject    TEXT NOT NULL,
  act        TEXT NOT NULL,
  object     TEXT NOT NULL,
  polarity   TEXT NOT NULL CHECK (polarity IN ('affirm','deny'))
);

CREATE TABLE IF NOT EXISTS event_claims (
  event_id INTEGER NOT NULL REFERENCES events(event_id),
  claim_id INTEGER NOT NULL REFERENCES claims(claim_id),
  role     TEXT NOT NULL CHECK (role IN ('truth','asserted','withheld')),
  PRIMARY KEY (event_id, claim_id, role)
);

CREATE TABLE IF NOT EXISTS memory_sources (
  memory_id                INTEGER NOT NULL REFERENCES memories(memory_id),
  derived_from_memory_id   INTEGER REFERENCES memories(memory_id),
  derived_from_event_id    INTEGER REFERENCES events(event_id),
  CHECK ((derived_from_memory_id IS NULL) <> (derived_from_event_id IS NULL))
);

CREATE TRIGGER IF NOT EXISTS claims_guard_insert BEFORE INSERT ON claims
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'writes require a mutation'); END;
CREATE TRIGGER IF NOT EXISTS claims_no_update BEFORE UPDATE ON claims
BEGIN SELECT RAISE(ABORT, 'claims are append-only'); END;
CREATE TRIGGER IF NOT EXISTS claims_no_delete BEFORE DELETE ON claims
BEGIN SELECT RAISE(ABORT, 'claims are append-only'); END;

CREATE TRIGGER IF NOT EXISTS event_claims_guard_insert BEFORE INSERT ON event_claims
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'writes require a mutation'); END;
CREATE TRIGGER IF NOT EXISTS event_claims_no_update BEFORE UPDATE ON event_claims
BEGIN SELECT RAISE(ABORT, 'event_claims are append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_claims_no_delete BEFORE DELETE ON event_claims
BEGIN SELECT RAISE(ABORT, 'event_claims are append-only'); END;

CREATE TRIGGER IF NOT EXISTS memory_sources_guard_insert BEFORE INSERT ON memory_sources
WHEN NOT EXISTS (SELECT 1 FROM mutation_guard)
BEGIN SELECT RAISE(ABORT, 'writes require a mutation'); END;
CREATE TRIGGER IF NOT EXISTS memory_sources_no_update BEFORE UPDATE ON memory_sources
BEGIN SELECT RAISE(ABORT, 'memory_sources are append-only'); END;
CREATE TRIGGER IF NOT EXISTS memory_sources_no_delete BEFORE DELETE ON memory_sources
BEGIN SELECT RAISE(ABORT, 'memory_sources are append-only'); END;

-- Input log for replay; deliberately outside the world snapshot.
CREATE TABLE IF NOT EXISTS llm_cache (
  request_hash  TEXT PRIMARY KEY,
  provider      TEXT NOT NULL,
  model         TEXT NOT NULL,
  request_json  TEXT NOT NULL,
  response_json TEXT NOT NULL,
  created_at    INTEGER NOT NULL
);
