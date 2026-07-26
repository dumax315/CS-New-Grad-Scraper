from datetime import datetime, timezone
import logging
import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Listing, ListingSource, SourceRun
from app.source_types import Candidate, SourceFetchResult
from app.sources import fetch_source_batch

logger = logging.getLogger(__name__)


def stable_source_key(candidate: Candidate) -> str:
    if candidate.source_key:
        return candidate.source_key
    slug = re.sub(r"[^a-z0-9]+", "-", candidate.source_name.lower()).strip("-")
    return f"legacy:{slug or 'unknown'}"


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
                scope_decision=candidate.scope_decision,
                timing_explicit=candidate.timing_explicit,
                exact_posted_date=candidate.exact_posted_date,
                is_open=True,
            )
            session.add(listing)
            session.flush()
            new_listings.append(listing)
        else:
            listing.last_seen_at = now
            listing.company, listing.title, listing.location = candidate.company, candidate.title, candidate.location
            listing.salary, listing.category, listing.source_age = candidate.salary, candidate.category, candidate.source_age
            listing.graduation_year = candidate.graduation_year or listing.graduation_year
            if candidate.scope_decision == "include_explicit":
                listing.scope_decision = candidate.scope_decision
            elif listing.scope_decision is None:
                listing.scope_decision = candidate.scope_decision
            listing.timing_explicit = bool(listing.timing_explicit or candidate.timing_explicit)
            had_exact_posted_date = bool(listing.exact_posted_date)
            listing.exact_posted_date = bool(
                had_exact_posted_date or candidate.exact_posted_date
            )
            if candidate.posted_at:
                if candidate.exact_posted_date and (
                    not had_exact_posted_date
                    or listing.posted_at is None
                    or candidate.posted_at < listing.posted_at
                ):
                    listing.posted_at = candidate.posted_at
                elif not had_exact_posted_date and (
                    listing.posted_at is None
                    or candidate.posted_at < listing.posted_at
                ):
                    listing.posted_at = candidate.posted_at
        source_exists = session.scalar(select(ListingSource).where(
            ListingSource.listing_id == listing.id,
            or_(
                ListingSource.source_key == stable_source_key(candidate),
                (
                    ListingSource.source_key.is_(None)
                    & (ListingSource.source_name == candidate.source_name)
                ),
            ),
        ))
        if source_exists is None:
            session.add(ListingSource(
                listing_id=listing.id,
                source_name=candidate.source_name,
                source_url=candidate.source_url,
                source_key=stable_source_key(candidate),
                source_external_id=candidate.source_external_id,
                source_posted_at=candidate.posted_at,
                first_seen_at=now,
                last_seen_at=now,
                consecutive_misses=0,
                is_active=True,
            ))
        else:
            source_exists.source_key = stable_source_key(candidate)
            source_exists.source_name = candidate.source_name
            source_exists.source_url = candidate.source_url
            source_exists.source_external_id = (
                candidate.source_external_id or source_exists.source_external_id
            )
            if candidate.posted_at and (
                source_exists.source_posted_at is None
                or candidate.posted_at < source_exists.source_posted_at
            ):
                source_exists.source_posted_at = candidate.posted_at
            source_exists.last_seen_at = now
            source_exists.consecutive_misses = 0
            source_exists.is_active = True
            source_exists.closed_at = None
        listing.is_open = True
        listing.closed_at = None
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
    if result.succeeded:
        apply_successful_source_observations(session, result, now)
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


def apply_successful_source_observations(
    session: Session,
    result: SourceFetchResult,
    observed_at: datetime,
) -> None:
    observed_urls = {
        candidate.application_url
        for candidate in result.candidates
    }
    source_rows = session.scalars(
        select(ListingSource)
        .join(Listing)
        .where(ListingSource.source_key == result.source_key)
    ).all()
    affected_listing_ids: set[int] = set()
    for source_row in source_rows:
        affected_listing_ids.add(source_row.listing_id)
        if source_row.listing.application_url in observed_urls:
            continue
        if not source_row.is_active:
            continue
        source_row.consecutive_misses += 1
        if source_row.consecutive_misses >= 2:
            source_row.is_active = False
            source_row.closed_at = observed_at
    session.flush()

    for listing_id in affected_listing_ids:
        active_sources = session.scalar(
            select(func.count(ListingSource.id)).where(
                ListingSource.listing_id == listing_id,
                ListingSource.is_active.is_(True),
            ),
        )
        listing = session.get(Listing, listing_id)
        if active_sources:
            listing.is_open = True
            listing.closed_at = None
        elif listing.is_open:
            listing.is_open = False
            listing.closed_at = observed_at


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
