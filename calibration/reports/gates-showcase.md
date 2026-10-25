# Quality gates: showcase

1 match(es). Thresholds are PRD 12.10's starting values.

| Gate | Status | What it found |
| --- | --- | --- |
| 1. Realism | fail | Outside: median_pass_m 15.3 (real 5th–95th: 15.9817–19.7506); possessions 196 (real 5th–95th: 211.502–309.004); fouls 12.5 (real 5th–95th: 13.5196–29.007); corners 4.82 (real 5th–95th: 4.9905–15.8026); throw_ins 70.3 (real 5th–95th: 29.0156–62.9388); running_share 0.107 (real 5th–95th: 0.1091–0.183); in_play_share 0.475 (real 5th–95th: 0.5091–0.5992); KS pass_length_m 0.101 (at most 0.1); KS shot_distance_m 0.184 (at most 0.1); KS player_km_per95 0.389 (at most 0.1); KS player_peak_speed_kmh 0.54 (at most 0.1) |
| 2. Physics | fail | Over the limits: decel (16 times), separation (918 times) |
| 3. Consistency | pass | Events, tracking and the score agree. |
| 4. Behaviour | fail | behindrun 0.60 per 30 min on average (real average 2.426) |
| 5. Discriminator | not run | Needs at least two matches with 10 Hz tracking, to hold one out. |
| 6. Detectability | pass | 2 of 2 planted moments found from the data alone; 0 null moments credited. |
| 7. Novelty | pass | No real names, and no possession closer than 3.3 m on average to any of 20000 real ones. |
| 8. Diversity | not run | Needs at least two matches in the set. |
| 9. Determinism | pass | 7 files match their generation hashes. |
