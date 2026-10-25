# Quality gates: smoke

18 match(es). Thresholds are PRD 12.10's starting values.

| Gate | Status | What it found |
| --- | --- | --- |
| 1. Realism | fail | Outside: passes 897 (real 5th–95th: 765.839–1174.83); completion 0.756 (real 5th–95th: 0.7437–0.8634); median_pass_m 15.2 (real 5th–95th: 15.9817–19.7506); long_pass_share 0.229 (real 5th–95th: 0.1429–0.2675); shots 18.3 (real 5th–95th: 14.8808–31.2604); shots_in_box_share 0.454 (real 5th–95th: 0.387–0.75); possessions 244 (real 5th–95th: 211.502–309.004); fouls 27.1 (real 5th–95th: 13.5196–29.007); offsides 3.9 (real 5th–95th: 0.9747–7.9918); corners 4.4 (real 5th–95th: 4.9905–15.8026); throw_ins 52.9 (real 5th–95th: 29.0156–62.9388); KS pass_length_m 0.105 (at most 0.1); KS shot_distance_m 0.217 (at most 0.1); KS player_km_per95 0.211 (at most 0.1); KS player_peak_speed_kmh 0.297 (at most 0.1) |
| 2. Physics | fail | Over the limits: separation (1742 times) |
| 3. Consistency | pass | Events, tracking and the score agree. |
| 4. Behaviour | fail | behindrun 0.89 per 30 min on average (real average 2.426) |
| 5. Discriminator | fail | A classifier tells our windows from real ones with ROC AUC 0.998 (at most 0.65) on held-out matches; its strongest tells: accel_p90 (real 2.191, ours 3.926), nn_opp_mean (real 6.343, ours 7.376), accel_mean (real 1.033, ours 1.468). |
| 6. Detectability | pass | 17 of 17 planted moments found from the data alone; 0 null moments credited. |
| 7. Novelty | pass | No real names, and no possession closer than 2.8 m on average to any of 20000 real ones. |
| 8. Diversity | pass | Closest pair of matches 0.95 interquartile ranges apart; 6 different scorelines. |
| 9. Determinism | pass | 126 files match their generation hashes. |
