from datetime import date, datetime, timezone

from starlette.requests import Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base
from app import main
from app.main import app, index, resume, visible_listing_condition
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


def request(query_string: bytes = b"", path: str = "/") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": query_string,
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "app": app,
    })


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


def test_visible_listing_condition_hides_closed_listings(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        open_listing = listing("open", date(2026, 7, 24))
        closed_listing = listing("closed", date(2026, 7, 24))
        closed_listing.is_open = False
        closed_listing.closed_at = datetime(2026, 7, 25, tzinfo=timezone.utc)
        session.add_all([open_listing, closed_listing])
        session.commit()

        visible = session.scalars(
            select(Listing).where(visible_listing_condition(date(2026, 7, 24)))
        ).all()

    assert [item.title for item in visible] == ["open"]

    monkeypatch.setattr(main, "settings", Settings(lifecycle_visibility=False))
    with Session() as session:
        visible_without_lifecycle = session.scalars(
            select(Listing).where(visible_listing_condition(date(2026, 7, 24)))
        ).all()
    assert {item.title for item in visible_without_lifecycle} == {"open", "closed"}


def test_index_hides_resume_fit_and_resume_page_shows_both_evaluations():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as session:
        job = listing("rendered", date(2026, 7, 24))
        job.company = "Acme & <Partners>"
        job.application_url = "https://jobs.example/apply?a=1&b=2"
        job.salary = "$120k–$140k"
        job.graduation_year = 2027
        job.fit_confidence = 88
        job.fit_reasoning = "Spring 2027 timing is supported."
        job.resume_fit_confidence = 93
        job.resume_fit_reasoning = "Resume shows strong Python experience."
        job.sources = [
            ListingSource(
                source_name="Curated & <List>",
                source_url="https://github.com/example/list?a=1&b=2",
            ),
            ListingSource(source_name="Company site", source_url="https://jobs.example"),
        ]
        pending = listing("pending", date(2026, 7, 23))
        pending.sources = [
            ListingSource(source_name="Curated List", source_url="https://github.com/example/list"),
        ]
        failed = listing("failed", date(2026, 7, 22))
        failed.fit_evaluation_failed_at = datetime(2026, 7, 25, tzinfo=timezone.utc)
        failed.fit_evaluation_error = "Codex review timed out."
        failed.sources = [
            ListingSource(source_name="Curated List", source_url="https://github.com/example/list"),
        ]
        session.add_all([job, pending, failed])
        session.commit()
        response = index(request(), q="", source="", session=session)
        resume_response = resume(
            request(path="/resume"),
            q="",
            source="",
            session=session,
        )

    html = response.body.decode()
    resume_html = resume_response.body.decode()
    assert response.status_code == 200
    assert f'href="http://testserver/static/styles.css?v={main.STYLES_VERSION}"' in html
    assert f'src="http://testserver/static/filters.js?v={main.FILTERS_VERSION}"' in html
    assert 'href="http://testserver/static/favicon.svg"' in html
    assert "<h1>New Grad SWE Jobs</h1>" in html
    assert "Updated twice daily" in html
    assert 'aria-label="Filter job listings"' in html
    assert ">Search</span>" in html
    assert ">Source</span>" in html
    assert 'class="filter-submit" type="submit">Filter</button>' in html
    assert "3 jobs" in html
    assert "Newest first" in html
    assert html.count('class="job-reviews job-reviews--single"') == 3
    assert "Is Spring 2027 New Grad" in html
    assert "88% match" in html
    assert "Spring 2027 timing is supported." in html
    assert "Theo's Resume fit" not in html
    assert "ignoring dates" not in html
    assert "93% match" not in html
    assert "Resume shows strong Python experience." not in html
    assert "$120k–$140k" in html
    assert "Class of 2027" in html
    assert html.count("Not yet evaluated") == 1
    assert html.count("Evaluation failed") == 1
    assert html.count("fit-score--failed") == 1
    assert "Codex review timed out." in html
    assert 'class="fit-reasoning fit-error"' in html
    assert ">Sources</span>" in html
    assert "Acme &amp; &lt;Partners&gt;" in html
    assert "Curated &amp; &lt;List&gt;" in html
    assert "Company site" in html
    github_group = html.index('<optgroup label="GitHub lists">')
    job_board_group = html.index('<optgroup label="Company job boards">')
    assert github_group < job_board_group
    assert github_group < html.index('value="Curated &amp; &lt;List&gt;"') < job_board_group
    assert job_board_group < html.index('value="Company site"')
    assert 'href="https://jobs.example/apply?a=1&amp;b=2" target="_blank" rel="noopener">Apply' in html
    assert 'href="https://github.com/example/list?a=1&amp;b=2" target="_blank" rel="noopener">Curated &amp; &lt;List&gt;</a>' in html
    assert 'id="email-signup"' in html
    assert 'action="/subscribe"' in html
    assert ">Subscribe</button>" in html
    assert resume_response.status_code == 200
    assert '<meta name="robots" content="noindex,nofollow">' in resume_html
    assert resume_html.count('class="job-reviews"') == 3
    assert "Theo's Resume fit" in resume_html
    assert "93% match" in resume_html
    assert "Resume shows strong Python experience." in resume_html
    assert resume_html.count("Not yet evaluated") == 2
    assert resume_html.count("Evaluation failed") == 2
    assert resume_html.count("fit-score--failed") == 2


def test_index_preserves_filter_state_and_renders_subscription_notice():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as session:
        job = listing("Backend Engineer", date(2026, 7, 24))
        job.sources = [
            ListingSource(source_name="Curated List", source_url="https://github.com/example/list"),
        ]
        session.add(job)
        session.commit()
        response = index(
            request(b"subscription=check-email"),
            q="Acme",
            source="Curated List",
            session=session,
        )

    html = response.body.decode()
    assert 'name="q" value="Acme"' in html
    assert '<option value="Curated List" selected>Curated List</option>' in html
    assert '<a class="clear-filter" href="/">Clear</a>' in html
    assert "1 job" in html
    assert "If this address still needs confirmation" in html
    assert 'class="signup-notice signup-notice--success" role="status"' in html


def test_index_renders_empty_and_unavailable_states(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "settings", Settings(
        public_url="",
        smtp_host="",
        smtp_from="",
        subscription_token_secret="",
    ))

    with Session() as session:
        response = index(request(), q="missing", source="", session=session)

    html = response.body.decode()
    assert "0 jobs" in html
    assert "No matching jobs" in html
    assert "Try a broader search or clear your filters." in html
    assert '<a href="/">Clear all filters</a>' in html
    assert "Email signup is temporarily unavailable." in html
    assert 'id="signup-email"' in html
    assert "disabled" in html
