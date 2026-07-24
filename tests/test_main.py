from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import visible_listing_condition
from app.models import Listing


def listing(
    title: str,
    posted_at: date | None,
    first_seen_at: datetime = datetime(2026, 7, 24, tzinfo=timezone.utc),
) -> Listing:
    return Listing(
        company="Acme",
        title=title,
        location="Remote",
        application_url=f"https://jobs.example/{title}",
        posted_at=posted_at,
        first_seen_at=first_seen_at,
    )


def test_visible_listing_condition_hides_only_known_dates_older_than_one_year():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        session.add_all([
            listing("old", date(2025, 7, 23)),
            listing("boundary", date(2025, 7, 24)),
            listing("recent", date(2026, 7, 24)),
            listing("recent-unknown", None),
            listing("old-unknown", None, datetime(2025, 7, 23, tzinfo=timezone.utc)),
        ])
        session.commit()
        visible = session.scalars(
            select(Listing).where(visible_listing_condition(date(2026, 7, 24)))
        ).all()

    assert {item.title for item in visible} == {"boundary", "recent", "recent-unknown"}
