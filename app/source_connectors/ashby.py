"""Ashby public job-board connector."""

from datetime import datetime, timezone

import httpx

from app.source_connectors.common import clean_description, failed_result, parse_iso_date
from app.source_scope import scope_direct_candidates
from app.source_types import Candidate, SourceFetchResult, SourceSpec
from app.source_utils import canonicalize_url


def fetch(spec: SourceSpec, client: httpx.Client) -> SourceFetchResult:
    started_at = datetime.now(timezone.utc)
    tenant = spec.parameters["tenant"]
    try:
        response = client.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{tenant}",
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise ValueError("Ashby response has no jobs list")
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
        return failed_result(spec, error, started_at)

    candidates: list[Candidate] = []
    malformed_count = 0
    for record in records:
        if not isinstance(record, dict):
            malformed_count += 1
            continue
        title = record.get("title")
        application_url = record.get("jobUrl") or record.get("applyUrl")
        external_id = record.get("id") or record.get("jobPostingId")
        if not isinstance(title, str) or not isinstance(application_url, str) or external_id is None:
            malformed_count += 1
            continue
        posted_at = parse_iso_date(record.get("publishedAt"))
        candidates.append(Candidate(
            company=spec.parameters.get("employer", spec.name),
            title=title.strip(),
            location=record.get("location", "") if isinstance(record.get("location"), str) else "",
            application_url=canonicalize_url(application_url),
            source_name=spec.name,
            source_url=spec.public_url,
            salary=(
                record.get("compensationTierSummary", "")
                if isinstance(record.get("compensationTierSummary"), str)
                else ""
            ),
            posted_at=posted_at,
            source_key=spec.key,
            source_external_id=str(external_id),
            source_kind=spec.kind,
            description_text=clean_description(
                record.get("descriptionPlain") or record.get("descriptionHtml"),
            ),
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
