"""Shared, sanitized source-connector failure handling."""

from datetime import datetime, timezone

import httpx

from app.source_types import SourceFetchResult, SourceSpec

MAX_ERROR_SUMMARY_LENGTH = 255


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


def failed_result(
    spec: SourceSpec,
    error: Exception,
    started_at: datetime,
) -> SourceFetchResult:
    category, summary = sanitized_fetch_error(error)
    return SourceFetchResult(
        source_key=spec.key,
        source_name=spec.name,
        succeeded=False,
        error_category=category,
        error_summary=summary,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )
