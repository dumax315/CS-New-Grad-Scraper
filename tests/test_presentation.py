from datetime import date, datetime, timezone

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
        resume_fit_confidence=91 if confidence is not None else None,
        resume_fit_reasoning="Resume shows matching backend experience.",
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
    assert job.resume_fit_label == "91% match"
    assert job.resume_fit_tone == "strong"
    assert job.sources[0].name == "Curated List"


def test_present_listing_handles_unscored_and_source_age_without_awkward_ago():
    item = listing(confidence=None, posted_at=None)
    item.source_age = "Today"
    item.fit_reasoning = None
    item.resume_fit_reasoning = None

    job = present_listing(item)

    assert job.posted_label == "Posted Today"
    assert job.fit_label == "Not yet evaluated"
    assert job.fit_tone == "pending"
    assert job.resume_fit_label == "Not yet evaluated"
    assert job.resume_fit_tone == "pending"


def test_present_listing_distinguishes_failed_evaluation_from_pending():
    item = listing()
    item.fit_evaluation_failed_at = datetime(2026, 7, 25, tzinfo=timezone.utc)
    item.fit_evaluation_error = "Codex review timed out."

    job = present_listing(item)

    assert job.fit_evaluation_error == "Codex review timed out."
    assert job.fit_confidence is None
    assert job.fit_label == "Evaluation failed"
    assert job.fit_tone == "failed"
    assert job.fit_reasoning is None
    assert job.resume_fit_confidence is None
    assert job.resume_fit_label == "Evaluation failed"
    assert job.resume_fit_tone == "failed"
    assert job.resume_fit_reasoning is None


def test_present_listing_promotes_http_failure_to_fit_label():
    item = listing()
    item.fit_evaluation_failed_at = datetime(2026, 7, 25, tzinfo=timezone.utc)
    item.fit_evaluation_error = "Job posting returned HTTP 403."

    job = present_listing(item)

    assert job.fit_label == "HTTP 403"
    assert job.fit_evaluation_error == "Job posting returned HTTP 403."
    assert job.resume_fit_label == "Evaluation failed"


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
