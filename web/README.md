# OffBall UI

Design tokens, components and screens for OffBall, built with React, TypeScript and Vite. Every screen reads the same contract feed for the same synthetic showcase match: Kestrel Bay's 63rd-minute decoy-run goal against Ashmoor.

The design spec is `../PRD.md`, sections 15 (experience) and 16 (visualization and motion). The original design canvas sources are in `../design/canvas/`. Message shapes follow `../contracts/`.

Building a backend or AI to drive this frontend? `../INTEGRATION.md` says what the frontend reads, what the AI writes for each screen, and how to test output against the UI with a JSONL file and no server.

## Run it

```bash
npm install
npm run dev
```

Then open http://localhost:5173. `npm run build` type-checks and builds to `dist/`.

## Test it

```bash
npm run check               # type-check the app and tests, lint tokens, then unit, browser and visual tests
npm run test:perf           # performance budgets (PRD 16.7); run on its own, since other work on the machine skews it
npm run test:visual:update  # refresh screenshot baselines after an intended visual change, then review the diff
npm run clips               # re-render the tier D clips and the share clip (needs ffmpeg and Chrome)
npm run feed:export         # write public/feeds/showcase.jsonl, the showcase feed in the partner JSONL format
npm run feed:serve          # a local live feed on :8787: /sse, /ws, /showcase.jsonl (?speed=2, ?stall=2:4)
```

Browser tests run against a production build served on port 4180, in Google Chrome. To use Playwright's own Chromium instead, run `npx playwright install chromium` and set `PW_CHANNEL=bundled`.

| Folder | What it checks |
| --- | --- |
| `tests/unit` | Every feed message against `../contracts` (JSON Schema 2020-12, with Ajv); the feed store's revisions, retractions and late drops; frame interpolation; the control field and contours; contrast and every fixture's kit check; label layout; easing; the evaluation statistics (KS, calibration error, frame reports) |
| `tests/e2e` | Every route in every theme with axe (WCAG 2.2 AA) and a clean console; the pitch's keyboard and pointer access; the drawer's focus trap; shortcuts; Arabic; phone portrait; feed stall and recovery; Ask OffBall; producer approvals and corrections across tabs; captions in every language and mode; the 3D views and fallbacks; offline; recaps (halftime, spoiler-safe, the producer's curated recap reaching open tabs); snapshots as PNG and SVG in every tier; Change one decision from picking a player to its result; the evaluation screen, its labels and its frame-time test in 2D and 3D |
| `tests/visual` | Screenshot baselines at fixed moments with reduced motion, per platform (`__screenshots__/*-win32.png`) |
| `tests/perf` | Frame time p95 counted in display frames, calibrated on an empty page (none dropped at 1x CPU, at most one at 4x, which is the 33 ms tier C budget at 60 Hz); first frame within 2 s; no heap growth over 10 s of playback; initial JavaScript 300 KB or less compressed |

`npm run lint:tokens` (`scripts/check-tokens.mjs`) fails on any colour, duration or easing outside `tokens.css`. Mark a deliberate exception with `tokens-ok: <reason>` on the line.

## Screens

| Route | Screen |
| --- | --- |
| `#/` | Index of every screen, theme and reduced-motion switches (every screen also ends with a footer for jumping to any other) |
| `#/match` | Match view: six modes, the 2D pitch or four 3D cameras (broadcast, tactical, player cam, behind the goal), control field with contours, "what if" overlaid or side by side, Change one decision, adaptive density (an Overlays menu on the pitch that remembers what you hide, per mode), captions and voice in ten languages, replay controls, snapshots, keyboard shortcuts, Ask OffBall, phone pairing, Personalize drawer, simulated feed stall and slow device |
| `#/phone` | Second-screen companion: pairs by code or QR, follows the main screen's clock, Ask OffBall |
| `#/onboarding` | First run, with a live preview drawn by the real renderer |
| `#/space-centre` | Ten-match whip-around with colour-checked kits |
| `#/broadcast` | 1080p broadcast output with safe areas and a key output, and the partner template below it |
| `/partner/index.html` | The partner graphics template: one HTML file for OBS (Browser Source) and CasparCG (HTML template), reading the overlay protocol from a JSONL replay, SSE or WebSocket. Options: `feed`, `lang`, `approvals`, `speed`, `loop`, `autoplay`, `safe`, `key`; CasparCG's `play`, `stop`, `next` and `update` |
| `#/producer` | Producer console: decisions, traces, corrections, decision log, and the recap builder |
| `#/recap` | Halftime and full-time recaps: the top space moments as diagrams, the Space Created leaderboard and shot map, the vertical clip, and player cards, spoiler-safe on request (`?kind=halftime` or `fulltime`) |
| `#/eval` | Evaluation: the synthetic data against real football (distributions and the nine quality gates), the models against what happened (reliability diagrams and Brier scores), the agents against OffBall-Bench (versions, baselines, release history and the PRD 19.2 targets), and a frame-time test on the viewer's device |
| `#/components` | Every component, live |
| `#/visual-language` | Tokens for every theme, colour-vision and kit checks, ramps, type, overlay grammar |
| `#/motion` | Motion principles, tokens and micro-interaction demos |
| `#/states` | System states |
| `#/clip` | The stage alone at an exact size, stepped frame by frame by `npm run clips` (options: `view`, `w`, `h`, `captions=1`) |

Options after `?` in the hash: `#/match?t=4.5` opens paused at a moment time (for tests and links), `?state=loading` or `?state=offline` previews those states, `?feed=sse:URL`, `?feed=ws://…` or `?feed=jsonl:/path` reads a live or recorded feed (try `#/match?feed=sse:http://localhost:8787/sse` with `npm run feed:serve`, or `?feed=jsonl:feeds/showcase.jsonl`), and `#/phone?pair=CODE` pairs a phone.

## How it works

- **The feed.** `lib/feed/emitter.ts` turns the scripted moment into contract messages (25 Hz `frame`s, `overlay.upsert`, `clock.sync`, `match.status`) with text, speech and accessible text in every language. It stands in for the backend; every renderer reads the messages, never the script. `lib/feed/store.ts` keeps rev-aware overlays and retractions, drops late overlays in live mode, and publishes producer decisions on a `BroadcastChannel`, so they reach every open tab.
- **One clock.** `useMatchClock` drives every layer. Replay runs from 0.25x to 60x with frame steps and moment jumps; live follows `clock.sync` 1.5 s behind the newest data and holds the last frame when data stops. `lib/frame-loop.ts` runs one `requestAnimationFrame` for the whole app: the clock moves first, then every renderer draws that instant. Renderers read `clock.now()` each frame; React hears about the clock ten times a second (as a transition), so text and panels never hold up a frame.
- **Frames and the field.** Positions are interpolated from 25 Hz frames with cubic Hermite curves. Control fields are computed per frame in a Web Worker and blended for display frames; contours at 25, 50 and 75% are drawn so the field reads without colour.
- **Tier C, the 2D view.** `components/match/Stage2D.tsx` draws with Canvas 2D (`components/pitch/render2d.ts`): the field, contours (traced once per 25 Hz data frame), rings, runs, passes, ghosts, players and ball, with every entrance built from the motion tokens. Text stays in the DOM above the canvas: labels are positioned each frame by transform only, laid out to avoid each other and the players, and each player is a focusable button for keyboards and screen readers. The SVG components in `components/pitch/overlays.tsx` draw the same grammar for the galleries.
- **Tiers A and B, the 3D views.** `three/scene3d.ts` builds the scene with Babylon.js and loads only when a 3D view is picked, so it adds nothing to the first frame. Four cameras: a broadcast gantry that pans and zooms to keep the ball and whatever the graphics are about in shot, a high tactical view, a player cam behind the followed player, and a view from behind the goal. The overlay grammar is painted onto the grass by the same Canvas 2D renderer as the 2D view, and `components/match/Stage3D.tsx` places the same DOM labels and focus targets by projecting each anchor every frame. Tier A runs on WebGPU and computes the control field per pixel on the GPU from the 22 positions (in WGSL, so nothing is fetched to compile shaders); tier B runs on WebGL2 and shows the worker's field as a texture. Players are stylised figures animated from speed and heading. With reduced motion the cameras cut instead of gliding.
- **Tier D, the recorded clip.** `components/match/StageVideo.tsx` plays a clip of the moment with its graphics burned in, kept in step with the match clock (playback rate up to 4x, frame seeks beyond), while the caption bar stays live text in the viewer's language. It covers replays, not live matches. `npm run clips` renders the clips from the real renderer: `scripts/render-clips.mjs` steps the `#/clip` route frame by frame in Chrome (the scene, the camera and the labels' CSS entrances all follow the clip's own timeline, so every frame is exact) and pipes the frames to ffmpeg, writing `public/clips/` with a poster for each. The same script makes the vertical share clip, with the caption burned in. Without scripts, `index.html` shows a static recap with the clip.
- **Rendering tiers.** `lib/tiers.ts` probes the device, monitors frame times and steps down a tier after 2 s over budget (A to B to the 2D view to the clip), and back up after 10 s of headroom. If a 3D view can't start or loses its GPU, the 2D view takes over for the session and says so. The Slow device switch in the match view adds about 45 ms of work a frame, to show the steps down.
- **Installable and offline.** `public/manifest.webmanifest` and `public/icons/` (drawn by `scripts/make-icons.mjs`) make the app installable. The build emits `sw.js` (`src/pwa/sw.js`, with the shell list added by `vite.config.ts`): the app shell is cached on install, so the app opens with no network; charts and the 3D view are cached the first time they're used; live feeds and video are never cached. A new version waits for the viewer to choose Reload. A live feed keeps its last 10 minutes on the device (IndexedDB); opened offline, the match view replays those minutes and goes live again when the feed reconnects (PRD 15.11).
- **Languages.** `lib/i18n/` holds a pack per language: captions for every mode, Player focus stories, glossary and core UI text. Everything except English is a draft awaiting review by native-speaking fans, and the app says so. Arabic sets `dir="rtl"`; the pitch and timelines stay left to right.
- **Charts.** Panel and report charts are Vega-Lite specs themed from the tokens and loaded on demand; pitch-anchored charts use the pitch renderer. Match charts colour their series by club; charts of measures that aren't about a club (the evaluation charts) use the accent and a neutral, so a club's colour never stands for something else. Every chart has a text summary, a table view and CSV, SVG and PNG exports labelled synthetic and AI-generated, and keeps its own accessible name.
- **Snapshots.** Snapshot in the replay bar (or `S`) saves what the pitch shows now, about 1920 pixels across, with a footer: the export label, the match clock, the mode and the score. Each stage makes its own picture (`components/pitch/snapshot.ts`): the 2D view draws the moment again as a still, every graphic fully drawn, and paints the DOM labels where they are; the 3D view draws its scene again and copies it in the same task, so the copy never depends on the drawing buffer; the clip copies its current frame. In 2D, SVG keeps the markings, shapes, shirt numbers and labels as vectors (the renderer draws into a small SVG recording context instead of a canvas), with only the control field as an image. The side-by-side what-if saves both sides in one picture.
- **Change one decision.** The replay bar's Change a decision button, or `D`, opens a panel in the side panel's place (the bottom sheet on phones; `D` or Escape closes it). Pick one of three players (on the pitch, where they wear a dashed ring, or in the list), choose what they do instead, and re-run the moment 32 times. `lib/decisions.ts` holds each option's changed tracks, its modelled value and the Tactician's precomputed result, standing in for `run_counterfactual`; each language pack's `decide` holds the words. While choosing, the pitch previews the change: the real path faint, the changed one dashed, a dashed ring where a player holds. The result plays the changed world, with ghosts, its own control field (computed like any other from the changed tracks) and a ring, beside a table of what happened against the change, and can go side by side. Analyst adds each option's value and rank, intervals and xG, in English like the rest of its panel.
- **Evaluation.** `lib/eval.ts` works out every statistic on the evaluation screen from the data it shows, as the CI gate reports and Foundry evaluation runs will: the two-sample Kolmogorov–Smirnov statistic against the realism gate's 0.10, expected calibration error (space value must be 0.02 or less), and each model's Brier gain over its baseline. The data is sample data until those runs publish, drawn so the charts show distributions rather than the luck of a small draw, and every chart and table says so. Human studies that haven't run show as not run, not as numbers. The frame-time test is real: it plays the moment in Analyst mode in the 2D or 3D view, records 4 seconds of frames through the app's own frame loop, and reports the 95th-percentile frame time, dropped frames and the loop's own work against the tier's budget. Its results stay on the page.
- **Recaps.** `lib/recap.ts` holds the match's top space moments, each told twice: with its result, and spoiler-safe. Until the producer publishes, a recap is the period's moments, biggest space first; the recap builder in the producer console picks the moments, orders them and can make the recap spoiler-safe, and publishing reaches every open recap at once (`localStorage` and a `BroadcastChannel`). The halftime recap knows nothing of the second half: its leaderboard and shot map stop at 45 minutes, and cards and the clip wait for full time. Player cards (`lib/cards.ts`) are 1080 × 1350 PNGs drawn in the dark theme, with their text as alt text; share uses the Web Share API where the device has it, and downloads otherwise.

## Structure

```text
src/
  styles/        tokens.css (themes: dark, light, contrast, broadcast, print; motion tokens), motion.css (keyframes, designed reduced motion), base.css, components.css
  lib/           match.ts, field.ts, frame-loop.ts, feed/ (emitter, store, sources, clock, frames, field worker), i18n/ (ten language packs, pitch labels),
                 prefs.tsx, tiers.ts, audio.ts, pundit.ts, pairing.ts, kits.ts, color.ts, glossary.ts, stats.ts, export.ts, motion.ts, hooks.ts,
                 recap.ts, cards.ts, pwa.ts, eval.ts
  three/         scene3d.ts: the 3D scene, cameras and GPU control field (tiers A and B), loaded on demand
  components/
    ui/          Button, Switch, Segmented, Chip, Live indicators, Skeleton and Toasts, CountUp, CaptionReveal, Drawer and Dialog, BottomSheet,
                 Stepper, Card, Logo, QrCode, ErrorBoundary
    pitch/       Pitch (horizontal and vertical), render2d (the tier C canvas renderer), PitchLayer (labels and focus targets for
                 every view), label layout, snapshot (PNG and SVG exports), and the SVG grammar
                 (ControlField and Contours, PlayerLayer, OverlayLayer, overlays) used by the galleries
    charts/      ChartFrame, VegaChart and specs, PitchCharts, MomentumRibbon, Sparkline, Leaderboard, BarList, AgentTrace
    match/       Stage2D, Stage3D, StageVideo, Scoreboard, ModeSwitcher, ReplayBar, CaptionBar, mode panels, PersonalizeDrawer, PairDialog, ShortcutsDialog, LiveRegion
    recap/       MomentDiagram, RecapBuilder
    ask/         AskPanel
  screens/       One file per route
tests/           unit/, e2e/, visual/ (with __screenshots__ baselines), perf/, and helpers.ts with the shared fixtures
scripts/         check-tokens.mjs (the token lint), render-clips.mjs (tier D and share clips), export-feed.mjs and
                 feed-server.mjs (the JSONL feed and a local live feed), make-icons.mjs
public/          favicon.svg, manifest.webmanifest, icons/, clips/ (rendered clips and posters), feeds/showcase.jsonl
```

## Settings

- `VITE_FEED_URL`: a live feed to read by default (same forms as `?feed=`).
- `VITE_FABRIC_DASHBOARD_URL`: the Fabric Real-Time Dashboard link in the producer console.

## Rules the code follows

- Every colour, duration and easing comes from `tokens.css`. Themes switch by `data-theme` on `<html>`.
- Animations use transform and opacity, and only live indicators loop. The one exception is the caption reveal's unblur, which PRD 16.10 asks for.
- Reduced motion is a designed mode: it follows the OS setting or the in-app switch (`data-motion="reduced"`), turning movement into fades and loops into steady dots.
- Preferences, the Learn glossary, producer decisions and published recaps stay in the browser (`localStorage`, guarded); nothing identifies the viewer.
- All match data is synthetic, every caption and answer is labelled AI-generated, and anything not built yet is labelled rather than mocked as working.
