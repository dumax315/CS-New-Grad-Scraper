from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Listing, ListingSource
from app.sources import Candidate, fetch_candidates

logger = logging.getLogger(__name__)


def store_candidates(session: Session, candidates: list[Candidate]) -> list[Listing]:
    new_listings: list[Listing] = []
    now = datetime.now(timezone.utc)
    for candidate in candidates:
        listing = session.scalar(select(Listing).where(Listing.application_url == candidate.application_url))
        if listing is None:
            listing = Listing(
                company=candidate.company, title=candidate.title, location=candidate.location,
                application_url=candidate.application_url, salary=candidate.salary,
                category=candidate.category, graduation_year=candidate.graduation_year,
                source_age=candidate.source_age, last_seen_at=now,
            )
            session.add(listing)
            session.flush()
            new_listings.append(listing)
        else:
            listing.last_seen_at = now
            listing.company, listing.title, listing.location = candidate.company, candidate.title, candidate.location
            listing.salary, listing.category, listing.source_age = candidate.salary, candidate.category, candidate.source_age
            listing.graduation_year = candidate.graduation_year or listing.graduation_year
        source_exists = session.scalar(select(ListingSource).where(
            ListingSource.listing_id == listing.id, ListingSource.source_name == candidate.source_name,
        ))
        if source_exists is None:
            session.add(ListingSource(listing_id=listing.id, source_name=candidate.source_name, source_url=candidate.source_url))
    session.commit()
    return new_listings


def run_ingestion(session: Session) -> list[Listing]:
    candidates = fetch_candidates()
    logger.info("Fetched %s matching candidates", len(candidates))
    return store_candidates(session, candidates)
