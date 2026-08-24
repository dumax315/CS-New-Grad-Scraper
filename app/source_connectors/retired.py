"""Successful empty observations for sources that no longer exist upstream."""

from datetime import datetime, timezone

import httpx

from app.source_types import SourceFetchResult, SourceSpec


def fetch(spec: SourceSpec, client: httpx.Client) -> SourceFetchResult:
    del client
    observed_at = datetime.now(timezone.utc)
    return SourceFetchResult(
        source_key=spec.key,
        source_name=spec.name,
        succeeded=True,
        started_at=observed_at,
        finished_at=observed_at,
    )
