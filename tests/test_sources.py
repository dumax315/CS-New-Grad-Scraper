from datetime import date
from pathlib import Path

import httpx

from app.sources import (
    SOURCES,
    Source,
    canonicalize_url,
    fetch_candidates,
    fetch_source_batch,
    parse_posted_date,
    parse_source,
)


TEST_SOURCE = Source("Test", "https://example.test/raw", "https://example.test")
FIXTURES = Path(__file__).parent / "fixtures"


def test_parser_extracts_swe_rows_and_excludes_quant_rows():
    markdown = """## SWE
| Company | Position | Location | Salary | Posting | Age |
|---|---|---|---|---|---|
| Acme | New Grad 2027 Software Engineer | Seattle, WA | $100k | [Apply](https://jobs.example/1?utm_source=list) | 1d |
| Fund | Quantitative Developer | New York, NY | $200k | [Apply](https://jobs.example/2) | 1d |
"""
    jobs = parse_source(markdown, TEST_SOURCE)
    assert len(jobs) == 1
    assert jobs[0].company == "Acme"
    assert jobs[0].graduation_year == 2027
    assert jobs[0].application_url == "https://jobs.example/1"
    assert jobs[0].category == "SWE"


def test_parser_handles_apply_column_and_missing_optional_values():
    markdown = """### Other
| Company | Role | Location | Apply | Date |
|---|---|---|---|---|
| Acme | Backend Developer | Remote | [Apply now](https://jobs.example/a/) | Today |
"""
    jobs = parse_source(markdown, TEST_SOURCE)
    assert jobs[0].title == "Backend Developer"
    assert jobs[0].source_age == "Today"


def test_parser_converts_relative_and_calendar_post_dates():
    today = date(2026, 7, 23)
    assert parse_posted_date("1d", today) == date(2026, 7, 22)
    assert parse_posted_date("Jul 09", today) == date(2026, 7, 9)
    assert parse_posted_date("2026-07-09", today) == date(2026, 7, 9)


def test_canonicalization_removes_tracking_and_fragment():
    assert canonicalize_url("HTTPS://Jobs.Example/a/?utm_medium=x&keep=y#top") == "https://jobs.example/a?keep=y"


def test_parser_supports_html_links_used_by_live_github_feeds():
    markdown = """### FAANG+
| Company | Position | Location | Posting | Age |
|---|---|---|---|---|
| <a href="https://company.example"><strong>Acme</strong></a> | Software Engineer | Remote | <a href="https://jobs.example/role"><img src="apply.svg" /></a> | 0d |
"""
    jobs = parse_source(markdown, TEST_SOURCE)
    assert jobs[0].company == "Acme"
    assert jobs[0].application_url == "https://jobs.example/role"


def test_parser_supports_application_link_and_date_posted_headers():
    markdown = """## The List
| Company | Role | Location | Application/Link | Date Posted |
| --- | --- | --- | :---: | :---: |
| **Acme** | Software Engineer I | Remote | <a href="https://jobs.example/role"><img src="apply.svg"></a> | Jul 09 |
"""
    jobs = parse_source(markdown, TEST_SOURCE)
    assert jobs[0].company == "Acme"
    assert jobs[0].source_age == "Jul 09"


def test_two_source_baseline_preserves_counts_order_and_canonical_overlap():
    bodies = {
        SOURCES[0].raw_url: (FIXTURES / "speedyapply_new_grad.md").read_text(),
        SOURCES[1].raw_url: (FIXTURES / "vansh_new_grad.md").read_text(),
    }
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        url = str(request.url)
        if url in bodies:
            return httpx.Response(200, text=bodies[url])
        if request.url.host == "api.lever.co":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"jobs": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        candidates = fetch_candidates(client)

    assert requested_urls[:2] == [source.raw_url for source in SOURCES]
    assert len(requested_urls) == 5
    assert [candidate.company for candidate in candidates] == [
        "Acme",
        "Beta",
        "Acme Incorporated",
        "Gamma",
    ]
    assert [candidate.source_name for candidate in candidates] == [
        SOURCES[0].name,
        SOURCES[0].name,
        SOURCES[1].name,
        SOURCES[1].name,
    ]
    assert candidates[0].application_url == candidates[2].application_url
    assert candidates[0].application_url == "https://boards.greenhouse.io/acme/jobs/100"


def fetch_batch_with_statuses(statuses):
    valid_markdown = (FIXTURES / "speedyapply_new_grad.md").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses[str(request.url)]
        return httpx.Response(status, text=valid_markdown)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return fetch_source_batch(client, SOURCES)


def test_first_source_failure_does_not_block_second_source():
    batch = fetch_batch_with_statuses({
        SOURCES[0].raw_url: 503,
        SOURCES[1].raw_url: 200,
    })

    assert [result.succeeded for result in batch.results] == [False, True]
    assert batch.failed_count == 1
    assert len(batch.candidates) == 2
    assert {candidate.source_key for candidate in batch.candidates} == {SOURCES[1].key}
    assert batch.results[0].error_category == "http_status"
    assert batch.results[0].error_summary == "Source returned HTTP 503."


def test_second_source_failure_does_not_block_first_source():
    batch = fetch_batch_with_statuses({
        SOURCES[0].raw_url: 200,
        SOURCES[1].raw_url: 500,
    })

    assert [result.succeeded for result in batch.results] == [True, False]
    assert len(batch.candidates) == 2
    assert {candidate.source_key for candidate in batch.candidates} == {SOURCES[0].key}


def test_both_source_failures_return_an_empty_batch_without_raising():
    batch = fetch_batch_with_statuses({
        SOURCES[0].raw_url: 429,
        SOURCES[1].raw_url: 503,
    })

    assert batch.succeeded_count == 0
    assert batch.failed_count == 2
    assert batch.candidates == []


def test_successful_empty_source_is_not_reported_as_failed():
    empty_markdown = "# No current roles\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=empty_markdown)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batch = fetch_source_batch(client, (SOURCES[0],))

    assert batch.results[0].succeeded is True
    assert batch.results[0].fetched_count == 0
    assert batch.results[0].candidates == ()


def test_malformed_rows_do_not_poison_valid_rows():
    markdown = """## SWE
| Company | Position | Location | Posting | Age |
|---|---|---|---|---|
| Broken | Software Engineer |
| Valid | Software Engineer | Remote | [Apply](https://jobs.example/valid) | Today |
"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=markdown)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batch = fetch_source_batch(client, (SOURCES[0],))

    assert batch.results[0].succeeded is True
    assert [candidate.company for candidate in batch.candidates] == ["Valid"]
