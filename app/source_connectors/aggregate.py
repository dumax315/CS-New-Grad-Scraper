"""Strict parser for third-party aggregate job lists."""

from collections import Counter
from datetime import datetime, timezone
from html import unescape
import re

import httpx

from app.source_connectors.common import failed_result
from app.source_connectors.markdown import (
    HREF_RE,
    clean_text,
    extract_link,
    is_separator,
    normalized_header,
    parse_posted_date,
    split_markdown_row,
)
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
CURATED_ENTRY_RE = re.compile(
    r"\b(?:junior|jr\.?|entry[ -]?level|associate|engineer (?:i|1)|"
    r"developer (?:i|1)|sde (?:i|1))\b",
    re.I,
)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
BR_RE = re.compile(r"<br\s*/?>", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def _scope_result(title: str) -> ScopeResult:
    result = classify_direct_candidate(title)
    if result.code != "exclude_unknown":
        return result
    year_match = YEAR_RE.search(title)
    if year_match and int(year_match.group(1)) == 2027:
        return ScopeResult(
            "include_explicit",
            "curated title explicitly names 2027",
            timing_explicit=True,
        )
    if CURATED_ENTRY_RE.search(title):
        return ScopeResult(
            "include_plausible",
            "curated source with entry-level title",
        )
    return result


def _html_text(value: str) -> str:
    value = BR_RE.sub("; ", value)
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub("", value))).strip()


def _clean_company(value: str) -> str:
    company = clean_text(value)
    return re.sub(r"^[^\w]+", "", company).strip()


def _candidate(
    spec: SourceSpec,
    *,
    company: str,
    title: str,
    location: str,
    application_url: str,
    posted: str,
) -> tuple[Candidate | None, str | None]:
    company = _clean_company(company)
    title = clean_text(title)
    location = clean_text(location)
    posted = clean_text(posted)
    if (
        not company
        or company == "↳"
        or not title
        or not application_url.startswith(("http://", "https://"))
    ):
        return None, "exclude_unknown"
    if not SWE_TITLE_RE.search(title):
        return None, "exclude_non_engineering"
    scope_result = _scope_result(title)
    if not scope_result.included:
        return None, scope_result.code

    year_match = YEAR_RE.search(title)
    graduation_year = int(year_match.group(1)) if year_match else None
    posted_at = parse_posted_date(posted)
    return Candidate(
        company=company,
        title=title,
        location=location,
        application_url=canonicalize_url(application_url),
        source_name=spec.name,
        source_url=spec.public_url,
        category="Software Engineering",
        source_age=posted,
        posted_at=posted_at,
        graduation_year=graduation_year,
        source_key=spec.key,
        source_kind=spec.kind,
        scope_decision=scope_result.code,
        timing_explicit=(
            scope_result.timing_explicit or graduation_year == 2027
        ),
        exact_posted_date=bool(posted_at and ISO_DATE_RE.fullmatch(posted)),
    ), None


def _markdown_records(
    body: str,
    *,
    title_link: bool,
) -> list[tuple[str, str, str, str, str]]:
    lines = body.splitlines()
    records: list[tuple[str, str, str, str, str]] = []
    index = 0
    last_company = ""
    while index + 1 < len(lines):
        if "|" not in lines[index] or not is_separator(lines[index + 1]):
            index += 1
            continue
        headers = [normalized_header(value) for value in split_markdown_row(lines[index])]
        index += 2
        while index < len(lines) and lines[index].strip().startswith("|"):
            row = split_markdown_row(lines[index])
            index += 1
            if len(row) < len(headers):
                continue
            fields = {headers[position]: row[position] for position in range(len(headers))}
            company_cell = fields.get("company", "")
            if clean_text(company_cell) == "↳":
                company = last_company
            else:
                company = _clean_company(company_cell)
                if company:
                    last_company = company
            title_cell = fields.get("role") or fields.get("title") or fields.get("jobtitle", "")
            application_cell = (
                title_cell
                if title_link
                else fields.get("apply")
                or fields.get("application")
                or fields.get("posting")
                or fields.get("link", "")
            )
            records.append((
                company,
                title_cell,
                fields.get("location", ""),
                extract_link(application_cell),
                fields.get("posted")
                or fields.get("dateposted")
                or fields.get("date")
                or fields.get("age", ""),
            ))
    return records


def _simplify_records(body: str) -> list[tuple[str, str, str, str, str]]:
    records: list[tuple[str, str, str, str, str]] = []
    last_company = ""
    for row_html in TR_RE.findall(body):
        cells = TD_RE.findall(row_html)
        if len(cells) < 5:
            continue
        company = _html_text(cells[0])
        if company == "↳":
            company = last_company
        elif company:
            last_company = company
        links = [link for link in HREF_RE.findall(cells[3]) if "simplify.jobs/" not in link]
        records.append((
            company,
            _html_text(cells[1]),
            _html_text(cells[2]),
            links[0] if links else "",
            _html_text(cells[4]),
        ))
    return records


def fetch(spec: SourceSpec, client: httpx.Client) -> SourceFetchResult:
    started_at = datetime.now(timezone.utc)
    try:
        response = client.get(spec.parameters["feed_url"])
        response.raise_for_status()
        feed_format = spec.parameters["format"]
        if feed_format == "simplify_html":
            records = _simplify_records(response.text)
        elif feed_format in {"markdown", "markdown_title_link"}:
            records = _markdown_records(
                response.text,
                title_link=feed_format == "markdown_title_link",
            )
        else:
            raise ValueError("Unsupported aggregate feed format")
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
        return failed_result(spec, error, started_at)

    candidates: list[Candidate] = []
    exclusion_counts: Counter[str] = Counter()
    for company, title, location, application_url, posted in records:
        candidate, exclusion = _candidate(
            spec,
            company=company,
            title=title,
            location=location,
            application_url=application_url,
            posted=posted,
        )
        if candidate:
            candidates.append(candidate)
        elif exclusion:
            exclusion_counts[exclusion] += 1

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
