# swellsense

## Ingest

`uv run swellsense ingest` downloads the sources in `data/sources.yaml` into `data/raw/` and writes `data/raw/_last_run.json`. Use `--source ID` to download one source.

## Verify changes

`bash scripts/check.sh` is the one command for lint, format check, and tests. It stops at the first failure.
