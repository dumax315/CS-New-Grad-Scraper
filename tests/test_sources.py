from datetime import date
from pathlib import Path

import httpx

from app.sources import SOURCES, Source, canonicalize_url, fetch_candidates, parse_posted_date, parse_source


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
        return httpx.Response(200, text=bodies[str(request.url)])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        candidates = fetch_candidates(client)

    assert requested_urls == [source.raw_url for source in SOURCES]
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
