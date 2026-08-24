from datetime import date

import httpx

from app.source_connectors import fetch_source
from app.source_types import SourceSpec


def aggregate_spec(feed_format: str = "markdown") -> SourceSpec:
    return SourceSpec(
        key=f"aggregate:{feed_format}",
        name="Aggregate Feed",
        kind="aggregate",
        public_url="https://github.com/example/jobs",
        parameters={
            "feed_url": "https://raw.githubusercontent.com/example/jobs",
            "format": feed_format,
        },
    )


def fetch_body(body: str, feed_format: str = "markdown"):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=body),
        ),
    ) as client:
        return fetch_source(aggregate_spec(feed_format), client)


def test_markdown_aggregate_strictly_scopes_roles_and_uses_direct_links():
    body = """# 2027 jobs
| Company | Role | Location | Posted | Apply |
|---|---|---|---|---|
| Acme | Software Engineer, New Grad 2027 | New York, NY | 2026-08-24 | [Apply](https://jobs.example/new-grad?utm_source=list) |
| Beta | Software Engineer I | Remote | 1d | [Apply](https://jobs.example/entry) |
| Senior Co | Senior Platform Software Engineer | Remote | Today | [Apply](https://jobs.example/senior) |
| Intern Co | Software Engineering Intern | Remote | Today | [Apply](https://jobs.example/intern) |
| Generic Co | Platform Software Engineer | Remote | Today | [Apply](https://jobs.example/generic) |
| Civil Co | Civil Engineer, New Grad 2027 | Remote | Today | [Apply](https://jobs.example/civil) |
| Old Co | New Grad Software Engineer, 2026 Start | Remote | Today | [Apply](https://jobs.example/old) |
| Broken Co | Junior Software Engineer | Remote | Today | — |
"""

    result = fetch_body(body)

    assert result.succeeded is True
    assert result.fetched_count == 8
    assert [candidate.company for candidate in result.candidates] == ["Acme", "Beta"]
    assert result.candidates[0].application_url == "https://jobs.example/new-grad"
    assert result.candidates[0].posted_at == date(2026, 8, 24)
    assert result.candidates[0].exact_posted_date is True
    assert result.candidates[0].timing_explicit is True
    assert result.candidates[1].scope_decision == "include_plausible"
    assert dict(result.exclusion_counts) == {
        "exclude_internship": 1,
        "exclude_non_engineering": 1,
        "exclude_seniority": 1,
        "exclude_timing": 1,
        "exclude_unknown": 2,
    }


def test_jobright_format_uses_title_link_and_inherits_continuation_company():
    body = """# Jobs
| Company | Job Title | Location | Work Model | Date Posted |
|---|---|---|---|---|
| **[Acme](https://acme.example)** | **[Jr. Software Developer](https://jobright.ai/jobs/info/one?utm_source=list)** | Boston, MA | Hybrid | Aug 24 |
| ↳ | **[Software Engineer - 2027 Start](https://jobright.ai/jobs/info/two?utm_campaign=swe)** | Austin, TX | On Site | Aug 23 |
| **[Intern Co](https://intern.example)** | **[Software Engineering Intern](https://jobright.ai/jobs/info/intern)** | Remote | Remote | Aug 22 |
"""

    result = fetch_body(body, "markdown_title_link")

    assert result.fetched_count == 3
    assert [(candidate.company, candidate.application_url) for candidate in result.candidates] == [
        ("Acme", "https://jobright.ai/jobs/info/one"),
        ("Acme", "https://jobright.ai/jobs/info/two"),
    ]
    assert dict(result.exclusion_counts) == {"exclude_internship": 1}


def test_simplify_html_uses_employer_link_and_skips_closed_and_senior_rows():
    body = """<table><tbody>
<tr><td><strong><a href="https://simplify.jobs/c/Acme">🔥 Acme</a></strong></td><td>Software Engineer I</td><td>Boston, MA<br>Remote</td><td><a href="https://jobs.example/one?utm_source=Simplify"><img alt="Apply"></a><a href="https://simplify.jobs/p/one">Simplify</a></td><td>0d</td></tr>
<tr><td>↳</td><td>Software Engineer - 2027 Start</td><td>Austin, TX</td><td><a href="https://jobs.example/two">Apply</a></td><td>2026-08-23</td></tr>
<tr><td>Closed</td><td>Junior Software Engineer</td><td>Remote</td><td>🔒</td><td>2d</td></tr>
<tr><td>Senior</td><td>Senior Software Engineer</td><td>Remote</td><td><a href="https://jobs.example/senior">Apply</a></td><td>2d</td></tr>
</tbody></table>"""

    result = fetch_body(body, "simplify_html")

    assert result.fetched_count == 4
    assert [(candidate.company, candidate.application_url) for candidate in result.candidates] == [
        ("Acme", "https://jobs.example/one"),
        ("Acme", "https://jobs.example/two"),
    ]
    assert result.candidates[0].location == "Boston, MA; Remote"
    assert result.candidates[1].exact_posted_date is True
    assert dict(result.exclusion_counts) == {
        "exclude_seniority": 1,
        "exclude_unknown": 1,
    }


def test_retired_source_returns_empty_success_without_network_request():
    requested = []
    spec = SourceSpec(
        key="json:retired",
        name="Retired Feed",
        kind="retired",
        public_url="https://github.com/example/retired",
        parameters={},
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: requested.append(request) or httpx.Response(500),
        ),
    ) as client:
        result = fetch_source(spec, client)

    assert result.succeeded is True
    assert result.fetched_count == 0
    assert result.candidates == ()
    assert requested == []
