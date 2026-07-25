"""Fetch and parse the two curated GitHub job-list sources."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.source_types import Candidate, SourceBatch, SourceFetchResult

logger = logging.getLogger(__name__)
MAX_ERROR_SUMMARY_LENGTH = 255


@dataclass(frozen=True)
class Source:
    name: str
    raw_url: str
    repository_url: str
    key: str = ""


SOURCES = (
    Source(
        "SpeedyApply 2027 SWE",
        "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/NEW_GRAD_USA.md",
        "https://github.com/speedyapply/2027-SWE-College-Jobs/blob/main/NEW_GRAD_USA.md",
        "markdown:speedyapply-2027-swe",
    ),
    Source(
        "Vansh New Grad 2027",
        "https://raw.githubusercontent.com/vanshb03/New-Grad-2027/main/README.md",
        "https://github.com/vanshb03/New-Grad-2027",
        "markdown:vansh-new-grad-2027",
    ),
)


LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
HREF_RE = re.compile(r'''href=["']([^"']+)["']''', re.I)
HTML_TAG_RE = re.compile(r"<[^>]+>")
YEAR_RE = re.compile(r"\b(20(?:2[5-9]|[3-9]\d))\b")
EXCLUDED_ROLE_RE = re.compile(r"\b(quant(?:itative)?|trader|product manager|\bpm\b|analyst|recruiter)\b", re.I)
ENGINEERING_ROLE_RE = re.compile(
    r"\b(software|swe|developer|engineer|sdet|devops|site reliability|platform|machine learning|data engineer|backend|frontend|full[ -]?stack|infrastructure)\b",
    re.I,
)
RELATIVE_AGE_RE = re.compile(r"^(\d+)\s*(?:d|day|days)\b", re.I)


def clean_text(value: str) -> str:
    value = LINK_RE.sub(lambda match: match.group(1), value)
    value = HTML_TAG_RE.sub("", value)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", value.replace("\\|", "|")).strip()


def extract_link(value: str) -> str:
    links = LINK_RE.findall(value)
    if links:
        # Posting cells normally have an Apply link; the final link is safest if an icon precedes it.
        return links[-1][1].strip()
    html_links = HREF_RE.findall(value)
    return html_links[-1].strip() if html_links else ""


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    kept_query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                  if not key.lower().startswith("utm_") and key.lower() not in {"ref", "source"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(kept_query)), ""))


def parse_posted_date(value: str, today: date | None = None) -> date | None:
    """Convert source age/date cells into a calendar date when possible."""
    value = clean_text(value).strip()
    if not value:
        return None
    today = today or date.today()
    if value.lower() == "today":
        return today
    if value.lower() == "yesterday":
        return today - timedelta(days=1)
    if relative_age := RELATIVE_AGE_RE.match(value):
        return today - timedelta(days=int(relative_age.group(1)))

    for format_string in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, format_string).date()
        except ValueError:
            pass
    for format_string in ("%b %d", "%B %d", "%m/%d"):
        try:
            # Use an explicit leap year while parsing to avoid Python's
            # yearless-date ambiguity and preserve February 29 when present.
            parsed = datetime.strptime(f"2000 {value}", f"%Y {format_string}").date()
            parsed = parsed.replace(year=today.year)
            # A yearless source date in the future belongs to the prior year.
            return parsed.replace(year=today.year - 1) if parsed > today else parsed
        except ValueError:
            pass
    return None


def split_markdown_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line)]


def normalized_header(value: str) -> str:
    return re.sub(r"[^a-z]", "", clean_text(value).lower())


def is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*", line))


def category_before_table(lines: list[str], table_index: int) -> str:
    """Return the nearest preceding Markdown heading for this table."""
    for index in range(table_index - 1, -1, -1):
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", lines[index])
        if heading:
            return clean_text(heading.group(1))
    return "Other"


def row_to_candidate(headers: list[str], row: list[str], source: Source, category: str) -> Candidate | None:
    if len(row) < len(headers):
        return None
    fields = {headers[index]: row[index] for index in range(len(headers))}

    def field(*names: str) -> str:
        for name in names:
            if name in fields:
                return fields[name]
        return ""

    company = clean_text(field("company"))
    title = clean_text(field("position", "role", "title"))
    location = clean_text(field("location"))
    posting = field("posting", "apply", "application", "applicationlink", "link")
    application_url = extract_link(posting)
    if not all((company, title, application_url)) or not application_url.startswith(("http://", "https://")):
        return None
    combined_role = f"{title} {category}"
    if EXCLUDED_ROLE_RE.search(combined_role) or not ENGINEERING_ROLE_RE.search(combined_role):
        return None
    year_match = YEAR_RE.search(title)
    source_age = clean_text(field("age", "date", "dateposted"))
    return Candidate(
        company=company,
        title=title,
        location=location,
        application_url=canonicalize_url(application_url),
        source_name=source.name,
        source_url=source.repository_url,
        category=category,
        salary=clean_text(field("salary")),
        source_age=source_age,
        posted_at=parse_posted_date(source_age),
        graduation_year=int(year_match.group(1)) if year_match else None,
        source_key=source.key,
    )


def parse_source(markdown: str, source: Source) -> list[Candidate]:
    """Parse every standard Markdown table, accepting source-specific columns."""
    lines = markdown.splitlines()
    candidates: list[Candidate] = []
    index = 0
    while index + 1 < len(lines):
        if "|" not in lines[index] or not is_separator(lines[index + 1]):
            index += 1
            continue
        headers = [normalized_header(value) for value in split_markdown_row(lines[index])]
        category = category_before_table(lines, index)
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip().startswith("|"):
            candidate = row_to_candidate(headers, split_markdown_row(lines[index]), source, category)
            if candidate:
                candidates.append(candidate)
            index += 1
    return candidates


def sanitized_fetch_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, httpx.HTTPStatusError):
        category = "http_status"
        summary = f"Source returned HTTP {error.response.status_code}."
    elif isinstance(error, httpx.TimeoutException):
        category = "timeout"
        summary = "Source request timed out."
    elif isinstance(error, httpx.HTTPError):
        category = "network"
        summary = "Source request failed."
    else:
        category = "parser"
        summary = "Source response could not be parsed."
    return category, summary[:MAX_ERROR_SUMMARY_LENGTH]


def fetch_source_batch(
    client: httpx.Client | None = None,
    sources: tuple[Source, ...] = SOURCES,
) -> SourceBatch:
    own_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "cs-new-grad-jobs/0.1"})
    try:
        results: list[SourceFetchResult] = []
        for source in sources:
            logger.info("Fetching %s from %s", source.name, source.raw_url)
            try:
                response = client.get(source.raw_url)
                response.raise_for_status()
                parsed = parse_source(response.text, source)
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
                category, summary = sanitized_fetch_error(error)
                logger.warning(
                    "Source fetch failed: key=%s category=%s summary=%s",
                    source.key,
                    category,
                    summary,
                )
                results.append(SourceFetchResult(
                    source_key=source.key,
                    source_name=source.name,
                    succeeded=False,
                    error_category=category,
                    error_summary=summary,
                ))
                continue
            logger.info(
                "Parsed %s matching candidates from %s (%s bytes, %s lines)",
                len(parsed),
                source.name,
                len(response.text),
                len(response.text.splitlines()),
            )
            if logger.isEnabledFor(logging.DEBUG) and parsed:
                for candidate in parsed[:5]:
                    logger.debug(
                        "Candidate sample from %s: %s | %s | %s",
                        source.name,
                        candidate.company,
                        candidate.title,
                        candidate.application_url,
                    )
            results.append(SourceFetchResult(
                source_key=source.key,
                source_name=source.name,
                succeeded=True,
                candidates=tuple(parsed),
                fetched_count=len(parsed),
            ))
        return SourceBatch(tuple(results))
    finally:
        if own_client:
            client.close()


def fetch_candidates(client: httpx.Client | None = None) -> list[Candidate]:
    """Compatibility wrapper returning candidates from successful sources."""
    return fetch_source_batch(client).candidates
