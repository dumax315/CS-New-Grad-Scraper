"""Source connector dispatch."""

import httpx

from app.source_connectors import (
    aggregate,
    applyguy,
    ashby,
    greenhouse,
    lever,
    markdown,
    retired,
)
from app.source_types import SourceFetchResult, SourceSpec


def fetch_source(spec: SourceSpec, client: httpx.Client) -> SourceFetchResult:
    connectors = {
        "aggregate": aggregate.fetch,
        "applyguy": applyguy.fetch,
        "ashby": ashby.fetch,
        "greenhouse": greenhouse.fetch,
        "lever": lever.fetch,
        "markdown": markdown.fetch,
        "retired": retired.fetch,
    }
    if connector := connectors.get(spec.kind):
        return connector(spec, client)
    raise ValueError(f"Unsupported source kind: {spec.kind}")
