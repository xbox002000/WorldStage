-- v5 -> v6: indexes only (no table, no row, no hash changes). The queries the rules and the agents ask most, by a
-- profile of 30-day worlds: what someone believes about someone (memories by observer and claim, claims by
-- subject/object/act), what someone took part in (participants by person), the events of a kind in a time range,
-- and events by who did what to whom (the actor and target inside truth, as expression indexes that the queries'
-- json_extract(truth, '$.actor') = ? use as written).
CREATE INDEX IF NOT EXISTS idx_memories_claim      ON memories(observer_id, claim_id);
CREATE INDEX IF NOT EXISTS idx_memories_by_claim   ON memories(claim_id);
CREATE INDEX IF NOT EXISTS idx_claims_key          ON claims(subject, object, act);
CREATE INDEX IF NOT EXISTS idx_participants_person ON event_participants(person_id, event_id);
CREATE INDEX IF NOT EXISTS idx_events_type_time    ON events(type, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_actor        ON events(json_extract(truth, '$.actor'), timestamp);
CREATE INDEX IF NOT EXISTS idx_events_target       ON events(json_extract(truth, '$.target'), timestamp);
