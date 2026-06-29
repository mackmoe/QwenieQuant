-- Extensions only. PostgreSQL is the platform's system of record for
-- everything — predictions, learning history, memory, reflections, and
-- operational records. pgvector is one extension among many here, not a
-- separate database: it lets `memory` store embeddings next to the facts
-- they describe, in the same transactional store as everything else.

CREATE EXTENSION IF NOT EXISTS vector;
