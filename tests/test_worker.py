import subprocess

import httpx
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app import database
from app.database import Base
from app.config import Settings
from app.models import Listing, Subscriber
from app import worker


def listing(index: int = 0) -> Listing:
    return Listing(
        company="Acme",
        title=f"Software Engineer {index}",
        location="Remote",
        application_url=f"https://jobs.example/{index}",
    )


def assessment(index: int = 0) -> worker.FitAssessment:
    return worker.FitAssessment(
        confidence=80,
        reasoning=f"Spring 2027 fit for Software Engineer {index}.",
        resume_confidence=90,
        resume_reasoning=f"Resume fit for Software Engineer {index}.",
    )


def test_extract_visible_text_ignores_scripts_and_styles():
    html = """
    <html><style>.hidden { display: none }</style><script>stealSecrets()</script>
    <body><h1>Software Engineer</h1><p>Class of 2027 accepted.</p></body></html>
    """
    assert worker.extract_visible_text(html) == "Software Engineer\nClass of 2027 accepted."


def test_extract_structured_job_text_reads_job_posting_json_ld():
    html = """
    <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"JobPosting",
       "title":"Graduate Engineer","datePosted":"2026-07-24",
       "description":"<p>Class of 2027 accepted.</p>"}
    </script>
    """
    assert worker.extract_structured_job_text(html) == (
        "Title: Graduate Engineer\n"
        "Date posted: 2026-07-24\n"
        "Description: Class of 2027 accepted."
    )


def test_scrape_job_listing_uses_workday_structured_endpoint():
    page_url = (
        "https://nvidia.wd5.myworkdayjobs.com/en-US/nvidiaexternalcareersite/"
        "job/US-CA-Remote/Software-Engineer_JR123"
    )

    def handler(request: httpx.Request):
        assert request.url.path == (
            "/wday/cxs/nvidia/nvidiaexternalcareersite/"
            "job/US-CA-Remote/Software-Engineer_JR123"
        )
        return httpx.Response(200, json={
            "jobPostingInfo": {
                "title": "Software Engineer",
                "jobReqId": "JR123",
                "location": "US, Remote",
                "additionalLocations": [],
                "postedOn": "Posted Today",
                "jobDescription": "<p>Full job description.</p>",
            },
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert worker.scrape_job_listing(page_url, client) == (
            "Title: Software Engineer\n"
            "Job requisition: JR123\n"
            "Location: US, Remote\n"
            "Posting age: Posted Today\n"
            "Description: Full job description."
        )


def test_parse_fit_result_requires_requested_format():
    assert worker.parse_fit_result(
        "IS SPRING 2027 NEW GRAD: 87% — Accepts Spring 2027 CS graduates.\n"
        "THEO'S RESUME FIT: 93% — Resume shows the required backend experience.\n"
    ) == worker.FitAssessment(
        confidence=87,
        reasoning="Accepts Spring 2027 CS graduates.",
        resume_confidence=93,
        resume_reasoning="Resume shows the required backend experience.",
    )


def test_run_codex_assessment_uses_noninteractive_sandbox_and_sanitized_env(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "IS SPRING 2027 NEW GRAD: 91% — Strong new-grad fit.\n"
                "THEO'S RESUME FIT: 86% — Resume shows relevant Python experience.\n"
            ),
            stderr="",
        )

    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("CODEX_API_KEY", "codex-secret")
    monkeypatch.setenv("SUBSCRIPTION_TOKEN_SECRET", "subscription-secret")
    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    assert worker.run_codex_assessment(
        listing(), "Actual scraped listing",
    ) == worker.FitAssessment(
        confidence=91,
        reasoning="Strong new-grad fit.",
        resume_confidence=86,
        resume_reasoning="Resume shows relevant Python experience.",
    )
    assert captured["command"][:3] == ["codex", "exec", "--ephemeral"]
    assert "read-only" in captured["command"]
    assert captured["input"] == "Actual scraped listing"
    assert captured["env"]["CODEX_API_KEY"] == "codex-secret"
    assert captured["env"]["CODEX_HOME"] == captured["cwd"]
    assert "DATABASE_URL" not in captured["env"]
    assert "SUBSCRIPTION_TOKEN_SECRET" not in captured["env"]


def test_codex_prompt_makes_spring_2027_timing_a_gate(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["prompt"] = command[-1]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "IS SPRING 2027 NEW GRAD: 70% — Technical fit is strong, but spring 2027 timing is unstated.\n"
                "THEO'S RESUME FIT: 90% — Resume shows strong matching C skills.\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    assert worker.run_codex_assessment(
        listing(),
        "Bachelor's degree. Strong C skills; coursework and internships count.",
    ).confidence == 70
    prompt = " ".join(captured["prompt"].split())
    assert "hiring timing as a gating requirement" in prompt
    assert "must be 75% or below" in prompt
    assert "do not by themselves prove" in prompt
    assert "spring 2027 timing is" in prompt
    assert "Do not use the candidate resume as evidence for this score" in prompt


def test_codex_prompt_uses_resume_as_candidate_evidence(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["prompt"] = command[-1]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "IS SPRING 2027 NEW GRAD: 84% — Spring 2027 timing is supported.\n"
                "THEO'S RESUME FIT: 91% — Resume shows matching C++ experience.\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    worker.run_codex_assessment(
        listing(),
        "Class of 2027. C++ experience preferred.",
        candidate_resume="# Candidate\n\n- Built embedded systems in C++.",
    )

    prompt = " ".join(captured["prompt"].split())
    assert "<candidate_resume>" in prompt
    assert "Built embedded systems in C++." in prompt
    assert "For THEO'S RESUME FIT" in prompt
    assert "compare the role's responsibilities and requirements with concrete evidence in Theo's resume" in prompt
    assert "Ignore all graduation dates, hiring windows, start dates" in prompt
    assert "must not discuss date eligibility" in prompt


def test_load_candidate_resume_rejects_empty_file(tmp_path):
    resume_path = tmp_path / "resume.md"
    resume_path.write_text("\n", encoding="utf-8")

    try:
        worker.load_candidate_resume(resume_path)
    except ValueError as error:
        assert "candidate resume is empty" in str(error)
    else:
        raise AssertionError("empty resume should be rejected")


def test_load_candidate_resume_omits_contact_header(tmp_path):
    resume_path = tmp_path / "resume.md"
    resume_path.write_text(
        "# Candidate Name\n\n555-0100 | candidate@example.com\n\n"
        "## Education\n\nComputer Science\n",
        encoding="utf-8",
    )

    assert worker.load_candidate_resume(resume_path) == "## Education\n\nComputer Science"


def test_load_candidate_resume_defaults_to_process_working_directory(tmp_path, monkeypatch):
    resume_path = tmp_path / worker.DEFAULT_RESUME_FILENAME
    resume_path.write_text("## Experience\n\nBuilt reliable systems.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert worker.load_candidate_resume() == "## Experience\n\nBuilt reliable systems."


def test_codex_environment_uses_persistent_login_without_api_key(monkeypatch):
    monkeypatch.setenv("CODEX_API_KEY", "")
    environment = worker.codex_environment("/tmp/temporary-codex")
    assert environment["CODEX_HOME"] == worker.settings.codex_home
    assert environment["HOME"] == "/tmp/temporary-codex"
    assert "CODEX_API_KEY" not in environment


def test_evaluate_new_listings_caps_each_run_at_ten(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    jobs = [listing(index) for index in range(12)]
    seen = []

    def fake_scrape(url):
        seen.append(url)
        return "job text"

    monkeypatch.setattr(worker, "scrape_job_listing", fake_scrape)
    monkeypatch.setattr(
        worker,
        "run_codex_assessment",
        lambda job, text: assessment(int(job.title.rsplit(" ", 1)[1])),
    )

    with Session() as session:
        session.add_all(jobs)
        session.commit()
        assert worker.evaluate_new_listings(session, jobs) == 10

    assert len(seen) == 10
    assert all(job.fit_confidence == 80 for job in jobs[:10])
    assert all(job.resume_fit_confidence == 90 for job in jobs[:10])
    assert all(job.fit_selected_at is not None for job in jobs[:10])
    assert all(job.fit_confidence is None for job in jobs[10:])
    assert all(job.resume_fit_confidence is None for job in jobs[10:])
    assert all(job.fit_selected_at is None for job in jobs[10:])


def test_selected_jobs_are_retried_after_worker_restart(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    job = listing()

    monkeypatch.setattr(worker, "scrape_job_listing", lambda url: "job text")
    monkeypatch.setattr(worker, "run_codex_assessment", lambda listing, text: assessment())

    with Session() as session:
        session.add(job)
        session.commit()
        job.fit_selected_at = worker.datetime.now(worker.timezone.utc)
        session.commit()
        assert worker.evaluate_new_listings(session, []) == 1
        assert job.fit_confidence == 80
        assert job.resume_fit_confidence == 90


def test_failed_evaluation_is_persisted_and_remains_retryable(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    job = listing()

    def failed_codex(listing, text):
        raise subprocess.TimeoutExpired(["codex", "candidate-secret"], 120)

    monkeypatch.setattr(worker, "scrape_job_listing", lambda url: "job text")
    monkeypatch.setattr(worker, "run_codex_assessment", failed_codex)

    with Session() as session:
        session.add(job)
        session.commit()

        assert worker.evaluate_new_listings(session, [job]) == 0
        assert job.fit_evaluated_at is None
        assert job.fit_evaluation_failed_at is not None
        assert job.fit_evaluation_error == "Codex review timed out."
        assert "candidate-secret" not in job.fit_evaluation_error

    monkeypatch.setattr(worker, "run_codex_assessment", lambda listing, text: assessment())

    with Session() as session:
        saved = session.get(Listing, job.id)
        assert worker.evaluate_new_listings(session, []) == 1
        assert saved.fit_evaluated_at is not None
        assert saved.fit_evaluation_failed_at is None
        assert saved.fit_evaluation_error is None


def test_create_tables_migrates_existing_listing_table(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE listings (id INTEGER PRIMARY KEY, posted_at DATE)")

    monkeypatch.setattr(database, "engine", engine)
    database.create_tables()

    columns = {column["name"] for column in inspect(engine).get_columns("listings")}
    assert {
        "fit_confidence", "fit_reasoning", "resume_fit_confidence",
        "resume_fit_reasoning", "fit_selected_at", "fit_evaluated_at",
        "fit_evaluation_failed_at", "fit_evaluation_error", "fit_model",
    } <= columns
    assert "subscribers" in inspect(engine).get_table_names()
    assert "source_runs" in inspect(engine).get_table_names()

    database.create_tables()
    assert "source_runs" in inspect(engine).get_table_names()


def test_scrape_and_notify_sends_only_to_active_subscribers(monkeypatch):
    engine = create_engine("sqlite://")
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    captured = {}
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)

    with Session() as session:
        session.add(listing(99))
        session.add_all([
            Subscriber(
                email="active@example.com",
                confirmation_token_hash="a" * 64,
                confirmation_expires_at=now,
                confirmed_at=now,
            ),
            Subscriber(
                email="pending@example.com",
                confirmation_token_hash="b" * 64,
                confirmation_expires_at=now,
            ),
            Subscriber(
                email="left@example.com",
                confirmation_token_hash="c" * 64,
                confirmation_expires_at=now,
                confirmed_at=now,
                unsubscribed_at=now,
            ),
        ])
        session.commit()

    def fake_ingestion(session):
        new_listing = listing(100)
        session.add(new_listing)
        session.commit()
        return [new_listing]

    def fake_send(listings, config=worker.settings, recipients=()):
        captured["listings"] = listings
        captured["recipients"] = list(recipients)
        return True

    monkeypatch.setattr(worker, "SessionLocal", Session)
    monkeypatch.setattr(worker, "run_ingestion", fake_ingestion)
    monkeypatch.setattr(worker, "evaluate_new_listings", lambda session, listings: 0)
    monkeypatch.setattr(worker, "send_new_jobs_digest", fake_send)
    monkeypatch.setattr(worker, "settings", Settings(
        public_url="https://board.example",
        subscription_token_secret="test-secret",
    ))

    worker.scrape_and_notify()

    assert len(captured["listings"]) == 1
    assert [recipient.address for recipient in captured["recipients"]] == [
        "active@example.com",
    ]
    assert captured["recipients"][0].unsubscribe_url.startswith(
        "https://board.example/unsubscribe?token=",
    )


def test_ingestion_cycle_can_skip_codex_and_force_initial_digest(monkeypatch):
    engine = create_engine("sqlite://")
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    captured = {}

    def fake_ingestion(session):
        new_listing = listing(101)
        session.add(new_listing)
        session.commit()
        return [new_listing]

    def unexpected_evaluation(session, listings):
        raise AssertionError("Codex evaluation should be disabled")

    def fake_send(listings, config=worker.settings, recipients=()):
        captured["listings"] = listings
        return True

    monkeypatch.setattr(worker, "SessionLocal", Session)
    monkeypatch.setattr(worker, "run_ingestion", fake_ingestion)
    monkeypatch.setattr(worker, "evaluate_new_listings", unexpected_evaluation)
    monkeypatch.setattr(worker, "send_new_jobs_digest", fake_send)
    monkeypatch.setattr(worker, "settings", Settings(send_initial_digest=False))

    result = worker.run_ingestion_cycle(
        review_with_codex=False,
        force_digest=True,
    )

    assert result == worker.IngestionResult(
        new_listings=1,
        evaluated=0,
        digest_sent=True,
        initial_run=True,
    )
    assert [item.application_url for item in captured["listings"]] == [
        "https://jobs.example/101",
    ]
