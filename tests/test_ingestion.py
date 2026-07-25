from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import ingestion
from app.database import Base
from app.ingestion import run_ingestion, store_candidates
from app.main import visible_listing_condition
from app.models import Listing, SourceRun
from app.source_types import SourceBatch, SourceFetchResult
from app.sources import SOURCES, Candidate, fetch_candidates


FIXTURES = Path(__file__).parent / "fixtures"


def candidate(source_name="Source A"):
    return Candidate(
        "Acme", "Software Engineer", "Seattle", "https://jobs.example/role", source_name,
        "https://github.com/example", posted_at=date(2026, 7, 23),
    )


def test_store_is_idempotent_and_keeps_both_sources():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        first = store_candidates(session, [candidate()])
        second = store_candidates(session, [candidate(), candidate("Source B")])
        listing = session.query(Listing).one()
        assert len(first) == 1
        assert second == []
        assert len(listing.sources) == 2
        assert listing.posted_at == date(2026, 7, 23)


def test_curated_source_overlap_is_one_listing_with_two_provenance_rows():
    fixture_names = ("speedyapply_new_grad.md", "vansh_new_grad.md")
    bodies = {
        source.raw_url: (FIXTURES / fixture_name).read_text()
        for source, fixture_name in zip(SOURCES, fixture_names, strict=True)
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=bodies[str(request.url)])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        candidates = fetch_candidates(client)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        stored = store_candidates(session, candidates)
        listings = session.query(Listing).order_by(Listing.application_url).all()

        assert len(stored) == 3
        assert len(listings) == 3
        assert session.scalar(
            select(func.count(Listing.id)).where(
                visible_listing_condition(date(2026, 7, 25)),
            ),
        ) == 3
        overlap = next(listing for listing in listings if listing.company == "Acme Incorporated")
        assert [source.source_name for source in overlap.sources] == [
            SOURCES[0].name,
            SOURCES[1].name,
        ]


def source_result(
    source_key: str,
    *,
    succeeded: bool = True,
    candidates=(),
    fetched_count: int = 0,
) -> SourceFetchResult:
    now = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
    return SourceFetchResult(
        source_key=source_key,
        source_name=source_key,
        succeeded=succeeded,
        candidates=tuple(candidates),
        fetched_count=fetched_count,
        error_category=None if succeeded else "timeout",
        error_summary=None if succeeded else "Source request timed out.",
        started_at=now,
        finished_at=now,
    )


def test_run_ingestion_persists_success_and_failure_metrics(monkeypatch, caplog):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    batch = SourceBatch((
        source_result("markdown:working", candidates=(candidate(),), fetched_count=1),
        source_result("markdown:failed", succeeded=False),
    ))
    monkeypatch.setattr(ingestion, "fetch_source_batch", lambda: batch)

    with Session() as session:
        new_listings = run_ingestion(session)
        runs = session.scalars(select(SourceRun).order_by(SourceRun.id)).all()

    assert len(new_listings) == 1
    assert [
        (run.source_key, run.status, run.fetched_count, run.accepted_count, run.new_count)
        for run in runs
    ] == [
        ("markdown:working", "success", 1, 1, 1),
        ("markdown:failed", "failed", 0, 0, 0),
    ]
    assert runs[1].error_category == "timeout"
    assert runs[1].error_summary == "Source request timed out."
    assert "1 successful and 1 failed sources" in caplog.text


def test_failed_source_run_does_not_modify_existing_listings(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(
        ingestion,
        "fetch_source_batch",
        lambda: SourceBatch((source_result("markdown:failed", succeeded=False),)),
    )

    with Session() as session:
        store_candidates(session, [candidate()])
        before = session.query(Listing).one().last_seen_at
        assert run_ingestion(session) == []
        listing = session.query(Listing).one()

        assert listing.last_seen_at == before
        assert session.query(SourceRun).one().status == "failed"
