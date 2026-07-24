import subprocess

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app import database
from app.database import Base
from app.models import Listing
from app import worker


def listing(index: int = 0) -> Listing:
    return Listing(
        company="Acme",
        title=f"Software Engineer {index}",
        location="Remote",
        application_url=f"https://jobs.example/{index}",
    )


def test_extract_visible_text_ignores_scripts_and_styles():
    html = """
    <html><style>.hidden { display: none }</style><script>stealSecrets()</script>
    <body><h1>Software Engineer</h1><p>Class of 2027 accepted.</p></body></html>
    """
    assert worker.extract_visible_text(html) == "Software Engineer\nClass of 2027 accepted."


def test_parse_fit_result_requires_requested_format():
    assert worker.parse_fit_result("87% — Accepts Spring 2027 CS graduates.") == (
        87,
        "Accepts Spring 2027 CS graduates.",
    )


def test_run_codex_assessment_uses_noninteractive_sandbox_and_sanitized_env(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="91% — Strong new-grad fit.\n", stderr="")

    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("CODEX_API_KEY", "codex-secret")
    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    assert worker.run_codex_assessment(listing(), "Actual scraped listing") == (
        91,
        "Strong new-grad fit.",
    )
    assert captured["command"][:3] == ["codex", "exec", "--ephemeral"]
    assert "read-only" in captured["command"]
    assert captured["input"] == "Actual scraped listing"
    assert captured["env"]["CODEX_API_KEY"] == "codex-secret"
    assert captured["env"]["CODEX_HOME"] == captured["cwd"]
    assert "DATABASE_URL" not in captured["env"]


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
    monkeypatch.setattr(worker, "run_codex_assessment", lambda job, text: (80, f"Fit for {job.title}."))

    with Session() as session:
        session.add_all(jobs)
        session.commit()
        assert worker.evaluate_new_listings(session, jobs) == 10

    assert len(seen) == 10
    assert all(job.fit_confidence == 80 for job in jobs[:10])
    assert all(job.fit_selected_at is not None for job in jobs[:10])
    assert all(job.fit_confidence is None for job in jobs[10:])
    assert all(job.fit_selected_at is None for job in jobs[10:])


def test_selected_jobs_are_retried_after_worker_restart(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    job = listing()

    monkeypatch.setattr(worker, "scrape_job_listing", lambda url: "job text")
    monkeypatch.setattr(worker, "run_codex_assessment", lambda listing, text: (75, "Eligible new grad role."))

    with Session() as session:
        session.add(job)
        session.commit()
        job.fit_selected_at = worker.datetime.now(worker.timezone.utc)
        session.commit()
        assert worker.evaluate_new_listings(session, []) == 1
        assert job.fit_confidence == 75


def test_create_tables_migrates_existing_listing_table(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE listings (id INTEGER PRIMARY KEY, posted_at DATE)")

    monkeypatch.setattr(database, "engine", engine)
    database.create_tables()

    columns = {column["name"] for column in inspect(engine).get_columns("listings")}
    assert {
        "fit_confidence", "fit_reasoning", "fit_selected_at", "fit_evaluated_at", "fit_model",
    } <= columns
