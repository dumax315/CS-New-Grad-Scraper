from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import refetch
from app.database import Base
from app.models import Listing, ListingSource
from app.refetch import delete_most_recent_saved_listings
from app.worker import IngestionResult


def listing(index: int, first_seen_at: datetime) -> Listing:
    return Listing(
        company="Acme",
        title=f"Software Engineer {index}",
        location="Remote",
        application_url=f"https://jobs.example/{index}",
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
        sources=[
            ListingSource(
                source_name="Curated List",
                source_url="https://github.com/example/jobs",
            ),
        ],
    )


def test_delete_most_recent_saved_listings_cascades_sources():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        session.add_all([
            listing(1, datetime(2026, 7, 23, tzinfo=timezone.utc)),
            listing(2, datetime(2026, 7, 24, tzinfo=timezone.utc)),
            listing(3, datetime(2026, 7, 25, tzinfo=timezone.utc)),
        ])
        session.commit()

        deleted_urls = delete_most_recent_saved_listings(session, 2)

        assert deleted_urls == [
            "https://jobs.example/3",
            "https://jobs.example/2",
        ]
        assert session.scalar(select(func.count(Listing.id))) == 1
        assert session.scalar(select(func.count(ListingSource.id))) == 1
        assert session.scalar(select(Listing.application_url)) == "https://jobs.example/1"


def test_refetch_command_can_skip_codex_and_requires_digest(monkeypatch, capsys):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    captured = {}

    with Session() as session:
        session.add(listing(1, datetime(2026, 7, 25, tzinfo=timezone.utc)))
        session.commit()

    def fake_cycle(**kwargs):
        captured.update(kwargs)
        return IngestionResult(
            new_listings=1,
            evaluated=0,
            digest_sent=True,
            initial_run=True,
        )

    monkeypatch.setattr(refetch, "SessionLocal", Session)
    monkeypatch.setattr(refetch, "create_tables", lambda: None)
    monkeypatch.setattr(refetch, "run_ingestion_cycle", fake_cycle)

    refetch.main(["1", "--no-codex"])

    assert captured == {
        "review_with_codex": False,
        "force_digest": True,
    }
    assert "deleted=1 refetched=1 evaluated=0 digest_sent=True" in capsys.readouterr().out
