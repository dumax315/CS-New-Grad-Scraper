from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.ingestion import store_candidates
from app.models import Listing
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
        overlap = next(listing for listing in listings if listing.company == "Acme Incorporated")
        assert [source.source_name for source in overlap.sources] == [
            SOURCES[0].name,
            SOURCES[1].name,
        ]
