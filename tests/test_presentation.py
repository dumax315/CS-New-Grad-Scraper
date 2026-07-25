from datetime import date

from app.models import Listing, ListingSource
from app.presentation import present_listing, present_listings


def listing(
    company: str = "Acme & Co.",
    confidence: int | None = 82,
    posted_at: date | None = date(2026, 7, 4),
) -> Listing:
    job = Listing(
        company=company,
        title="Software Engineer, New Grad",
        location="San Francisco, CA",
        application_url="https://jobs.example/apply",
        salary="$120k–$140k",
        graduation_year=2027,
        posted_at=posted_at,
        fit_confidence=confidence,
        fit_reasoning="Spring 2027 timing is explicitly supported.",
    )
    job.sources = [
        ListingSource(source_name="Curated List", source_url="https://github.com/example/list"),
    ]
    return job


def test_present_listing_formats_shared_job_card_content():
    job = present_listing(listing())

    assert job.company == "Acme & Co."
    assert job.meta == ("San Francisco, CA", "$120k–$140k", "Class of 2027")
    assert job.posted_label == "Posted Jul 4, 2026"
    assert job.fit_label == "82% match"
    assert job.fit_tone == "strong"
    assert job.sources[0].name == "Curated List"


def test_present_listing_handles_unscored_and_source_age_without_awkward_ago():
    item = listing(confidence=None, posted_at=None)
    item.source_age = "Today"
    item.fit_reasoning = None

    job = present_listing(item)

    assert job.posted_label == "Posted Today"
    assert job.fit_label == "Not yet evaluated"
    assert job.fit_tone == "pending"


def test_present_listings_places_highest_scores_first_and_unscored_last():
    jobs = [
        listing("Unscored", None),
        listing("Promising", 68),
        listing("Strong", 91),
        listing("Limited", 25),
    ]

    presented = present_listings(jobs, highest_fit_first=True)

    assert [job.company for job in presented] == [
        "Strong",
        "Promising",
        "Limited",
        "Unscored",
    ]
    assert [job.fit_tone for job in presented] == [
        "strong",
        "promising",
        "limited",
        "pending",
    ]
