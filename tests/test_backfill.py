from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.backfill import recent_listing_condition
from app.database import Base
from app.models import Listing


def listing(title: str, posted_at: date | None, first_seen_at: datetime) -> Listing:
    return Listing(
        company="Acme",
        title=title,
        location="Remote",
        application_url=f"https://jobs.example/{title}",
        posted_at=posted_at,
        first_seen_at=first_seen_at,
    )


def test_recent_backfill_uses_posted_date_then_falls_back_to_first_seen():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    cutoff = datetime(2026, 7, 14, tzinfo=timezone.utc)

    with Session() as session:
        session.add_all([
            listing("recent-post", date(2026, 7, 20), datetime(2025, 1, 1, tzinfo=timezone.utc)),
            listing("old-post", date(2025, 1, 1), datetime(2026, 7, 24, tzinfo=timezone.utc)),
            listing("recent-undated", None, datetime(2026, 7, 20, tzinfo=timezone.utc)),
            listing("old-undated", None, datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ])
        session.commit()
        recent = session.scalars(
            select(Listing).where(recent_listing_condition(cutoff))
        ).all()

    assert {item.title for item in recent} == {"recent-post", "recent-undated"}
