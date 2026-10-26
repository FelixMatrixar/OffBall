# OffBall integration guide: connecting a backend and AI to the frontend

The OffBall frontend (`web/`) is finished: every screen, mode, view, state and language. It runs on built-in stand-ins that produce the same messages and answers a backend will. The backend in `offball/` now drives the stream, Ask OffBall, the panel numbers and the producer console (sections 6 and 9 say which calls are built); everything else still comes from the stand-ins, which stay the fallback.

This guide is the specification a future backend or AI pipeline must meet to drive that frontend. It says what the frontend reads, in what format, and what the AI must write for each screen. It also shows how to test output against the finished UI without changing it and without running a server.

`PRD.md` says what OffBall does and why. The schemas in `contracts/` are the formats. This guide joins the two to what the frontend actually does. PRD sections 11, 14 and 18 specify the backend, agents and deployment built to meet it.

## Contents

1. [How the frontend gets its data today](#1-how-the-frontend-gets-its-data-today)
2. [What the frontend assumes about the match](#2-what-the-frontend-assumes-about-the-match)
3. [Ground rules](#3-ground-rules)
4. [The stream](#4-the-stream)
5. [What the AI writes, screen by screen](#5-what-the-ai-writes-screen-by-screen)
6. [The calls the frontend will make](#6-the-calls-the-frontend-will-make)
7. [Testing against the frontend without a backend](#7-testing-against-the-frontend-without-a-backend)
8. [Contract notes](#8-contract-notes)
9. [What the frontend still needs when a backend arrives](#9-what-the-frontend-still-needs-when-a-backend-arrives)
10. [Checklist](#10-checklist)

---

## 1. How the frontend gets its data today

The frontend joins a backend in two ways:

- **The stream:** one ordered stream of JSON messages per match, pushed to the browser. It carries everything tied to the match clock: 25 Hz frames, graphics and captions, retractions, the clock and the score. The match view and the partner template read it today. See [section 4](#4-the-stream).
- **Calls:** requests the frontend makes when a viewer acts. These cover a fan's question, a changed decision, a producer's approval, a recap, panel numbers, pairing and evaluation results. See [section 6](#6-the-calls-the-frontend-will-make).

Each feature below has a stand-in module with the same shape as the service that will replace it.

| Feature | Stand-in | Replaced by |
| --- | --- | --- |
| Pitch graphics, captions, voice lines, score and clock in every mode | `web/src/lib/feed/emitter.ts` builds the stream from scripted data | [The stream](#4-the-stream) |
| Producer approvals, holds, skips, retractions and the correction flow | `decide`, `retract`, `queue` and `correct` in `web/src/lib/feed/store.ts`, shared between tabs | [6.3](#63-producer-actions-and-the-trace) |
| Ask OffBall | `answer` and `suggestions` in `web/src/lib/pundit.ts` | [6.1](#61-ask-offball) |
| Change one decision | `DECISIONS` and `scenarioFor` in `web/src/lib/decisions.ts`, with words in each language pack's `decide` block | [6.2](#62-change-one-decision) |
| Recaps | `web/src/lib/recap.ts` | [6.4](#64-recaps-and-clips) |
| Analyst and Player panels, charts, leaderboards | `web/src/lib/content.ts`, `web/src/lib/stats.ts` | [6.5](#65-panel-numbers-and-charts) |
| Space Centre | `MATCHDAY` in `web/src/lib/content.ts` | [6.6](#66-space-centre) |
| Second-screen pairing | `web/src/lib/pairing.ts`, between tabs on one device | [6.7](#67-second-screen-pairing) |
| Evaluation screen | `web/src/lib/eval.ts` and the sample results in `web/src/lib/stats.ts` | [6.8](#68-evaluation-results) |
| Spoken lines | The device's own voices, in `web/src/lib/audio.ts` | [6.9](#69-voice) |
| Tier D video and share clips | `web/public/clips/*.mp4`, rendered by `npm run clips` | [6.4](#64-recaps-and-clips) |

Until a backend answers, the frontend uses the stand-in, so the demo never breaks.

---

## 2. What the frontend assumes about the match

The frontend is built around the showcase moment: Kestrel Bay's 63rd-minute decoy-run goal against Ashmoor. A backend can drive it today only with output for that match and moment.

| Assumption | Value | Where |
| --- | --- | --- |
| Match | `m07`, Kestrel Bay (`kes`) v Ashmoor (`ash`) | `MATCH_ID`, `CLUBS` in `web/src/lib/match.ts` |
| Players | `kes-01` to `kes-11` and `ash-01` to `ash-11`, with fixed names, numbers and roles. Frames and anchors must use these IDs. | `PLAYERS` in `web/src/lib/match.ts` |
| Period and window | Period 2, from `t_ms` 1,080,000 (63:00) for 9 s, held 2.5 s, so up to `t_ms` 1,091,500 | `PERIOD`, `BASE_MS`, `T_END` in `match.ts`; `HOLD` in `emitter.ts` |
| Moment time | The frontend's clock runs in seconds after 63:00: `t = (t_ms − 1,080,000) / 1000` | `ms` and `tOf` in `web/src/lib/feed/emitter.ts` |
| Story beats | Build-up 0 s, run 1.0 s, follow 2.5 s, gap 3.8 s, pass 4.2 s, shot 6.4 s, goal 6.9 s | `STEP_TIMES`, `T_GOAL` in `match.ts` |
| Attacking direction | Kestrel Bay attack left to right | `match.ts` |

The beats are fixed in the frontend. They drive Casual's "How the goal was made" steps, Learn's ideas, the timeline markers and the replay controls. Time the AI's captions to the same beats so the panels and the pitch tell one story.

Showing other matches needs frontend work first: loading the roster, clubs, kits and moment window from the backend. That is listed in [section 9](#9-what-the-frontend-still-needs-when-a-backend-arrives), not built.

---

## 3. Ground rules

These hold for every message and every answer. They follow PRD 12.8.

| Rule | Value |
| --- | --- |
| Coordinates | Metres on a 105 × 68 m pitch. x runs left to right, y bottom to top. |
| Orientation | Radians, 0 facing positive x, counter-clockwise. |
| Time | `period` plus `t_ms`, milliseconds since that period's kick-off. Period 2 at `t_ms` 1,080,000 shows as 63:00. |
| Frames | 25 Hz. `frame_id` counts frames within the period. |
| IDs | Strings prefixed by the match: `m07-e0912` (event), `m07-o0041` (overlay), `m07-c0007` (counterfactual), `m07-f2-27000` (frame, as `{match}-f{period}-{frame_id}`). |
| Versions | Every contract object carries `schema_version: "2.0"`. |
| Languages | `en`, `es`, `pt`, `fr`, `ar`, `hi`, `id`, `zh`, `ja`, `sw`. Text fields are maps keyed by locale. English is always present; the frontend falls back to it for any missing locale. |
| Numbers | Every number a viewer reads must come from computation on the match data, never from a language model, and its claim carries `evidence_ids` (PRD 13, 14.7). |
| Truth | Nothing sent to the frontend may come from `truth/` or an answer key (PRD 12.9). |
| Labels | Every overlay carries `labels: ["synthetic-data", "ai-generated"]`. A corrected replacement adds `"correction"`. |

---

## 4. The stream

### 4.1 How the frontend connects

The frontend (`web/src/lib/feed/sources.ts`) and the partner template (`web/public/partner/index.html`) read the same messages over any of these:

| Transport | How to point the frontend at it | Notes |
| --- | --- | --- |
| Server-Sent Events | `#/match?feed=sse:https://host/path` | One message per event. Named events (`event: overlay.upsert`) and unnamed ones both work. |
| WebSocket | `#/match?feed=wss://host/path` | One message per text frame. It reconnects with backoff from 0.5 s to 8 s. |
| JSONL file | `#/match?feed=jsonl:/feeds/file.jsonl` | A recorded stream, played as a replay. The easiest way to test (section 7). |
| Build setting | `VITE_FEED_URL=sse:https://…` | The same forms as `?feed=`. |
| Nothing set | | The built-in replay, with precomputed output for every mode and language |

The match view reads several messages per event or frame, one per line, but the partner template reads one message per event or frame, so send one at a time to reach both. A malformed line is skipped, never fatal.

In production the stream goes through Azure Web PubSub (PRD 11), one group per match. Send to the group as JSON with no subprotocol, so each WebSocket frame the browser receives is one message.

### 4.2 Message types

| `type` | Format | When to send | What the frontend does with it |
| --- | --- | --- | --- |
| `frame` | `{type, match_id, frame}`, with `frame` per `contracts/tracked-frame.schema.json` | 25 Hz while play is live | Moves players and the ball, draws the control field, fills live numbers in labels |
| `overlay.upsert` | `contracts/overlay-upsert.schema.json` | When a graphic is scheduled, and again with a higher `rev` whenever it changes | Draws graphics, captions, voice lines and stat cards |
| `overlay.retract` | `contracts/overlay-retract.schema.json` | When a producer pulls a graphic, or a correction replaces it | Takes the graphic off at once, with a Correction tag for 3 s |
| `clock.sync` | `contracts/clock-sync.schema.json` | At least once a second, always, even when nothing else is happening | Runs the live clock, and knows the feed is alive |
| `match.status` | `contracts/match-status.schema.json` | At kick-off, on every score change, at half and full time | Shows the score at any moment time |

A frame:

```json
{"type": "frame", "match_id": "m07",
 "frame": {"period": 2, "frame_id": 27000, "t_ms": 1080000, "ball": [55.8, 39.3, 0.11],
           "players": {"kes-09": [84.0, 34.0, 0.0], "ash-05": [90.0, 37.0, 3.142]}}}
```

`players` maps every player on the pitch to `[x, y, orientation]`; a real frame lists all 22.

An overlay and a retraction:

```json
{"type": "overlay.upsert", "match_id": "m07", "sent_at": "2026-10-24T15:18:01.000Z",
 "overlay": {"schema_version": "2.0", "overlay_id": "m07-o0041", "rev": 1, "match_id": "m07", "period": 2,
   "t_start_ms": 1081000, "t_end_ms": 1086400, "kind": "run_arrow", "layer": "pitch", "priority": 1, "mode": "casual",
   "anchors": {"player_id": "kes-09", "from_xy": [84.0, 34.0], "to_xy": [91.0, 53.0]},
   "text": {}, "speech": {}, "a11y_text": {"en": "No. 9 runs from the centre towards the right touchline."},
   "data": {"lead_s": 0.8}, "evidence_ids": ["m07-f2-27025", "m07-e0912"], "confidence": 0.91,
   "approval": "auto", "counterfactual_id": null, "detected_moment_id": "live-0007",
   "ai_generated": true, "labels": ["synthetic-data", "ai-generated"]}}

{"type": "overlay.retract", "match_id": "m07", "overlay_id": "m07-o0052", "reason": "correction",
 "corrects_event_id": "m07-e1033", "replacement_id": "m07-o0052r1", "sent_at": "2026-10-24T15:18:09.208Z"}
```

`web/public/feeds/showcase.jsonl` holds the frontend's own stream: 461 messages covering every type, every mode and all ten languages. It is the best reference for what good output looks like.

### 4.3 Timing and order

These are what the frontend does. Send so that they work.

- **Live viewers watch 1.5 s behind the newest data**, so network jitter never shows. The frontend's target time is the last `clock.sync` time, plus the time since it arrived, minus 1.5 s (`LIVE_BUFFER_MS` in `web/src/lib/feed/store.ts`).
- **Late graphics are dropped.** An upsert whose `t_end_ms` is already behind that target is logged and never shown. Leave time on the clock for a graphic to be seen after it arrives.
- **Every graphic should hold at least 2.5 s** (PRD 15.2). The match view doesn't stretch short ones. The partner template holds each caption at least 1.5 s and queues the next, so nothing flashes past.
- **Silence means a stall.** With no message of any kind for 2 s, the frontend freezes and dims the picture and shows "Feed interrupted". Keep `clock.sync` going in quiet spells and after full time.
- **Revisions win by number.** An upsert replaces the stored overlay only if its `rev` is higher. For an approval, a patched number or a newly added language, reuse the `overlay_id` and raise `rev`.
- **Corrections replace, then retract.** First send the replacement upsert: a new `overlay_id`, with `"correction"` in `labels`. Then send `overlay.retract` with `reason: "correction"`, `corrects_event_id` and `replacement_id`. The target is 5 s from the feed correction to the screen (PRD 10.6). `store.correct()` shows the exact sequence.
- **Order beyond `rev` is up to the sender.** Frames are stored by time, so out-of-order frames are fine. Remove duplicates before sending.
- **Offline:** on a live feed the frontend keeps the last 10 minutes on the device, saved every 5 s, and replays them when the network drops.

### 4.4 Approvals and modes

- Viewers see an overlay only when its `approval` is `auto` or `approved`. `pending` and `held` overlays appear only in the producer console's queue, and the partner template hides them on a live feed too.
- `mode` takes one value, so **send one overlay per mode**. The same moment usually becomes six overlays; the showcase sends 220 upserts for its 11.5 s moment.
- Density per mode (PRD 15.2): Casual and Learn show one pitch graphic at a time; Analyst up to four; Broadcaster whatever the producer schedules. `priority` 0 is the most important.
- Viewers can hide groups of pitch graphics themselves from the pitch's Overlays menu. That happens on the device and needs nothing from the backend, but it relies on each overlay's `kind` being right.

### 4.5 What each overlay kind needs

The overlay schema leaves `data` open. This table is what the renderers in `web/src/components/pitch/` actually read.

| `kind` | Modes in the showcase | `anchors` | `data` | Text |
| --- | --- | --- | --- | --- |
| `caption` | All six | `player_id`, optional | None | The line in the caption bar. Spoken in Audio-described mode. In Player focus, a caption anchored to anyone but the followed player is left out. |
| `gap_ring` | All six | `centre_xy`, `radius_m` | `rx_m`, `ry_m` (the ellipse's radii in metres), `with_pass`, `live: "gap_zone"` | The ring's label, such as "Space opens here". With `live: "gap_zone"` it may hold `{pts}`. |
| `gap_ring` in a what-if | All six | `centre_xy`, `radius_m` | `shut: true`, `shut_in`, `reruns` | "Gap stays shut". Drawn dashed; shakes once. |
| `run_arrow` | All six | `player_id`, `from_xy`, `to_xy` | `lead_s` (how far ahead of the runner it draws, in seconds); `style: "displacement"` for a defender pulled away, whose metres the frontend labels itself | None |
| `pass_line` | Analyst, Broadcaster | `from_xy`, `to_xy`, `player_ids: [passer, receiver]` | `difficulty` (0–10, sets the line's weight), `distance_m`, `planned` (a pass that wasn't played, drawn dashed) | None |
| `ghost` | All six, in a what-if | `player_id`, `ghost_track_id` | `track` (see [note 2](#8-contract-notes)), `reruns` | The ghost's tag, such as "9 · no run". Empty text leaves it unnamed. |
| `offside_line` | Analyst | None | `team`, `live` | May hold `{m}`, the back line's distance from goal |
| `player_tag` | All but Player focus | `player_id` | None | The tag over the player, such as "No. 5 follows" |
| `badge` | Analyst, Player focus | `player_id` | `threshold_kmh`, `live` | Shown only while the player is above 25.2 km/h. May hold `{speed}`. |
| `stat_card` | Broadcaster | `player_id` | `value`, `unit`, `player` | The card's title, such as "DEFENDER PULLED" |
| `chart` | (answers) | None | None | `chart` holds a Vega-Lite spec. The frontend applies its own theme, so send no colours. |
| `correction`, `control_field` | | | | Not sent. The frontend draws the Correction tag from a retraction, and computes the control field's display from frames. |

**Live placeholders.** The frontend fills `{pts}`, `{m}` and `{speed}` from the current frame, so a label stays exact as play moves. Put the placeholder in every language's text. Every other number goes in as computed.

**What-if packages.** Every part of a counterfactual replay shares one `counterfactual_id`: the ghosts, the shut ring and the captions. The frontend shows them only while the viewer has "What if no run?" switched on. The producer console lists them as one row and approves them together.

**Speech and accessibility.** `speech[locale]` carries `ssml` (or an `ssml_ref` to fetch), `voice` and, for audio cues, `pan` from −1 (left) to 1 (right). `a11y_text[locale]` is what screen readers announce: describe the picture, don't repeat the caption.

---

## 5. What the AI writes, screen by screen

The frontend shows AI output in many places, and each has its own voice. The language packs in `web/src/lib/i18n/` hold the showcase's lines for every mode and language. Today `emitter.ts` turns those lines into overlays, so they are the reference for tone and length. Read `web/src/lib/i18n/en.ts` before writing a prompt.

| Where | What the AI writes | Voice and limits | Reference |
| --- | --- | --- | --- |
| Casual captions | One line per beat | One clear idea in plain words, no jargon, about 15 words | `casual` in `en.ts` |
| Learn captions | One line per beat | Names the idea and defines it the first time it appears ("a decoy run: a run made so a teammate gets space") | `learn`, `glossary` |
| Analyst captions | One line per beat | Numbers with units and intervals, each from computation, each claim with evidence IDs | `analyst` |
| Player focus captions | Lines about the followed player, anchored with `player_id` | Second person to the fan, about that one player's off-ball work | `player`, `generic` |
| Audio-described captions and speech | Spoken description of shape and space | Says where on the pitch things happen; never talks over itself; `pan` points to the space | `audio` |
| Broadcaster lower thirds and stat cards | Short broadcast lines and card titles | Card titles in capitals, a number with its unit | `stat_card` overlays in `showcase.jsonl` |
| What-if captions | The counterfactual's story | States the result as counts out of the re-runs ("in 29 of 32 re-runs") | `whatIf` |
| Pitch tags and ring labels | Two to four words | Fits over a player; may hold live placeholders | `web/src/lib/i18n/labels.ts` |
| Ask OffBall answers | Claims with evidence, optional chart | Answers in the viewer's mode; says what it couldn't verify | [6.1](#61-ask-offball) |
| Change one decision words | Each option's label, detail, the changed world and a plain verdict | Plain words for Casual and Learn; Analyst gets the numbers | `decide` in `en.ts`, [6.2](#62-change-one-decision) |
| Recap stories | Each moment told twice: with its result, and spoiler-safe | The safe telling never gives the outcome away | `RECAP_MOMENTS` in `recap.ts` |

Every text is a map with all ten languages, or at least English. Arabic is shown right to left, and its numbers keep Latin digits.

---

## 6. The calls the frontend will make

Each section gives the stand-in it replaces, the endpoint, and the shapes. The shapes are the TypeScript types the frontend already uses, so a backend that returns them needs no UI change, and `contracts/` publishes them (`answer`, `decision-point`, `decision-result`, `recap`, `round-moments`, `alert`). The frontend reaches the API through `web/src/lib/api.ts`, at `?api=`, `VITE_API_BASE`, or the server behind an `sse:` feed from an OffBall API.

| Call | Backend | Frontend |
| --- | --- | --- |
| 6.1 Ask OffBall and suggestions | Built | Built: `AskPanel.tsx` streams it, falling back to `pundit.ts` |
| 6.2 Change one decision | Not built | Stand-in |
| 6.3 Producer actions, the trace, degrade flags | Built | Built for approvals and the trace; flags show in the API only |
| 6.4 Recaps and clips | Not built | Stand-in |
| 6.5 Panel numbers and charts | Built | Built, except the momentum ribbon |
| 6.6 to 6.9 Space Centre, pairing, evaluation, voice | Not built | Stand-ins |

### 6.1 Ask OffBall

- **Stand-in:** `answer(question, ctx)` and `suggestions(t)` in `web/src/lib/pundit.ts`, shown by `web/src/components/ask/AskPanel.tsx`.
- **Proposed call:** `POST /api/matches/{match_id}/ask`, answered as a Server-Sent Events stream.

The request:

```json
{"question": "Why did No. 5 follow the run?", "period": 2, "t_ms": 1083200,
 "mode": "learn", "lang": "es", "fav": "kes-09"}
```

The response events:

```text
event: tool    data: {"name": "query_match_state"}
event: tool    data: {"name": "compute_metric"}
event: answer  data: { ...Answer... }
```

While the answer is being made, the panel shows each tool's name as it arrives. The final `Answer`:

```ts
interface Answer {
  question: string;
  state: 'ok' | 'partial' | 'declined' | 'unknown';
  claims: { text: string; verified: boolean; evidence: string[] }[];
  chart?: { title: string; spec: VegaLiteSpec; summary: string; columns: string[]; rows: (string | number)[][] };
  tools: string[];
  alternative?: { label: string; question: string }; // for a declined or unknown question
  corrected?: boolean;                              // a corrected event changed the answer
}
```

- A claim that couldn't be checked goes in with `verified: false`, and the panel says so plainly.
- An out-of-scope question gets `state: "declined"` with an `alternative`, the nearest useful thing.
- A chart always comes with `summary`, `columns` and `rows`: the frontend shows them as its text equivalent and table view.
- The Pundit answers in English, Spanish or French as `lang` asks; for other languages the panel still says answers are in English.
- Suggested questions can stay on the device, or come from `GET /api/matches/{match_id}/suggestions?period=&t_ms=` as three strings.

### 6.2 Change one decision

- **Stand-in:** `DECISIONS`, `OPTIONS` and `scenarioFor` in `web/src/lib/decisions.ts`, shown by `web/src/components/match/DecisionPanel.tsx`. The words live in each language pack's `decide` block.
- **Proposed calls:** one to list the decisions in the moment, one to re-run an option.

`GET /api/matches/{match_id}/decisions?period=2&from_ms=1080000&to_ms=1091500` lists the decision points:

```json
[{"point_id": "k9-run", "player_id": "kes-09", "period": 2, "t_ms": 1081000,
  "words": {"en": {"what": "No. 9's run", "question": "What could No. 9 have done instead?"}},
  "options": [
    {"option_id": "k9-decoy", "actual": true, "value": 0.62,
     "words": {"en": {"label": "Decoy run wide", "detail": "What happened"}}},
    {"option_id": "k9-stay", "value": 0.18,
     "words": {"en": {"label": "Stay central", "detail": "Hold the centre-back's attention",
                      "world": "if No. 9 stays central", "plain": "The gap rarely opens.",
                      "ring": "Gap stays shut"}}}]}]
```

`POST /api/matches/{match_id}/decisions/{point_id}/runs` with `{"option_id": "k9-stay", "runs": 32}` starts the re-runs. It answers `202` with `{"run_id", "queue_position", "eta_s"}`, or with the result straight away if it was worked out in advance. Results come back from `GET …/runs/{run_id}`:

```ts
interface DecisionResult {
  option_id: string;
  counterfactual_id: string;                 // shown in the panel's metadata
  result: {
    gapOpens: number; shots: number; goals: number;  // counts out of the re-runs
    space: [median: number, lo: number, hi: number]; // m², with the 90% interval
    xg: number;                                      // the best chance's, median
    offside?: number;
  };
  tracks: Record<string, [t_ms: number, x: number, y: number][]>; // every player the change moved
  ball?: [t_ms: number, x: number, y: number][];
  pass?: { to: [number, number]; difficulty: number };            // a pass that wasn't played
  ring: { at: [number, number]; open: boolean };                  // where space opens or stays shut
  analyst: string;                                                // the verdict with its numbers
}
```

- **Speed:** precomputed options show within 2 s; a live result within 15 s (PRD 10.10).
- **Busy:** answer `429` with `{"queue_position", "eta_s"}`. The panel already has the "Re-runs busy" state, and options already re-run stay one click away.
- **Words:** the `words` fields match the language packs' `DecisionChoice`: `label`, `detail`, `world`, `plain` and `ring`.
- **Only real options.** Options come from the observed state, ranked by modelled value; never from the generator's own decision log.

### 6.3 Producer actions and the trace

- **Stand-in:** `decide`, `retract`, `queue` and `correct` in `web/src/lib/feed/store.ts`. Each one makes the resulting stream message itself, applies it, and shares it with other open tabs.
- **Proposed call:** `POST /api/matches/{match_id}/approvals`:

```json
{"overlay_id": "m07-o0247", "decision": "approve", "by": "producer", "note": ""}
```

`decision` is `approve`, `hold`, `skip` or `retract`. The backend answers by sending the result on the stream to everyone: an `overlay.upsert` with `rev + 1` and the new `approval`, or an `overlay.retract`. The console then sees its own decision come back like every other screen. Producer calls are never public: they need the `X-Producer-Token` header with the token `POST /api/live-runs` returned to whoever started the run (PRD 11.7). The frontend takes it from `?producer=`, sends its approvals with it, and adds it to the stream URL so the stream also carries the graphics waiting for approval.

- **The trace:** `GET /api/matches/{match_id}/overlays/{overlay_id}/trace` returns the steps behind one graphic. Its `rows` are what the console draws, `{agent, start, end, kind}`, with times in seconds after the moment was found and `kind` one of `ok`, `rejected`, `async` or `fallback`. On a live run the console reads it; otherwise `traceFor()` in `web/src/screens/ProducerConsole.tsx` stands in.
- **System health:** `GET /api/flags` lists the degrade flags and their latest changes, and `POST /api/matches/{match_id}/flags/{flag}/undo` (or `/keep`) is the producer's undo. The console's health panel still shows its static design; the Engineer's incident notes are `incident` envelopes in the match state.
- **Alerts:** a data alert becomes a `pending` overlay in the queue, as `store.queue()` shows.

### 6.4 Recaps and clips

- **Stand-in:** `RECAP_MOMENTS`, `autoPackage`, `publishRecap` and `useRecapPackage` in `web/src/lib/recap.ts`.
- **Proposed calls:**
  - `GET /api/matches/{match_id}/recaps/{halftime|fulltime}` returns the package and its moments, in the `RecapPackage` and `RecapMoment` shapes from `recap.ts`.
  - A producer's `PUT` on the same path publishes it.
  - A `recap.published` message on the stream tells open recaps to reload.
- **Clips:** the frontend plays `clips/{name}.mp4` with a poster at `clips/{name}.jpg`. A backend can return each clip's full URL in its recap moment instead.

### 6.5 Panel numbers and charts

- **Stand-in:** fixed numbers in the real shapes.
  - `web/src/lib/content.ts`: `LEADERS` (Space Created with 90% intervals) and `focusStats` (a player's tallies before and after the move, a season line, runs by type).
  - `web/src/lib/stats.ts`: `MOMENTUM`, `CONTROL_INDEX`, `SHOTS`, `SHAPE`, `PASS_NETWORK`, `occupancy` (heat map), `runMap` and `distanceSeries`.
- **Call:** `GET /api/matches/{match_id}/stats/{name}?period=&t_ms=&player_id=&from_ms=`, returning exactly those shapes, computed from the match up to `period` and `t_ms`. The names are `leaders`, `momentum`, `control_index`, `shots`, `shape` and `pass_network`, and per player `focus` (which also takes the moment's `from_ms`), `occupancy`, `run_map` and `distance_series`. `shots` answers 404 until the xG model is in place.
- **In the frontend:** `web/src/lib/served.ts` fetches each one up to the end of the showcase moment, and the stand-ins in `content.ts` and `stats.ts` return the computed value once it arrives (`focusStats` keeps its scripted season line, which the backend doesn't write). The momentum ribbon stays on the stand-in: the backend computes field tilt, not the ribbon's space value. Chart text equivalents are worded from the computed numbers, so they never claim a trend the data doesn't show.

### 6.6 Space Centre

- **Stand-in:** `MATCHDAY` in `web/src/lib/content.ts`: ten `MatchdayGame` records, each with a score, clock, moment type, value, caption and positions.
- **Proposed:** a stream for the round carrying moments ranked across matches. Positions should be in metres; see [note 4](#8-contract-notes).

### 6.7 Second-screen pairing

- **Stand-in:** `useHostCode`, `usePairHost` and `usePairGuest` in `web/src/lib/pairing.ts`, which pair tabs on one device. The messages are `hello`, `state` and `bye`. `state` carries `SharedState`: `t`, `playing`, `mode`, `lang`, `fav` and `at`.
- **Proposed:** a Web PubSub group per pairing code, which phones and screens join and send to (PRD 15.5). Keep the three messages unchanged. Codes last 2 hours and identify nobody.

### 6.8 Evaluation results

- **Stand-in:** sample results in `web/src/lib/stats.ts` (`FIDELITY`, `RELIABILITY`, `BENCH`, `BENCH_RUNS`) and `web/src/lib/eval.ts` (`GATES`, `TARGETS`). The screen labels them as sample data.
- **Proposed call:** `GET /api/eval/latest`, in those shapes. The frontend computes the statistics itself (`ks`, `ece`, `quantile` in `eval.ts`), so send the raw distributions and bins.

### 6.9 Voice

The frontend speaks captions with the device's own voices (`web/src/lib/audio.ts`). To use synthesised voices instead, a backend would send a playable audio file per line; see [note 5](#8-contract-notes).

---

## 7. Testing against the frontend without a backend

The frontend can show any output you write as a file, with no server and no code change.

1. **Write a JSONL file.** Use one message per line, following section 4, for match `m07` in the window from section 2. Copy frames from `web/public/feeds/showcase.jsonl` if you only want to change the AI's output.
2. **Put it next to the showcase feed,** for example `web/public/feeds/mine.jsonl`.
3. **Run the frontend.**

   ```bash
   cd web
   npm install
   npm run dev
   ```

4. **Open it** at `http://localhost:5173/#/match?feed=jsonl:/feeds/mine.jsonl`.
   - Change modes with keys 1 to 6, and the language from the header.
   - Press W for the what-if.
   - Press 6 for Broadcaster mode. Its panel is the producer's queue for your file, with approve, hold, skip and retract.
   - Open `/partner/index.html?feed=jsonl:/feeds/mine.jsonl` for the broadcast graphics as a partner would show them.

   Only the match view and the partner template read `?feed=`. The producer console (`#/producer`), the broadcast reference (`#/broadcast`) and the phone companion show the built-in replay.
5. **Check it against the contracts.** `web/tests/unit/contracts.spec.ts` validates every message of the showcase feed against `contracts/*.schema.json`. Point the same check at your file.
6. **Try it live.** The reference server streams the showcase over SSE and WebSocket in real time, and can simulate a stall:

   ```bash
   npm run feed:serve
   ```

   Open `http://localhost:5173/#/match?feed=sse:http://localhost:8787/sse`. Add `?speed=2` to the stream URL to play faster, or `?stall=2:4` to go quiet from 2 s to 6 s. A live stream of your own goes in the same `?feed=`.

What to look for:

| Check | Where |
| --- | --- |
| Graphics appear on their beats, hold long enough to read, and don't crowd | Each mode, playing at 1x |
| Every language reads correctly, Arabic right to left | The language menu |
| Live numbers update in labels (`{pts}`, `{m}`, `{speed}`) | Analyst mode |
| The what-if shows ghosts, a shut ring and its own captions | W, in Casual and Analyst |
| Pending graphics wait in the queue and appear once approved | Broadcaster mode's queue, then any other mode |
| A correction swaps the graphic with a Correction tag | Put a replacement upsert and an `overlay.retract` with `reason: "correction"` in your file |
| Nothing shows a number the data can't back | Analyst panel's evidence list |

---

## 8. Contract notes

Places where the frontend's formats differ from what a backend might assume. Send what the frontend reads.

1. **`frame` messages.** The frontend reads `{type: "frame", match_id, frame}` (`FrameMessage` in `web/src/lib/feed/types.ts`). The schema covers the frame itself (`contracts/tracked-frame.schema.json`), but there is no schema for the wrapper yet. The Python contracts in `offball/contracts/feed.py` leave it out of `PartnerMessage` too.
2. **Ghost track times.** The frontend reads a ghost's `data.track` as `[seconds after 63:00, x, y]`: moment time, as in section 2. The showcase sends, for example, `[[0, 84, 34], [9, 85, 35]]`. The Python `CounterfactualResult.ghost_tracks` uses `[t_ms, x, y]`, so convert with `t = (t_ms − 1,080,000) / 1000`. Changed-decision tracks in [6.2](#62-change-one-decision) are proposed in `t_ms` for when the frontend reads them from a call; whichever unit is chosen, use the same one in both places. The partner template currently reads ghost times relative to the graphic's own start, which still needs aligning.
3. **One overlay per mode.** `mode` is a single value, so each mode gets its own overlay. The same moment in six modes is six overlays, each with all its languages.
4. **Space Centre positions.** The stand-in's `MatchdayGame.gap` and `arrow` are in pitch drawing units (10 per metre). Send metres; the frontend would convert.
5. **No field for synthesised speech.** `speech[locale]` has `ssml` and `ssml_ref`, but no field for an audio file. The frontend would need an optional `audio_url` and a change to `audio.ts` to play it.

---

## 9. What the frontend needs for the backend

The frontend changes for the backend, all small and contained. With no backend set, every one falls back to the stand-in, so the demo never changes.

| Change | Where | Status |
| --- | --- | --- |
| One module for calls, each stand-in falling back to itself when a call fails, so components stay unchanged | `web/src/lib/api.ts` and `served.ts`; `content.ts`, `stats.ts`, `AskPanel.tsx` | Built for Ask OffBall and the panel numbers; `decisions.ts` and `recap.ts` still to do |
| An API address setting, next to `VITE_FEED_URL` | `VITE_API_BASE`, or `?api=` | Built |
| A Web PubSub connection that fetches its access URL first and refreshes it on reconnect, naming the viewer's language so the backend writes only the languages someone is watching (PRD 11.6) | A `negotiate:` kind in `web/src/lib/feed/sources.ts` | Not built: waits for Web PubSub |
| Producer actions sent to the backend instead of other tabs, with the producer token of the live run being produced (PRD 11.7) | `decide()` and `retract()` in `web/src/lib/feed/store.ts` | Built |
| The producer console and phone companion reading the same `?feed=` as the match view. The broadcast output stays a static reference design; the partner template is its live version. | `web/src/screens/ProducerConsole.tsx`, `PhoneCompanion.tsx` | Built for the console; the phone companion still to do |
| Loading the match, roster, clubs, kits and moment window from the backend, so any match can be shown | `web/src/lib/match.ts` and the code that reads it | Not built |
| Pairing over a Web PubSub group instead of between tabs | `web/src/lib/pairing.ts` | Not built: waits for Web PubSub |
| Playing synthesised speech when a line has it | `web/src/lib/audio.ts` | Not built |
| Removing the "answers are in English" note for languages the Pundit answers in | `web/src/components/ask/AskPanel.tsx` | Built for English, Spanish and French |

The default with no settings stays the built-in replay, so the demo always works (PRD 21.2). Every failure a backend can cause already has a designed state in the frontend (PRD 15.11, `#/states`). Map backend errors to these instead of new messages:

| Backend condition | What the frontend shows |
| --- | --- |
| No message for 2 s | Feed interrupted, then "Back in sync" |
| Re-runs or live runs busy (`429`) | Live runs busy, with the place in line |
| A claim that couldn't be checked | Couldn't verify |
| A question out of scope | The short refusal with a useful alternative |
| A retraction for a correction | The Correction tag |
| The backend can't be reached | The stand-in's answer, as in replay |

---

## 10. Checklist

Before calling a stream or answer ready for the frontend:

- [ ] It's for match `m07`, uses the roster's player IDs, and falls in the window in section 2.
- [ ] Every message validates against `contracts/*.schema.json`.
- [ ] `frame` arrives at 25 Hz while play is live, `clock.sync` at least once a second always, and `match.status` on every change.
- [ ] Every overlay has the right `kind` and `mode`, English `text` and `a11y_text`, `evidence_ids` and `labels`, and there is one overlay per mode.
- [ ] Graphics hold at least 2.5 s and arrive with time left to be seen.
- [ ] Changes reuse the `overlay_id` with a higher `rev`. A correction sends the replacement first, then the retraction.
- [ ] Graphics that need approval go out `pending`.
- [ ] Live numbers use `{pts}`, `{m}` or `{speed}`; every other number comes from computation on the match data.
- [ ] What-if parts share a `counterfactual_id`, and ghost tracks use the times in note 2.
- [ ] Nothing comes from `truth/` or an answer key.
- [ ] It looks right in every mode and language when loaded with `?feed=jsonl:` (section 7).
- [ ] For the window of a golden case, `offball golden check <case> --stream <file>` passes (PRD 19.5).
