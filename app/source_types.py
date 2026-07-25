"""Normalized types shared by source connectors and ingestion."""

from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    kind: str
    public_url: str
    parameters: Mapping[str, str]
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


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
    posted_at: date | None = None
    graduation_year: int | None = None
    source_key: str = ""
    source_external_id: str | None = None


@dataclass(frozen=True)
class SourceFetchResult:
    source_key: str
    source_name: str
    succeeded: bool
    candidates: tuple[Candidate, ...] = ()
    fetched_count: int = 0
    error_category: str | None = None
    error_summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class SourceBatch:
    results: tuple[SourceFetchResult, ...]

    @property
    def candidates(self) -> list[Candidate]:
        return [
            candidate
            for result in self.results
            if result.succeeded
            for candidate in result.candidates
        ]

    @property
    def succeeded_count(self) -> int:
        return sum(result.succeeded for result in self.results)

    @property
    def failed_count(self) -> int:
        return len(self.results) - self.succeeded_count
