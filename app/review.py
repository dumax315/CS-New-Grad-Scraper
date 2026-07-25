import argparse
import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, create_tables
from app.models import Listing
from app.refetch import positive_count
from app.worker import evaluate_listings

logger = logging.getLogger(__name__)


def select_recent_listings(
    session: Session,
    count: int,
    *,
    force: bool = False,
) -> list[Listing]:
    statement = select(Listing).order_by(
        Listing.posted_at.desc().nulls_last(),
        Listing.first_seen_at.desc(),
        Listing.id.desc(),
    )
    if not force:
        statement = statement.where(Listing.fit_evaluated_at.is_(None))
    return list(session.scalars(statement.limit(count)))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Codex-review the newest saved job postings and persist their fit results.",
    )
    parser.add_argument(
        "count",
        type=positive_count,
        help="Number of newest eligible listings to review.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Include previously reviewed listings and overwrite successful results.",
    )
    args = parser.parse_args(argv)

    create_tables()
    with SessionLocal() as session:
        listings = select_recent_listings(session, args.count, force=args.force)
        logger.info(
            "Selected %s newest listings for Codex review (force=%s)",
            len(listings),
            args.force,
        )
        evaluated = evaluate_listings(session, listings)
    print(f"attempted={len(listings)} evaluated={evaluated} failed={len(listings) - evaluated}")
    if evaluated != len(listings):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
