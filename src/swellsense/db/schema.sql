CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    license TEXT NOT NULL,
    attribution TEXT NOT NULL,
    usage TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (id),
    "index" INTEGER NOT NULL,
    section TEXT NOT NULL,
    text TEXT NOT NULL,
    word_count INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    license TEXT NOT NULL,
    attribution TEXT NOT NULL,
    usage TEXT NOT NULL,
    embedding vector(768) NOT NULL,
    embedding_model TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
