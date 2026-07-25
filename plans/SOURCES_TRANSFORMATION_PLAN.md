# Sources Transformation Plan

## Goal

Evolve the application from a scraper of two curated GitHub lists into a
resilient hybrid new-grad sourcing system:

- Keep the existing curated lists because they provide valuable human
  curation and broad new-grad coverage.
- Use their application links to discover company applicant-tracking-system
  (ATS) boards.
- Add a small number of direct employer-board connectors so the application
  can find relevant roles before a curated list republishes them.
- Preserve the product's actual scope: software-engineering and adjacent
  new-grad roles for a student graduating in Spring 2027.
- Track source health and listing lifecycle without treating a failed fetch as
  evidence that a job closed.

The intended steady state is a hybrid pipeline:

```text
curated GitHub lists ───────────────┐
                                   ├─> normalized candidates
stored application URLs ─> ATS     │       │
                         discovery │       ▼
                                   └─> deterministic new-grad scope filter
                                               │
                                               ▼
                                      URL-keyed persistence
                                               │
                                  at most 10 newly selected roles
                                               │
                                               ▼
                                      Codex fit evaluation
```

This is a sources transformation, not a scope expansion. Internship, co-op,
quant-trading, product-management, and experienced-only roles remain outside
the target population.

## Current state

- `app/sources.py` fetches two Markdown sources sequentially:
  - SpeedyApply's `NEW_GRAD_USA.md`.
  - Vansh's `New-Grad-2027` README.
- Both sources are parsed into the existing typed `Candidate` dataclass.
- A failed HTTP response from either source raises out of `fetch_candidates()`
  and prevents the rest of the ingestion cycle from completing.
- Deterministic title filtering excludes several unrelated role families and
  requires an engineering-related term.
- `Listing.application_url` is the unique listing key.
- `ListingSource` records provenance when the same canonical application URL
  appears in more than one source.
- `Listing.first_seen_at` and `Listing.last_seen_at` are stored, but source
  observations and explicit open/closed lifecycle are not.
- A listing remains visible until its known posted date, or its first-seen
  fallback date, becomes more than 365 days old.
- The worker scrapes the job page and evaluates at most 10 newly selected
  listings. Selection is persisted so failed evaluations retry after restart.
- The Codex prompt correctly treats Spring 2027 timing as a gating requirement
  and caps unstated timing rather than assuming that an entry-level role will
  wait for graduation.

Several foundations should be retained:

- The normalized `Candidate` boundary.
- URL canonicalization.
- URL-keyed idempotent ingestion.
- Multi-source provenance.
- New-listing-only page scraping and fit evaluation.
- The persisted 10-listing evaluation batch.

## Non-goals

- Do not ingest internship lists as if they were new-grad sources.
- Do not infer Spring 2027 eligibility from a recent posting date.
- Do not weaken the timing requirements in the Codex evaluation prompt.
- Do not immediately poll thousands of company boards.
- Do not replace `Listing.application_url` as the deduplication key.
- Do not add a message queue, browser automation service, frontend framework,
  or external source-management service.
- Do not send test email, run live ingestion, invoke Codex, or deploy merely to
  implement or verify the transformation.
- Do not copy implementation from an unlicensed repository. Reimplement the
  general architecture using public ATS interfaces, project conventions, and
  independently written tests.

## Decisions

### Keep curated lists as first-class sources

The two current lists remain enabled and continue to contribute provenance.
Direct employer feeds supplement them; they do not silently replace them.

Curated sources serve three purposes:

1. Supply already-filtered new-grad candidates.
2. Reveal employers that are actively hiring new graduates.
3. Seed ATS discovery from their application URLs.

Coverage and latency measurements, not assumptions, will determine whether a
curated source is ever removed.

### Separate source definition, fetching, and scope filtering

Split the current responsibilities into small modules:

- `app/source_types.py`
  - `SourceSpec`: stable source key, display name, kind, public URL, and
    connector parameters.
  - `Candidate`: the normalized candidate shape currently in `app/sources.py`.
  - `SourceFetchResult`: candidates plus success/failure and count metadata.
- `app/source_registry.py`
  - The reviewed, enabled source registry.
  - The two curated sources and approved employer ATS boards.
- `app/source_connectors/`
  - One connector per source format or ATS.
  - Begin with Markdown, Greenhouse, Lever, and Ashby.
- `app/source_scope.py`
  - Deterministic software/adjacent-role and new-grad plausibility filtering.
- `app/sources.py`
  - Orchestration across registered sources and compatibility exports while
    call sites transition.

The exact file split may be adjusted if fewer modules remain clearer, but ATS
response parsing must not be mixed with database persistence, Codex
evaluation, or email delivery.

### Use a reviewed registry before automatic growth

ATS discovery should initially produce proposals rather than automatically
enable every board it sees.

Add a non-networking discovery command that examines stored application URLs
and emits candidate source definitions for recognizable ATS hosts. A proposed
entry includes:

- Stable key such as `greenhouse:acme`.
- Employer display name.
- ATS kind.
- ATS tenant or board identifier.
- The listing/source from which it was discovered.
- A confidence or reason describing the URL match.

Human review then adds approved definitions to the committed registry. This
keeps production behavior reviewable and prevents noisy or malicious scraped
URLs from becoming scheduled inputs.

Automatic scheduled discovery can be considered only after the proposal flow,
quality gates, source health, and rollback behavior have been exercised.

### Start with three direct ATS connectors

Implement connectors in this order:

1. Greenhouse.
2. Lever.
3. Ashby.

Each connector must:

- Use a public JSON endpoint where available.
- Supply the employer, title, location, canonical application URL, source
  identity, and exact posted date when exposed.
- Preserve a connector-specific external identifier only as source metadata;
  it does not replace the application URL key.
- Handle missing optional fields and malformed records without failing the
  entire source.
- Return a failed `SourceFetchResult` for board-level HTTP or schema failures.
- Avoid logging response bodies, tokens, query strings, or secrets.
- Be tested with `httpx.MockTransport`; tests never call live ATS endpoints.

Workday, Oracle, SmartRecruiters, Rippling, Workable, Breezy, Recruitee,
Eightfold, and company-specific systems are deferred until the first three
connectors demonstrate useful incremental coverage.

### Apply new-grad scope before persistence and Codex

Curated lists already perform substantial human filtering. Direct boards do
not, so direct candidates require an explicit deterministic scope gate.

Strong positive signals include:

- `new grad`, `new graduate`, `university graduate`, or `early career`.
- `class of 2027`.
- A graduation-date range containing Spring 2027.
- An explicit 2027 start date.
- Entry-level title families such as `Software Engineer I` when the description
  also supports zero-to-one-year or university hiring.

Hard negative signals include:

- Internship, intern, co-op, or apprenticeship scope.
- Senior, staff, principal, lead, manager, or director seniority.
- Explicit requirements for multiple years of professional experience.
- Quantitative trader, product manager, recruiter, and other already-excluded
  role families.
- Explicit timing that only targets an earlier graduating class when the
  posting does not also include Spring 2027.

Ambiguous direct-board roles must not be converted into positive Spring 2027
matches merely because they were recently posted. The scope layer may retain a
small plausible-entry-level class for Codex evaluation, but it must record
timing as unstated and apply a lower selection priority.

Keep the deterministic classifier explainable. It should return a typed result
such as:

- `include_explicit`
- `include_plausible`
- `exclude_internship`
- `exclude_seniority`
- `exclude_experience`
- `exclude_timing`
- `exclude_non_engineering`
- `exclude_unknown`

Persist or log aggregate reason counts so source tuning is evidence-based.

### Rank before selecting the 10-listing batch

The evaluation cap and persisted retry behavior remain unchanged. Replace
source-order-dependent slicing with deterministic priority ordering before a
new batch is selected.

Suggested ordering:

1. Explicit Spring/Class of 2027 timing.
2. Explicit new-grad or university-graduate wording.
3. Exact recent ATS posted date.
4. Corroboration by more than one source.
5. Plausible entry-level roles with unstated timing.

Use stable tie breakers such as posted date, first-seen time, and listing ID.
Once selected, the same persisted batch must retry until evaluated; a later
source run must not replace it.

### Isolate all source failures

Every source fetch is an independent unit:

- One source's timeout, HTTP error, or parser drift does not prevent successful
  sources from being stored.
- A run can succeed partially.
- The worker logs one sanitized summary per failed source.
- A completely failed run produces no false new, closed, or missing state.
- Existing source data is left unchanged when that source fails.

Keep fetching sequential for the first resilience refactor. Add bounded
concurrency only when direct-source volume makes it necessary and after tests
prove that results and lifecycle updates remain deterministic.

### Track source observations before closing listings

Add source-level observation fields to `ListingSource`:

- `source_key`: stable machine key.
- `first_seen_at`.
- `last_seen_at`.
- `consecutive_misses`.
- `is_active`.
- `closed_at`.

Add a `SourceRun` table containing:

- `source_key`.
- Start and finish timestamps.
- Success/failure status.
- Fetched, accepted, and newly stored counts.
- A bounded error category and sanitized summary.

All schema changes require model updates and safe additive migration logic in
`create_tables()`. PostgreSQL startup remains protected by the existing
advisory transaction lock, and SQLite migrations remain additive.

On a successful source run:

1. Upsert every observed candidate and its `ListingSource` observation.
2. Reset observed source rows to active with zero misses.
3. Increment misses only for previously active rows belonging to that
   successfully fetched source.
4. Mark a source observation inactive only after two consecutive successful
   runs omit it, protecting against transient incomplete responses.
5. Consider a listing closed only when every known source observation is
   inactive.

On a failed source run, do not increment misses or close anything.

Pre-migration provenance rows remain active until their source has been
successfully observed under the new lifecycle rules. No migration may mass
close existing listings.

The public board should eventually add `Listing.is_open`/`closed_at` or an
equivalent queryable state and show only open listings in addition to the
existing 365-day freshness rule. This visibility change belongs in the
lifecycle phase, after source observation backfill is verified.

### Preserve and improve date semantics

Direct ATS dates are generally stronger evidence than relative dates copied
into a curated list.

- Preserve the raw source date per observation when useful for diagnostics.
- Prefer an exact employer-feed posting date over a curated relative age.
- Backfill a missing listing date when a stronger source provides one.
- Do not continually move a real posting date forward.
- When exact sources conflict, retain the earliest credible original posting
  date and record the per-source observations for auditability.
- Never use the posting date itself as proof of Spring 2027 hiring timing.

### Measure incremental value

Persist or emit structured metrics for:

- Sources attempted, succeeded, and failed.
- Records fetched and accepted per source.
- Exclusion counts by deterministic scope reason.
- New listings per source.
- Listings discovered directly before appearing in a curated list.
- Cross-source duplicate/corroboration counts.
- Exact posted-date coverage.
- Time from employer posting to first detection.
- Evaluation success, failure, and backlog counts.

Start with database records plus structured logs. Do not expose a public admin
dashboard or sensitive error details as part of the initial transformation.

## Implementation sequence

### 1. Capture a baseline

- Add deterministic tests that describe the current two-source behavior and
  expected candidate counts from representative fixtures.
- Add a fixture containing overlap between the two curated sources.
- Record how URL canonicalization and multi-source provenance behave.
- Document the current source-order effect on the 10-listing selection.
- Do not call live sources while establishing the baseline.

The baseline makes it possible to distinguish coverage changes from parser
regressions.

### 2. Introduce source results and failure isolation

- Add `SourceFetchResult` and stable source keys.
- Wrap each curated-source fetch independently.
- Continue ingesting successful results when one source fails.
- Return run-level information alongside the flattened candidate list without
  breaking database transaction boundaries.
- Add tests for:
  - First source fails, second succeeds.
  - Second source fails, first succeeds.
  - Both fail.
  - Parser returns zero candidates.
  - Malformed rows do not poison valid rows.
- Preserve all existing `Candidate` and URL behavior.

This phase should not change which successful rows are accepted.

### 3. Add source-run observability

- Add the `SourceRun` model and table.
- Persist one run record per attempted source.
- Sanitize and bound stored errors.
- Include fetched, accepted, and new counts.
- Add additive-migration tests for both a fresh database and a database with
  the current schema.
- Add worker summary logging for partial and total source failure.

Do not implement closure semantics in the same change. First prove that source
success and failure are recorded correctly.

### 4. Refactor connectors behind a normalized interface

- Move Markdown-specific parsing behind a curated Markdown connector.
- Keep compatibility imports from `app.sources` while call sites and tests
  transition.
- Add the reviewed source registry containing the two existing curated sources.
- Ensure ingestion consumes normalized `Candidate` objects without knowing
  which connector produced them.
- Run the full test suite because this touches shared ingestion behavior.

### 5. Build ATS discovery proposals

- Recognize Greenhouse, Lever, and Ashby tenant identifiers from stored
  application URLs.
- Generate deterministic, sorted proposals.
- Deduplicate proposals by ATS kind and tenant.
- Include discovery provenance.
- Default to read-only output.
- Require an explicit path/flag to write a reviewed registry update.
- Test URLs with tracking parameters, redirects encoded as query parameters,
  malformed tenants, and unsupported hosts.

Do not automatically enable discovered boards in the scheduled worker.

### 6. Implement the direct-source pilot

- Add mocked Greenhouse, Lever, and Ashby connectors.
- Add the deterministic direct-source scope classifier.
- Approve a small pilot registry drawn from employers already present in the
  curated new-grad data.
- Start with no more than roughly 10–25 boards across the three ATS types.
- Preserve the source display hierarchy in web and email provenance.
- Verify that direct-source candidates do not displace stronger explicit-2027
  candidates merely due to registry order.

Live pilot fetching is an external effect and must be explicitly requested.
Implementation verification uses recorded or hand-built fixtures only.

### 7. Add deterministic evaluation priority

- Add a small typed priority function based only on stored listing/source
  evidence.
- Order newly eligible listings before taking the maximum of 10.
- Preserve `fit_selected_at` retry semantics.
- Add tests showing:
  - Explicit 2027 roles outrank ambiguous roles.
  - Source registry order does not change selection.
  - An already selected failed batch is retried unchanged.
  - No more than 10 new listings are selected.

The priority score is queue ordering, not offer probability and not a
replacement for either Codex score.

### 8. Add per-source lifecycle

- Add the `ListingSource` observation fields and safe additive migrations.
- Backfill stable keys for the two curated sources without closing any rows.
- Update observations only after successful fetches.
- Require two successful misses before deactivating an observation.
- Compute listing closure only after every source observation is inactive.
- Update the visible-listing query to require open state while retaining the
  365-day cutoff.
- Decide and test reopening behavior. A reopened application URL should become
  visible again, but it should not automatically trigger a duplicate digest
  until notification semantics are explicitly defined.
- Add eager loading where lifecycle or provenance is used after session close.

### 9. Evaluate the pilot before expanding

Run the pilot for a defined observation window only after deployment is
authorized. Compare:

- Direct-only discoveries.
- How much earlier direct sources find roles.
- False positives admitted by deterministic filtering.
- ATS failure rates and response stability.
- Evaluation backlog pressure.
- Duplicate/corroboration behavior.
- Added run duration.

Expand connectors or boards only when the measurements justify it. Prefer
adding high-yield boards over indiscriminate registry growth.

### 10. Consider later connectors

After the pilot is stable, evaluate connector additions in measured order.
Workday and Oracle should be treated as later projects because tenant shapes,
pagination, access behavior, and failure modes are more complex.

Each new connector requires:

- A documented public endpoint and rate-limit approach.
- Mocked success, pagination, malformed-record, timeout, and HTTP-error tests.
- At least one reviewed source definition.
- Source-health integration.
- Evidence that it adds relevant new-grad coverage.

## Verification

For every implementation phase, run focused tests while iterating and the full
suite before handoff:

```sh
uv run python -m pytest -q
uv run python -m compileall -q app tests
docker compose config --quiet
```

Schema phases must additionally test:

- Fresh SQLite table creation.
- Additive migration from the current SQLite schema.
- Idempotent repeated `create_tables()` calls.
- PostgreSQL-safe SQL construction and concurrent-start assumptions through
  existing migration tests or a controlled Compose database test.

Connector tests use `httpx.MockTransport`. Worker tests monkeypatch source
fetching and Codex subprocess calls. No verification command may call live job
boards, SMTP, or Codex.

## Acceptance criteria

- A failure in one curated or direct source does not block successful sources.
- Failed sources never cause listings to be marked missing or closed.
- Existing curated-source coverage and provenance remain intact.
- Greenhouse, Lever, and Ashby share one normalized candidate interface.
- Direct candidates pass an explicit new-grad scope gate before persistence.
- Internship-style posting-date inference is never used for Spring 2027
  eligibility.
- The application still evaluates at most 10 newly selected listings, and a
  failed batch retries unchanged.
- Selection priority is deterministic and independent of registry order.
- `Listing.application_url` remains the deduplication key.
- Exact ATS dates can backfill missing dates without shifting established dates
  forward.
- Listing closure requires successful source observations and tolerates a
  transient omission.
- Schema startup remains additive and safe when web and worker containers start
  concurrently.
- All connector and worker tests are fully mocked.
- No new runtime framework or service is introduced.
- No secrets, live response dumps, credentials, database files, or generated
  caches are added to Git.

## Rollout and rollback

Implement each numbered phase as a separate logical change. Do not commit any
phase unless explicitly requested.

Recommended rollout:

1. Deploy failure isolation and source-run observation with only the two
   existing sources enabled.
2. Confirm several normal scheduled runs before enabling any ATS source.
3. Enable a small direct-source pilot without lifecycle-based hiding.
4. Measure relevance and stability.
5. Enable lifecycle visibility only after observation backfill and miss
   handling are proven.
6. Expand the registry gradually.

Feature flags or registry `enabled` fields should allow direct sources and
lifecycle hiding to be disabled independently.

Rollback must be additive and data-preserving:

- Disable direct source definitions instead of deleting their listings.
- Stop applying lifecycle visibility rather than erasing observation history.
- Keep new nullable columns and tables in place if older application code can
  safely ignore them.
- Never use destructive schema rollback, broad Git cleanup, or database resets
  to reverse a rollout.

## References

- Current source implementation: `app/sources.py`
- Current persistence behavior: `app/ingestion.py`
- Current worker selection/evaluation: `app/worker.py`
- Current models and migrations: `app/models.py`, `app/database.py`
- Architectural reference studied independently:
  <https://github.com/zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships>
