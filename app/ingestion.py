from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Listing, ListingSource, SourceRun
from app.source_types import Candidate, SourceFetchResult
from app.sources import fetch_source_batch

logger = logging.getLogger(__name__)


def _store_candidates(session: Session, candidates: list[Candidate]) -> list[Listing]:
    new_listings: list[Listing] = []
    now = datetime.now(timezone.utc)
    for candidate in candidates:
        listing = session.scalar(select(Listing).where(Listing.application_url == candidate.application_url))
        if listing is None:
            listing = Listing(
                company=candidate.company, title=candidate.title, location=candidate.location,
                application_url=candidate.application_url, salary=candidate.salary,
                category=candidate.category, graduation_year=candidate.graduation_year,
                source_age=candidate.source_age, posted_at=candidate.posted_at, last_seen_at=now,
            )
            session.add(listing)
            session.flush()
            new_listings.append(listing)
        else:
            listing.last_seen_at = now
            listing.company, listing.title, listing.location = candidate.company, candidate.title, candidate.location
            listing.salary, listing.category, listing.source_age = candidate.salary, candidate.category, candidate.source_age
            listing.graduation_year = candidate.graduation_year or listing.graduation_year
            if candidate.posted_at and (listing.posted_at is None or candidate.posted_at > listing.posted_at):
                listing.posted_at = candidate.posted_at
        source_exists = session.scalar(select(ListingSource).where(
            ListingSource.listing_id == listing.id, ListingSource.source_name == candidate.source_name,
        ))
        if source_exists is None:
            session.add(ListingSource(listing_id=listing.id, source_name=candidate.source_name, source_url=candidate.source_url))
    return new_listings


def store_candidates(session: Session, candidates: list[Candidate]) -> list[Listing]:
    new_listings = _store_candidates(session, candidates)
    session.commit()
    return new_listings


def record_source_result(
    session: Session,
    result: SourceFetchResult,
) -> list[Listing]:
    now = datetime.now(timezone.utc)
    new_listings = _store_candidates(session, list(result.candidates)) if result.succeeded else []
    session.add(SourceRun(
        source_key=result.source_key,
        started_at=result.started_at or now,
        finished_at=result.finished_at or now,
        succeeded=result.succeeded,
        status="success" if result.succeeded else "failed",
        fetched_count=result.fetched_count,
        accepted_count=len(result.candidates) if result.succeeded else 0,
        new_count=len(new_listings),
        error_category=result.error_category,
        error_summary=result.error_summary,
    ))
    session.commit()
    return new_listings


def run_ingestion(session: Session) -> list[Listing]:
    logger.info("Starting ingestion run")
    batch = fetch_source_batch()
    new_listings = [
        listing
        for result in batch.results
        for listing in record_source_result(session, result)
    ]
    fetched_count = sum(result.fetched_count for result in batch.results)
    logger.info(
        "Source run summary: attempted=%s succeeded=%s failed=%s fetched=%s new=%s",
        len(batch.results),
        batch.succeeded_count,
        batch.failed_count,
        fetched_count,
        len(new_listings),
    )
    if batch.failed_count == len(batch.results) and batch.results:
        logger.error("All %s sources failed; no listing data was changed", batch.failed_count)
    elif batch.failed_count:
        logger.warning(
            "Ingestion completed with %s successful and %s failed sources",
            batch.succeeded_count,
            batch.failed_count,
        )
    return new_listings
