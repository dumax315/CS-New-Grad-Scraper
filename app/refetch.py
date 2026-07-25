import argparse
import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, create_tables
from app.models import Listing
from app.worker import run_ingestion_cycle

logger = logging.getLogger(__name__)


def positive_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("count must be an integer") from error
    if count < 1:
        raise argparse.ArgumentTypeError("count must be at least 1")
    return count


def delete_most_recent_saved_listings(session: Session, count: int) -> list[str]:
    listings = list(session.scalars(
        select(Listing)
        .order_by(Listing.first_seen_at.desc(), Listing.id.desc())
        .limit(count)
    ))
    deleted_urls = [listing.application_url for listing in listings]
    for listing in listings:
        session.delete(listing)
    session.commit()
    return deleted_urls


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Delete recently saved listings, refetch sources, and send the resulting "
            "new-listing digest."
        ),
    )
    parser.add_argument(
        "count",
        type=positive_count,
        help="Number of most recently saved listings to delete before refetching.",
    )
    parser.add_argument(
        "--no-codex",
        action="store_true",
        help="Skip Codex review of the refetched listings.",
    )
    args = parser.parse_args(argv)

    create_tables()
    with SessionLocal() as session:
        deleted_urls = delete_most_recent_saved_listings(session, args.count)
    if not deleted_urls:
        parser.exit(1, "No saved listings were available to delete; refetch was not run.\n")
    logger.info("Deleted %s recently saved listings before test refetch", len(deleted_urls))

    result = run_ingestion_cycle(
        review_with_codex=not args.no_codex,
        force_digest=True,
    )
    print(
        f"deleted={len(deleted_urls)} refetched={result.new_listings} "
        f"evaluated={result.evaluated} digest_sent={result.digest_sent}"
    )
    if not result.new_listings:
        parser.exit(1, "Refetch stored no new listings; check whether deleted jobs remain in the sources.\n")
    if not result.digest_sent:
        parser.exit(
            1,
            "Listings were refetched, but no digest was sent; check SMTP and recipient settings.\n",
        )


if __name__ == "__main__":
    main()
