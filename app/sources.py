"""Fetch and parse the two curated GitHub job-list sources."""

from dataclasses import dataclass
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx


@dataclass(frozen=True)
class Source:
    name: str
    raw_url: str
    repository_url: str


SOURCES = (
    Source(
        "SpeedyApply 2027 SWE",
        "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/NEW_GRAD_USA.md",
        "https://github.com/speedyapply/2027-SWE-College-Jobs/blob/main/NEW_GRAD_USA.md",
    ),
    Source(
        "Vansh New Grad 2027",
        "https://raw.githubusercontent.com/vanshb03/New-Grad-2027/main/README.md",
        "https://github.com/vanshb03/New-Grad-2027",
    ),
)


@dataclass(frozen=True)
class Candidate:
    company: str
    title: str
    location: str
    application_url: str
    source_name: str
    source_url: str
    category: str = "Other"
    salary: str = ""
    source_age: str = ""
    graduation_year: int | None = None


LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
HREF_RE = re.compile(r'''href=["']([^"']+)["']''', re.I)
HTML_TAG_RE = re.compile(r"<[^>]+>")
YEAR_RE = re.compile(r"\b(20(?:2[5-9]|[3-9]\d))\b")
EXCLUDED_ROLE_RE = re.compile(r"\b(quant(?:itative)?|trader|product manager|\bpm\b|analyst|recruiter)\b", re.I)
ENGINEERING_ROLE_RE = re.compile(
    r"\b(software|swe|developer|engineer|sdet|devops|site reliability|platform|machine learning|data engineer|backend|frontend|full[ -]?stack|infrastructure)\b",
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
        # Posting cells normally have an Apply link; the final link is safest if an icon precedes it.
        return links[-1][1].strip()
    html_links = HREF_RE.findall(value)
    return html_links[-1].strip() if html_links else ""


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    kept_query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                  if not key.lower().startswith("utm_") and key.lower() not in {"ref", "source"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(kept_query)), ""))


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
    return Candidate(
        company=company,
        title=title,
        location=location,
        application_url=canonicalize_url(application_url),
        source_name=source.name,
        source_url=source.repository_url,
        category=category,
        salary=clean_text(field("salary")),
        source_age=clean_text(field("age", "date", "dateposted")),
        graduation_year=int(year_match.group(1)) if year_match else None,
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


def fetch_candidates(client: httpx.Client | None = None) -> list[Candidate]:
    own_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "cs-new-grad-jobs/0.1"})
    try:
        candidates: list[Candidate] = []
        for source in SOURCES:
            response = client.get(source.raw_url)
            response.raise_for_status()
            candidates.extend(parse_source(response.text, source))
        return candidates
    finally:
        if own_client:
            client.close()
