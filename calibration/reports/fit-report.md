# Calibration fit

Fitted 2026-10-25 from 380 real matches and season aggregates. Only these fitted numbers are kept; the raw sources stay out of the repository (PRD 12.2).

## Per-match targets (both teams, per 95 minutes)

| Metric | Mean | 5th | 25th | Median | 75th | 95th | Source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| passes | 949.006 | 765.839 | 865.928 | 935.579 | 1024.25 | 1174.83 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| completion | 0.8081 | 0.7437 | 0.7857 | 0.8107 | 0.8336 | 0.8634 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| median_pass_m | 17.8027 | 15.9817 | 17.0544 | 17.8427 | 18.6363 | 19.7506 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| long_pass_share | 0.2038 | 0.1429 | 0.1782 | 0.2046 | 0.2283 | 0.2675 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| shots | 23.0898 | 14.8808 | 19.7508 | 22.9898 | 25.9761 | 31.2604 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| goals | 2.5659 | 0 | 1.0016 | 2.0195 | 3.9276 | 5.0424 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| shots_in_box_share | 0.5716 | 0.387 | 0.5 | 0.5789 | 0.6478 | 0.75 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| possessions | 258.959 | 211.502 | 239.83 | 257.519 | 277.33 | 309.004 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| fouls | 21.1369 | 13.5196 | 17.973 | 21.1939 | 24.2047 | 29.007 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| offsides | 4.0503 | 0.9747 | 2.021 | 3.9484 | 5.81 | 7.9918 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| corners | 10.1657 | 4.9905 | 7.8893 | 9.9793 | 12.1092 | 15.8026 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| throw_ins | 44.3375 | 29.0156 | 37.7586 | 43.5107 | 50.6197 | 62.9388 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| goals_per_shot | 0.1134 | 0 | 0.0526 | 0.1111 | 0.16 | 0.2354 | Wyscout, English first division 2017/18 (CC BY 4.0) |
| km_per_outfield | 10.9048 | 9.58 | 10.3253 | 10.8932 | 11.5232 | 12.2488 | SkillCorner open data, A-League 2024/25 aggregates (MIT) |
| hsr_share | 0.0683 | 0.0428 | 0.0527 | 0.0689 | 0.0813 | 0.0973 | SkillCorner open data, A-League 2024/25 aggregates (MIT) |
| running_share | 0.1431 | 0.1091 | 0.1274 | 0.1403 | 0.1577 | 0.183 | SkillCorner open data, A-League 2024/25 aggregates (MIT) |
| sprint_share | 0.0154 | 0.0059 | 0.0095 | 0.0146 | 0.0201 | 0.0282 | SkillCorner open data, A-League 2024/25 aggregates (MIT) |
| in_play_share | 0.5587 | 0.5091 | 0.5415 | 0.562 | 0.577 | 0.5992 | SkillCorner open data, A-League 2024/25 aggregates (MIT) |

## Distributions (quantiles kept for the KS checks in gate 1)

| Distribution | Median | 5th | 95th | n |
| --- | --- | --- | --- | --- |
| pass_length_m | 17.738 | 5.203 | 53.113 | 364650 |
| shot_distance_m | 17.33 | 6.862 | 31.806 | 8881 |
| player_km_per95 | 10.893 | 9.58 | 12.249 | 210 |
| player_peak_speed_kmh | 28.315 | 26.319 | 30.316 | 210 |
| player_sprints_per95 | 9.066 | 3.722 | 16.087 | 210 |

## Off-ball runs per 30 minutes of team possession, per outfield player

| Run type | Mean | Median | 95th |
| --- | --- | --- | --- |
| aheadoftheballrun | 9.1752 | 8.87 | 20.297 |
| behindrun | 2.426 | 1.13 | 9.595 |
| comingshortrun | 3.4334 | 1.82 | 12.007 |
| crossreceiverrun | 2.9751 | 1.49 | 10.591 |
| droppingoffrun | 2.3684 | 1.32 | 8.097 |
| offballrun | 29.3969 | 29.43 | 52.19 |
| overlaprun | 0.7908 | 0.3 | 3.292 |
| pullinghalfspacerun | 0.8699 | 0.41 | 3.118 |
| pullingwiderun | 1.9005 | 1.53 | 5.098 |
| supportrun | 4.8416 | 4.42 | 11.24 |
| underlaprun | 0.6164 | 0.33 | 2.034 |

## Tracking through a broadcast camera (10 s live-play windows at 10 Hz)

| Feature | 25th | Median | 75th | Windows |
| --- | --- | --- | --- | --- |
| accel_p90 | 1.9972 | 2.1866 | 2.3714 | 1500 |
| accel_mean | 0.9274 | 1.026 | 1.1298 | 1500 |
| players_seen | 13.32 | 15.245 | 16.9825 | 1500 |
| nn_team_mean | 8.4778 | 10.0737 | 11.5118 | 1500 |
| nn_opp_mean | 5.3926 | 6.3195 | 7.274 | 1500 |
| turn_mean | 0.3232 | 0.3669 | 0.4124 | 1500 |
