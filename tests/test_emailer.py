from datetime import datetime, timezone
from email.message import EmailMessage

from app.config import Settings
from app.emailer import DigestRecipient, render_confirmation, render_digest, send_new_jobs_digest
from app.models import Listing, ListingSource


def listing(
    company: str,
    confidence: int | None,
    *,
    application_url: str = "https://jobs.example/apply?a=1&b=2",
) -> Listing:
    job = Listing(
        company=company,
        title="SWE <New Grad>",
        location="Remote",
        application_url=application_url,
        graduation_year=2027,
        fit_confidence=confidence,
        fit_reasoning="Timing supported & technical fit is strong.",
        resume_fit_confidence=89 if confidence is not None else None,
        resume_fit_reasoning=(
            "Resume shows matching systems experience."
            if confidence is not None else None
        ),
    )
    job.sources = [
        ListingSource(
            source_name="GitHub & Friends",
            source_url="https://github.com/example/list?a=1&b=2",
        ),
    ]
    return job


def test_render_digest_uses_shared_hierarchy_sorting_and_escaping():
    digest = render_digest(
        [listing("Unscored", None), listing("Top & <Choice>", 94)],
        "https://board.example/",
    )

    assert digest.subject == "2 new roles for Spring 2027"
    assert digest.text.index("Top & <Choice>") < digest.text.index("Unscored")
    assert "IS SPRING 2027 NEW GRAD: 94% MATCH" in digest.text
    assert "THEO'S RESUME FIT: 89% MATCH" in digest.text
    assert "IS SPRING 2027 NEW GRAD: NOT YET EVALUATED" in digest.text
    assert "THEO'S RESUME FIT: NOT YET EVALUATED" in digest.text
    assert "Browse all jobs: https://board.example" in digest.text
    assert "Top &amp; &lt;Choice&gt;" in digest.html
    assert "SWE &lt;New Grad&gt;" in digest.html
    assert 'href="https://jobs.example/apply?a=1&amp;b=2"' in digest.html
    assert "Remote &nbsp;·&nbsp; Class of 2027" in digest.html
    assert "&amp;nbsp;" not in digest.html
    assert digest.html.index("Top &amp; &lt;Choice&gt;") < digest.html.index(
        "Is Spring 2027 New Grad"
    )
    assert digest.html.count('width="50%" valign="top"') == 4
    assert "background:#e9f5f0;color:#056246" in digest.html
    assert "border-bottom:1px solid #d9dfdb" in digest.html
    assert "border-top:1px solid #d9dfdb" in digest.html
    assert "border-radius:12px" not in digest.html
    assert "Timing supported &amp; technical fit is strong." in digest.html
    assert "Resume shows matching systems experience." in digest.html
    assert "ignoring dates" not in digest.html
    assert "ignoring dates" not in digest.text
    assert "Browse all jobs" in digest.html


def test_render_digest_omits_browse_button_without_public_url():
    digest = render_digest([listing("Acme", 75)])

    assert digest.subject == "1 new role for Spring 2027"
    assert "Browse all jobs" not in digest.text
    assert "Browse all jobs" not in digest.html


def test_render_digest_distinguishes_failed_evaluation_from_pending():
    failed = listing("Failed", None)
    failed.fit_evaluation_failed_at = datetime(2026, 7, 25, tzinfo=timezone.utc)
    failed.fit_evaluation_error = "Codex review timed out."

    digest = render_digest([failed])

    assert "IS SPRING 2027 NEW GRAD: EVALUATION FAILED" in digest.text
    assert "THEO'S RESUME FIT: EVALUATION FAILED" in digest.text
    assert "Evaluation error: Codex review timed out." in digest.text
    assert "Evaluation failed" in digest.html
    assert "Codex review timed out." in digest.html
    assert "background:#fdf0f0;color:#923e3e" in digest.html


def test_confirmation_and_digest_render_tokenized_links_safely():
    confirmation = render_confirmation("https://board.example/confirm?token=a&next=b")
    digest = render_digest(
        [listing("Acme", 75)],
        "https://board.example",
        "https://board.example/unsubscribe?token=secret&next=1",
    )

    assert "https://board.example/confirm?token=a&next=b" in confirmation.text
    assert "token=a&amp;next=b" in confirmation.html
    assert "background:#f7f8f7;color:#17211c" in confirmation.html
    assert "border-bottom:1px solid #d9dfdb" in confirmation.html
    assert "border-radius:12px" not in confirmation.html
    assert "Unsubscribe: https://board.example/unsubscribe?token=secret&next=1" in digest.text
    assert "token=secret&amp;next=1" in digest.html


def test_send_digest_builds_multipart_message(monkeypatch):
    captured: dict[str, EmailMessage | bool] = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.example", 587, 30)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            captured["tls"] = True

        def login(self, username, password):
            assert (username, password) == ("mailer", "secret")

        def send_message(self, message):
            captured["message"] = message

    monkeypatch.setattr("app.emailer.smtplib.SMTP", FakeSMTP)
    config = Settings(
        smtp_host="smtp.example",
        smtp_username="mailer",
        smtp_password="secret",
        smtp_from="Jobs <jobs@example.com>",
        alert_recipient="reader@example.com",
        public_url="https://board.example",
    )

    assert send_new_jobs_digest([listing("Acme", 88)], config) is True
    message = captured["message"]
    assert isinstance(message, EmailMessage)
    assert message["Subject"] == "1 new role for Spring 2027"
    assert message.is_multipart()
    assert message.get_body(preferencelist=("html",)).get_content_type() == "text/html"
    assert captured["tls"] is True


def test_send_digest_reuses_connection_and_deduplicates_admin_recipient(monkeypatch):
    messages = []
    connections = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            connections.append((host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            return None

        def login(self, username, password):
            return None

        def send_message(self, message):
            messages.append(message)

    monkeypatch.setattr("app.emailer.smtplib.SMTP", FakeSMTP)
    config = Settings(
        smtp_host="smtp.example",
        smtp_from="Jobs <jobs@example.com>",
        alert_recipient="reader@example.com",
        public_url="https://board.example",
    )

    assert send_new_jobs_digest(
        [listing("Acme", 88)],
        config,
        recipients=[
            DigestRecipient("reader@example.com", "https://board.example/unsubscribe?token=one"),
            DigestRecipient("other@example.com", "https://board.example/unsubscribe?token=two"),
        ],
    ) is True

    assert len(connections) == 1
    assert {message["To"] for message in messages} == {
        "reader@example.com", "other@example.com",
    }
    reader_message = next(message for message in messages if message["To"] == "reader@example.com")
    assert reader_message["List-Unsubscribe"] == (
        "<https://board.example/unsubscribe?token=one>"
    )
    assert reader_message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
