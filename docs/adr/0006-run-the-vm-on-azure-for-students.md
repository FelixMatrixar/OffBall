# 6. Run the VM on Azure, beside Foundry, in an Azure for Students subscription

Date: 27 October 2026. Status: accepted.

## Context

ADR 0003 put the VM outside Azure, on any provider or the team's own hardware. The team's own machine sits behind a company VPN, so it can't serve the public, and renting a VM elsewhere would add another account to pay. The team now has an Azure for Students subscription: $100 of credit for 12 months, renewable while a student, with no card. The offer limits regions by policy, allows about 4 vCPUs per region with no increases, isn't supported by Cost Management budgets, and is disabled when the credit runs out unless it's upgraded to pay-as-you-go.

Measured on 27 October under `docker compose up`, the stack idles at about 215 MB. With a live match the `offball` container grows to about 1.2 GB, and a second match adds about 45 MB. The VM sizes the offer gives free have 1 GB of memory, which is too little.

## Decision

- The VM runs in Azure, in the same subscription and resource group as Foundry. It's a Standard_B2als_v2 (2 vCPUs, 4 GB) with Ubuntu 24.04 and a 32 GB Standard SSD. `infra/vm.bicep` creates it with `deploy/cloud-init.yaml` as its user data, and `infra/main.bicep` deploys it and Foundry together. What runs on the VM stays as ADR 0003 has it: Docker Compose, Valkey, Caddy, the Aspire Dashboard and, later, PostgreSQL.
- The VM's public address has an Azure host name, `<label>.<region>.cloudapp.azure.com`, which Caddy gets a certificate for, so no domain is needed.
- The VM signs in to Foundry with its system-assigned managed identity, which holds the roles that `offball-app` and `offball-azmcp` would have held (PRD 18.11). Those two app registrations and their certificates aren't needed. CI keeps `offball-ci`, with workload identity federation, only if it runs the evaluations.
- The models stay on OpenRouter (ADR 0004). If agent tokens used up the credit, Azure would disable the subscription and take the VM and Foundry down with it.
- There's no budget resource on Azure for Students, because Cost Management doesn't support the offer; the credit is the limit. `infra/foundry.bicep` keeps its optional budget for a pay-as-you-go subscription.

## Consequences

- Azure now runs two things: the VM, with its network, address and disk, and Foundry. Nothing else moves to Azure.
- In Sweden Central the VM costs about $34.50 a month while it runs ($28.40 for the VM, $3.65 for the address and $2.40 for the disk) and about $6 a month while it's deallocated. Running it without a break until judging ends on 10 November (rule 4.8) costs about $17. Replay on Vercel keeps playing while the VM is off (OPS-9).
- When the credit runs out, Azure disables the subscription unless it's upgraded to pay-as-you-go, so the team watches the credit balance in the portal in place of budget alerts.
- The region must be one the subscription's policy allows and where Foundry offers Agent Service. `main.bicep` can put Foundry in a different region from the VM.
- The load test (18.3) still has to show whether 2 vCPUs and 4 GB carry the 10-match target. A student subscription can't go above about 4 vCPUs; a pay-as-you-go one can.
- Rule 4.12 asks for Azure on terms open to every entrant. Azure for Students is a public offer, but only students can take it, so the team confirms it's acceptable (PRD open question 2). The same Bicep deploys to a pay-as-you-go subscription unchanged.
- The offer is for learning and non-commercial use, which the submission is.
