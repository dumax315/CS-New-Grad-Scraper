"""Lever public postings connector."""

from datetime import datetime, timezone

import httpx

from app.source_connectors.common import clean_description, failed_result
from app.source_scope import scope_direct_candidates
from app.source_types import Candidate, SourceFetchResult, SourceSpec
from app.source_utils import canonicalize_url


def epoch_milliseconds_date(value: object):
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def fetch(spec: SourceSpec, client: httpx.Client) -> SourceFetchResult:
    started_at = datetime.now(timezone.utc)
    tenant = spec.parameters["tenant"]
    try:
        response = client.get(
            f"https://api.lever.co/v0/postings/{tenant}",
            params={"mode": "json"},
        )
        response.raise_for_status()
        records = response.json()
        if not isinstance(records, list):
            raise ValueError("Lever response is not a postings list")
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
        return failed_result(spec, error, started_at)

    candidates: list[Candidate] = []
    malformed_count = 0
    for record in records:
        if not isinstance(record, dict):
            malformed_count += 1
            continue
        title = record.get("text")
        application_url = record.get("hostedUrl") or record.get("applyUrl")
        external_id = record.get("id")
        if not isinstance(title, str) or not isinstance(application_url, str) or external_id is None:
            malformed_count += 1
            continue
        categories = record.get("categories")
        location = categories.get("location", "") if isinstance(categories, dict) else ""
        posted_at = epoch_milliseconds_date(record.get("createdAt"))
        description = "\n".join(
            value
            for value in (
                record.get("descriptionPlain"),
                record.get("additionalPlain"),
            )
            if isinstance(value, str)
        )
        candidates.append(Candidate(
            company=spec.parameters.get("employer", spec.name),
            title=title.strip(),
            location=location if isinstance(location, str) else "",
            application_url=canonicalize_url(application_url),
            source_name=spec.name,
            source_url=spec.public_url,
            posted_at=posted_at,
            source_key=spec.key,
            source_external_id=str(external_id),
            source_kind=spec.kind,
            description_text=clean_description(description),
            exact_posted_date=posted_at is not None,
        ))
    accepted, exclusions = scope_direct_candidates(
        candidates,
        malformed_count=malformed_count,
    )
    return SourceFetchResult(
        source_key=spec.key,
        source_name=spec.name,
        succeeded=True,
        candidates=accepted,
        fetched_count=len(records),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        exclusion_counts=exclusions,
    )
