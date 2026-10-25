# Quality gates: calib

10 match(es). Thresholds are PRD 12.10's starting values.

| Gate | Status | What it found |
| --- | --- | --- |
| 1. Realism | fail | Outside: completion 0.782 (real 5th–95th: 0.7437–0.8634); median_pass_m 16.2 (real 5th–95th: 15.9817–19.7506); possessions 233 (real 5th–95th: 211.502–309.004); corners 7.21 (real 5th–95th: 4.9905–15.8026); throw_ins 56.4 (real 5th–95th: 29.0156–62.9388); running_share 0.108 (real 5th–95th: 0.1091–0.183); KS player_km_per95 0.117 (at most 0.1); KS player_peak_speed_kmh 0.364 (at most 0.1) |
| 2. Physics | fail | Over the limits: separation (9274 times) |
| 3. Consistency | pass | Events, tracking and the score agree. |
| 4. Behaviour | fail | behindrun 0.93 per 30 min on average (real average 2.426) |
| 5. Discriminator | fail | A classifier tells our windows from real ones with ROC AUC 0.991 (at most 0.65) on held-out matches; its strongest tells: nn_opp_mean (real 6.261, ours 8.358), speed_p90 (real 4.123, ours 3.68), accel_p90 (real 2.186, ours 2.438). |
| 6. Detectability | not run | No answer keys with detectable moments. |
| 7. Novelty | pass | No real names, and no possession closer than 2.6 m on average to any of 20000 real ones. |
| 8. Diversity | pass | Closest pair of matches 0.71 interquartile ranges apart; 10 different scorelines. |
| 9. Determinism | pass | 70 files match their generation hashes. |
