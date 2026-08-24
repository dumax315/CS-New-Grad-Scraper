"""Connector for ApplyGuy's machine-readable 2027 new-grad feed."""

from collections import Counter
from datetime import datetime, timezone
import re

import httpx

from app.source_connectors.common import failed_result, parse_iso_date
from app.source_scope import ScopeResult, classify_direct_candidate
from app.source_types import Candidate, SourceFetchResult, SourceSpec
from app.source_utils import canonicalize_url

YEAR_RE = re.compile(r"\b(20(?:2[5-9]|[3-9]\d))\b")
SWE_TITLE_RE = re.compile(
    r"\b(?:software|swe|developer|programmer|backend|back[ -]?end|frontend|"
    r"front[ -]?end|full[ -]?stack|web|mobile|ios|android|devops|devsecops|"
    r"site reliability|sre|platform|infrastructure|cloud|data engineer(?:ing)?|"
    r"machine learning|ml engineer(?:ing)?|ai engineer(?:ing)?|"
    r"security engineer(?:ing)?|cybersecurity|embedded|firmware|sdet|"
    r"quality assurance|qa engineer(?:ing)?|test automation)\b",
    re.I,
)
SUPPORTED_ELIGIBILITY = {"Entry Level", "New Grad"}


def _scope_result(title: str, eligibility: str) -> ScopeResult:
    result = classify_direct_candidate(title, eligibility)
    if result.code != "exclude_unknown":
        return result
    if eligibility == "New Grad":
        return ScopeResult("include_explicit", "curated new-grad eligibility")
    if eligibility == "Entry Level":
        return ScopeResult("include_plausible", "curated entry-level eligibility")
    return result


def fetch(spec: SourceSpec, client: httpx.Client) -> SourceFetchResult:
    started_at = datetime.now(timezone.utc)
    try:
        response = client.get(spec.parameters["feed_url"])
        response.raise_for_status()
        payload = response.json()
        records = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise ValueError("ApplyGuy response has no jobs list")
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
        return failed_result(spec, error, started_at)

    candidates: list[Candidate] = []
    exclusion_counts: Counter[str] = Counter()
    for record in records:
        if not isinstance(record, dict):
            exclusion_counts["exclude_unknown"] += 1
            continue
        company = record.get("company")
        title = record.get("title")
        location = record.get("location")
        eligibility = record.get("eligibility")
        application_url = record.get("listingUrl")
        external_id = record.get("id")
        if (
            not isinstance(company, str)
            or not company.strip()
            or not isinstance(title, str)
            or not title.strip()
            or eligibility not in SUPPORTED_ELIGIBILITY
            or not isinstance(application_url, str)
            or not application_url.startswith(("http://", "https://"))
            or external_id is None
        ):
            exclusion_counts["exclude_unknown"] += 1
            continue
        if not SWE_TITLE_RE.search(title):
            exclusion_counts["exclude_non_engineering"] += 1
            continue

        scope_result = _scope_result(title, eligibility)
        if not scope_result.included:
            exclusion_counts[scope_result.code] += 1
            continue

        posted_at = parse_iso_date(record.get("posted"))
        year_match = YEAR_RE.search(title)
        graduation_year = int(year_match.group(1)) if year_match else None
        candidates.append(Candidate(
            company=company.strip(),
            title=title.strip(),
            location=location.strip() if isinstance(location, str) else "",
            application_url=canonicalize_url(application_url),
            source_name=spec.name,
            source_url=spec.public_url,
            category="Software Engineering",
            source_age=(
                record.get("age", "")
                if isinstance(record.get("age"), str)
                else ""
            ),
            posted_at=posted_at,
            graduation_year=graduation_year,
            source_key=spec.key,
            source_external_id=str(external_id),
            source_kind=spec.kind,
            scope_decision=scope_result.code,
            timing_explicit=(
                scope_result.timing_explicit or graduation_year == 2027
            ),
            exact_posted_date=posted_at is not None,
        ))

    return SourceFetchResult(
        source_key=spec.key,
        source_name=spec.name,
        succeeded=True,
        candidates=tuple(candidates),
        fetched_count=len(records),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        exclusion_counts=tuple(sorted(exclusion_counts.items())),
    )
