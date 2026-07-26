from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database import Base
from app import main
from app.models import Subscriber
from app.subscriptions import (
    confirm_subscription,
    find_unsubscribe_subscriber,
    mark_confirmation_sent,
    prepare_confirmation,
    token_hash,
    unsubscribe,
    unsubscribe_token,
)


NOW = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)


def subscriber_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_confirmation_normalizes_email_hashes_token_and_enforces_resend_delay():
    Session = subscriber_session()

    with Session() as session:
        subscriber, raw_token = prepare_confirmation(
            session, "  Reader@Example.COM ", now=NOW,
        )
        assert subscriber.email == "reader@example.com"
        assert raw_token is not None
        assert subscriber.confirmation_token_hash == token_hash(raw_token)
        assert raw_token not in subscriber.confirmation_token_hash
        assert subscriber.confirmation_expires_at.replace(tzinfo=timezone.utc) == NOW + timedelta(hours=48)

        mark_confirmation_sent(session, subscriber, now=NOW)
        same_subscriber, resend_token = prepare_confirmation(
            session, "reader@example.com", now=NOW + timedelta(minutes=9),
        )

    assert same_subscriber.id == subscriber.id
    assert resend_token is None


def test_confirmation_expiry_activation_unsubscribe_and_resubscribe():
    Session = subscriber_session()

    with Session() as session:
        subscriber, expired_token = prepare_confirmation(session, "reader@example.com", now=NOW)
        assert expired_token is not None
        assert confirm_subscription(
            session, expired_token, now=NOW + timedelta(hours=49),
        ) is None

        subscriber, confirmation_token = prepare_confirmation(
            session, "reader@example.com", now=NOW + timedelta(hours=49),
        )
        assert confirmation_token is not None
        confirmed = confirm_subscription(session, confirmation_token, now=NOW + timedelta(hours=50))
        assert confirmed is not None
        assert confirm_subscription(session, confirmation_token, now=NOW + timedelta(hours=50)) is confirmed

        old_unsubscribe_token = unsubscribe_token(confirmed, "test-secret")
        assert find_unsubscribe_subscriber(session, old_unsubscribe_token, "wrong-secret") is None
        assert unsubscribe(
            session, old_unsubscribe_token, "test-secret", now=NOW + timedelta(hours=51),
        ) is confirmed
        assert confirmed.unsubscribed_at is not None

        _, new_confirmation_token = prepare_confirmation(
            session, "reader@example.com", now=NOW + timedelta(hours=52),
        )
        assert new_confirmation_token is not None
        assert confirm_subscription(
            session, new_confirmation_token, now=NOW + timedelta(hours=53),
        ) is confirmed
        assert confirmed.unsubscribed_at is None
        assert find_unsubscribe_subscriber(session, old_unsubscribe_token, "test-secret") is None


def test_invalid_email_is_rejected():
    Session = subscriber_session()

    with Session() as session:
        for value in ("", "missing-at.example.com", "name@example", "Name <name@example.com>"):
            try:
                prepare_confirmation(session, value, now=NOW)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{value!r} should be invalid")


def test_signup_route_sends_confirmation_then_activates(monkeypatch):
    Session = subscriber_session()
    sent: dict[str, str] = {}
    config = Settings(
        database_url="sqlite://",
        public_url="https://board.example",
        smtp_host="smtp.example",
        smtp_from="Jobs <jobs@example.com>",
        subscription_token_secret="test-secret",
    )

    def override_session():
        with Session() as session:
            yield session

    def fake_send(recipient, confirmation_url, config=main.settings):
        sent["recipient"] = recipient
        sent["url"] = confirmation_url
        return True

    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(main, "send_confirmation_email", fake_send)
    main.app.dependency_overrides[main.get_session] = override_session
    try:
        client = TestClient(main.app)
        response = client.post(
            "/subscribe",
            data={"email": "Reader@Example.com"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/?subscription=check-email#email-signup"
        assert sent["recipient"] == "reader@example.com"
        assert sent["url"].startswith("https://board.example/subscribe/confirm?token=")

        token = sent["url"].split("token=", 1)[1]
        confirmation = client.get(f"/subscribe/confirm?token={token}")
        assert confirmation.status_code == 200
        assert "Email alerts confirmed" in confirmation.text
        assert f"/static/styles.css?v={main.STYLES_VERSION}" in confirmation.text
        assert 'href="http://testserver/static/favicon.svg"' in confirmation.text
        assert 'class="subscription-card"' in confirmation.text
        assert '<a class="button-link" href="/">Back to the job board</a>' in confirmation.text

        with Session() as session:
            subscriber = session.scalar(select(Subscriber))
            assert subscriber is not None
            assert subscriber.confirmed_at is not None
            assert token not in subscriber.confirmation_token_hash
            removal_token = unsubscribe_token(subscriber, "test-secret")

        unsubscribe_page = client.get(f"/unsubscribe?token={removal_token}")
        assert "Unsubscribe from alerts?" in unsubscribe_page.text
        assert 'form method="post"' in unsubscribe_page.text
        assert f'action="/unsubscribe?token={removal_token}"' in unsubscribe_page.text
        assert ">Unsubscribe</button>" in unsubscribe_page.text
        removed = client.post(f"/unsubscribe?token={removal_token}")
        assert "You’re unsubscribed" in removed.text

        with Session() as session:
            subscriber = session.scalar(select(Subscriber))
            assert subscriber is not None
            assert subscriber.unsubscribed_at is not None
    finally:
        main.app.dependency_overrides.clear()


def test_signup_route_keeps_pending_record_when_smtp_fails(monkeypatch):
    Session = subscriber_session()
    config = Settings(
        public_url="https://board.example",
        smtp_host="smtp.example",
        smtp_from="Jobs <jobs@example.com>",
        subscription_token_secret="test-secret",
    )

    def override_session():
        with Session() as session:
            yield session

    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(main, "send_confirmation_email", lambda *_: False)
    main.app.dependency_overrides[main.get_session] = override_session
    try:
        response = TestClient(main.app).post(
            "/subscribe",
            data={"email": "reader@example.com"},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/?subscription=delivery-error#email-signup"
        with Session() as session:
            subscriber = session.scalar(select(Subscriber))
            assert subscriber is not None
            assert subscriber.confirmation_sent_at is None
    finally:
        main.app.dependency_overrides.clear()
