# OffBall

OffBall makes space visible: it finds the off-ball runs that create chances in a synthetic football match, explains why they matter, fact-checks every claim and puts the story on screen for six kinds of viewer. All match data is synthetic, and every caption and answer is AI-generated.

- `PRD.md` says what OffBall does and why.
- `INTEGRATION.md` says what the frontend reads and what the backend and AI must send.
- `web/README.md` covers the frontend.

## Run it

You need Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 22 for the frontend.

```bash
uv sync
```

```bash
uv run offball serve all
```

That starts the API on port 8000 and the OffBall MCP server on port 8001. To watch a live run of the showcase goal in the partner graphics template, start the frontend (`npm run dev` in `web/`) and open:

```text
http://localhost:5173/partner/index.html?feed=sse:http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fmatches%2Fm07%2Fstream%3Fperiod%3D2%26from_ms%3D1238000%26to_ms%3D1252000
```

## Give the agents a model

Every caption, graphic and answer comes from a model; there are no templates to fall back on. Without a model the match still streams (players, clock and score), but nothing an agent would write airs.

1. In Microsoft Foundry, create a resource and deploy two models: a fast one for the Scout, Persona and Producer, and a reasoning one for the Explainer, Fact-checker and Pundit.
2. Copy `.env.example` to `.env` (git ignores it) and set the endpoint, key and deployment names.
3. Restart `offball serve all`.

## Commands

| Command | What it does |
| --- | --- |
| `uv run offball serve all` | API and MCP server (`serve api` or `serve mcp` for one) |
| `uv run offball replay m07 --period 2 --from-ms 1225000 --to-ms 1252000` | Runs a window of a match through the live pipeline and the crew, and writes the stream to `replays/m07.jsonl`, checked against `contracts/` |
| `uv run offball showcase` | Regenerates the showcase match |
| `uv run offball schemas` | Exports the JSON Schemas in `contracts/` from the code |
| `uv run pytest` | Python tests |
| `uv run ruff check offball tests` | Lint |

## Layout

| Folder | What's in it |
| --- | --- |
| `offball/generator/` | The league, the emergent match engine and the director |
| `offball/models/` | Pitch control, the metric registry and the moment detectors |
| `offball/services/` | The feed emitter, the live service, the API and replay builds |
| `offball/mcp/` | The OffBall MCP server and its tools |
| `offball/agents/` | The agents: instructions, the broadcast workflow (Microsoft Agent Framework) and Ask OffBall |
| `contracts/` | JSON Schemas for every message |
| `datasets/`, `truth/` | Generated matches, and their answer keys (read only by evaluation) |
| `web/` | The frontend |
