import base64
from datetime import date, datetime, timezone
import json

import httpx

from app.config import Settings
from app.github_publisher import (
    README_END_MARKER,
    README_START_MARKER,
    publish_jobs_section,
    render_jobs_section,
    replace_generated_jobs,
)
from app.models import Listing


def listing(
    company: str,
    *,
    posted_at: date | None = date(2026, 7, 25),
    confidence: int | None = 82,
) -> Listing:
    return Listing(
        company=company,
        title="Software | Engineer\nNew Grad",
        location="Remote",
        salary="$100k–$120k",
        application_url="https://jobs.example/apply/(new grad)?a=1&b=2",
        posted_at=posted_at,
        first_seen_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        fit_confidence=confidence,
        resume_fit_confidence=99,
        resume_fit_reasoning="Private candidate-specific reasoning.",
    )


def config() -> Settings:
    return Settings(
        github_publish_token="secret-token",
        github_publish_repository="owner/repository",
        github_publish_branch="main",
    )


def encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def readme(section: str = "Old table", *, suffix: str = "## Documentation") -> str:
    return (
        "# Project\n\n"
        f"{README_START_MARKER}\n"
        f"{section}\n"
        f"{README_END_MARKER}\n\n"
        f"{suffix}\n"
    )


def test_render_jobs_section_escapes_values_and_omits_resume_fit():
    scored = listing("Acme | Labs <script>alert(1)</script> & Co.")
    pending = listing("Pending", posted_at=None, confidence=None)
    pending.location = ""
    pending.salary = ""
    failed = listing("Failed", confidence=75)
    failed.fit_evaluation_failed_at = datetime(2026, 7, 26, tzinfo=timezone.utc)

    section = render_jobs_section(
        [scored, pending, failed],
        public_url="https://board.example/",
    )

    assert "3 open roles currently listed." in section
    assert "[Browse the searchable job board](https://board.example)." in section
    assert "Acme \\| Labs" in section
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; Co." in section
    assert "<script>" not in section
    assert "Software \\| Engineer New Grad" in section
    assert "| 82% | 2026-07-25 |" in section
    assert "| Pending | First seen 2026-07-24 |" in section
    assert "| Evaluation failed | 2026-07-25 |" in section
    assert "[Apply](https://jobs.example/apply/%28new%20grad%29?a=1&b=2)" in section
    assert "99" not in section
    assert "Private candidate-specific reasoning." not in section


def test_replace_generated_jobs_preserves_hand_written_readme():
    original = readme(suffix="Human-authored documentation")

    updated = replace_generated_jobs(original, "## Current Openings\n\nNew table")

    assert updated.startswith("# Project\n\n")
    assert "Human-authored documentation" in updated
    assert f"{README_START_MARKER}\n## Current Openings" in updated
    assert f"New table\n{README_END_MARKER}" in updated
    assert "Old table" not in updated


def test_replace_generated_jobs_rejects_missing_or_reversed_markers():
    for invalid in (
        "# README without markers",
        f"{README_END_MARKER}\nold\n{README_START_MARKER}",
        f"{README_START_MARKER}\none\n{README_START_MARKER}\ntwo\n{README_END_MARKER}",
    ):
        try:
            replace_generated_jobs(invalid, "new")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid README markers should be rejected")


def test_publish_jobs_section_updates_readme_with_current_sha():
    original = readme()
    captured = {}

    def handler(request: httpx.Request):
        assert request.url.path == "/repos/owner/repository/contents/README.md"
        if request.method == "GET":
            assert request.url.params["ref"] == "main"
            return httpx.Response(200, json={
                "encoding": "base64",
                "content": encoded(original),
                "sha": "old-sha",
            })
        payload = json.loads(request.content)
        captured.update(payload)
        return httpx.Response(200, json={"content": {"sha": "new-sha"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        status = publish_jobs_section("## Current Openings\n\nNew table", config=config(), client=client)

    assert status == "published"
    assert captured["sha"] == "old-sha"
    assert captured["branch"] == "main"
    assert captured["message"] == "Update generated jobs table"
    updated = base64.b64decode(captured["content"]).decode()
    assert "New table" in updated
    assert "## Documentation" in updated


def test_publish_jobs_section_skips_unchanged_readme():
    section = "## Current Openings\n\nCurrent table"
    current = readme(section)
    methods = []

    def handler(request: httpx.Request):
        methods.append(request.method)
        return httpx.Response(200, json={
            "encoding": "base64",
            "content": encoded(current),
            "sha": "current-sha",
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        status = publish_jobs_section(section, config=config(), client=client)

    assert status == "unchanged"
    assert methods == ["GET"]


def test_publish_jobs_section_refetches_conflict_and_preserves_human_edit():
    first_readme = readme()
    edited_readme = readme(suffix="Documentation edited during publishing")
    get_count = 0
    put_count = 0
    final_readme = ""

    def handler(request: httpx.Request):
        nonlocal get_count, put_count, final_readme
        if request.method == "GET":
            get_count += 1
            remote = first_readme if get_count == 1 else edited_readme
            return httpx.Response(200, json={
                "encoding": "base64",
                "content": encoded(remote),
                "sha": f"sha-{get_count}",
            })
        put_count += 1
        if put_count == 1:
            return httpx.Response(409, json={"message": "Conflict"})
        payload = json.loads(request.content)
        assert payload["sha"] == "sha-2"
        final_readme = base64.b64decode(payload["content"]).decode()
        return httpx.Response(200, json={"content": {"sha": "new-sha"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        status = publish_jobs_section("## Current Openings\n\nNew table", config=config(), client=client)

    assert status == "published"
    assert get_count == 2
    assert put_count == 2
    assert "Documentation edited during publishing" in final_readme
    assert "New table" in final_readme


def test_publish_jobs_section_is_disabled_without_credentials_and_handles_bad_readme():
    assert publish_jobs_section(
        "table",
        config=Settings(github_publish_token="", github_publish_repository=""),
    ) == "disabled"

    def handler(_: httpx.Request):
        return httpx.Response(200, json={
            "encoding": "base64",
            "content": encoded("# README without markers"),
            "sha": "sha",
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert publish_jobs_section("table", config=config(), client=client) == "failed"
