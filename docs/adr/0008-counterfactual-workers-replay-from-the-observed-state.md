# 8. Counterfactual workers replay from the observed state and free only the decision's players

Date: 27 October 2026. Status: accepted; off-ball credit's target is still open.

## Context

ADR 0005 has ghost players come from the counterfactual workers' engine re-runs rather than a learned ghosting model, and PRD 12.9 has those re-runs start from the observed state (tracking and events), never the generator's hidden state, so they estimate credit as they would on real data. PRD 19.2 asks for off-ball credit within 25% of the generator's true credit on 80% of planted moments, with a rank correlation of 0.8.

The generator measures its true credit by re-running a planted moment from its own checkpoint, with and without the creator's decision, while the moment's plan choreographs the other actors: whether the dragged defender follows, who receives and when (`offball.generator.moments`). Its re-runs know every hidden attribute and intent.

## Decision

- `offball.models.counterfactual` seeds the engine from the observed frame: every player's position and velocity, the ball, the score and each side's direction. Line-ups come from the published league; substitutes take the slots their side's starters left. Each player's top speed is the fastest his smoothed tracking has shown before the moment, and every other attribute and both clubs' styles take league-typical values. Nothing hidden is read.
- A replay starts at the first frame within 2 s of the moment's start where a player has the ball, because a ball in flight carries a pass plan the tracking doesn't show; otherwise the nearest player of the side in possession gets it.
- "With the decision" is what happened. "Without it" is 16 replays in which the creator makes the moment type's alternative (he holds his place in the shape after a run, rotation, screen or cover; comes inside instead of holding the touchline for a switch of play; drops towards the ball for a broken press or a pin) and the defenders he pulled are free to react; everyone else, and the ball, replay as tracked.
- The gap zone is measured with `control_fast`, the model the generator measures its truth with, at the pass into the gap (or about 3 s in). Space Created is what happened minus the median replay, with a 90% interval from resampling; Threat Created weights the same by space value; the creator's median path without his decision is the ghost.
- The smoke moments chose the design; the matchday and showcase moments were scored once (`calibration/reports/models.md`).

## What the experiments showed

| Design, on the development moments | Within 25% | Rank correlation |
| --- | --- | --- |
| Only the creator and the defenders he pulled free; with the decision is what happened (chosen) | 20% | 0.80 |
| Every defender free in both replays, the creator tracked in one and making the alternative in the other | 27% | 0.50 |
| As chosen, with the engine's shape anchored to where each player stood | 0% | 0.57 |
| As the second, with the shape anchored | 13% | 0.58 |

On the test moments the chosen design scores 30% within 25% and a rank correlation of 0.48; the simpler observed-tracking estimate (`offball.models.credit`) scores 40% and 0.64 on the same moments. Both reach about the target's rank on off-ball runs (0.78 and 0.70 across all of them) but not its 25% band, and neither handles the moments whose creator's decision isn't a run.

The more of a moment the engine plays, the further it drifts: from observed state and league-typical attributes, its free defenders don't follow runs as the real ones did, and the generator's truth depends on its plans' choreography of the other actors.

## Consequences

- Off-ball credit's numbers stay with the observed-tracking estimate (`space_created_by_m2`, `threat_created`) until replays beat it on the test moments. Credit's target in PRD 19.2 isn't met.
- The workers supply what only replays can: the ghost path for what-if replays, intervals, whether the gap opens anyway, and the machinery Change one decision and the Tactician will drive. They run in process; the `cf-workers` service and its process pool (PRD 11.4) come with the Tactician. Sixteen replays of a moment take about a second.
- The promising next step is choreography: replaying each moment type the way the generator's plans do, so the defender who was dragged is steered to follow in one replay and not in the other, and the receiver keeps his timing, from the observed state. On real data that choreography is the moment type's definition, which the detectors already supply.
