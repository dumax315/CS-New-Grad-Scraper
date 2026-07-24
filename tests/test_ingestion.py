from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.ingestion import store_candidates
from app.models import Listing
from app.sources import Candidate


def candidate(source_name="Source A"):
    return Candidate("Acme", "Software Engineer", "Seattle", "https://jobs.example/role", source_name, "https://github.com/example")


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
