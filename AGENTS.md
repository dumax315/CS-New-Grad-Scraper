# Agent Instructions

## Project overview

This repository is a Python 3.12 application that aggregates new-grad
software-engineering jobs, evaluates a limited batch for Spring 2027 fit,
serves a public FastAPI/Jinja job board, and sends HTML/plain-text email
digests.

The production stack is:

- FastAPI and Jinja for the web application.
- SQLAlchemy with PostgreSQL in Docker and SQLite as the local fallback.
- APScheduler for twice-daily ingestion and notification work.
- `httpx` and purpose-built parsers for source and job-page fetching.
- The Codex CLI for fit evaluation.
- Docker Compose for local development and Coolify deployment.

Do not add a framework, frontend build step, or service dependency when the
existing Python/Jinja/CSS architecture can handle the change cleanly.

## Repository map

- `app/main.py` — FastAPI routes, filtering, and visible-listing query.
- `app/worker.py` — scheduled ingestion, page scraping, fit evaluation, and
  digest orchestration.
- `app/sources.py` — curated-source fetching and candidate parsing.
- `app/ingestion.py` — listing deduplication and persistence.
- `app/models.py` — SQLAlchemy models.
- `app/database.py` — engine/session setup and additive startup migrations.
- `app/presentation.py` — shared user-facing job labels and metadata for web
  and email.
- `app/emailer.py` — digest rendering and SMTP delivery.
- `app/templates/` — board and email templates.
- `app/static/styles.css` — board styling; email CSS remains inline for client
  compatibility.
- `tests/` — unit and rendering tests.
- `docker-compose.yml` — deployable services.
- `docker-compose.override.yml` — local port exposure.
- `LAZYGIT_WORKFLOW.md` — expanded human-facing Git/Lazygit workflow.

## Development and verification

Use uv 0.11.32 and run Python commands through `uv run` so the repository
environment is synchronized before each command:

```sh
uv run python -m pytest -q
uv run python -m compileall -q app tests
docker compose config --quiet
```

Create or synchronize `.venv` from the committed lockfile with:

```sh
uv sync --locked
```

Dependency changes must update both `pyproject.toml` and `uv.lock`; run
`uv lock` after intentionally editing dependency declarations. Do not run
`uv lock --upgrade`, `uv sync --upgrade`, or `uv add` unless the task
explicitly requests a dependency change. Agents should use `uv run` rather
than relying on shell activation, because commands may run in separate shells.

Run the full test suite for shared models, ingestion, worker, database, or
presentation changes. A focused test is useful while iterating, but do not
substitute it for the full suite before handoff when the full suite is
available and fast.

Tests must not call live job sources, SMTP servers, or Codex. Use
`httpx.MockTransport`, fake SMTP objects, and monkeypatched subprocess calls,
following the existing tests.

For local end-to-end development:

```sh
docker compose up --build
```

The board is then available at `http://localhost:8000`. Do not send a test
email, run a live ingestion, invoke a billable Codex evaluation, or deploy
unless the user asks for that external effect.

## Application invariants

- The worker owns external fetching and scheduled bulk digest delivery. The web
  service may send only user-initiated subscription confirmation emails; keep
  all other notification delivery out of web requests.
- `Listing.application_url` is the listing deduplication key. Preserve that
  behavior unless a schema and migration change intentionally replaces it.
- Scheduled runs evaluate at most `CODEX_MAX_EVALUATIONS` newly selected
  listings (10 by default). Selection is persisted so a failed or
  unauthenticated worker restart retries the same batch.
- Fit evaluation treats Spring 2027 timing as a gating requirement. Do not
  weaken that prompt or silently reinterpret the score as offer probability.
- The web board hides known postings older than 365 days. Unknown posting
  dates fall back to `first_seen_at`.
- `SessionLocal` uses `expire_on_commit=False`, but relationships needed after
  a session closes must still be eagerly loaded.
- Schema changes require both a model update and a safe additive migration in
  `create_tables()`. Web and worker containers can start concurrently, so
  PostgreSQL migrations must tolerate both processes attempting them.
- Keep secrets out of logs, tests, templates, and subprocess environments.
  The Codex subprocess receives only the allowlisted environment assembled by
  `codex_environment()`.
- Never commit `.env`, database files, Codex credentials, SMTP credentials, or
  generated caches.

## Web and email presentation

The board and digest should share presentation semantics through
`app/presentation.py`, but they should not share exact markup:

- The board may use semantic HTML, responsive external CSS, filters, and richer
  interaction.
- Email HTML must use conservative table layout and inline styles, retain the
  plain-text alternative, and render acceptably without images or external
  assets.
- Keep Jinja autoescaping enabled for HTML. Never mark scraped or database
  content safe.
- Preserve the content hierarchy: fit status, company, role, metadata, posted
  date, fit reasoning, sources, and apply action.
- Add or update rendering tests when changing labels, ordering, escaping,
  optional fields, links, or score treatment.
- `APP_PUBLIC_URL` controls the digest's “Browse all jobs” link. The digest
  must still render correctly when it is unset.

## Python conventions

- Prefer small typed functions and dataclasses for data passed into templates.
- Keep network, database, presentation, and delivery concerns separated.
- Use timezone-aware UTC datetimes for stored timestamps.
- Preserve graceful fallbacks for missing listing fields and malformed remote
  content.
- Match the existing direct, readable style; no formatter or linter is
  currently configured.

## Git and Lazygit workflow

This repository uses ordinary Git with Lazygit as the human interface. Each
logical change should be an individual commit that can be reviewed as the diff
from its parent. Pull requests are not the unit of change in this workflow.

Lazygit is interactive and intended for the human operator. Agents should use
non-interactive Git commands against the same native repository state. Do not
use Sapling (`sl`) in this repository. See `LAZYGIT_WORKFLOW.md` for the
expanded human workflow.

## Before editing

Inspect the current branch, working tree, index, and relevant history:

```sh
git status --short --branch
git diff
git diff --cached
```

Treat all existing modifications and untracked files as user work unless the
task clearly establishes otherwise. Preserve them and work around unrelated
changes.

Do not use commands that can discard or conceal existing work, including:

```sh
git reset --hard
git checkout -- .
git clean
git stash
```

Do not switch branches, pull, rebase, amend, or otherwise rewrite history
unless the user requests it or it is an unavoidable, clearly in-scope part of
the requested Git operation.

## Editing and verification

Make narrowly scoped changes and inspect the resulting diff:

```sh
git diff -- path/to/changed-file
git status --short
```

Run tests and checks appropriate to the affected code. Report failures and
distinguish failures caused by the agent's changes from pre-existing failures.

Lazygit automatically reflects changes made through the filesystem or Git
CLI. It can remain open while an agent works, but the human and agent must not
perform simultaneous state-changing Git operations.

## Commits

Do not create a commit unless the user explicitly requests one.

When asked to commit:

1. Create one coherent, independently reviewable commit.
2. Stage only the files or patches that belong to the requested change.
3. Never use `git add .`, `git add -A`, or another broad staging command when
   unrelated work may exist.
4. Review the staged diff before committing.
5. Verify the resulting commit as a parent-relative diff.

Typical sequence:

```sh
git add -- path/to/file1 path/to/file2
git diff --cached
git diff --cached --check
git commit -m "Describe the logical change"
git show --stat --oneline HEAD
```

If a file contains both pre-existing user work and agent-authored changes, do
not stage the whole file. Isolate the intended patch safely or stop and ask
for direction.

Do not rewrite commits that may already be shared. Do not push unless the user
explicitly requests it.

## Remote operations

Before an explicitly requested synchronization or push, inspect the working
tree and remote relationship:

```sh
git status --short --branch
git fetch origin
git log --oneline --decorate origin/main..HEAD
```

This repository publishes commits directly to `main`. Before pushing, ensure
the local commits are based on the current `origin/main`. If the remote has
advanced, use a rebase only when the working state is safe and the user has
authorized the synchronization:

```sh
git pull --rebase
git log --oneline origin/main..HEAD
git push origin main
```

Never force-push shared `main`.

## Interrupted operations

Finish or abort an interrupted operation with the tool that started it. For
example, continue a Git rebase with:

```sh
git rebase --continue
```

Before attempting recovery, inspect `git status` and the reflog. Avoid
destructive recovery commands unless their exact targets and effects have been
verified and the user has authorized them.
