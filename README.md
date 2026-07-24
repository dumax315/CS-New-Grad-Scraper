# New Grad SWE Jobs

A small, public job board that aggregates software-engineering new-grad listings from two curated GitHub repositories and emails a digest when new roles appear.

## Run locally

1. Copy `.env.example` to `.env` and set `POSTGRES_USERNAME`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE`, and `POSTGRES_PORT` (normally `5432`). Set `CODEX_API_KEY` for API billing, or leave it blank and follow the ChatGPT login steps below. SMTP settings can remain blank for local development.
2. Run `docker compose up --build`.
3. Open `http://localhost:8000`. The worker ingests once at startup, then at 8 AM and 8 PM in `APP_TIMEZONE`.

## Deploy on Coolify

Create a Docker Compose resource from this repository, set its Compose file location to `/docker-compose.yml`, add the variables in `.env.example` as Coolify secrets, attach a public domain to `web` on port `8000`, and deploy. Keep the generated Postgres volume persistent. The `worker` is internal and does not need a domain. The main Compose file intentionally has no host-port mapping: Coolify's proxy routes traffic to the internal `web:8000` service. `docker-compose.override.yml` adds `localhost:8000` automatically for local development.

The worker is intentionally the only component that fetches GitHub and sends alerts. Its initial import establishes a baseline without emailing every existing listing; later runs email only newly inserted, deduplicated application URLs. Set `SEND_INITIAL_DIGEST=true` if you want that first full digest.

After each ingestion, the worker scrapes the actual application pages for the first 10 new listings and runs the scraped text through `codex exec` in non-interactive, ephemeral, read-only mode. The resulting Spring 2027 CS-undergraduate fit percentage and short reasoning are stored with the listing and displayed on the board. `CODEX_MODEL` defaults to the cost-efficient `gpt-5.6-luna`; `CODEX_TIMEOUT_SECONDS` controls the per-listing timeout.

### Codex authentication on Coolify

`CODEX_API_KEY` uses separately billed OpenAI API usage; it does not use a ChatGPT Plus subscription. Add it as a Coolify secret if that is the billing method you want.

To use a ChatGPT/Codex account instead, leave `CODEX_API_KEY` blank, deploy once, open a terminal for the `worker` container in Coolify, and run:

```sh
codex login --device-auth
```

Open the URL printed by Codex on your own computer, enter the displayed code, verify the container with `codex login status`, and restart the worker service once. The initial batch selection is persisted, so the restart retries the same first 10 jobs if the first evaluation ran before login was ready. The `codex_data` volume persists and refreshes the login stored under `/var/lib/codex` across later worker redeployments. Treat that volume as a secret: anyone who can read it can use the signed-in account.
