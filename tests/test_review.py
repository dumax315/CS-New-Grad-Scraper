from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import review
from app.database import Base
from app.models import Listing
from app.review import select_recent_listings


def listing(
    index: int,
    posted_at: date | None,
    first_seen_at: datetime,
    *,
    reviewed: bool = False,
) -> Listing:
    return Listing(
        company="Acme",
        title=f"Software Engineer {index}",
        location="Remote",
        application_url=f"https://jobs.example/{index}",
        posted_at=posted_at,
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
        fit_evaluated_at=first_seen_at if reviewed else None,
        resume_fit_confidence=85 if reviewed else None,
        resume_fit_reasoning="Resume fit complete." if reviewed else None,
    )


def test_select_recent_listings_defaults_to_newest_unreviewed_jobs():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        session.add_all([
            listing(
                1,
                date(2026, 7, 23),
                datetime(2026, 7, 25, tzinfo=timezone.utc),
            ),
            listing(
                2,
                date(2026, 7, 25),
                datetime(2026, 7, 25, tzinfo=timezone.utc),
                reviewed=True,
            ),
            listing(
                3,
                date(2026, 7, 24),
                datetime(2026, 7, 24, tzinfo=timezone.utc),
            ),
        ])
        session.commit()

        selected = select_recent_listings(session, 2)

        assert [item.application_url for item in selected] == [
            "https://jobs.example/3",
            "https://jobs.example/1",
        ]


def test_select_recent_listings_force_includes_reviewed_jobs():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        session.add_all([
            listing(
                1,
                date(2026, 7, 24),
                datetime(2026, 7, 24, tzinfo=timezone.utc),
            ),
            listing(
                2,
                date(2026, 7, 25),
                datetime(2026, 7, 25, tzinfo=timezone.utc),
                reviewed=True,
            ),
        ])
        session.commit()

        selected = select_recent_listings(session, 1, force=True)

        assert [item.application_url for item in selected] == [
            "https://jobs.example/2",
        ]


def test_select_recent_listings_includes_legacy_review_missing_resume_fit():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    reviewed_at = datetime(2026, 7, 25, tzinfo=timezone.utc)

    with Session() as session:
        legacy = listing(
            1,
            date(2026, 7, 25),
            reviewed_at,
            reviewed=True,
        )
        legacy.resume_fit_confidence = None
        legacy.resume_fit_reasoning = None
        session.add(legacy)
        session.commit()

        selected = select_recent_listings(session, 1)

        assert [item.application_url for item in selected] == [
            "https://jobs.example/1",
        ]


def test_review_command_force_persists_new_result(monkeypatch, capsys):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    reviewed_at = datetime(2026, 7, 25, tzinfo=timezone.utc)

    with Session() as session:
        session.add(listing(1, date(2026, 7, 25), reviewed_at, reviewed=True))
        session.commit()

    def fake_evaluate(session, listings):
        assert len(listings) == 1
        listings[0].fit_confidence = 92
        listings[0].fit_reasoning = "Updated Spring 2027 fit."
        listings[0].resume_fit_confidence = 96
        listings[0].resume_fit_reasoning = "Updated resume-based fit."
        session.commit()
        return 1

    monkeypatch.setattr(review, "SessionLocal", Session)
    monkeypatch.setattr(review, "create_tables", lambda: None)
    monkeypatch.setattr(review, "evaluate_listings", fake_evaluate)

    review.main(["1", "--force"])

    with Session() as session:
        saved = session.query(Listing).one()
        assert saved.fit_confidence == 92
        assert saved.fit_reasoning == "Updated Spring 2027 fit."
        assert saved.resume_fit_confidence == 96
        assert saved.resume_fit_reasoning == "Updated resume-based fit."
    assert "attempted=1 evaluated=1 failed=0" in capsys.readouterr().out
