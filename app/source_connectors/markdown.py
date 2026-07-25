"""Connector for curated Markdown tables."""

from datetime import date, datetime, timedelta, timezone
import logging
import re

import httpx

from app.source_connectors.common import failed_result
from app.source_types import Candidate, SourceFetchResult, SourceSpec
from app.source_utils import canonicalize_url

logger = logging.getLogger(__name__)

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
NEW_GRAD_RE = re.compile(
    r"\b(new grad(?:uate)?|university grad(?:uate)?|early career|class of 20\d{2})\b",
    re.I,
)


def clean_text(value: str) -> str:
    value = LINK_RE.sub(lambda match: match.group(1), value)
    value = HTML_TAG_RE.sub("", value)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", value.replace("\\|", "|")).strip()


def extract_link(value: str) -> str:
    links = LINK_RE.findall(value)
    if links:
        return links[-1][1].strip()
    html_links = HREF_RE.findall(value)
    return html_links[-1].strip() if html_links else ""


def parse_posted_date(value: str, today: date | None = None) -> date | None:
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
            parsed = datetime.strptime(f"2000 {value}", f"%Y {format_string}").date()
            parsed = parsed.replace(year=today.year)
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
    for index in range(table_index - 1, -1, -1):
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", lines[index])
        if heading:
            return clean_text(heading.group(1))
    return "Other"


def row_to_candidate(
    headers: list[str],
    row: list[str],
    spec: SourceSpec,
    category: str,
) -> Candidate | None:
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
    graduation_year = int(year_match.group(1)) if year_match else None
    return Candidate(
        company=company,
        title=title,
        location=location,
        application_url=canonicalize_url(application_url),
        source_name=spec.name,
        source_url=spec.public_url,
        category=category,
        salary=clean_text(field("salary")),
        source_age=source_age,
        posted_at=parse_posted_date(source_age),
        graduation_year=graduation_year,
        source_key=spec.key,
        scope_decision=(
            "include_explicit" if NEW_GRAD_RE.search(title) else "include_curated"
        ),
        timing_explicit=graduation_year == 2027,
    )


def parse_source(markdown: str, spec: SourceSpec) -> list[Candidate]:
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
            candidate = row_to_candidate(headers, split_markdown_row(lines[index]), spec, category)
            if candidate:
                candidates.append(candidate)
            index += 1
    return candidates


def fetch(spec: SourceSpec, client: httpx.Client) -> SourceFetchResult:
    started_at = datetime.now(timezone.utc)
    try:
        response = client.get(spec.parameters["raw_url"])
        response.raise_for_status()
        parsed = parse_source(response.text, spec)
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
        return failed_result(spec, error, started_at)

    logger.info(
        "Parsed %s matching candidates from %s (%s bytes, %s lines)",
        len(parsed),
        spec.name,
        len(response.text),
        len(response.text.splitlines()),
    )
    return SourceFetchResult(
        source_key=spec.key,
        source_name=spec.name,
        succeeded=True,
        candidates=tuple(parsed),
        fetched_count=len(parsed),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )
