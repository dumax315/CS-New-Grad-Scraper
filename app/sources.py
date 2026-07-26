"""Orchestrate registered sources and preserve compatibility exports."""

from dataclasses import dataclass
import logging

import httpx

from app.source_connectors import fetch_source
from app.source_connectors.common import sanitized_fetch_error
from app.source_connectors.markdown import (
    category_before_table,
    clean_text,
    extract_link,
    is_separator,
    normalized_header,
    parse_posted_date,
    parse_source as parse_markdown_source,
    row_to_candidate,
    split_markdown_row,
)
from app.source_registry import CURATED_SOURCES, SOURCE_REGISTRY
from app.source_types import Candidate, SourceBatch, SourceFetchResult, SourceSpec
from app.source_utils import canonicalize_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Source:
    """Legacy Markdown source shape retained for compatibility."""

    name: str
    raw_url: str
    repository_url: str
    key: str = ""

    def as_spec(self) -> SourceSpec:
        return SourceSpec(
            key=self.key,
            name=self.name,
            kind="markdown",
            public_url=self.repository_url,
            parameters={"raw_url": self.raw_url},
        )


def legacy_source(spec: SourceSpec) -> Source:
    return Source(
        name=spec.name,
        raw_url=spec.parameters["raw_url"],
        repository_url=spec.public_url,
        key=spec.key,
    )


SOURCES = tuple(
    legacy_source(spec)
    for spec in CURATED_SOURCES
    if spec.kind == "markdown"
)


def parse_source(markdown: str, source: Source | SourceSpec) -> list[Candidate]:
    spec = source.as_spec() if isinstance(source, Source) else source
    return parse_markdown_source(markdown, spec)


def fetch_source_batch(
    client: httpx.Client | None = None,
    sources: tuple[Source | SourceSpec, ...] | None = None,
) -> SourceBatch:
    specs = SOURCE_REGISTRY if sources is None else tuple(
        source.as_spec() if isinstance(source, Source) else source
        for source in sources
    )
    own_client = client is None
    client = client or httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "cs-new-grad-jobs/0.1"},
    )
    try:
        results: list[SourceFetchResult] = []
        for spec in specs:
            if not spec.enabled:
                continue
            logger.info("Fetching source key=%s kind=%s", spec.key, spec.kind)
            try:
                result = fetch_source(spec, client)
            except (ValueError, TypeError, KeyError) as error:
                category, summary = sanitized_fetch_error(error)
                result = SourceFetchResult(
                    source_key=spec.key,
                    source_name=spec.name,
                    succeeded=False,
                    error_category=category,
                    error_summary=summary,
                )
            if not result.succeeded:
                logger.warning(
                    "Source fetch failed: key=%s category=%s summary=%s",
                    result.source_key,
                    result.error_category,
                    result.error_summary,
                )
            elif result.exclusion_counts:
                logger.info(
                    "Source scope exclusions: key=%s counts=%s",
                    result.source_key,
                    dict(result.exclusion_counts),
                )
            results.append(result)
        return SourceBatch(tuple(results))
    finally:
        if own_client:
            client.close()


def fetch_candidates(client: httpx.Client | None = None) -> list[Candidate]:
    """Compatibility wrapper returning candidates from successful sources."""
    return fetch_source_batch(client).candidates


__all__ = [
    "Candidate",
    "SOURCES",
    "Source",
    "SourceBatch",
    "SourceFetchResult",
    "SourceSpec",
    "canonicalize_url",
    "category_before_table",
    "clean_text",
    "extract_link",
    "fetch_candidates",
    "fetch_source_batch",
    "is_separator",
    "normalized_header",
    "parse_posted_date",
    "parse_source",
    "row_to_candidate",
    "split_markdown_row",
]
