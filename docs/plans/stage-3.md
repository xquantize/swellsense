# Plan: roadmap stage 3 (processing: cleaning, chunking, embeddings, Postgres + pgvector)

## Decisions (final)

- Dependencies: add `psycopg[binary]` and `pgvector`.
- Embedding model: `nomic-embed-text` (768 dimensions).
- Local Postgres: Docker Compose.
- CI: a Postgres service container (slice 7), run right after slice 4.
- Chunking: 300 words, 50 words overlap. No intermediate files. No `swellsense search` command in this stage.

## Progress (tick each box in the slice's own PR)

- [x] Slice 1: Clean raw pages into sections
- [ ] Slice 2: Chunk a document with its citation metadata
- [ ] Slice 3: Embedding function in `swellsense.llm`
- [ ] Slice 4: Local Postgres, schema and `swellsense db init`
- [ ] Slice 7: Postgres service container in CI
- [ ] Slice 5: Chunk store (upsert, prune, nearest)
- [ ] Slice 6: `swellsense process` end to end

Slices are run one at a time, in the order above.

Based on `origin/develop` @ `6939762`. Nothing for stage 3 exists yet. There is no processing package, no DB code and no DB dependency, and no open PRs or branches. The only knowledge source is `wikipedia` (9 articles, CC BY-SA 4.0, `open`). Raw pages are `RawDocument` JSON in `data/raw/<source>/<slug>.json`, loaded with `ingest.store.load_all()`.

## 1. Scope and non-goals

**In scope** (stage 3 is done when this works end to end on a laptop):
- **Clean**: turn a `RawDocument`'s MediaWiki plain text into sections (heading plus body). Drop non-content sections (References, See also, External links, Further reading, Notes, Bibliography) and normalise whitespace.
- **Chunk**: split sections into overlapping chunks with a word budget. Each chunk carries its document's id, title, URL, section, license, attribution and usage, so stage 4 can cite it.
- **Embed**: add an `embed(texts)` function in `swellsense.llm`, calling the configured provider's OpenAI-compatible `/v1/embeddings` endpoint. Ollama supports this endpoint. It reuses the existing `openai` client, so the provider stays swappable and embedding needs no new library.
- **Store**: run Postgres with pgvector locally, using an idempotent `schema.sql` with `documents` and `chunks` tables, a `vector(N)` column and an HNSW `vector_cosine_ops` index. Provide upsert, stale-chunk deletion and a `nearest(embedding, k)` query. The query only proves the index works; stage 4 builds retrieval on it.
- **Run as its own stage**: `uv run swellsense process` reads `data/raw/`, cleans, chunks, embeds only new or changed chunks (skipped by content hash), upserts, removes chunks that no longer exist, and prints a run report. It can be rerun on its own without re-ingesting.
- README and AGENTS.md are updated (commands, layout, roadmap tick).

**Non-goals** (later stages, or deliberately left out):
- Retrieval in the chatbot, citations in answers, prompt changes, reranking, hybrid or keyword search (stage 4).
- Any change to "How the bot must answer".
- New data sources or a `web` fetcher; changes to `data/sources.yaml`.
- Eval sets and retrieval-quality metrics (stage 10). Model choice is not tuned by evals yet.
- Migration frameworks (Alembic, an ORM), async DB access, connection pooling.
- Hosted or cloud Postgres, deployment, and anything public. The database is local only.
- Storing forecasts or tides in the DB (they stay live tools, per AGENTS.md).

## 2. Decisions

1. **New dependencies (approved).** `psycopg[binary]` (Psycopg 3) and `pgvector` (the Python adapter: `register_vector`, `Vector`). No embedding library: embeddings go through the existing `openai` client to Ollama. *Rejected alternative:* `sentence-transformers`, which pulls in torch, is a heavy install and bypasses `swellsense.llm`.
2. **Embedding model.** **Decided: `nomic-embed-text`** (768 dimensions, already installed locally). Switching to another 768-dimension model later means re-embedding, not a schema change. Comparing models belongs with the stage 10 evals. Avoid `all-minilm`, whose context is too short for our chunks. Avoid `qwen3-embedding:8b` at full size: its 4096 dimensions exceed pgvector's 2000-dimension HNSW limit. `nomic-embed-text` expects task prefixes (`search_document:` / `search_query:`), and the code applies the right one.
3. **Chunk size.** Use about **300 words, with 50 words of overlap**. Never cross a section boundary; split on paragraphs first, then sentences. A short trailing chunk is merged into the previous one. The limit is counted in words, using the existing `count_words`, so no tokenizer dependency is needed. ~300 words is roughly 400 tokens, well inside the model's context. Both numbers are settings, not constants.
4. **Postgres locally.** **Decided: `docker-compose.yml`** with the `pgvector/pgvector:pg17` image (pgvector 0.8.x), with the port bound to localhost only and data in a named Docker volume. A new `DATABASE_URL` setting goes in `.env` / `.env.example`, holding a local-only dev password.
5. **Postgres in CI.** **Decided: CI gets a Postgres service container (slice 7, right after slice 4).** Unit tests use fakes. DB integration tests are marked and **skipped unless `DATABASE_URL` is set**, so local runs without Postgres stay green. CI sets `DATABASE_URL` to a `pgvector/pgvector:pg17` service container, so the integration tests run there against a real database. Tests talk only to this localhost container, never the internet.
6. **Intermediate files.** **no** `data/processed/` JSON. Chunking is cheap and deterministic, so `process` goes straight from raw files to the DB. The expensive step (embedding) is skipped by chunk content hash and embedding model name. This keeps the stages separate (rerun `process` alone) with one less store to keep in sync.
7. **Private sources.** None exist today. storing the `usage` label on every chunk now, and making `nearest()` accept a `public_only` flag. Then stage 4 can never return `private` text in public output, without another schema change.
8. **A `swellsense search "query"` debug command?** **not in stage 3**. It is the first retrieval feature and belongs in stage 4. Stage 3 is verified with `nearest()` integration tests plus a manual `psql` row count.

## 3. Vertical slices, in order

Each slice is one Engineer task and one branch/PR, run strictly one at a time. Sizes include tests. Every slice must pass `bash scripts/check.sh` and update README/AGENTS.md where it adds a command, setting or folder.

**Slice 1: Clean raw pages into sections** (~150 lines)
- Files: new `src/swellsense/processing/__init__.py`, `src/swellsense/processing/clean.py`, `tests/test_clean.py`; read `ingest/models.py`.
- Change: `clean_sections(text: str) -> list[Section]`, where `Section` is a Pydantic model (`heading`, `text`). Split on MediaWiki `== Heading ==` lines (any level), with the lead text as heading `""`. Drop the boilerplate sections listed above, collapse runs of blank lines and trailing whitespace, and drop empty sections.
- Acceptance: tests with small synthetic MediaWiki strings (no real pages) cover the lead section, nested headings, each dropped heading, an empty section, and whitespace normalisation. No I/O.

**Slice 2: Chunk a document with its citation metadata** (~220 lines)
- Files: new `src/swellsense/processing/chunk.py`, `src/swellsense/processing/models.py`, `tests/test_chunk.py`; `config.py` gets `chunk_words=300` and `chunk_overlap_words=50`.
- Change: a `Chunk` model (`id = <document_id>#<index>`, `document_id`, `index`, `section`, `text`, `word_count`, `content_hash`, plus `title`, `url`, `license`, `attribution`, `usage` copied from the `RawDocument`). Add `chunk_document(doc, max_words, overlap_words) -> list[Chunk]` built on slice 1.
- Acceptance: tests check that no chunk exceeds `max_words` (except a single over-long sentence, which is kept whole), that overlap is exactly `overlap_words` between neighbours in a section, that no chunk crosses sections, that a short tail is merged, and that metadata matches the source doc. Ids and output must be deterministic, and the same input gives the same hashes.

**Slice 3: Embedding function in `swellsense.llm`** (~130 lines)
- Files: `src/swellsense/llm/client.py` (or a new `llm/embeddings.py`, re-exported), `src/swellsense/config.py` (`embedding_model`, `embedding_dimensions=768`, `embedding_batch_size`), `.env.example`, `tests/test_llm.py`.
- Change: `embed(texts: list[str], kind: Literal["document", "query"]) -> list[list[float]]`. It adds the model's task prefix, batches requests, preserves order, and raises if any vector's length is not `embedding_dimensions`.
- Acceptance: tests mock the OpenAI client (as `test_llm.py` already does). They cover batching across 2+ calls, order, prefixes, the dimension mismatch error and empty input. No network.
- Model: `nomic-embed-text`, using its `search_document:` / `search_query:` prefixes.

**Slice 4: Local Postgres + schema + `swellsense db init`** (~200 lines)
- Files: new `docker-compose.yml`, `src/swellsense/db/__init__.py`, `src/swellsense/db/schema.sql`, `src/swellsense/db/connection.py`, `tests/test_db_schema.py`; `config.py` (`database_url`), `.env.example`, `cli.py` (a `db init` subcommand), `pyproject.toml` + `uv.lock` (the two new deps), README, `tests/conftest.py` (marker plus skip-if-no-`DATABASE_URL`).
- Change: `connect()` opens a Psycopg 3 connection and calls `register_vector`. `init_schema()` runs `CREATE EXTENSION IF NOT EXISTS vector` and creates `documents` and `chunks` (`embedding vector(768)`, `embedding_model text`, `content_hash`, `usage`) plus an HNSW cosine index, all `IF NOT EXISTS`. At startup, check that the column's dimension equals `embedding_dimensions`, and fail with a clear message if not.
- Acceptance: a unit test checks the SQL file parses and names the expected tables, index and dimension (no DB). Integration tests, skipped without `DATABASE_URL`, check that `init_schema` is idempotent (runs twice) and that the vector type round-trips. Human smoke test: `docker compose up -d && uv run swellsense db init`.
- Decisions 1 and 4 are made (deps approved, Docker Compose).

**Slice 5: Chunk store: upsert, prune, nearest** (~200 lines)
- Files: new `src/swellsense/db/chunks.py`, `tests/test_db_chunks.py`.
- Change: `upsert_document(conn, doc)`, `existing_hashes(conn, document_id) -> dict[chunk_id, (content_hash, embedding_model)]`, `upsert_chunks(conn, chunks, embeddings, model)`, `delete_chunks_except(conn, document_id, keep_ids)`, and `nearest(conn, embedding, k, public_only=True) -> list[ChunkHit]` using `<=>` (cosine distance). It returns the citation fields plus the distance.
- Acceptance: integration tests (skipped without `DATABASE_URL`) use tiny hand-made 768-dimension vectors to check that nearest returns the expected order, `public_only` hides `private` rows, upsert is idempotent and pruning removes stale chunks. Each test runs in a rolled-back transaction or its own schema, so it never touches real data.

**Slice 6: `swellsense process`, the processing stage end to end** (~250 lines)
- Files: new `src/swellsense/processing/run.py`, `cli.py`, `tests/test_process_run.py`, README + AGENTS.md (commands, layout, roadmap stage 3 ticked).
- Change: `process(docs, embed_fn, store) -> ProcessReport`, with `embed_fn` and `store` injected so tests use fakes. For each `RawDocument`, it chunks the document, skips chunks whose hash and model are unchanged, embeds the rest in batches, upserts and prunes. One failing document is recorded and the run continues, mirroring `ingest/run.py`. The report counts documents, chunks embedded, unchanged and removed, plus failures. The CLI wires the real `load_all`, `embed` and DB connection. If Ollama or Postgres is unreachable, it prints a one-line error and exits non-zero.
- Acceptance: tests with a fake embedder (one deterministic vector per text) and an in-memory fake store cover the first run (everything embedded), the second run (0 embedded, all unchanged), a changed doc (only changed chunks re-embedded, removed ones pruned), a model change (everything re-embedded) and one failing doc. Human smoke test: `uv run swellsense ingest && uv run swellsense process`, run twice; the second run embeds 0.

**Slice 7 (runs right after slice 4, before slices 5 and 6): Postgres service container in CI** (~20 lines, `.github/workflows/ci.yml` only). Add a `pgvector/pgvector:pg17` service with a health check and set `DATABASE_URL` for the `check` job, so DB integration tests run in CI. Acceptance: CI `check` passes with the DB tests executed, not skipped. Tests still never touch the internet or Ollama.

That is 7 slices, which is above my ~5 threshold. The human confirmed the plan.

## 4. Risks and mitigations

- **Dependency gates.** Slices 4–6 add `psycopg[binary]` and `pgvector`, which are approved. Slices 1–3 need no new dependencies.
- **The Engineer and Reviewer may not have Docker, Postgres or Ollama running.** The DB integration tests would then be skipped, and SQL could merge without ever running. Mitigations: keep the SQL small and the logic in pure, faked code; give slices 4–6 a human smoke-test step before I mark them done; run the DB integration tests in CI (slice 7).
- **The embedding dimension is locked into the schema.** The column is `vector(768)`, and a model with a different size needs a re-create. Mitigations: `embedding_model` is stored per chunk, a mismatch makes `process` re-embed, and a dimension mismatch fails loudly at `db init`/`process` instead of storing junk.
- **Silent truncation by the model.** If a chunk is longer than the embedding context, the end is ignored. Mitigation: 300 words (~400 tokens) is far below the context, and the size is a setting.
- **MediaWiki text format assumptions.** Cleaning assumes `== Heading ==` markers in the `explaintext` output. Mitigation: tests use synthetic fixtures. Before slice 1 merges, the human (only you can read `data/raw/`) spot-checks one cleaned page. Nothing from `data/raw/` is copied into tests.
- **Licensing and citations.** CC BY-SA requires attribution. Mitigation: every chunk row has `url`, `license`, `attribution` and `usage`, and slice 5 tests that `public_only` filters `private`. The DB lives in a Docker volume, outside the repo, so nothing derived from raw data is committed.
- **Network in tests.** Slices 1–2 and 6 are pure, using fakes. Slice 3 mocks the OpenAI client. Slices 4–5 hit only a local DB, and only when `DATABASE_URL` is set; they are skipped locally by default, and run in CI against the service container. No test calls Ollama, Wikipedia or the internet.
- **Scope creep into stage 4.** The `nearest()` query is the boundary. Nothing in this stage touches `chatbot.py`, `chat/tools.py` or prompts.

## 5. Team

**Engineer + Reviewer is enough.** Every slice is a small, test-first Python change of the same kind they have shipped for stages 1–2 and 5. The new parts (SQL, pgvector) are covered by the docs and kept thin. A specialist (for example a retrieval/ML engineer) would mainly add value for tuning: model choice, chunking strategy and retrieval quality. That only makes sense once there are evals to tune against (stage 10, or stage 4 at the earliest). Adding one now would add coordination cost on a 9-document corpus.

The one real gap is **end-to-end verification with live Postgres and Ollama**, which no agent can reliably do. I'm covering it with short human smoke-test steps on slices 4–6 rather than a new role.
