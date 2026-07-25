from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
import hashlib
import hmac
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Subscriber


CONFIRMATION_LIFETIME = timedelta(hours=48)
CONFIRMATION_RESEND_DELAY = timedelta(minutes=10)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    _, parsed = parseaddr(normalized)
    if (
        not normalized
        or len(normalized) > 320
        or parsed != normalized
        or not EMAIL_PATTERN.fullmatch(normalized)
    ):
        raise ValueError("invalid email address")
    return normalized


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def prepare_confirmation(
    session: Session,
    email: str,
    *,
    now: datetime | None = None,
) -> tuple[Subscriber, str | None]:
    normalized = normalize_email(email)
    current_time = now or datetime.now(timezone.utc)
    subscriber = session.scalar(select(Subscriber).where(Subscriber.email == normalized))

    if subscriber and subscriber.confirmed_at is not None and subscriber.unsubscribed_at is None:
        return subscriber, None
    if (
        subscriber
        and subscriber.confirmation_sent_at is not None
        and current_time - _aware_utc(subscriber.confirmation_sent_at) < CONFIRMATION_RESEND_DELAY
    ):
        return subscriber, None

    raw_token = secrets.token_urlsafe(32)
    if subscriber is None:
        subscriber = Subscriber(
            email=normalized,
            confirmation_token_hash=token_hash(raw_token),
            confirmation_expires_at=current_time + CONFIRMATION_LIFETIME,
        )
        session.add(subscriber)
    else:
        subscriber.confirmation_token_hash = token_hash(raw_token)
        subscriber.confirmation_expires_at = current_time + CONFIRMATION_LIFETIME
        subscriber.confirmation_sent_at = None
        subscriber.confirmed_at = None
    session.commit()
    return subscriber, raw_token


def mark_confirmation_sent(
    session: Session,
    subscriber: Subscriber,
    *,
    now: datetime | None = None,
) -> None:
    subscriber.confirmation_sent_at = now or datetime.now(timezone.utc)
    session.commit()


def confirm_subscription(
    session: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> Subscriber | None:
    current_time = now or datetime.now(timezone.utc)
    subscriber = session.scalar(
        select(Subscriber).where(Subscriber.confirmation_token_hash == token_hash(token))
    )
    if (
        subscriber is None
        or _aware_utc(subscriber.confirmation_expires_at) < current_time
    ):
        return None
    if subscriber.confirmed_at is None or subscriber.unsubscribed_at is not None:
        subscriber.confirmed_at = current_time
        subscriber.unsubscribed_at = None
        session.commit()
    return subscriber


def unsubscribe_token(subscriber: Subscriber, secret: str) -> str:
    if not secret or subscriber.confirmed_at is None:
        raise ValueError("active subscription and token secret are required")
    confirmed_at = _aware_utc(subscriber.confirmed_at).isoformat()
    payload = f"{subscriber.id}:{confirmed_at}".encode()
    signature = hmac.new(secret.encode(), payload + b":" + subscriber.email.encode(), hashlib.sha256).digest()
    return f"{urlsafe_b64encode(payload).decode().rstrip('=')}.{urlsafe_b64encode(signature).decode().rstrip('=')}"


def find_unsubscribe_subscriber(
    session: Session,
    token: str,
    secret: str,
) -> Subscriber | None:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload = urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
        signature = urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
        subscriber_id_text, _ = payload.decode().split(":", 1)
        subscriber = session.get(Subscriber, int(subscriber_id_text))
    except (ValueError, UnicodeDecodeError):
        return None
    if subscriber is None or subscriber.confirmed_at is None or not secret:
        return None
    current_payload = (
        f"{subscriber.id}:{_aware_utc(subscriber.confirmed_at).isoformat()}".encode()
    )
    if not hmac.compare_digest(payload, current_payload):
        return None
    expected = hmac.new(
        secret.encode(),
        current_payload + b":" + subscriber.email.encode(),
        hashlib.sha256,
    ).digest()
    return subscriber if hmac.compare_digest(signature, expected) else None


def unsubscribe(
    session: Session,
    token: str,
    secret: str,
    *,
    now: datetime | None = None,
) -> Subscriber | None:
    subscriber = find_unsubscribe_subscriber(session, token, secret)
    if subscriber is None:
        return None
    if subscriber.unsubscribed_at is None:
        subscriber.unsubscribed_at = now or datetime.now(timezone.utc)
        session.commit()
    return subscriber
