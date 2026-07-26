from datetime import date

import httpx
import pytest

from app.source_connectors import fetch_source
from app.source_registry import CURATED_SOURCES, DIRECT_SOURCES
from app.source_types import SourceSpec


def spec(kind: str) -> SourceSpec:
    return SourceSpec(
        key=f"{kind}:acme",
        name=f"Acme Careers ({kind})",
        kind=kind,
        public_url=f"https://jobs.example/{kind}/acme",
        parameters={"tenant": "acme", "employer": "Acme"},
    )


def test_greenhouse_connector_normalizes_and_scopes_records():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/boards/acme/jobs"
        assert request.url.params["content"] == "true"
        return httpx.Response(200, json={"jobs": [
            {
                "id": 101,
                "title": "Software Engineer, Class of 2027",
                "location": {"name": "New York, NY"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/101?gh_src=list",
                "first_published": "2026-07-20T12:00:00Z",
                "content": "<p>Start in summer 2027.</p>",
            },
            {
                "id": 102,
                "title": "Software Engineering Intern",
                "location": {"name": "Remote"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/102",
                "content": "Internship.",
            },
            {"id": 103, "title": "Software Engineer"},
        ]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_source(spec("greenhouse"), client)

    assert result.succeeded is True
    assert result.fetched_count == 3
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.application_url == (
        "https://boards.greenhouse.io/acme/jobs/101?gh_src=list"
    )
    assert candidate.source_external_id == "101"
    assert candidate.posted_at == date(2026, 7, 20)
    assert candidate.exact_posted_date is True
    assert candidate.timing_explicit is True
    assert dict(result.exclusion_counts) == {
        "exclude_internship": 1,
        "exclude_unknown": 1,
    }


def test_lever_connector_uses_hosted_url_and_entry_level_evidence():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v0/postings/acme"
        assert request.url.params["mode"] == "json"
        return httpx.Response(200, json=[
            {
                "id": "lever-1",
                "text": "Backend Engineer I",
                "categories": {"location": "Remote"},
                "hostedUrl": "https://jobs.lever.co/acme/lever-1/",
                "applyUrl": "https://jobs.lever.co/acme/lever-1/apply",
                "createdAt": 1784592000000,
                "descriptionPlain": "University candidates with 0-1 years welcome.",
            },
            {
                "id": "lever-2",
                "text": "Staff Software Engineer",
                "hostedUrl": "https://jobs.lever.co/acme/lever-2",
                "descriptionPlain": "Experienced role.",
            },
        ])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_source(spec("lever"), client)

    assert result.succeeded is True
    assert result.candidates[0].application_url == (
        "https://jobs.lever.co/acme/lever-1"
    )
    assert result.candidates[0].scope_decision == "include_plausible"
    assert result.candidates[0].posted_at == date(2026, 7, 21)
    assert dict(result.exclusion_counts) == {"exclude_seniority": 1}


def test_ashby_connector_handles_optional_fields_and_scope_exclusions():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/posting-api/job-board/acme"
        return httpx.Response(200, json={"jobs": [
            {
                "id": "ashby-1",
                "title": "New Graduate Platform Engineer",
                "location": "San Francisco, CA",
                "jobUrl": "https://jobs.ashbyhq.com/acme/ashby-1",
                "publishedAt": "2026-07-19",
                "descriptionPlain": "Early career engineering role.",
            },
            {
                "jobPostingId": "ashby-2",
                "title": "Product Manager, New Grad",
                "applyUrl": "https://jobs.ashbyhq.com/acme/ashby-2",
                "descriptionHtml": "<p>University hiring.</p>",
            },
            {
                "id": "ashby-3",
                "title": "Infrastructure Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/acme/ashby-3",
                "descriptionPlain": "Must have 5 years of experience.",
            },
        ]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_source(spec("ashby"), client)

    assert result.succeeded is True
    assert [candidate.title for candidate in result.candidates] == [
        "New Graduate Platform Engineer",
    ]
    assert result.candidates[0].scope_decision == "include_explicit"
    assert dict(result.exclusion_counts) == {
        "exclude_experience": 1,
        "exclude_non_engineering": 1,
    }


@pytest.mark.parametrize("kind", ["greenhouse", "lever", "ashby"])
def test_connector_http_failure_returns_sanitized_result(kind):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            request=request,
            text="secret response body that must not be retained",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_source(spec(kind), client)

    assert result.succeeded is False
    assert result.error_category == "http_status"
    assert result.error_summary == "Source returned HTTP 503."
    assert "secret" not in result.error_summary


def test_connector_timeout_and_board_schema_failure_are_isolated():
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("tenant-secret", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout_handler)) as client:
        timed_out = fetch_source(spec("lever"), client)
    assert timed_out.error_category == "timeout"
    assert timed_out.error_summary == "Source request timed out."

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"unexpected": []}),
        ),
    ) as client:
        malformed = fetch_source(spec("greenhouse"), client)
    assert malformed.succeeded is False
    assert malformed.error_category == "parser"


def test_direct_pilot_contains_only_the_reviewed_enabled_boards():
    assert 1 <= len(DIRECT_SOURCES) <= 25
    assert {source.kind for source in DIRECT_SOURCES} == {
        "ashby",
        "greenhouse",
        "lever",
    }
    assert {source.key for source in DIRECT_SOURCES if source.enabled} == {
        "ashby:ramp",
        "greenhouse:figma",
        "lever:palantir",
    }
    assert [source.key for source in CURATED_SOURCES] == [
        "markdown:speedyapply-2027-swe",
        "markdown:vansh-new-grad-2027",
    ]
    assert all(source.enabled is True for source in CURATED_SOURCES)
