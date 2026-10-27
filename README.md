# OffBall

[![CI](https://github.com/FelixMatrixar/OffBall/actions/workflows/ci.yml/badge.svg)](https://github.com/FelixMatrixar/OffBall/actions/workflows/ci.yml)

OffBall makes space visible: it finds the off-ball runs that create chances in a synthetic football match, explains why they matter, fact-checks every claim and puts the story on screen for six kinds of viewer. All match data is synthetic, and every caption and answer is AI-generated.

- `PRD.md` says what OffBall does and why.
- `INTEGRATION.md` says what the frontend reads and what the backend and AI must send.
- `web/README.md` covers the frontend.
- `TRANSPARENCY.md` says what the AI does, how it's checked and its limits; `DATASHEET.md` describes the data; `SECURITY.md` says how to report a vulnerability; `docs/adr/` records design decisions.

## Run it

You need Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 22.6 or later for the frontend (the Python tests use it too, to read the frontend's showcase).

```bash
uv sync
```

```bash
uv run offball serve all
```

That starts the API on port 8000 and the OffBall MCP server on port 8001. Or, with Docker, `docker compose up --build` runs the same two with the Valkey event bus and the Aspire Dashboard, as the VM does (`deploy/README.md`). Then start the frontend (`npm run dev` in `web/`) and open the match view on the local pipeline:

```text
http://localhost:5173/#/match?feed=sse:http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fmatches%2Fm07%2Fstream%3Fperiod%3D2%26from_ms%3D1066000%26to_ms%3D1093000
```

With an `sse:` feed from this API, the frontend also uses the API for the rest: the Analyst and Player focus panels show numbers computed from the match, Ask OffBall goes to the Pundit, and the producer console reads the same feed. Anything the API can't answer falls back to the frontend's built-in content. Set `?api=` or `VITE_API_BASE` to point at an API on its own.

To produce a live run, start it with `POST /api/live-runs` (for example `{"match_id": "m07", "period": 2, "from_ms": 1066000, "to_ms": 1093000}`), then open `#/producer` with the same `?feed=` and `&producer=` set to the token it returns: approvals, holds, skips and retractions then go to the backend and reach every screen on the stream.

The partner graphics template reads the same stream:

```text
http://localhost:5173/partner/index.html?feed=sse:http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fmatches%2Fm07%2Fstream%3Fperiod%3D2%26from_ms%3D1238000%26to_ms%3D1252000
```

## Give the agents a model

Every caption, graphic and answer comes from a model; there are no templates to fall back on. Without a model the match still streams (players, clock and score) and the panels still show computed numbers, but nothing an agent would write airs.

1. Get an OpenRouter key. The agents use two of its models (PRD 14.13): a fast one for the Scout, Persona, Producer and Engineer, and a reasoning one for the Explainer, Fact-checker and Pundit.
2. Copy `.env.example` to `.env` (git ignores it) and set `OPENROUTER_API_KEY`, plus the two model IDs if you want others than the defaults. A model deployed in a Foundry resource works too: set its endpoint instead, as `.env.example` shows.
3. Restart `offball serve all`, and run `uv run offball eval agents` to score each agent on its own task set.

## Commands

| Command | What it does |
| --- | --- |
| `uv run offball serve all` | API and MCP server (`serve api` or `serve mcp` for one) |
| `uv run offball replay m07 --period 2 --from-ms 1225000 --to-ms 1252000` | Runs a window of a match through the live pipeline and the crew, and writes the stream to `replays/m07.jsonl`, checked against `contracts/` |
| `uv run offball golden run` | Puts the eight golden render cases through the pipeline and checks what it sends the frontend (PRD 19.5); `golden check <case> --stream out.jsonl` checks any stream |
| `uv run offball eval agents` | Scores each agent on its own task set against the model in `.env` (PRD 14.15), and writes `calibration/reports/agents.md` |
| `uv run offball gates smoke` | Runs the nine quality gates on the smoke set and writes the report |
| `uv run offball showcase` | Regenerates the showcase match |
| `uv run offball schemas` | Exports the JSON Schemas in `contracts/` from the code |
| `uv run pytest` | Python tests, including the schema and truth-isolation checks |
| `uv run ruff check offball tests` | Lint |

CI (`.github/workflows/ci.yml`) runs the lint and tests for both sides, tests the event bus against a real Valkey, checks the deployment files and builds the image, and publishes the smoke set's quality-gate report, on every push and pull request. On `main` it also pushes the image to GitHub Container Registry.

### Settings

| Setting | What it does |
| --- | --- |
| `OFFBALL_MAX_MOMENTS` | Moments the crew works on at once in a live run (default 2) |
| `TOKENS_PER_MATCH` | The match's token budget: past 80% only priority-0 moments air, at 100% none (default 2,000,000) |
| `OFFBALL_ENGINEER_EVERY_S` | How often the Engineer checks the crew's health in a live run (default 60) |
| `OFFBALL_TRACE=console` | Prints traces of every agent call; `OTEL_EXPORTER_OTLP_ENDPOINT` sends them to the Aspire Dashboard instead (needs the `vm` extra) |
| `VALKEY_URL` | Sends each live run's feed through its stream on the Valkey event bus, `feed.{match_id}` (PRD 11.5; needs the `vm` extra). Without it the feed goes straight to ingest. `docker compose up` sets it |
| `OFFBALL_WEB_ORIGINS` | The web app's origins, comma-separated, that may call the API from a browser (default `*`; `deploy/up.sh` sets it) |
| `FAULTS` | Dev only: injects faults, such as `latency:explainer:4000` |

## Layout

| Folder | What's in it |
| --- | --- |
| `offball/generator/` | The league, the emergent match engine and the director |
| `offball/models/` | Pitch control, the metric registry and the moment detectors |
| `offball/services/` | The feed emitter, the event bus, the live service, the API, panel stats, degrade flags, tracing and replay builds |
| `offball/mcp/` | The OffBall MCP server and its tools |
| `offball/agents/` | The agents: instructions, the broadcast workflow (Microsoft Agent Framework), corrections, the Engineer and Ask OffBall |
| `offball/eval/` | Golden render tests and the per-agent evaluations |
| `contracts/` | JSON Schemas for every message |
| `deploy/`, `infra/` | The VM's stack and scripts, and the Foundry Bicep (`deploy/README.md`) |
| `datasets/`, `truth/` | Generated matches, and their answer keys (read only by evaluation) |
| `web/` | The frontend |
