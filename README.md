# SwellSense

**A surf assistant for New Zealand surfers.** Ask about boards, swell, wind, tides, spots and safety, and get answers grounded in cited sources instead of guesses.

> 🏄 This is my first project built with **agentic coding**: AI agents write most of the code, and I plan the work, review every change, and decide what ships. See [How it's built](#how-its-built).

## Status

Early development. What works today:

- **Terminal chat** with a local model through Ollama. Conditions questions ("is it worth surfing?", "where should I go?") are answered from the conditions check. The model chooses the tool and phrases the result; the score is computed in code. Other answers are not grounded in sources yet, so treat those with caution.
- **Knowledge ingestion**: downloads surf knowledge from Wikipedia into local storage, keeping the source URL, license and attribution on every document.
- **Processing**: cleans and chunks ingested pages, embeds new or changed chunks via the configured provider, and stores them in local Postgres for retrieval.
- **Tauranga tides**: prints LINZ high and low waters for a day, with the required acknowledgement.
- **Spot forecast**: hourly swell, wind waves and wind for a Bay of Plenty spot, from Open-Meteo.
- **Conditions check**: rates the next few hours at a spot from that forecast, the tide and the spot profile, or ranks every spot by its best hour. Tied scores share a rank, and a skill level leaves harder spots on a separate list.

Next up: a database with retrieval, so answers come from real sources with citations. See the [Roadmap](#roadmap).

## What it will do

- Explain how swell, wind, tides and the seafloor shape waves
- Recommend boards and volume for your weight, ability and local waves
- Check live forecasts and suggest where and when to surf
- Flag hazards like rips, and conditions beyond your ability
- Cite where every answer came from

## How it's built

SwellSense is built with an agentic workflow, where AI coding agents do the implementation and a human stays in charge:

1. **I write a task** as a GitHub issue, often from my phone, with exact files, functions and tests.
2. **A cloud agent** (Cursor) picks it up, implements it, and opens a pull request.
3. **Automatic checks** run on every change: linting, formatting and tests in CI, plus hooks that auto-format agent edits and block agents from reading secrets.
4. **I review** every pull request and merge it myself. Nothing reaches `main` without passing CI.

[`AGENTS.md`](AGENTS.md) is the rulebook every agent reads: how the project works, its rules, and when to stop and ask a human.

## Getting started

Requires macOS or Linux, [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com).

```bash
ollama pull qwen3:8b
uv sync
cp .env.example .env
docker compose up -d
uv run swellsense db init
```

In `.env`, set `HTTP_USER_AGENT` to identify the project to source sites, for example `SwellSense/0.1 (https://github.com/<you>/swellsense)`. Postgres runs locally via Docker Compose; `DATABASE_URL` in `.env.example` matches the compose service.

## Commands

| Command | What it does |
| --- | --- |
| `uv run python -m swellsense.chatbot` | Chat in the terminal (needs Ollama). Conditions questions use the live check |
| `uv run swellsense ingest` | Download all sources into `data/raw/` |
| `uv run swellsense ingest --source wikipedia` | Download a single source |
| `uv run swellsense process` | Clean, chunk and embed `data/raw/` into Postgres |
| `uv run swellsense search "what is a rip?"` | Vector search over embedded chunks (debug) |
| `uv run swellsense search "swell period" --k 10` | Return more nearest chunks |
| `uv run swellsense tides` | Print today's Tauranga highs and lows |
| `uv run swellsense tides --date 2026-01-15` | Print one day's Tauranga tides |
| `uv run swellsense forecast mount-main-beach` | Print 12 hours of swell and wind for a spot |
| `uv run swellsense forecast mount-main-beach --hours 48` | Print a longer forecast |
| `uv run swellsense check mount-main-beach` | Rate the next 12 hours at a spot |
| `uv run swellsense check --all` | Rank every spot by its best hour, showing ties as ties |
| `uv run swellsense check --all --skill beginner` | Rank spots at a skill level, and list the harder ones |
| `docker compose up -d` | Start local Postgres with pgvector (localhost only) |
| `uv run swellsense db init` | Create the documents and chunks schema |
| `bash scripts/check.sh` | Lint, format check and tests |

## Data and licensing

Every source in [`data/sources.yaml`](data/sources.yaml) has a license, an attribution and a usage label:

- `open`: openly licensed or public domain, usable anywhere with attribution
- `permission`: the owner has agreed, usable anywhere with attribution
- `private`: for local development only, never used in anything public

Downloaded documents in `data/raw/` are never committed. Tide CSVs downloaded by `swellsense tides` and `swellsense check`, and forecasts downloaded by `swellsense forecast` and `swellsense check`, live in `data/cache/` and are not committed. Current knowledge source: Wikipedia (CC BY-SA 4.0). Tide predictions are LINZ data and the command prints their required acknowledgement. Wave and wind forecasts are Open-Meteo data (CC BY 4.0). The free API is for non-commercial use, and the command prints the required credit.

## Project structure

```
src/swellsense/
  llm/          the only code that talks to the LLM
  extraction/   structured extraction (board specs, unit parsing)
  ingest/       source registry, fetchers, storage, ingest runs
  processing/   cleaning, chunking, and the process run
  db/           local Postgres connection and schema
  spots/        spot profiles
  tides/        LINZ tide predictions and tide state
  forecast/     Open-Meteo swell and wind for one spot
  conditions/   wind, swell and tide judgements, and the hourly rating
  chat/         conditions tools the chatbot can call
  chatbot.py    terminal chat
  cli.py        the swellsense command
data/sources.yaml   all data sources
.cursor/hooks/      agent hooks (formatting, file protection)
scripts/check.sh    the single check command
```

## Roadmap

- [x] Foundations: provider-agnostic LLM client, structured extraction
- [x] Knowledge ingestion: source registry, fetching, raw storage
- [x] Processing: cleaning, chunking, embeddings, Postgres with pgvector
- [ ] Grounded chat: retrieval with citations
- [ ] Live conditions: forecast, tides, classifiers, an explainable conditions check and a ranking are in. The chatbot answers a spot check or "where should I go" from those tools. Other answers are not grounded in sources yet.
- [ ] Spots and maps: spot profiles and "where to surf" recommendations
- [ ] Board advice grounded in sources
- [ ] Session logbook and personalisation
- [ ] Web app
- [ ] Evals for answer quality, run in CI

## License

See [LICENSE](LICENSE).
