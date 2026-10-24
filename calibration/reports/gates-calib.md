# Quality gates: calib

10 match(es). Thresholds are PRD 12.10's starting values.

| Gate | Status | What it found |
| --- | --- | --- |
| 1. Realism | fail | Outside: median_pass_m 16.1 (real 5th–95th: 15.9817–19.7506); long_pass_share 0.178 (real 5th–95th: 0.1429–0.2675); goals 3.57 (real 5th–95th: 0–5.0424); shots_in_box_share 0.546 (real 5th–95th: 0.387–0.75); possessions 218 (real 5th–95th: 211.502–309.004); offsides 0.791 (real 5th–95th: 0.9747–7.9918); corners 7.83 (real 5th–95th: 4.9905–15.8026); throw_ins 44.7 (real 5th–95th: 29.0156–62.9388); running_share 0.192 (real 5th–95th: 0.1091–0.183); KS shot_distance_m 0.201 (at most 0.1); KS player_peak_speed_kmh 0.127 (at most 0.1) |
| 2. Physics | fail | Over the limits: accel (563 times), separation (3630 times) |
| 3. Consistency | pass | Events, tracking and the score agree. |
| 4. Behaviour | fail | behindrun 1.14 per 30 min on average (real average 2.426) |
| 5. Discriminator | not run | Needs SkillCorner's tracking files (about 89 MB a match, in Git LFS), not downloaded yet. |
| 6. Detectability | not run | No answer keys with detectable moments. |
| 7. Novelty | pass | No real names, and no possession closer than 3.4 m on average to any of 20000 real ones. |
| 8. Diversity | pass | Closest pair of matches 1.03 interquartile ranges apart; 10 different scorelines. |
| 9. Determinism | pass | 70 files match their generation hashes. |
