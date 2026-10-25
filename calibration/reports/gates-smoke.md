# Quality gates: smoke

18 match(es). Thresholds are PRD 12.10's starting values.

| Gate | Status | What it found |
| --- | --- | --- |
| 1. Realism | fail | Outside: passes 1.01e+03 (real 5th–95th: 765.839–1174.83); median_pass_m 15.5 (real 5th–95th: 15.9817–19.7506); long_pass_share 0.189 (real 5th–95th: 0.1429–0.2675); shots 25.2 (real 5th–95th: 14.8808–31.2604); goals 2.41 (real 5th–95th: 0–5.0424); shots_in_box_share 0.487 (real 5th–95th: 0.387–0.75); possessions 243 (real 5th–95th: 211.502–309.004); fouls 16.2 (real 5th–95th: 13.5196–29.007); offsides 4.24 (real 5th–95th: 0.9747–7.9918); corners 4.96 (real 5th–95th: 4.9905–15.8026); throw_ins 52.6 (real 5th–95th: 29.0156–62.9388); running_share 0.109 (real 5th–95th: 0.1091–0.183); KS pass_length_m 0.103 (at most 0.1); KS shot_distance_m 0.104 (at most 0.1); KS player_peak_speed_kmh 0.279 (at most 0.1) |
| 2. Physics | fail | Over the limits: separation (2949 times) |
| 3. Consistency | pass | Events, tracking and the score agree. |
| 4. Behaviour | fail | behindrun 0.81 per 30 min on average (real average 2.426) |
| 5. Discriminator | fail | A classifier tells our windows from real ones with ROC AUC 0.989 (at most 0.65) on held-out matches; its strongest tells: speed_p90 (real 4.16, ours 3.823), accel_p90 (real 2.191, ours 2.478), nn_opp_mean (real 6.343, ours 7.904). |
| 6. Detectability | pass | 17 of 17 planted moments found from the data alone; 0 null moments credited. |
| 7. Novelty | pass | No real names, and no possession closer than 3.0 m on average to any of 20000 real ones. |
| 8. Diversity | pass | Closest pair of matches 0.82 interquartile ranges apart; 10 different scorelines. |
| 9. Determinism | pass | 126 files match their generation hashes. |
