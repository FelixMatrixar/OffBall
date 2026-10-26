# 2. The crew runs in process until Foundry hosting is confirmed

Date: 26 October 2026. Status: accepted.

## Context

PRD 14 plans the agents as Foundry hosted agents, scaffolded with `azd ai agent init`, with tools through Foundry Toolboxes. Hosted agents, Toolboxes and Routines are previews whose availability to our tenant and region is still open question 13, and the PRD names the fallback for each (section 24): Container Apps workers for hosted agents and direct MCP connections for Toolboxes.

## Decision

The crew runs as Microsoft Agent Framework workflows inside the `api` service, calling the models deployed in the Foundry resource (`offball/agents/llm.py`). Agents reach their tools in process, or through the OffBall MCP server when `OFFBALL_MCP_URL` is set. Per-agent evaluations run with `offball eval agents` against the same models, ahead of Foundry's own evaluations.

## Consequences

- The workflows, contracts and evaluations stay the same whether the crew runs in process or as hosted agents, so moving to hosted agents later changes only where the crew runs.
- Agent Optimizer, which works only with agents set up through `azd ai agent init`, waits for that move, and so does the learning loop (M9).
