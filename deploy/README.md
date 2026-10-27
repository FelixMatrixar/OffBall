# Deploying OffBall

OffBall runs in three places (PRD 18.9, ADR 0003):
- **Vercel** serves the web app and its built-in replays.
- **One Ubuntu 24.04 VM** runs everything else under Docker Compose.
- **Microsoft Foundry** is the only Azure resource.

This folder holds the VM side, and `infra/foundry.bicep` holds the Foundry side.

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

## Put it on a VM

1. **Get a VM.** Use Ubuntu 24.04 LTS with a public IP address, on any provider. 4 vCPUs, 8 GB of memory and 80 GB of disk is enough for the demo.
2. **Prepare it.** Paste `cloud-init.yaml` as the VM's user data after putting your SSH public key in it.
3. **Point DNS at it.** Make an A record for the API's host name, such as `api.example.com`, pointing at the VM's address. Caddy gets the certificate from Let's Encrypt when the stack starts.
4. **Start the stack.** On the VM:

   ```bash
   sudo git clone https://github.com/FelixMatrixar/OffBall /opt/offball
   ```

   ```bash
   sudo OPENROUTER_API_KEY=<your key> bash /opt/offball/deploy/up.sh --host api.example.com --web-origin https://<your app>.vercel.app
   ```

   While the repository is private, `git clone` needs a GitHub token or a deploy key. Without `--image`, `up.sh` builds the image on the VM. It writes:
   - `/etc/offball/settings.env`, which isn't secret
   - `/etc/offball/secrets/offball.env`, which holds the Valkey password it generates and your OpenRouter key, readable only by root and `deploy`
   - `/etc/offball/release/current.env`, which names the image to run

   Running `up.sh` again keeps the secrets it made.
5. **Read the traces.** Open an SSH tunnel to the VM's Aspire Dashboard, then browse to `http://localhost:18888`:

   ```bash
   ssh -L 18888:127.0.0.1:18888 you@api.example.com
   ```

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

`infra/foundry.bicep` creates:
- the Foundry resource and project
- the gateway connection to OpenRouter, with the key kept only in the connection (ADR 0004)
- the roles for the three app registrations, once their principal IDs are passed in
- a monthly budget that alerts at 50%, 80% and 100%

You need the Azure CLI and a pay-as-you-go subscription (PRD 18.9). Run these two commands:

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
