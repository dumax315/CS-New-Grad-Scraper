from datetime import date

from app.sources import Source, canonicalize_url, parse_posted_date, parse_source


TEST_SOURCE = Source("Test", "https://example.test/raw", "https://example.test")


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
