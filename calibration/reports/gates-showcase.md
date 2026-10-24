# Quality gates: showcase

1 match(es). Thresholds are PRD 12.10's starting values.

| Gate | Status | What it found |
| --- | --- | --- |
| 1. Realism | fail | Outside: fouls 34.9 (real 5th–95th: 13.5196–29.007); km_per_outfield 9.55 (real 5th–95th: 9.58–12.2488); hsr_share 0.208 (real 5th–95th: 0.0428–0.0973); running_share 0.227 (real 5th–95th: 0.1091–0.183); sprint_share 0.039 (real 5th–95th: 0.0059–0.0282); in_play_share 0.604 (real 5th–95th: 0.5091–0.5992); KS shot_distance_m 0.229 (at most 0.1); KS player_km_per95 0.478 (at most 0.1); KS player_peak_speed_kmh 0.597 (at most 0.1) |
| 2. Physics | fail | Over the limits: accel (155 times), separation (813 times) |
| 3. Consistency | pass | Events, tracking and the score agree. |
| 4. Behaviour | fail | behindrun 0.87 per 30 min on average (real average 2.426) |
| 5. Discriminator | not run | Needs SkillCorner's tracking files (about 89 MB a match, in Git LFS), not downloaded yet. |
| 6. Detectability | pass | 2 of 2 planted moments found from the data alone; 0 null moments credited. |
| 7. Novelty | pass | No real names, and no possession closer than 2.6 m on average to any of 20000 real ones. |
| 8. Diversity | not run | Needs at least two matches in the set. |
| 9. Determinism | pass | 7 files match their generation hashes. |
