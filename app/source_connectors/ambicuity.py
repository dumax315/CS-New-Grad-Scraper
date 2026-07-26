"""Connector for Ambicuity's machine-readable new-grad feed."""

from collections import Counter
from datetime import datetime, timezone
import re

import httpx

from app.source_connectors.common import clean_description, failed_result, parse_iso_date
from app.source_scope import scope_direct_candidates
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


def _salary_text(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    minimum = value.get("min")
    maximum = value.get("max")
    if (
        not isinstance(minimum, (int, float))
        or isinstance(minimum, bool)
        or not isinstance(maximum, (int, float))
        or isinstance(maximum, bool)
    ):
        return ""
    currency = value.get("currency")
    currency_label = currency if isinstance(currency, str) else ""
    symbol = "$" if currency_label == "USD" else ""
    suffix = "" if symbol or not currency_label else f" {currency_label}"
    return (
        f"{symbol}{minimum:,.0f}–{symbol}{maximum:,.0f}{suffix}"
    )


def fetch(spec: SourceSpec, client: httpx.Client) -> SourceFetchResult:
    started_at = datetime.now(timezone.utc)
    try:
        response = client.get(spec.parameters["feed_url"])
        response.raise_for_status()
        payload = response.json()
        records = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise ValueError("Ambicuity response has no jobs list")
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
        return failed_result(spec, error, started_at)

    candidates: list[Candidate] = []
    malformed_count = 0
    closed_count = 0
    non_swe_title_count = 0
    for record in records:
        if not isinstance(record, dict):
            malformed_count += 1
            continue
        if record.get("is_closed") is True:
            closed_count += 1
            continue
        company = record.get("company")
        title = record.get("title")
        location = record.get("location")
        application_url = record.get("url")
        external_id = record.get("id")
        if (
            not isinstance(company, str)
            or not company.strip()
            or not isinstance(title, str)
            or not title.strip()
            or not isinstance(application_url, str)
            or not application_url.startswith(("http://", "https://"))
            or external_id is None
        ):
            malformed_count += 1
            continue
        if not SWE_TITLE_RE.search(title):
            non_swe_title_count += 1
            continue
        category = record.get("category")
        category_name = category.get("name", "") if isinstance(category, dict) else ""
        posted_at = parse_iso_date(record.get("posted_at"))
        description = clean_description(
            record.get("full_description") or record.get("description"),
        )
        year_match = YEAR_RE.search(title)
        candidates.append(Candidate(
            company=company.strip(),
            title=title.strip(),
            location=location.strip() if isinstance(location, str) else "",
            application_url=canonicalize_url(application_url),
            source_name=spec.name,
            source_url=spec.public_url,
            category=category_name if isinstance(category_name, str) else "",
            salary=_salary_text(record.get("comp")),
            source_age=(
                record.get("posted_display", "")
                if isinstance(record.get("posted_display"), str)
                else ""
            ),
            posted_at=posted_at,
            graduation_year=int(year_match.group(1)) if year_match else None,
            source_key=spec.key,
            source_external_id=str(external_id),
            source_kind=spec.kind,
            description_text=description,
            exact_posted_date=posted_at is not None,
        ))

    accepted, exclusions = scope_direct_candidates(
        candidates,
        malformed_count=malformed_count,
    )
    exclusion_counts = Counter(dict(exclusions))
    if closed_count:
        exclusion_counts["exclude_closed"] += closed_count
    if non_swe_title_count:
        exclusion_counts["exclude_non_engineering"] += non_swe_title_count
    return SourceFetchResult(
        source_key=spec.key,
        source_name=spec.name,
        succeeded=True,
        candidates=accepted,
        fetched_count=len(records),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        exclusion_counts=tuple(sorted(exclusion_counts.items())),
    )
