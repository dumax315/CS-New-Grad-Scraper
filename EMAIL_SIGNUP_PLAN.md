# Email Signup Implementation Plan

## Summary

Add a public, double-opt-in email signup panel to the board. The web service
synchronously sends user-requested confirmation emails through shared SMTP
code, while the worker remains responsible for scheduled job digests.
Confirmation links expire after 48 hours, and every subscriber digest provides
a secure unsubscribe mechanism.

## Implementation

- Add a normalized, unique subscriber record with pending, confirmed, and
  unsubscribed lifecycle timestamps. Store confirmation tokens only as SHA-256
  hashes and sign reproducible unsubscribe tokens with an application secret.
- Serialize PostgreSQL startup migrations so the web and worker can safely
  create the subscriber table concurrently; preserve SQLite compatibility.
- Add a hero signup form, synchronous confirmation delivery, a 10-minute resend
  cooldown, a 48-hour confirmation route, and idempotent unsubscribe routes.
- Keep rendering, multipart message construction, SMTP authentication, TLS,
  timeout, and batch delivery code shared in `app/emailer.py`.
- Send individualized digests to confirmed subscribers over one reused SMTP
  connection. Keep `ALERT_RECIPIENT` as a deduplicated operator copy.
- Include visible unsubscribe links plus standard `List-Unsubscribe` and
  `List-Unsubscribe-Post` headers.
- Keep v1 focused: no cadence preferences, public subscriber list, tracking
  pixels, broker, additional worker, or delivery ledger.

## Interfaces

- `POST /subscribe`
- `GET /subscribe/confirm?token=…`
- `GET /unsubscribe?token=…`
- `POST /unsubscribe?token=…`
- `SUBSCRIPTION_TOKEN_SECRET` signs unsubscribe links.
- `APP_PUBLIC_URL` supplies the trusted origin for email links.

## Verification

- Cover normalization, duplicate submissions, resend cooldown, token hashing,
  expiry, activation, resubscription, SMTP failures, unsubscribe behavior,
  subscriber filtering, individualized digest links, admin deduplication,
  escaping, and migration creation.
- Run the full test suite, compile checks, Docker Compose validation, and Git
  whitespace validation before handoff.
