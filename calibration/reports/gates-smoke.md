# Quality gates: smoke

6 match(es). Thresholds are PRD 12.10's starting values.

| Gate | Status | What it found |
| --- | --- | --- |
| 1. Realism | fail | Outside: completion 0.768 (real 5th–95th: 0.7437–0.8634); median_pass_m 15.7 (real 5th–95th: 15.9817–19.7506); long_pass_share 0.18 (real 5th–95th: 0.1429–0.2675); shots 20.3 (real 5th–95th: 14.8808–31.2604); goals 2 (real 5th–95th: 0–5.0424); shots_in_box_share 0.717 (real 5th–95th: 0.387–0.75); possessions 241 (real 5th–95th: 211.502–309.004); fouls 18.2 (real 5th–95th: 13.5196–29.007); offsides 0 (real 5th–95th: 0.9747–7.9918); corners 5.45 (real 5th–95th: 4.9905–15.8026); throw_ins 57.3 (real 5th–95th: 29.0156–62.9388); running_share 0.194 (real 5th–95th: 0.1091–0.183); KS shot_distance_m 0.423 (at most 0.1); KS player_peak_speed_kmh 0.367 (at most 0.1) |
| 2. Physics | fail | Over the limits: accel (23 times), separation (376 times) |
| 3. Consistency | pass | Events, tracking and the score agree. |
| 4. Behaviour | pass | Run rates sit within the real range. |
| 5. Discriminator | not run | Needs SkillCorner's tracking files (about 89 MB a match, in Git LFS), not downloaded yet. |
| 6. Detectability | pass | 4 of 4 planted moments found from the data alone; 0 null moments credited. |
| 7. Novelty | pass | No real names, and no possession closer than 2.4 m on average to any of 20000 real ones. |
| 8. Diversity | pass | Closest pair of matches 1.70 interquartile ranges apart; 5 different scorelines. |
| 9. Determinism | pass | 42 files match their generation hashes. |
