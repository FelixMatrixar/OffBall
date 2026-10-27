# 3. Host on Vercel and one Ubuntu VM, with Foundry the only Azure service

Date: 26 October 2026. Status: accepted. ADR 0006 moves the VM into Azure, beside Foundry, and gives it a managed identity in place of the app registrations. ADR 0007 moves the web app from Vercel to a Blob Storage static website in Azure.

## Context

PRD 18.9 planned the deployment on Azure: Container Apps, Static Web Apps, Container Registry, Event Hubs, Cosmos DB, Web PubSub, Blob Storage, App Configuration and Application Insights, all deployed with `azd`. The team would rather run its own Ubuntu VM, outside Azure, and deploy nothing to Azure except Microsoft Foundry, which the agents depend on. None of the Azure transports or stores had been built (PRD 23.4), so the change costs no rework.

## Decision

- The web app, with the replays, clips and posters it plays by default, is hosted on Vercel.
- Everything else runs on one Ubuntu 24.04 VM under Docker Compose. Valkey Streams replace Event Hubs, a Valkey hash replaces App Configuration, PostgreSQL replaces Cosmos DB, the live service's own WebSocket relay replaces Web PubSub, and the VM's volumes and GitHub release assets replace Blob Storage. The .NET Aspire Dashboard replaces Application Insights, GitHub Container Registry replaces Azure Container Registry, and Caddy handles TLS.
- Microsoft Foundry is the only Azure resource. It holds the agents as prompt agents, the evaluations and red teaming, and the Speech, Translator and Content Safety that come with the resource. Azure MCP Server runs on the VM in read-only mode and reads only the Foundry resource.
- The VM and CI sign in to Foundry with Microsoft Entra app registrations: certificates on the VM, and workload identity federation in CI.

## Consequences

- Foundry's own trace view needs Application Insights, so traces are read in the Aspire Dashboard instead.
- Foundry hosted agents and Toolboxes aren't used, because hosted agents ship through an Azure Container Registry. The crew stays on the VM (ADR 0002), and Agent Optimizer depends on its accepting prompt agents (PRD open question 13).
- Judging criterion 1's "Azure databases" is no longer claimed.
- Live mode depends on one VM. Replay doesn't (OPS-9).
- The Engineer's Azure view narrows to Foundry's own metrics and health. The pipeline's health comes from the OffBall MCP server's `system_health`, and flags change only through `set_flag`.
