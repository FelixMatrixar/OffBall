# Security

## Reporting a problem

Please report a vulnerability privately, through GitHub's private vulnerability reporting: on the repository's **Security** tab, choose **Report a vulnerability**. Don't open a public issue for it.

Say what you found, how to reproduce it, and what it lets someone do. We aim to reply within three working days, and we'll tell you when it's fixed.

## What's in scope

- The API and the live stream (`offball/services/`), including producer actions and their tokens.
- The OffBall MCP server (`offball/mcp/`).
- The agents (`offball/agents/`), including prompt injection through Ask OffBall that makes an agent state something unverified or leave its scope.
- The web app (`web/`).

## How OffBall is built to stay safe

- No accounts and no stored viewer data. Questions are processed in memory and never written to logs or traces.
- Producer actions need the producer token of the live run they act on. Tokens are random, kept only with their run, and expire with it.
- Agents can read only observed match data through fixed tools. Nothing they can reach holds the answer keys.
- The VM and CI sign in to Microsoft Foundry with Microsoft Entra app registrations, not keys. The OpenRouter key lives only in Foundry's connection, and the VM's few credentials only in its root-only secrets directory (PRD 18.5, 18.11, 18.14).
- No secrets live in the repository. Local model settings go in `.env`, which git ignores.
