# 7. Serve the web app from a Blob Storage static website

Date: 27 October 2026. Status: accepted.

## Context

ADR 0003 put the web app on Vercel, with the replays, clips and posters it plays by default. Nothing was ever deployed there: the repository has no Vercel settings. The team now has an Azure subscription for the VM and Foundry (ADR 0006) and would rather keep the whole deployment in it.

Azure Static Web Apps was the first choice, but it runs only in westeurope, eastus2, centralus, westus2 and eastasia. The subscription's policy allows only koreacentral, australiaeast, centralindia, malaysiawest and indiasouthcentral, and denies anything else. A storage account's static website works in any region. It serves files over HTTPS from `<account>.<zone>.web.core.windows.net` and costs cents a month for a build of about 14 MB. The app routes in the URL's hash, so it needs no rewrite rules.

## Decision

- The web app is served from the static website of a storage account in the VM's region. `infra/web.bicep` creates the account, and `infra/main.bicep` deploys it with the VM and Foundry. Turning the static website on is a data-plane setting that Bicep can't reach, so `deploy/README.md` does it once with the Azure CLI.
- CI builds `web/` on each push to `main` and uploads it (`.github/workflows/site.yml`). It signs in as `offball-ci` with workload identity federation, which holds Storage Blob Data Contributor on that account and nothing else there, so no Azure secret is stored. The workflow reads repository variables: the sign-in IDs, the account's name, and the build settings such as `VITE_API_BASE`.
- Hashed assets are uploaded with a year's cache, and everything else with `no-cache`. The replay feed and the manifest get their content types set by hand.
- Browsers still reach the live stream and the API on the VM directly; the website serves only static files.

## Consequences

- Azure holds three things: the VM, Foundry and the storage account. The account costs cents a month, and its transfer counts toward the subscription's outbound data.
- Pull requests get no preview environment; CI still builds and tests the web app on each one.
- There's no CDN, so viewers far from the region load the app more slowly the first time. The service worker caches the app shell after that.
- A static website can't add response headers, so `nosniff` and the referrer policy that Caddy sends on the API don't apply to the web app.
- Replay still doesn't depend on the VM (OPS-9). It does depend on the Azure subscription staying enabled, so the credit balance matters for the replay too (ADR 0006).
- Production updates on each push to `main` rather than on a release tag. Rolling back means running the Site workflow on an earlier commit.
- Old hashed assets stay in the container after later uploads. They're small, and clients that still hold an older page keep working.
