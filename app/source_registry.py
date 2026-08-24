"""Reviewed source definitions enabled for scheduled ingestion."""

import json
from pathlib import Path

from app.source_types import SourceSpec


CURATED_SOURCES = (
    SourceSpec(
        key="markdown:speedyapply-2027-swe",
        name="SpeedyApply 2027 SWE",
        kind="markdown",
        public_url=(
            "https://github.com/speedyapply/2027-SWE-College-Jobs/"
            "blob/main/NEW_GRAD_USA.md"
        ),
        parameters={
            "raw_url": (
                "https://raw.githubusercontent.com/speedyapply/"
                "2027-SWE-College-Jobs/main/NEW_GRAD_USA.md"
            ),
        },
    ),
    SourceSpec(
        key="markdown:vansh-new-grad-2027",
        name="Vansh New Grad 2027",
        kind="markdown",
        public_url="https://github.com/vanshb03/New-Grad-2027",
        parameters={
            "raw_url": (
                "https://raw.githubusercontent.com/vanshb03/"
                "New-Grad-2027/main/README.md"
            ),
        },
    ),
    SourceSpec(
        key="json:ambicuity-new-grad-jobs",
        name="Ambicuity New Grad Jobs (retired)",
        kind="retired",
        public_url="https://github.com/ambicuity/New-Grad-Jobs",
        parameters={},
    ),
    SourceSpec(
        key="json:applyguy-2027-new-grad-jobs",
        name="ApplyGuy 2027 New Grad Jobs",
        kind="applyguy",
        public_url="https://github.com/ApplyGuy/2027-New-Grad-Jobs",
        parameters={
            "feed_url": (
                "https://raw.githubusercontent.com/ApplyGuy/"
                "2027-New-Grad-Jobs/main/data/new-grad-jobs.json"
            ),
        },
    ),
    SourceSpec(
        key="markdown:keryx-2027-new-grad",
        name="Keryx 2027 New Grad",
        kind="aggregate",
        public_url="https://github.com/GodlyDonuts/keryx/blob/main/new-grad/2027.md",
        parameters={
            "feed_url": (
                "https://raw.githubusercontent.com/GodlyDonuts/"
                "keryx/main/new-grad/2027.md"
            ),
            "format": "markdown",
        },
    ),
    SourceSpec(
        key="html:simplify-new-grad-positions",
        name="Simplify New Grad Positions",
        kind="aggregate",
        public_url="https://github.com/SimplifyJobs/New-Grad-Positions",
        parameters={
            "feed_url": (
                "https://raw.githubusercontent.com/SimplifyJobs/"
                "New-Grad-Positions/dev/README.md"
            ),
            "format": "simplify_html",
        },
    ),
    SourceSpec(
        key="markdown:jobright-swe-new-grad",
        name="Jobright SWE New Grad",
        kind="aggregate",
        public_url="https://github.com/jobright-ai/2026-Software-Engineer-New-Grad",
        parameters={
            "feed_url": (
                "https://raw.githubusercontent.com/jobright-ai/"
                "2026-Software-Engineer-New-Grad/master/README.md"
            ),
            "format": "markdown_title_link",
        },
    ),
    SourceSpec(
        key="markdown:zapply-new-grad-2027",
        name="Zapply New Grad 2027",
        kind="aggregate",
        public_url="https://github.com/zapplyjobs/New-Grad-Jobs-2027",
        parameters={
            "feed_url": (
                "https://raw.githubusercontent.com/zapplyjobs/"
                "New-Grad-Jobs-2027/main/README.md"
            ),
            "format": "markdown",
        },
    ),
    SourceSpec(
        key="markdown:harry-new-grad-2027",
        name="Harry New Grad 2027 Tracker",
        kind="aggregate",
        public_url="https://github.com/harrycodingnow/new-grad-2027-tracker",
        parameters={
            "feed_url": (
                "https://raw.githubusercontent.com/harrycodingnow/"
                "new-grad-2027-tracker/main/README.md"
            ),
            "format": "markdown",
        },
    ),
)

DIRECT_REGISTRY_PATH = Path(__file__).with_name("approved_direct_sources.json")
DIRECT_PUBLIC_URLS = {
    "ashby": "https://jobs.ashbyhq.com/{tenant}",
    "greenhouse": "https://job-boards.greenhouse.io/{tenant}",
    "lever": "https://jobs.lever.co/{tenant}",
}


def load_direct_sources(path: Path = DIRECT_REGISTRY_PATH) -> tuple[SourceSpec, ...]:
    entries = json.loads(path.read_text())
    if not isinstance(entries, list):
        raise ValueError("Direct source registry must contain a JSON list.")
    sources: list[SourceSpec] = []
    seen_keys: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Direct source registry entries must be objects.")
        kind = entry.get("kind")
        tenant = entry.get("tenant")
        employer = entry.get("employer")
        key = entry.get("key")
        if kind not in DIRECT_PUBLIC_URLS:
            raise ValueError(f"Unsupported direct source kind: {kind}")
        if not all(isinstance(value, str) and value for value in (tenant, employer, key)):
            raise ValueError("Direct source registry entries require key, employer, and tenant.")
        if key != f"{kind}:{tenant.lower()}":
            raise ValueError(f"Direct source key does not match kind and tenant: {key}")
        if key in seen_keys:
            raise ValueError(f"Duplicate direct source key: {key}")
        seen_keys.add(key)
        sources.append(SourceSpec(
            key=key,
            name=f"{employer} Careers",
            kind=kind,
            public_url=DIRECT_PUBLIC_URLS[kind].format(tenant=tenant),
            parameters={"tenant": tenant, "employer": employer},
            enabled=True,
        ))
    return tuple(sources)


DIRECT_SOURCES = load_direct_sources()
SOURCE_REGISTRY = CURATED_SOURCES + DIRECT_SOURCES
