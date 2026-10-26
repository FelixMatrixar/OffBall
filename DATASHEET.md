# Datasheet: the OffBall synthetic football data

Following *Datasheets for Datasets* (Gebru et al., 2021). Covers every set the generator produces (PRD 12.11).

## Motivation

**Why was it made?** To measure whether an AI system can find the off-ball moments that create chances, explain them and prove their cause. That needs the true answer for every moment: who meant to do what, what happened, and what would have happened otherwise. Real data can't give that, and the hackathon rules (4.7, 7) require synthetic data that can be licensed commercially.

**Who made it?** The OffBall team, with the OffBall generator in this repository.

## Composition

**What is in it?** Football matches between the 20 fictional clubs of the OffBall League, each a set of files in the contracts of `contracts/`:

| File | Contents | Who may read it |
| --- | --- | --- |
| `match.json` | Clubs, line-ups, kits, attacking direction per period, final score | Everyone |
| `events.jsonl` | Every ball event: passes, carries, shots, tackles, fouls, restarts; time, player, metres, outcome | Everyone |
| `tracking.parquet`, `tracking_10hz.parquet` | x, y and body orientation of every player and the ball at 25 Hz, and a 10 Hz copy | Everyone |
| `answer_key.json` | Planted and oracle-labelled moments, the signals each should leave, the generator's measurements, counterfactual truth | The evaluator only |
| `intents.jsonl` | Every decision every player made, with its utility | The evaluator only |
| `probabilities.jsonl` | The true success chance of every pass and shot | The evaluator only |

Fast-engine matches (the season backdrop) have `match.json` and `events.jsonl` only.

**The sets:**

| Set | Matches | What | Where |
| --- | --- | --- | --- |
| Showcase | 1 | Kestrel Bay v Ashmoor, the demo match | Committed |
| Smoke | 18 short | Every one of the 18 moment types planted at least once, one moment a match | Committed |
| Calibration runs | 10+ full | Unscripted, for the realism and discriminator gates | Regenerated (`offball match --set calib`) |
| Showcase matchday | 10 full | One round played together: the showcase match, and nine that each plant one moment around the hour; oracle labels | Blob Storage (`offball matchday`) |
| Golden render tests | 8 stretches | About 30 s around one planted moment each, from the showcase and smoke sets: the feed as input, and what the pipeline's output must show (PRD 19.5) | Committed (`offball golden build`) |
| OffBall-Bench | 100 full | 70 with 3–6 planted moments, 20 with only null moments, 10 unscripted; 40 dev, 60 test | Blob Storage (`offball bench`) |
| Season backdrop | 380, events only | The whole season from the fast engine, with its table | Blob Storage (`offball season`) |

**Is anything real in it?** No. Every club, player, name, badge and kit is generated, and names are checked against a salted-hash blocklist of real names from the calibration sources (gate 7). No row of real data is copied: the generator's settings are fitted to real matches and only those numbers are kept (`calibration/targets.json`, `calibration/params.json`, `calibration/fast_engine.json`).

**Labels.** Planted moments come from the Match director's scripts: the engine is asked for a moment with soft constraints, plays it, and keeps it only if its signals verify and re-runs with and without the creator's decision show the creator caused it. Oracle labels mark moments the players made on their own: the decision log names the participants and the detectors' signal definitions confirm the moment. Oracle labels carry no counterfactual. Null moments look like real ones but create nothing; any credit a system gives them counts as invented.

## Collection process

**How was it generated?** The emergent engine plays 22 policy-driven players at 25 Hz; the fast engine samples ball events from a ball-flow model fitted to real matches. Both are seeded: the same seed and generator version give byte-identical files on any machine (gate 9). Settings were tuned in eight Optuna stages against targets fitted from:

- Wyscout's English first division 2017/18, 380 matches (Pappalardo et al., 2019; CC BY 4.0): event rates, pass lengths, shot locations, the fast engine's ball flow.
- SkillCorner's A-League 2024/25 open data (MIT): physical output, speed bands, peak speed, ball-in-play time, run rates, and broadcast tracking for the discriminator and the tracking bands (acceleration, turning, spacing and players in view).

See `ATTRIBUTION.md`.

## How real is it

Measured by the nine quality gates (`offball gates <set>`, reports in `calibration/reports/`; PRD 12.12 has the figures). On 16 full matches every per-match average sits inside the real 5th–95th range except running at 15–20 km/h, just below it, and players' acceleration and turning through a broadcast camera match real tracking. Known gaps:

- Players stand too close to each other more often than real players (gate 2).
- A classifier can still tell 10 s of our tracking from SkillCorner's broadcast tracking (gate 5, ROC AUC 0.99): our players stand about 2 m further from their nearest opponent, and fewer of them are in view.
- Players make fewer runs in behind than real ones (gate 4), and their peak speeds run a little high.
- Some moments are hard to plant: in the pairings tried, the decoy run verified in 4 of 12, the cover shadow in 2 of 6 and the set-piece screen in 2 of 7.

## Models trained on it

The pass difficulty and xG models (`offball/models/`) learn from observed outcomes only, and are scored against the generator's true probabilities on matches they never trained on (`calibration/reports/models.md`, regenerated by `uv run python -m offball.models.train`):

- **Pass difficulty** trains on the smoke set's 3,398 passes and is tested on the showcase's 911. Its Brier score against the true completion probabilities is 0.016, 23% better than a model of pass length alone (PRD 19.2 asks for 10%). It reads only what is known as the ball is struck; a failed pass's end point is where it was cut out, so using it makes the probabilities overconfident.
- **xG** trains on the season backdrop's 9,490 shots and is tested on the showcase and smoke shots (108). It only matches its distance-and-angle baseline (Brier 0.0201 each), short of the 10% target: the season has events but no tracking, and its shots never record pressure or set pieces, which drive the generator's own chances. Shots with tracking from OffBall-Bench would close this.
- **Auto-eventing from tracking** finds passes with F1 0.86 and shots with F1 0.88 on the smoke set, against targets of 0.95 and 0.97.

## Uses

**Intended:** testing and benchmarking off-ball moment detection, explanation and counterfactual reasoning; the OffBall demo; agent evaluation.

**Not intended:** drawing conclusions about real players, clubs or leagues; training models meant to judge real players.

## Distribution and maintenance

The small sets are in this repository; the large ones are regenerated from their seeds and published to Azure Blob Storage, with OneLake shortcuts. Dev answer keys are public; test answer keys are held by the evaluation endpoint. The generator version is in every `match.json`; a change to the generator that changes files changes the version.
