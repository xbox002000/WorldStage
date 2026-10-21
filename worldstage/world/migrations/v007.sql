-- v6 -> v7: the Persona layer (contracts/persona.py). Each person is the instance of a CharacterGenome: written once with
-- the world, before anything happens, and never changed or removed. The genome embeds the profile (character_profiles
-- stays what the rule agents read). Which run this is (recipe, rules, cast, seed, where it was forked from) is the
-- SimulationBranch, kept in meta('branch').
CREATE TABLE IF NOT EXISTS character_genomes (
  person_id   TEXT PRIMARY KEY REFERENCES people(id),
  genome_id   TEXT NOT NULL,
  genome      TEXT NOT NULL CHECK (json_valid(genome)),
  source_kind TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS character_genomes_insert BEFORE INSERT ON character_genomes
WHEN EXISTS (SELECT 1 FROM events)
BEGIN SELECT RAISE(ABORT, 'genomes are written with the world, before anything happens'); END;
CREATE TRIGGER IF NOT EXISTS character_genomes_update BEFORE UPDATE ON character_genomes
BEGIN SELECT RAISE(ABORT, 'a genome never changes: life changes the instance, by events'); END;
CREATE TRIGGER IF NOT EXISTS character_genomes_delete BEFORE DELETE ON character_genomes
BEGIN SELECT RAISE(ABORT, 'genomes cannot be deleted'); END;
