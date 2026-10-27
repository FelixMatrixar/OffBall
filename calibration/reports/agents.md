# Agent evaluations

Model: openai/gpt-6-luna at low effort, up to 4,000 tokens (fast), openai/gpt-6-luna at high effort, up to 16,000 tokens (reasoning). Pass bars are PRD 14.15's starting values.

| Agent | Result | Numbers |
| --- | --- | --- |
| factchecker | pass | drafts 14, catches 1.0, passes 1.0 |
| scout | pass | planted 15, recall 1.0, nulls 0, invented_per_null 0.0 |
| persona | pass | modes 6, problems 0 |

Time per call, against each agent's p95 budget (PRD 14.10):

| Agent | Calls | Failed | p95 | Budget |
| --- | --- | --- | --- | --- |
| factchecker | 56 | 0 | 16,594 ms | 600 ms |
| persona | 6 | 0 | 23,406 ms | 500 ms |
| scout | 15 | 0 | 4,297 ms | 300 ms |
