# Deploying OffBall

OffBall runs in three places, all in one Azure subscription (PRD 18.9, ADRs 0003, 0006 and 0007):
- **A Blob Storage static website** serves the web app and its built-in replays.
- **One Ubuntu 24.04 VM** runs everything else under Docker Compose.
- **Microsoft Foundry** holds the agents.

This folder holds what runs on the VM. `infra/main.bicep` creates all three, and CI uploads the web app (`.github/workflows/site.yml`).

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

1. **Pick the regions.** Both must be ones your subscription allows. The VM's region, which the web app shares, must offer the VM size; an empty list, or a restriction in the last column, means try another region:

   ```bash
   az vm list-skus --location koreacentral --size Standard_B2als_v2 --all --output table
   ```

   Foundry's region must offer Agent Service. Australia East does, with the most models.
2. **Create CI's identity.** `offball-ci` is an app registration that GitHub Actions on `main` signs in as, with no secret (PRD 18.11). Create it, note the `appId`, then create its service principal and note that `id`:

   ```bash
   az ad app create --display-name offball-ci --query appId --output tsv
   ```

   ```bash
   az ad sp create --id <appId> --query id --output tsv
   ```

   ```bash
   az ad app federated-credential create --id <appId> --parameters infra/ci-federated-credential.json
   ```

   For a fork, change the repository in `infra/ci-federated-credential.json` first.
3. **Create the VM, Foundry and the web app's storage.** This makes the VM, with `cloud-init.yaml` preparing it, plus its network, address and disk; Foundry with its OpenRouter connection; and a storage account for the web app. It gives the VM's managed identity Foundry's roles, so the VM holds no Azure secret, and lets `offball-ci` upload the web app:

   ```bash
   az group create --name offball --location koreacentral
   ```

   ```bash
   az deployment group create --resource-group offball --template-file infra/main.bicep --parameters sshPublicKey="$(cat ~/.ssh/id_ed25519.pub)" openRouterKey=<your key> foundryLocation=australiaeast ciPrincipalId=<the service principal's id>
   ```

   The outputs give the `ssh` command, the VM's host name (`offball-<id>.<region>.cloudapp.azure.com`), and the web app's storage account and host name (`<account>.<zone>.web.core.windows.net`). Caddy gets a certificate for the VM's name from Let's Encrypt, so you don't need a domain.
4. **Turn on the static website.** Bicep can't reach this setting, so it's one command:

   ```bash
   az storage blob service-properties update --account-name <webAccount> --static-website --index-document index.html --404-document index.html --auth-mode key
   ```

5. **Let CI upload the web app.** In the repository's settings on GitHub, under Secrets and variables, then Actions, add these variables; none is a secret:
   - `AZURE_CLIENT_ID`: `offball-ci`'s `appId`
   - `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`: from `az account show`
   - `OFFBALL_WEB_ACCOUNT`: the `webAccount` output
   - `VITE_API_BASE`: `https://<the VM's host name>`, so the panels and Ask OffBall use the API; without it the web app uses its stand-ins

   Then run the Site workflow, or push to `main`. It builds `web/` and uploads it on each push to `main` (`.github/workflows/site.yml`).
6. **Start the stack.** Sign in with the `ssh` command from the outputs, wait for cloud-init to finish, and get the code:

   ```bash
   cloud-init status --wait
   ```

   ```bash
   sudo git clone https://github.com/FelixMatrixar/OffBall /opt/offball
   ```

   ```bash
   sudo OPENROUTER_API_KEY=<your key> bash /opt/offball/deploy/up.sh --host <the VM's host name> --web-origin https://<the web app's host name>
   ```

   While the repository is private, `git clone` needs a GitHub token or a deploy key. Without `--image`, `up.sh` builds the image on the VM. It writes:
   - `/etc/offball/settings.env`, which isn't secret
   - `/etc/offball/secrets/offball.env`, which holds the Valkey password it generates and your OpenRouter key, readable only by root and `deploy`
   - `/etc/offball/release/current.env`, which names the image to run

   Running `up.sh` again keeps the secrets it made.
7. **Read the traces.** Open an SSH tunnel to the VM's Aspire Dashboard, then browse to `http://localhost:18888`:

   ```bash
   ssh -L 18888:127.0.0.1:18888 offball@<the VM's host name>
   ```

8. **Stop paying while you don't need it.** In Korea Central the VM costs about $40 a month while it runs, with its address and disk, and about $6 while it's deallocated. The web app keeps playing its replay while the VM is off:

   ```bash
   az vm deallocate --resource-group offball --name offball-vm
   ```

   ```bash
   az vm start --resource-group offball --name offball-vm
   ```

### On Azure for Students

The offer gives $100 of credit for 12 months, with no card. It has a few limits:
- **Regions.** A policy allows only some regions, and the list differs between students. Find yours with `az policy assignment list --query "[].parameters"`, or in the portal under Policy, then Assignments, then "Allowed resource deployment regions". Azure Static Web Apps runs in none of the regions this project's subscription allows, which is why the web app is a storage account's static website (ADR 0007).
- **Size.** About 4 vCPUs per region, with no increases, and some sizes are withheld per region. The default Standard_B2als_v2 (2 vCPUs, 4 GB) fits; the free 1 GB sizes are too small for the stack.
- **No budgets.** Cost Management doesn't support the offer, so leave `budgetEmails` empty and check the credit balance in the portal instead.
- **The credit is the limit.** When it runs out, Azure disables the subscription, the VM, Foundry and the web app included, unless you upgrade it to pay-as-you-go. The models are paid from OpenRouter, so they don't draw on it.

## Put it on another provider

`up.sh` also runs on any Ubuntu 24.04 VM with a public address:
1. Create the VM with your SSH key, and paste `cloud-init.yaml` as its user data.
2. Make a DNS A record for the API's host name, such as `api.example.com`, pointing at the VM.
3. Run step 6 above with `--host api.example.com`.
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
