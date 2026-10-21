-- v4 -> v5: who each person is (contracts/character.py): identity, tastes, values, habits, social style, the
-- question their life is about. Written once with the world, before anything happens, and never changed: what life
-- changes is adaptive state (world_vars, goals, relationships) that events move. The topics are the content pack's
-- vocabulary for what people like and hate.
CREATE TABLE IF NOT EXISTS character_profiles (
  person_id    TEXT PRIMARY KEY REFERENCES people(id),
  profile      TEXT NOT NULL CHECK (json_valid(profile)),
  profile_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS content_topics (
  topic TEXT PRIMARY KEY,
  label TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS character_profiles_insert BEFORE INSERT ON character_profiles
WHEN EXISTS (SELECT 1 FROM events)
BEGIN SELECT RAISE(ABORT, 'profiles are written with the world, before anything happens'); END;
CREATE TRIGGER IF NOT EXISTS character_profiles_update BEFORE UPDATE ON character_profiles
BEGIN SELECT RAISE(ABORT, 'a profile never changes: life changes adaptive state, by events'); END;
CREATE TRIGGER IF NOT EXISTS character_profiles_delete BEFORE DELETE ON character_profiles
BEGIN SELECT RAISE(ABORT, 'profiles cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS content_topics_insert BEFORE INSERT ON content_topics
WHEN EXISTS (SELECT 1 FROM events)
BEGIN SELECT RAISE(ABORT, 'topics are written with the world, before anything happens'); END;
CREATE TRIGGER IF NOT EXISTS content_topics_update BEFORE UPDATE ON content_topics
BEGIN SELECT RAISE(ABORT, 'topics never change'); END;
CREATE TRIGGER IF NOT EXISTS content_topics_delete BEFORE DELETE ON content_topics
BEGIN SELECT RAISE(ABORT, 'topics cannot be deleted'); END;
