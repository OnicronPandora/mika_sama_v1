-- Mika-sama database schema (spec: docs/top_secret.md, "Database schema").
-- Safe to run again: everything is created only if missing. Apply it with
--   python -m app.db.schema      (from mika/server; reads mika/server/.env)
-- The allowed values in the CHECK constraints must match mika_shared.enums (a test checks this).

-- pgvector. Creating it needs a superuser; if the app's role isn't one, create it once as a superuser.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    user_id           TEXT PRIMARY KEY,
    username          TEXT,
    platform          TEXT,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_logs (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id       UUID NOT NULL,
    user_id          TEXT NOT NULL REFERENCES users (user_id),
    user_message     TEXT NOT NULL,
    rag_context_used TEXT,
    mika_intent      TEXT NOT NULL CHECK (mika_intent IN ('casual_conversation', 'filter_incident', 'error_recovery')),
    mika_emotion     TEXT NOT NULL CHECK (mika_emotion IN ('happy', 'sad', 'confused', 'angry', 'neutral')),
    mika_reply       TEXT NOT NULL,   -- what was actually spoken, after filtering
    original_reply   TEXT NOT NULL,   -- the raw LLM output
    filter_action    TEXT NOT NULL CHECK (filter_action IN ('ALLOW', 'REPLACE', 'BLOCK')),
    filter_reason    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_logs_user_created_idx ON chat_logs (user_id, created_at);

CREATE TABLE IF NOT EXISTS memory_embeddings (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_log_id BIGINT NOT NULL REFERENCES chat_logs (id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    embedding   vector(768) NOT NULL,  -- nomic-embed-text; must match EMBEDDING_DIM in app/config.py
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memory_embeddings_chat_log_idx ON memory_embeddings (chat_log_id);
CREATE INDEX IF NOT EXISTS memory_embeddings_embedding_idx ON memory_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS personality_traits (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trait              TEXT NOT NULL,
    source_chat_log_id BIGINT REFERENCES chat_logs (id) ON DELETE SET NULL,  -- null for traits the admin adds by hand
    active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
