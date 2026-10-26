# 5. Trim the milestones a little

Date: 26 October 2026. Status: accepted.

## Context

The PRD plans at full scope (PRD 23). On 26 October 2026 the team checked progress against the milestones in PRD 23.1 and found that some scope costs a lot for what it adds. Some of it also contradicts decisions already made: ADR 0001 defers Fabric, PRD 12.10 makes only five of the nine gates release gates, and the agents write three languages. The team asked for a small trim that leaves the core intact. The core is the hero technologies (Foundry, Agent Framework, MCP and Azure MCP Server), the visualization system, the tactics board and Change one decision.

## Decision

1. **Gates in the exit criteria.** M1, M2 and M4 still run their gates. Their exit criteria now ask that the release gates pass (consistency, detectability, novelty, diversity, determinism), and the other four gates are reported with their gaps, as PRD 12.10 already says. M4 no longer needs all nine gates to pass.
2. **Fabric is an optional add-on.** Eventstream, Eventhouse, KQL views, Real-Time Dashboards and Activator leave M2, M3 and M6. The Pundit answers from the match and season tools. PRD 17.4 stays as the plan if Fabric joins, and OffBall uses three hero technologies in depth rather than four.
3. **Captions and voice in three languages.** The agents write English, Spanish and French, and voices speak them. The interface keeps all ten languages, and a viewer whose interface is in another language gets English captions. No translation or language pack is deleted.
4. **One live transport.** The relay sends Server-Sent Events only. Groups, tokens and negotiate stay; clients send through the API, including a new `POST /api/pair/{code}` for second-screen pairing. Frame batching, which only applied to the WebSocket, goes. The frontend's WebSocket reader stays in the code.
5. **Ghost players from the engine.** No separately trained ghosting model (Le et al., 2017). The ghost players in what-if replays, Change one decision and the tactics board come from the counterfactual workers' re-runs, which the engine already produces.
6. **Narrower M7.**
   - The partner template is tested in OBS only. Its CasparCG calls stay but aren't tested.
   - Foundry's AI red teaming agent, with tests written from our responsible-AI policies, is the one adversarial suite in place of ASSERT.
   - The human studies are the fan comprehension A/B test and the producer walkthrough. Coach interviews and blind or low-vision listener sessions are optional.
7. **Benchmark and learning extras.**
   - OffBall-Bench is scored by `offball eval bench`, run by the evaluator on the VM for the test split and by anyone for the dev split, instead of a hosted evaluation endpoint. `POST /api/bench/submissions` is removed.
   - The optional reinforcement-learning track for the Scout is dropped, so the learning loop has two mechanisms: Agent Optimizer and procedural memory.

## Consequences

- By the team's estimate, progress across M0 to M7 and M9 rises from about 47% to about 54% with no new code. The five release gates already pass on the sets checked.
- The video's 1:04 shot shows Ask OffBall answered from the match tools instead of KQL and an Activator alert. The language shot switches the caption to Spanish and the interface to Arabic.
- Outside teams can't score the test split on their own: they send a test-split overlay feed, and the team scores it. PRD open question 10 is resolved.
- PRD open question 14 is resolved, and the last consequence in ADR 0004, a trained Scout hosted in Foundry, no longer applies.
- `INTEGRATION.md`'s production stream notes (4.1), pairing proposal (6.7) and section 9 rows now describe the relay as Server-Sent Events. Its WebSocket transport stays listed, because the frontend still reads one from other sources.
- Everything trimmed is listed in PRD 27 and can return later without changing the contracts.
