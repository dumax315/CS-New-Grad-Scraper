from datetime import date, datetime, timezone

from starlette.requests import Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app, index, visible_listing_condition
from app.models import Listing, ListingSource


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


def test_index_renders_shared_job_card_and_static_brand_styles():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "app": app,
    }

    with Session() as session:
        job = listing("rendered", date(2026, 7, 24))
        job.fit_confidence = 88
        job.fit_reasoning = "Spring 2027 timing is supported."
        job.sources = [
            ListingSource(source_name="Curated List", source_url="https://github.com/example/list"),
        ]
        session.add(job)
        session.commit()
        response = index(Request(scope), q="", source="", session=session)

    html = response.body.decode()
    assert response.status_code == 200
    assert 'href="http://testserver/static/styles.css"' in html
    assert "88% match" in html
    assert "Spring 2027 timing is supported." in html
    assert "Apply now" in html
    assert "Curated List" in html
