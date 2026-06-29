-- Empty schemas only — no tables, no data. Each schema is a namespace
-- for a later phase to build into; see docs/POSTGRES.md for what each
-- one is for. Do not add tables here — this file establishes structure,
-- not application logic.

CREATE SCHEMA IF NOT EXISTS prediction;
COMMENT ON SCHEMA prediction IS 'Generated predictions and their eventual outcomes.';

CREATE SCHEMA IF NOT EXISTS learning;
COMMENT ON SCHEMA learning IS 'Review of past predictions and outcomes, used to refine future strategy.';

CREATE SCHEMA IF NOT EXISTS memory;
COMMENT ON SCHEMA memory IS 'Persistent agent memory, including embeddings (pgvector).';

CREATE SCHEMA IF NOT EXISTS reflection;
COMMENT ON SCHEMA reflection IS 'Self-review of past decisions and reasoning.';

CREATE SCHEMA IF NOT EXISTS system;
COMMENT ON SCHEMA system IS 'Platform-level operational records (e.g. job runs, audit history).';
