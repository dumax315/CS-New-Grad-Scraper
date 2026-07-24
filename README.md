# New Grad SWE Jobs

A small, public job board that aggregates software-engineering new-grad listings from two curated GitHub repositories and emails a digest when new roles appear.

## Run locally

1. Copy `.env.example` to `.env` and set `POSTGRES_USERNAME`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE`, and `POSTGRES_PORT` (normally `5432`). SMTP settings can remain blank for local development.
2. Run `docker compose up --build`.
3. Open `http://localhost:8000`. The worker ingests once at startup, then at 8 AM and 8 PM in `APP_TIMEZONE`.

## Deploy on Coolify

Create a Docker Compose resource from this repository, set its Compose file location to `/docker-compose.yml`, add the variables in `.env.example` as Coolify secrets, attach a public domain to `web` on port `8000`, and deploy. Keep the generated Postgres volume persistent. The `worker` is internal and does not need a domain. The main Compose file intentionally has no host-port mapping: Coolify's proxy routes traffic to the internal `web:8000` service. `docker-compose.override.yml` adds `localhost:8000` automatically for local development.

The worker is intentionally the only component that fetches GitHub and sends alerts. Its initial import establishes a baseline without emailing every existing listing; later runs email only newly inserted, deduplicated application URLs. Set `SEND_INITIAL_DIGEST=true` if you want that first full digest.
