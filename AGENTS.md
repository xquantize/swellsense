# SwellSense: agent guide

SwellSense is a surf assistant for New Zealand surfers. It answers questions about surfing,
boards, swell, weather, tides, spots, technique, safety and etiquette, and helps people decide
where and when to surf. Answers are grounded in cited sources and live data, never guesses.

This is also a learning project in applied AI engineering. Prefer clear, simple code over clever
code, with short docstrings explaining why.

## What the finished product does
- **Surf knowledge:** explains how swell, wind, tides and bathymetry shape waves; board design;
  technique; etiquette; surf history and culture. Answers from the knowledge base, with citations.
- **Live conditions:** current and forecast swell (height, period, direction), wind and tides for
  any spot, from forecast APIs at question time.
- **Spots and maps:** finds spots near a location; each spot has a profile (break type, best swell
  direction, best wind, best tide, hazards, skill level).
- **Where to surf:** combines spot profiles with forecasts to recommend spots and times,
  explaining the reasoning.
- **Board advice:** recommends board types and volume ranges from the surfer's weight, ability and
  waves, grounded in sources.
- **Safety:** rips, hazards and conditions beyond someone's ability, flagged clearly.
- **Session logbook:** surfers log sessions; recommendations improve from their history.
- **Web app:** a chat interface with citations, forecast charts and a spot map.

## How the bot must answer
- Ground factual claims in retrieved sources and cite them. If nothing relevant is found, say so.
- Live conditions come only from forecast tools, with the time and source of the data.
- Never invent numbers. Calculations happen in code, not in the model.
- Safety first: flag dangerous conditions and hazards. Never encourage someone into surf beyond
  their ability.
- Be honest about uncertainty, especially for local knowledge.
- Tone: like a knowledgeable local surfer. Practical, friendly, concise, no emojis.
- Units: wave height in metres, wind in knots, weight in kg, board length and dimensions in
  feet/inches, board volume in litres.

## Architecture principles
- All LLM calls go through `swellsense.llm`. The LLM provider is configured in `.env` and must stay
  swappable (local Ollama by default).
- The model reads, code computes: no arithmetic or unit conversion in prompts.
- Validate all model output with Pydantic before using it.
- Static knowledge goes in the RAG store. Live data (forecasts, tides) is fetched by tools at
  question time and never stored as knowledge.
- Keep ingestion (fetch raw), processing (clean, chunk, embed) and serving (retrieve, answer) as
  separate stages, so each can be rerun alone.

## Data and licensing
- Every source in `data/sources.yaml` needs a license, attribution and usage label:
  - `open`: open license or public domain. Usable anywhere, with attribution.
  - `permission`: the owner agreed. Usable anywhere, with attribution.
  - `private`: local development only. Must never appear in anything public, and is never committed.
- Every stored document keeps its source URL, license and attribution, so answers can cite it.
- When fetching: respect robots.txt and site terms, send the project User-Agent, and rate limit.
- Never commit `.env`, anything in `data/raw/`, or downloaded tide and forecast files in `data/cache/`.

## Layout
- `src/swellsense/llm/`: the only code that talks to the LLM API
- `src/swellsense/extraction/`: structured extraction (boards, unit parsing)
- `src/swellsense/ingest/`: source registry, fetchers, raw document storage, ingest runs
- `src/swellsense/spots/`: spot profiles and the registry that loads them
- `src/swellsense/tides/`: LINZ Tauranga predictions and tide state at a time
- `src/swellsense/forecast/`: Open-Meteo swell and wind for one spot
- `src/swellsense/chatbot.py`: terminal chat
- `src/swellsense/cli.py`: the `swellsense` command
- `data/sources.yaml`: all data sources
- `data/spots.yaml`: baseline spot profiles
- `.cursor/hooks/`: agent hooks (auto-format, file protection)
- `scripts/check.sh`: the single check command
- `tests/`: unit tests

## Commands
- Install: `uv sync`
- Verify changes: `bash scripts/check.sh` (lint, format check, then tests; stops at the first failure)
- Apply lint and format fixes: `uv run ruff check --fix && uv run ruff format`
- Download sources: `uv run swellsense ingest` (or `--source ID` for one)
- Tauranga tides: `uv run swellsense tides` (or `--date YYYY-MM-DD`)
- Spot forecast: `uv run swellsense forecast SPOT` (or `--hours N`, default 12)
- Chat: `uv run python -m swellsense.chatbot`

## Roadmap
1. [x] Foundations: provider-agnostic LLM client, structured extraction
2. [x] Knowledge ingestion: source registry, fetching, raw storage
3. [ ] Processing: cleaning, chunking, local embeddings, Postgres + pgvector (in progress)
4. [ ] Grounded chat: retrieval with citations
5. [ ] Live conditions: Open-Meteo forecast and LINZ tides are in; the conditions check is still to come
6. [ ] Spots and maps: spot data and profiles, "where to surf" recommendations
7. [ ] Board advice grounded in sources
8. [ ] Session logbook and personalisation
9. [ ] Web app
10. [ ] Quality: eval sets for answers and retrieval, run in CI

Work on the current roadmap stage unless asked otherwise. Don't build ahead.

## Coding rules
- Edited Python files are auto-formatted by a hook.
- A beforeReadFile hook blocks reads of `.env` files (except `.env.example`) and anything under `data/raw/`, including case variants and symlinks that resolve there.
- Tests must never call the network or the LLM. Mock them.
- Keep changes small, one concern per pull request.
- Update the README and this file's roadmap when things change.

## Stop and ask a human first
- Adding or changing a data source, license or usage label
- Adding a dependency
- Deleting files or data
- Anything involving secrets, deployment or cloud accounts
- Changing how the bot answers (the "How the bot must answer" section)

## Definition of done
- `bash scripts/check.sh` passes
- A short summary of what changed, plus anything you were unsure about

## Cursor Cloud specific instructions
- Use `uv` for Python 3.13 (`.python-version`). The image's system Python may be older; `uv sync --locked` installs the pinned interpreter.
- Checks: `bash scripts/check.sh`. Tests must not call the network or the LLM.
- There is no dev server. `uv run swellsense ingest` downloads every source into `data/raw/` and writes `data/raw/_last_run.json`. `uv run swellsense ingest --source ID` downloads one source. `uv run swellsense tides` prints Tauranga high and low waters for today and caches the LINZ CSV under `data/cache/`. `uv run swellsense forecast SPOT` prints an Open-Meteo swell and wind table and caches it under `data/cache/forecast/` for one hour. Loading `data/sources.yaml` with `swellsense.ingest.registry.load_sources` and parsing board dimensions with `swellsense.extraction.units.parse_dimension` exercises the current product path.
- `uv run python -m swellsense.chatbot` expects a local OpenAI-compatible server (default `http://localhost:11434/v1`, see `.env.example`). The environment does not start that server.
