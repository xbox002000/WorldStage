-- production.db: how episodes get made. It is NOT world truth and never writes to world.db.
-- Every artifact row is addressed by the hash of what it was made from (see contracts/*).

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scene_specs (
  scene_hash     TEXT PRIMARY KEY,
  world_revision INTEGER NOT NULL,
  history_hash   TEXT NOT NULL,
  spec_json      TEXT NOT NULL CHECK (json_valid(spec_json)),
  created_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS packets (
  packet_hash TEXT PRIMARY KEY,
  scene_hash  TEXT NOT NULL REFERENCES scene_specs(scene_hash),
  packet_json TEXT NOT NULL CHECK (json_valid(packet_json)),
  created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS render_requests (
  request_hash TEXT PRIMARY KEY,
  packet_hash  TEXT NOT NULL REFERENCES packets(packet_hash),
  request_json TEXT NOT NULL CHECK (json_valid(request_json)),
  created_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS takes (
  take_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  request_hash     TEXT NOT NULL REFERENCES render_requests(request_hash),
  status           TEXT NOT NULL CHECK (status IN
    ('queued','submitted','generating','ready','failed','selected','rejected','needs_reconciliation')),
  artifact_path    TEXT,
  artifact_hash    TEXT,
  provider_job_id  TEXT,
  error            TEXT,
  created_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS qa_results (
  qa_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  take_id   INTEGER NOT NULL REFERENCES takes(take_id),
  layer     TEXT NOT NULL CHECK (layer IN ('deterministic','visual')),
  passed    INTEGER NOT NULL CHECK (passed IN (0,1)),
  status    TEXT NOT NULL,
  detail_json TEXT NOT NULL CHECK (json_valid(detail_json)),
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
  episode_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  scene_hash      TEXT NOT NULL REFERENCES scene_specs(scene_hash),
  take_id         INTEGER REFERENCES takes(take_id),
  title           TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'draft',
  created_at      INTEGER NOT NULL,
  sim_day         INTEGER,           -- world day the episode was made for (0-based)
  arc_kind        TEXT,
  score           REAL,
  continuity_json TEXT,              -- evidence that it continues earlier episodes, or null
  qa_status       TEXT,
  recap           TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS budget_ledger (
  entry_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  request_hash TEXT NOT NULL,
  backend      TEXT NOT NULL,
  currency     TEXT NOT NULL,
  amount       REAL NOT NULL,
  note         TEXT NOT NULL,
  created_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS publications (
  publication_id INTEGER PRIMARY KEY AUTOINCREMENT,
  episode_id     INTEGER NOT NULL REFERENCES episodes(episode_id),
  publisher      TEXT NOT NULL,
  reference      TEXT NOT NULL,
  created_at     INTEGER NOT NULL
);

-- Audience claims are never world truth; they can only become rumour events via the world validator.
CREATE TABLE IF NOT EXISTS audience_claims (
  audience_claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_ref        TEXT NOT NULL,
  claim_json        TEXT NOT NULL CHECK (json_valid(claim_json)),
  created_at        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
  experiment_id TEXT PRIMARY KEY,
  config_json   TEXT NOT NULL CHECK (json_valid(config_json)),
  config_hash   TEXT NOT NULL,
  created_at    INTEGER NOT NULL
);

-- Content-addressed rows never change once written.
CREATE TRIGGER IF NOT EXISTS scene_specs_immutable BEFORE UPDATE ON scene_specs
BEGIN SELECT RAISE(ABORT, 'scene_specs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS packets_immutable BEFORE UPDATE ON packets
BEGIN SELECT RAISE(ABORT, 'packets are immutable'); END;
CREATE TRIGGER IF NOT EXISTS render_requests_immutable BEFORE UPDATE ON render_requests
BEGIN SELECT RAISE(ABORT, 'render_requests are immutable'); END;
CREATE TRIGGER IF NOT EXISTS experiments_immutable BEFORE UPDATE ON experiments
BEGIN SELECT RAISE(ABORT, 'experiments are immutable'); END;

-- One row per simulated day the channel processed: what the world looked like and what the day cost.
CREATE TABLE IF NOT EXISTS daily_runs (
  run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id  TEXT,
  sim_day        INTEGER NOT NULL,
  world_revision INTEGER NOT NULL,
  snapshot_hash  TEXT NOT NULL,
  episode_id     INTEGER REFERENCES episodes(episode_id),
  status         TEXT NOT NULL,      -- episode | quiet_day | render_failed | qa_failed
  usage_json     TEXT NOT NULL CHECK (json_valid(usage_json)),
  created_at     INTEGER NOT NULL
);

-- A viewer's verdict on an episode (1 = boring .. 5 = gripping). The latest row for an episode is its rating.
CREATE TABLE IF NOT EXISTS episode_ratings (
  rating_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  episode_id    INTEGER NOT NULL REFERENCES episodes(episode_id),
  rating        INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  most_dramatic INTEGER NOT NULL DEFAULT 0 CHECK (most_dramatic IN (0, 1)),
  most_boring   INTEGER NOT NULL DEFAULT 0 CHECK (most_boring IN (0, 1)),
  note          TEXT NOT NULL DEFAULT '',
  created_at    INTEGER NOT NULL
);

-- v3: the capability layer. Which provider was chosen for a job and why the others were not.
CREATE TABLE IF NOT EXISTS provider_selections (
  selection_hash TEXT PRIMARY KEY,
  capability     TEXT NOT NULL,
  chosen         TEXT,               -- the provider that ended up doing the job (null: none could)
  selection_json TEXT NOT NULL CHECK (json_valid(selection_json)),
  created_at     INTEGER NOT NULL
);

-- v3: Render -> Diagnose -> Repair. Typed failures found in a take, and the targeted re-render each one led to.
CREATE TABLE IF NOT EXISTS visual_failures (
  failure_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  take_id       INTEGER NOT NULL REFERENCES takes(take_id),
  shot_id       TEXT NOT NULL,
  code          TEXT NOT NULL,
  detector      TEXT NOT NULL,
  evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
  created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS repair_requests (
  repair_hash         TEXT PRIMARY KEY,
  shot_id             TEXT NOT NULL,
  attempt             INTEGER NOT NULL,
  parent_request_hash TEXT NOT NULL REFERENCES render_requests(request_hash),
  next_request_hash   TEXT,          -- the request the repair produced (null: no repair left to try)
  repair_json         TEXT NOT NULL CHECK (json_valid(repair_json)),
  created_at          INTEGER NOT NULL
);
