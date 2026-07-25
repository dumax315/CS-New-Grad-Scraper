# New Grad SWE Jobs

A small, public job board that aggregates software-engineering new-grad listings from two curated GitHub repositories and emails a digest when new roles appear.

## Prerequisites

Docker Compose is the primary local and production workflow. Python development
outside Docker uses Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.11.32.
Install the pinned uv release on macOS or Linux with:

```sh
curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/0.11.32/install.sh | sh
```

## Run locally with Docker

1. Copy `.env.example` to `.env` and set `POSTGRES_USERNAME`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE`, and `POSTGRES_PORT` (normally `5432`). Set `APP_PUBLIC_URL` to the deployed board URL so email links use the public domain. Set `SUBSCRIPTION_TOKEN_SECRET` to a long random value. Set `CODEX_API_KEY` for API billing, or leave it blank and follow the ChatGPT login steps below. SMTP settings can remain blank for local development, in which case public email signup is disabled.
2. Start the web app and its database with hot reload:

   ```sh
   docker compose up --build web
   ```

3. Open `http://localhost:8000`.

The local Compose override bind-mounts `app/` and runs Uvicorn with `--reload`.
Starting only `web` also starts its database dependency without starting the
scheduled worker. Use these related commands as needed:

```sh
# Run the full stack, including the ingestion worker
docker compose up --build

# Run the hot-reloading web app in the background
docker compose up --build --detach web

# Follow web logs
docker compose logs --follow web

# Stop and remove the local containers
docker compose down
```

Starting the full stack runs the worker's external ingestion and fit-evaluation
workflow once at startup, then at 8 AM and 8 PM in `APP_TIMEZONE`. Hot reload
applies to the web service; the production Compose file remains unchanged.

### Test refetching, email, and Codex during local development

The normal hot-reload command starts only `web` and `db`, so the one-shot worker
commands can run alongside it without stopping anything:

```sh
# Terminal 1: keep the board running with hot reload
docker compose up --build web

# Terminal 2: build the worker after worker, CLI, resume, or packaging changes
docker compose build worker

# Delete five recently saved jobs, refetch them, and send email without Codex
docker compose run --rm worker jobs-refetch 5 --no-codex

# Codex-review and save the five newest unreviewed jobs
docker compose run --rm worker jobs-review 5
```

The one-shot container shares PostgreSQL with the hot-reloading board. Refresh
`http://localhost:8000` after a command finishes to see its database changes. Repeated
commands do not require another worker build unless its code, resume, packaging, or
dependencies changed.

Use `jobs-refetch 5` without `--no-codex` to delete, refetch, review, save, and email in
one pass. The refetch command exits unsuccessfully if there was nothing to delete, no
listing was restored, or no digest was sent. Deletion is committed before source
fetching, so use it only against a development database. Digest delivery requires valid
SMTP settings and at least one `ALERT_RECIPIENT` or confirmed subscriber.

Use `jobs-review 5 --force` to include previously reviewed listings and overwrite their
successful results. These commands are also available as `uv run jobs-refetch ...` and
`uv run jobs-review ...` when the required database, SMTP, and Codex environment is
available directly in the shell.

If the full stack is running through `docker compose up --build`, stop its scheduled
worker before a one-shot test and restart it afterward:

```sh
docker compose stop worker
docker compose run --rm worker jobs-refetch 5 --no-codex
docker compose start worker
```

## Develop with uv

Create or update the repository `.venv` from the exact versions in `uv.lock`:

```sh
uv sync --locked
```

Run Python commands through uv so it checks that the lockfile and environment
are current:

```sh
uv run python -m pytest -q
uv run python -m compileall -q app tests
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

When intentionally changing dependencies, update `pyproject.toml`, run
`uv lock`, and include the resulting `uv.lock` change in the same commit.

## Deploy on Coolify

Create a Docker Compose resource from this repository, set its Compose file location to `/docker-compose.yml`, add the variables in `.env.example` as Coolify secrets, attach a public domain to `web` on port `8000`, and deploy. Keep the generated Postgres volume persistent. The `worker` is internal and does not need a domain. The main Compose file intentionally has no host-port mapping: Coolify's proxy routes traffic to the internal `web:8000` service. `docker-compose.override.yml` adds `localhost:8000` automatically for local development.

The worker is the only component that fetches GitHub and sends scheduled bulk alerts. The web service sends only user-initiated subscription confirmation messages. New subscribers must follow the confirmation link within 48 hours and every subscriber digest includes an unsubscribe link. The worker's initial import establishes a baseline without emailing every existing listing; later runs email only newly inserted, deduplicated application URLs. `ALERT_RECIPIENT` continues to receive an operator copy, while confirmed subscribers receive individualized messages. Set `SEND_INITIAL_DIGEST=true` if you want the initial full digest.

After each ingestion, the worker scrapes the actual application pages for the first 10 new listings and runs the scraped text through `codex exec` in non-interactive, ephemeral, read-only mode. The assessment uses the trusted candidate profile in `TheoHalpernResume.md` to compare the role with concrete experience, skills, coursework, and projects while retaining Spring 2027 timing as a gating requirement. The resume's name and contact header are omitted from the model prompt because they are not relevant to fit. The resulting fit percentage and short reasoning are stored with the listing and displayed on the board. `CODEX_MODEL` defaults to the cost-efficient `gpt-5.6-luna`; `CODEX_TIMEOUT_SECONDS` controls the per-listing timeout.

The scraper reads standard HTML and JobPosting JSON-LD, and uses Workday's structured
job endpoint for client-rendered Workday listings. The board hides listings with a
known posting date older than 365 days.

### Refresh the candidate resume

The repository keeps a Markdown snapshot of the resume so scheduled evaluations do not
depend on the portfolio site being available. To regenerate it from the public PDF with
[Microsoft MarkItDown](https://github.com/microsoft/markitdown), run:

```sh
curl --fail --location --silent --show-error \
  https://www.theoh.dev/TheoHalpernResume.pdf \
  --output /tmp/TheoHalpernResume.pdf
uvx --from 'markitdown[pdf]==0.1.6' \
  markitdown /tmp/TheoHalpernResume.pdf \
  --output TheoHalpernResume.md
```

Review the resulting diff before committing it because PDF extraction can lose visual
structure such as headings or multi-column ordering.

To evaluate every unfinished listing posted in the last 10 days, bypassing the
scheduled worker's 10-listing cap, run this inside the Coolify `worker` terminal:

```sh
python -m app.backfill --days 10
```

Add `--force` to scrape and re-evaluate listings that already have a successful score.
The backfill runs one `codex exec` process at a time, but a large run can still take a
long time and consume significant API or ChatGPT plan usage. If a listing has no known
posting date, the command uses the date the scraper first discovered it.

### Codex authentication on Coolify

`CODEX_API_KEY` uses separately billed OpenAI API usage; it does not use a ChatGPT Plus subscription. Add it as a Coolify secret if that is the billing method you want.

To use a ChatGPT/Codex account instead, leave `CODEX_API_KEY` blank, deploy once, open a terminal for the `worker` container in Coolify, and run:

```sh
codex login --device-auth
```

Open the URL printed by Codex on your own computer, enter the displayed code, verify the container with `codex login status`, and restart the worker service once. The initial batch selection is persisted, so the restart retries the same first 10 jobs if the first evaluation ran before login was ready. The `codex_data` volume persists and refreshes the login stored under `/var/lib/codex` across later worker redeployments. Treat that volume as a secret: anyone who can read it can use the signed-in account.
