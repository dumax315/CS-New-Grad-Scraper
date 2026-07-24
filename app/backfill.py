import argparse
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import and_, or_, select

from app.database import SessionLocal, create_tables
from app.models import Listing
from app.worker import evaluate_listings

logger = logging.getLogger(__name__)


def recent_listing_condition(cutoff: datetime):
    return or_(
        Listing.posted_at >= cutoff.date(),
        and_(Listing.posted_at.is_(None), Listing.first_seen_at >= cutoff),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sequentially scrape and evaluate recent listings without the scheduled 10-job cap.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help="Include listings posted this many days ago (or first seen when no posting date exists).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-evaluate successful listings too; by default only unfinished listings are evaluated.",
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")

    create_tables()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    statement = (
        select(Listing)
        .where(recent_listing_condition(cutoff))
        .order_by(Listing.posted_at, Listing.first_seen_at, Listing.id)
    )
    if not args.force:
        statement = statement.where(Listing.fit_evaluated_at.is_(None))

    with SessionLocal() as session:
        listings = list(session.scalars(statement))
        logger.info(
            "Backfill selected %s listings posted or first seen in the last %s days (force=%s)",
            len(listings),
            args.days,
            args.force,
        )
        evaluated = evaluate_listings(session, listings)
    print(f"attempted={len(listings)} evaluated={evaluated} failed={len(listings) - evaluated}")


if __name__ == "__main__":
    main()
