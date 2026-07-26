import base64
from collections.abc import Iterable
from html import escape
import logging
from typing import Literal
from urllib.parse import quote

import httpx

from app.config import Settings, settings
from app.models import Listing

logger = logging.getLogger(__name__)

README_START_MARKER = "<!-- BEGIN GENERATED JOBS -->"
README_END_MARKER = "<!-- END GENERATED JOBS -->"
GITHUB_API_VERSION = "2022-11-28"
PublishStatus = Literal["disabled", "unchanged", "published", "failed"]


def _markdown_cell(value: object) -> str:
    text = escape(" ".join(str(value).split()), quote=False)
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _markdown_url(url: str) -> str:
    return quote(url, safe=":/?#[]@!$&'*+,;=%-._~")


def _fit_summary(listing: Listing) -> str:
    if listing.fit_evaluation_failed_at is not None:
        if listing.fit_evaluation_error:
            return f"Evaluation failed — {listing.fit_evaluation_error}"
        return "Evaluation failed"
    if listing.fit_confidence is None:
        return "Pending"
    if listing.fit_reasoning:
        return f"{listing.fit_confidence}% — {listing.fit_reasoning}"
    return f"{listing.fit_confidence}%"


def _posted_label(listing: Listing) -> str:
    if listing.posted_at is not None:
        return listing.posted_at.isoformat()
    if listing.source_age:
        return listing.source_age
    if listing.first_seen_at is not None:
        return f"First seen {listing.first_seen_at.date().isoformat()}"
    return "Unknown"


def render_jobs_section(
    listings: Iterable[Listing],
    *,
    public_url: str = "",
) -> str:
    jobs = list(listings)
    noun = "role" if len(jobs) == 1 else "roles"
    summary = f"{len(jobs)} open {noun} currently listed."
    if public_url:
        summary += (
            " "
            f"[Browse the searchable job board]({_markdown_url(public_url.rstrip('/'))})."
        )

    lines = [
        "## Current Openings",
        "",
        summary,
        "",
        "| Company | Role | Location | Is Spring 2027 New Grad | Posted | Application |",
        "|---|---|---|---|---|---|",
    ]
    for listing in jobs:
        values = (
            listing.company,
            listing.title,
            listing.location or "—",
            _fit_summary(listing),
            _posted_label(listing),
        )
        cells = [_markdown_cell(value) for value in values]
        apply_link = f"[Apply]({_markdown_url(listing.application_url)})"
        lines.append(f"| {' | '.join([*cells, apply_link])} |")
    return "\n".join(lines)


def replace_generated_jobs(readme: str, generated_section: str) -> str:
    if readme.count(README_START_MARKER) != 1 or readme.count(README_END_MARKER) != 1:
        raise ValueError("README must contain exactly one generated-jobs marker pair")
    start = readme.index(README_START_MARKER) + len(README_START_MARKER)
    end = readme.index(README_END_MARKER)
    if start > end:
        raise ValueError("README generated-jobs markers are reversed")
    return (
        readme[:start]
        + "\n"
        + generated_section.strip()
        + "\n"
        + readme[end:]
    )


def _repository_parts(repository: str) -> tuple[str, str]:
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("GitHub repository must use the owner/name format")
    return parts[0], parts[1]


def _read_remote_readme(
    client: httpx.Client,
    url: str,
    branch: str,
) -> tuple[str, str]:
    response = client.get(url, params={"ref": branch})
    response.raise_for_status()
    payload = response.json()
    if payload.get("encoding") != "base64":
        raise ValueError("GitHub returned an unsupported README encoding")
    content = payload.get("content")
    sha = payload.get("sha")
    if not isinstance(content, str) or not isinstance(sha, str):
        raise ValueError("GitHub returned incomplete README metadata")
    encoded_content = "".join(content.split())
    return base64.b64decode(encoded_content, validate=True).decode("utf-8"), sha


def _publish_jobs_section(
    generated_section: str,
    *,
    config: Settings,
    client: httpx.Client,
) -> PublishStatus:
    owner, repository = _repository_parts(config.github_publish_repository)
    path = quote("README.md", safe="")
    url = (
        f"https://api.github.com/repos/{quote(owner, safe='')}/"
        f"{quote(repository, safe='')}/contents/{path}"
    )

    for attempt in range(2):
        readme, sha = _read_remote_readme(
            client,
            url,
            config.github_publish_branch,
        )
        updated_readme = replace_generated_jobs(readme, generated_section)
        if updated_readme == readme:
            return "unchanged"

        response = client.put(url, json={
            "message": "Update generated jobs table",
            "content": base64.b64encode(updated_readme.encode("utf-8")).decode("ascii"),
            "sha": sha,
            "branch": config.github_publish_branch,
        })
        if response.status_code == 409 and attempt == 0:
            continue
        response.raise_for_status()
        return "published"
    raise RuntimeError("GitHub README update conflicted repeatedly")


def publish_jobs_section(
    generated_section: str,
    *,
    config: Settings = settings,
    client: httpx.Client | None = None,
) -> PublishStatus:
    if not config.github_publish_token or not config.github_publish_repository:
        return "disabled"

    own_client = client is None
    client = client or httpx.Client(
        timeout=30,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {config.github_publish_token}",
            "User-Agent": "cs-new-grad-scraper-worker",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        status = _publish_jobs_section(
            generated_section,
            config=config,
            client=client,
        )
        if status == "published":
            logger.info(
                "Published generated jobs table to %s@%s README.md",
                config.github_publish_repository,
                config.github_publish_branch,
            )
        elif status == "unchanged":
            logger.info("GitHub README jobs table is already current")
        return status
    except Exception as error:
        status_code = (
            error.response.status_code
            if isinstance(error, httpx.HTTPStatusError)
            else None
        )
        detail = f"HTTP {status_code}" if status_code is not None else type(error).__name__
        logger.error("Could not publish GitHub README jobs table: %s", detail)
        return "failed"
    finally:
        if own_client:
            client.close()
