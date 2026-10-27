# Deploying OffBall

OffBall runs in three places (PRD 18.9, ADRs 0003 and 0006):
- **Vercel** serves the web app and its built-in replays.
- **One Ubuntu 24.04 VM in Azure** runs everything else under Docker Compose.
- **Microsoft Foundry** holds the agents, beside the VM in the same subscription.

This folder holds what runs on the VM. `infra/main.bicep` creates the VM and Foundry together.

| File | What it does |
| --- | --- |
| `cloud-init.yaml` | Prepares a fresh VM: Docker, the firewall (SSH, HTTP and HTTPS only), automatic security updates, SSH with keys only, the `deploy` user and the data folders |
| `compose.yaml` | The stack: `offball` (the API and the OffBall MCP server), `valkey` (the event bus), `aspire` (traces) and, with the `vm` profile, `caddy` (TLS and routing). Images are pinned by digest |
| `defaults.env` | Settings every machine shares; the machine's own settings and secrets override them |
| `Caddyfile` | The public host name and its routes: `/api/`, `/mcp`, `/media/` and `/files/` |
| `up.sh` | One command on a new VM: settings, secrets, match data, the stack and the smoke test |
| `deploy.sh` | The only command CI's deploy key may run: a release's image by digest, or a rollback |
| `smoke.sh` | The post-deploy check: the API answers, the bus is ready, and a 60x run streams frames, plus graphics when a model is set |

## Run it on your own machine

You need Docker. From the repository root:

```bash
docker compose up --build
```

That builds the `offball` image and starts it with Valkey and the Aspire Dashboard. The API is at `http://localhost:8000` and the MCP server at `http://localhost:8001/mcp`. The Aspire Dashboard is at `http://localhost:18888`, and asks for the token that `docker compose logs aspire` prints. Your `.env` gives the agents a model, as `.env.example` shows.

## Put it on Azure

You need the Azure CLI, an SSH key and an Azure subscription. An Azure for Students subscription works (see below), and so does pay-as-you-go.

1. **Pick a region.** It must be one your subscription allows, where Foundry offers Agent Service and the VM size is available:

   ```bash
   az vm list-skus --location swedencentral --size Standard_B2als_v2 --output table
   ```

   An empty list, or a restriction in the last column, means try another region.
2. **Create the VM and Foundry.** This makes the VM, with `cloud-init.yaml` preparing it, plus its network, address and disk, and Foundry with its OpenRouter connection. It also gives the VM's managed identity Foundry's roles, so the VM holds no Azure secret:

   ```bash
   az group create --name offball --location swedencentral
   ```

   ```bash
   az deployment group create --resource-group offball --template-file infra/main.bicep --parameters sshPublicKey="$(cat ~/.ssh/id_ed25519.pub)" openRouterKey=<your key>
   ```

   The outputs give the `ssh` command and the VM's host name, `offball-<id>.<region>.cloudapp.azure.com`. Caddy gets a certificate for that name from Let's Encrypt, so you don't need a domain. If the region offers the VM but not Foundry, add `foundryLocation=<region>`.
3. **Start the stack.** Sign in with the `ssh` command from the outputs, wait for cloud-init to finish, and get the code:

   ```bash
   cloud-init status --wait
   ```

   ```bash
   sudo git clone https://github.com/FelixMatrixar/OffBall /opt/offball
   ```

   ```bash
   sudo OPENROUTER_API_KEY=<your key> bash /opt/offball/deploy/up.sh --host <the VM's host name> --web-origin https://<your app>.vercel.app
   ```

   While the repository is private, `git clone` needs a GitHub token or a deploy key. Without `--image`, `up.sh` builds the image on the VM. It writes:
   - `/etc/offball/settings.env`, which isn't secret
   - `/etc/offball/secrets/offball.env`, which holds the Valkey password it generates and your OpenRouter key, readable only by root and `deploy`
   - `/etc/offball/release/current.env`, which names the image to run

   Running `up.sh` again keeps the secrets it made.
4. **Read the traces.** Open an SSH tunnel to the VM's Aspire Dashboard, then browse to `http://localhost:18888`:

   ```bash
   ssh -L 18888:127.0.0.1:18888 offball@<the VM's host name>
   ```

5. **Stop paying while you don't need it.** The VM costs about $34.50 a month while it runs, and about $6 while it's deallocated. Replay on Vercel keeps playing while it's off:

   ```bash
   az vm deallocate --resource-group offball --name offball-vm
   ```

   ```bash
   az vm start --resource-group offball --name offball-vm
   ```

### On Azure for Students

The offer gives $100 of credit for 12 months, with no card. It has a few limits:
- **Regions.** A policy allows only some regions, and the list differs between students. Find yours in the portal under Policy, then Assignments, then "Allowed resource deployment regions".
- **Size.** About 4 vCPUs per region, with no increases. The default Standard_B2als_v2 (2 vCPUs, 4 GB) fits; the free 1 GB sizes are too small for the stack.
- **No budgets.** Cost Management doesn't support the offer, so leave `budgetEmails` empty and check the credit balance in the portal instead.
- **The credit is the limit.** When it runs out, Azure disables the subscription, VM and Foundry included, unless you upgrade it to pay-as-you-go. The models are paid from OpenRouter, so they don't draw on it.

## Put it on another provider

`up.sh` also runs on any Ubuntu 24.04 VM with a public address:
1. Create the VM with your SSH key, and paste `cloud-init.yaml` as its user data.
2. Make a DNS A record for the API's host name, such as `api.example.com`, pointing at the VM.
3. Run step 3 above with `--host api.example.com`.
4. Deploy Foundry alone with `infra/foundry.bicep` (below). The VM then needs an app registration to sign in to Foundry (PRD 18.11).

## Deploy from CI

On every push to `main`, CI pushes the image to `ghcr.io/<owner>/offball`, tagged with the commit, and writes its digest in the run summary. To let CI deploy:
1. Give `up.sh` a key for CI with `--ci-key "ssh-ed25519 AAAA..."`. The key can then run `deploy.sh` and nothing else.
2. Let the VM pull from GitHub Container Registry. While the package is private, run `docker login ghcr.io` with a token that can read packages.
3. Deploy a release, which pulls the image, restarts what changed, runs the smoke test, and goes back to the previous image if the test fails:

   ```bash
   ssh deploy@api.example.com deploy ghcr.io/<owner>/offball@sha256:<digest>
   ```

4. Go back to the release before:

   ```bash
   ssh deploy@api.example.com rollback
   ```

## Microsoft Foundry

`infra/main.bicep` deploys `infra/foundry.bicep` with the VM. It creates:
- the Foundry resource and project
- the gateway connection to OpenRouter, with the key kept only in the connection (ADR 0004)
- the roles of the VM's managed identity, and of CI's app registration if you pass its principal ID
- a monthly budget that alerts at 50%, 80% and 100%, only if you pass `budgetEmails` on a pay-as-you-go subscription

To deploy Foundry alone, for a VM on another provider, run these two commands:

```bash
az group create --name offball --location <region>
```

```bash
az deployment group create --resource-group offball --template-file infra/foundry.bicep --parameters openRouterKey=<your key> budgetEmails='["you@example.com"]'
```

Until the agents are registered in Foundry (ADR 0002), the crew calls OpenRouter directly with the key in the VM's secrets. The Foundry resource then holds the connection, and later Speech, Content Safety and the evaluations.

## Not here yet

These join the stack as they're built:
- PostgreSQL for match state
- the counterfactual workers
- the evaluator and the generator's live-run pool
- Azure MCP Server for the Engineer

Azure MCP Server's HTTP transport requires Microsoft Entra sign-in for incoming calls, unless that check is turned off with `--dangerously-disable-http-incoming-auth`. Choosing between those, or running it over stdio, is PRD open question 11.
