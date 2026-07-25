from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Listing, ListingSource
from app.source_discovery import discover_source_proposals, recognize_ats_url


def test_recognizes_supported_ats_urls_and_encoded_redirects():
    assert recognize_ats_url(
        "https://boards.greenhouse.io/Acme/jobs/123?gh_src=list",
    ) == (
        "greenhouse",
        "acme",
        "recognized greenhouse tenant in application URL",
    )
    assert recognize_ats_url(
        "https://redirect.example/apply?target="
        "https%3A%2F%2Fjobs.lever.co%2FBeta_Corp%2Fjob-id%3Flever-source%3Dlist",
    ) == (
        "lever",
        "beta_corp",
        "recognized lever tenant in encoded redirect target",
    )
    assert recognize_ats_url(
        "https://jobs.ashbyhq.com/gamma/job-id?utm_source=list",
    ) == (
        "ashby",
        "gamma",
        "recognized ashby tenant in application URL",
    )
    assert recognize_ats_url(
        "https://boards.greenhouse.io/embed/job_app?for=delta",
    )[:2] == ("greenhouse", "delta")


def test_rejects_unsupported_hosts_and_malformed_tenants():
    assert recognize_ats_url("https://jobs.example.com/acme/123") is None
    assert recognize_ats_url("https://jobs.lever.co/a/123") is None
    assert recognize_ats_url("https://boards.greenhouse.io/%2E%2E/jobs/123") is None
    assert recognize_ats_url("not a URL") is None


def listing(company: str, url: str, source_name: str) -> Listing:
    item = Listing(
        company=company,
        title="Software Engineer",
        location="Remote",
        application_url=url,
    )
    item.sources = [
        ListingSource(
            source_name=source_name,
            source_url="https://github.com/example/jobs",
        ),
    ]
    return item


def test_discovery_is_sorted_and_deduplicated_with_provenance():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add_all([
            listing(
                "Acme",
                "https://boards.greenhouse.io/acme/jobs/200?utm_source=one",
                "Source B",
            ),
            listing(
                "Acme Incorporated",
                "https://boards.greenhouse.io/acme/jobs/100",
                "Source A",
            ),
            listing(
                "Gamma",
                "https://jobs.ashbyhq.com/gamma/job-300",
                "Source A",
            ),
            listing(
                "Unsupported",
                "https://careers.example.com/jobs/1",
                "Source A",
            ),
        ])
        session.commit()

        proposals = discover_source_proposals(session)

    assert [proposal.key for proposal in proposals] == [
        "ashby:gamma",
        "greenhouse:acme",
    ]
    assert proposals[1].employer == "Acme Incorporated"
    assert proposals[1].discovered_from_url == (
        "https://boards.greenhouse.io/acme/jobs/100"
    )
    assert proposals[1].source_names == ("Source A", "Source B")
