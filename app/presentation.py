from dataclasses import dataclass
from datetime import date
from typing import Iterable

from app.models import Listing


@dataclass(frozen=True, slots=True)
class SourceView:
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class JobView:
    id: int | None
    company: str
    title: str
    meta: tuple[str, ...]
    posted_label: str
    fit_confidence: int | None
    fit_label: str
    fit_tone: str
    fit_reasoning: str | None
    resume_fit_confidence: int | None
    resume_fit_label: str
    resume_fit_tone: str
    resume_fit_reasoning: str | None
    application_url: str
    sources: tuple[SourceView, ...]


def _format_date(value: date) -> str:
    return value.strftime("%b %d, %Y").replace(" 0", " ")


def _posted_label(listing: Listing) -> str:
    if listing.posted_at:
        return f"Posted {_format_date(listing.posted_at)}"
    if listing.source_age:
        return f"Posted {listing.source_age}"
    return "Posting date unavailable"


def _fit_tone(confidence: int | None) -> str:
    if confidence is None:
        return "pending"
    if confidence >= 80:
        return "strong"
    if confidence >= 60:
        return "promising"
    return "limited"


def present_listing(listing: Listing) -> JobView:
    meta = [listing.location or "Location not listed"]
    if listing.salary:
        meta.append(listing.salary)
    if listing.graduation_year:
        meta.append(f"Class of {listing.graduation_year}")

    confidence = listing.fit_confidence
    return JobView(
        id=listing.id,
        company=listing.company,
        title=listing.title,
        meta=tuple(meta),
        posted_label=_posted_label(listing),
        fit_confidence=confidence,
        fit_label=f"{confidence}% match" if confidence is not None else "Not yet evaluated",
        fit_tone=_fit_tone(confidence),
        fit_reasoning=listing.fit_reasoning,
        resume_fit_confidence=listing.resume_fit_confidence,
        resume_fit_label=(
            f"{listing.resume_fit_confidence}% match"
            if listing.resume_fit_confidence is not None
            else "Not yet evaluated"
        ),
        resume_fit_tone=_fit_tone(listing.resume_fit_confidence),
        resume_fit_reasoning=listing.resume_fit_reasoning,
        application_url=listing.application_url,
        sources=tuple(
            SourceView(name=source.source_name, url=source.source_url)
            for source in listing.sources
        ),
    )


def present_listings(
    listings: Iterable[Listing],
    *,
    highest_fit_first: bool = False,
) -> list[JobView]:
    jobs = [present_listing(listing) for listing in listings]
    if highest_fit_first:
        jobs.sort(key=lambda job: (
            job.fit_confidence is None,
            -(job.fit_confidence or 0),
        ))
    return jobs
