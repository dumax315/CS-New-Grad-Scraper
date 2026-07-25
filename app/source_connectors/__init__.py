"""Source connector dispatch."""

import httpx

from app.source_connectors import markdown
from app.source_types import SourceFetchResult, SourceSpec


def fetch_source(spec: SourceSpec, client: httpx.Client) -> SourceFetchResult:
    if spec.kind == "markdown":
        return markdown.fetch(spec, client)
    raise ValueError(f"Unsupported source kind: {spec.kind}")
