# uv Migration Plan

## Goal

Make Python setup deterministic and low-friction for human developers, Codex
agents, local worktrees, Docker builds, and Coolify deployments.

The desired steady state is:

- `uv.lock` is the committed source of exact dependency versions.
- `uv sync` creates or updates `.venv` from `pyproject.toml` and `uv.lock`.
- `uv run ...` is the standard way to run Python commands because it verifies
  that the lockfile and environment are current before running them.
- Local development and production Docker builds use the same locked dependency
  graph.
- Python 3.12 remains the supported and tested runtime.

This plan changes dependency tooling only. It does not change application
behavior, add a runtime service, run live ingestion, send email, invoke Codex
fit evaluation, or deploy.

## Current state

- Runtime and development dependencies are declared in `pyproject.toml`.
- Development dependencies use the `dev` optional extra.
- Developers and agents install with:

  ```sh
  .venv/bin/python -m pip install -e '.[dev]'
  ```

- Verification directly invokes `.venv/bin/python`.
- There is no committed lockfile or Python-version pin.
- The existing `.venv` can become stale after `pyproject.toml` changes. For
  example, `python-multipart` can be declared without being installed until
  someone manually reinstalls the project.
- The Docker image uses Python 3.12 and performs an unlocked `pip install .`.
- `uv` is not currently installed on the development machine.

## Decisions

### Use a standard development dependency group

Replace:

```toml
[project.optional-dependencies]
dev = ["pytest>=8,<9"]
```

with:

```toml
[dependency-groups]
dev = ["pytest>=8,<9"]
```

`uv` includes the `dev` dependency group by default for `uv sync` and
`uv run`. Production commands will explicitly pass `--no-dev`.

### Pin the project to Python 3.12

Add `.python-version` containing:

```text
3.12
```

Keep `requires-python = ">=3.12"` unless the project intentionally decides to
drop later Python versions. The version file selects the local interpreter
family while the project metadata continues to describe package compatibility.

In Docker, keep `python:3.12-slim` and set `UV_PYTHON_DOWNLOADS=never` so the
build uses the image's interpreter rather than downloading another Python.

### Commit the lockfile

Generate and commit `uv.lock`. Dependency changes must update both
`pyproject.toml` and `uv.lock` in the same logical change.

Routine commands should not unexpectedly upgrade packages. Existing locked
versions remain preferred until constraints change or an explicit upgrade is
requested.

### Use `uv run` for agent commands

Use:

```sh
uv run python -m pytest -q
uv run python -m compileall -q app tests
```

For focused diagnostics:

```sh
uv run python -c "import multipart; print(multipart.__version__)"
```

`uv run` is preferable to shell activation for agents because tool calls may
run in separate shells. It also solves the more important problem: ensuring the
environment is synchronized before execution.

### Use the lockfile in Docker

Copy a pinned `uv` binary from Astral's official distroless image into the
existing Python image. Use a full uv version tag rather than `latest`.

Retain the existing Codex binary stage. The intended Dockerfile structure is:

1. Build or copy the existing pinned Codex CLI.
2. Copy a pinned `uv` binary into `python:3.12-slim`.
3. Copy `pyproject.toml` and `uv.lock`.
4. Run `uv sync --locked --no-dev --no-install-project` to cache third-party
   dependencies independently of application source changes.
5. Copy `app/` and `README.md`.
6. Run `uv sync --locked --no-dev --no-editable`.
7. Add `/app/.venv/bin` to `PATH`.
8. Preserve the current `uvicorn` command and worker Compose command.

Use:

```dockerfile
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
```

Do not copy the host `.venv` into the image.

## Implementation sequence

### 1. Establish the tooling prerequisite

- Choose and document a single pinned uv release for bootstrap examples and
  Docker.
- Install that uv release on the development machine using an official
  installation method.
- Verify:

  ```sh
  uv --version
  ```

Installing uv changes the developer machine and may require network access, so
an agent must request approval before doing it when the environment requires
approval.

### 2. Update project metadata

- Add `.python-version` with `3.12`.
- Move pytest from `[project.optional-dependencies]` to
  `[dependency-groups].dev`.
- Do not alter runtime dependency constraints as part of the tooling migration.
- Run:

  ```sh
  uv lock
  uv lock --check
  ```

- Inspect `uv.lock` to confirm it targets the declared Python compatibility and
  includes all runtime and development dependencies.

### 3. Synchronize and validate the local environment

- Run:

  ```sh
  uv sync --locked
  uv run python --version
  uv pip check
  ```

- Confirm Python reports 3.12.
- Confirm the newly synchronized environment imports every direct runtime
  dependency, including `multipart`.
- Do not manually install undeclared packages into `.venv`.

If the pre-existing `.venv` was created with a different Python minor version,
allow uv to recreate it. Before any removal, resolve the exact `.venv` target
and ensure it is ignored by Git.

### 4. Update agent and developer documentation

Update `AGENTS.md`:

- Replace `.venv/bin/python ...` verification commands with `uv run python ...`.
- Replace the pip install command with `uv sync --locked`.
- State that dependency edits require `uv lock` and must include `uv.lock`.
- State that agents should use `uv run` rather than depending on persistent
  shell activation.
- State that agents must not run `uv lock --upgrade`, `uv sync --upgrade`, or
  `uv add` unless the task actually requests a dependency change.

Update `README.md`:

- Add uv as a local-development prerequisite.
- Document `uv sync --locked`.
- Add direct commands for running the web app and worker outside Docker only if
  those workflows are useful and already supported.
- Keep Docker Compose as the primary end-to-end workflow.

Optionally configure a Codex local-environment setup script in the ChatGPT
desktop app to run:

```sh
uv sync --locked
```

Check in the app-generated `.codex` environment configuration only after
reviewing it for portability and secrets. Setup must be idempotent and must not
run tests, ingestion, SMTP, Codex evaluation, or deployment.

### 5. Convert the Docker build

- Add the pinned uv binary stage or copy instruction.
- Copy `uv.lock` before dependency installation.
- Install only production dependencies with `--no-dev`.
- Use `--locked` so a stale lockfile fails the build.
- Preserve:
  - Python 3.12.
  - The pinned Codex CLI and `/usr/local/bin/codex`.
  - Existing web and worker commands.
  - Existing environment variables and Compose services.

Build-layer optimization is secondary to correctness. First make a clear,
working locked build; then use cache mounts or split dependency/project sync
steps if the resulting Dockerfile remains readable.

### 6. Verify the complete migration

Run local checks:

```sh
uv lock --check
uv sync --locked
uv run python --version
uv pip check
uv run python -c "import multipart; print(multipart.__version__)"
uv run python -m pytest -q
uv run python -m compileall -q app tests
docker compose config --quiet
docker compose build web worker
```

Inspect the built image without starting external application work:

```sh
docker compose run --rm --no-deps web python --version
docker compose run --rm --no-deps web python -c "import multipart; print(multipart.__version__)"
docker compose run --rm --no-deps web uv pip check
```

Do not start the scheduled worker merely to test dependency installation,
because startup can perform external ingestion and Codex evaluation.

### 7. Test stale-environment behavior explicitly

Before handoff, prove the workflow addresses the original problem:

1. Start from a synchronized `.venv`.
2. Record the clean file state, then add a harmless test-only dependency with
   a narrow, uncommitted patch.
3. Run `uv run` and confirm it detects the project change and updates or rejects
   the stale lock according to the selected command flags.
4. Reverse only that temporary patch, run `uv lock`, and run
   `uv sync --locked` so the lockfile and environment return to the intended
   exact state.
5. Run `uv lock --check` and the full verification suite again.

Do not use destructive Git commands or broad cleanup commands for this test.

## Acceptance criteria

- A fresh checkout with Python 3.12 and the documented uv version can run
  `uv sync --locked` without manual venv creation.
- `uv run python` uses the repository `.venv`.
- Runtime imports, including `multipart`, work immediately after synchronization.
- The full test suite and compile check pass through `uv run`.
- `uv lock --check` succeeds with no metadata drift.
- Docker builds fail if `pyproject.toml` and `uv.lock` disagree.
- Docker includes runtime dependencies and excludes the development group.
- The web and worker containers retain their existing commands and behavior.
- `AGENTS.md` no longer requires agents to directly address
  `.venv/bin/python`.
- No secrets, caches, virtual environments, database files, or credentials are
  added to Git.

## Rollout and rollback

Implement the migration as one coherent commit after all checks pass. Stage
only:

- `.python-version`
- `uv.lock`
- `pyproject.toml`
- `Dockerfile`
- `AGENTS.md`
- `README.md`
- `UV_MIGRATION_PLAN.md`
- Any reviewed Codex local-environment configuration intentionally added for
  setup

Do not include unrelated application changes.

If the locked Docker build or Coolify compatibility cannot be verified, stop
before committing. The safe rollback is the parent-relative reversal of the
tooling changes: restore the pip-based Docker install and agent commands, remove
the uv-only metadata, and retain the existing application dependency
declarations. Do not delete or recreate unrelated developer environments.

## References

- [uv installation](https://docs.astral.sh/uv/getting-started/installation/)
- [uv project locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
- [uv dependency groups](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- [Using uv in Docker](https://docs.astral.sh/uv/guides/integration/docker/)
- [Codex local environments](https://learn.chatgpt.com/docs/environments/local-environment)
