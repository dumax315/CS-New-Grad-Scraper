from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
import hashlib
from pathlib import Path
import smtplib
from urllib.parse import quote, urlsplit

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import SessionLocal, create_tables
from app.emailer import send_confirmation_email
from app.models import Listing, ListingSource
from app.presentation import present_listings
from app.subscriptions import (
    confirm_subscription,
    find_unsubscribe_subscriber,
    mark_confirmation_sent,
    prepare_confirmation,
    unsubscribe,
)


def visible_listing_condition(today: date | None = None):
    cutoff_date = (today or date.today()) - timedelta(days=365)
    cutoff_time = datetime.combine(cutoff_date, time.min, tzinfo=timezone.utc)
    freshness_condition = or_(
        Listing.posted_at >= cutoff_date,
        and_(Listing.posted_at.is_(None), Listing.first_seen_at >= cutoff_time),
    )
    if not settings.lifecycle_visibility:
        return freshness_condition
    return and_(Listing.is_open.is_(True), freshness_condition)


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


app = FastAPI(title="New Grad SWE Jobs", lifespan=lifespan)
STATIC_DIRECTORY = Path(__file__).with_name("static")
STYLES_VERSION = hashlib.sha256(
    (STATIC_DIRECTORY / "styles.css").read_bytes()
).hexdigest()[:12]
FILTERS_VERSION = hashlib.sha256(
    (STATIC_DIRECTORY / "filters.js").read_bytes()
).hexdigest()[:12]
app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")
templates = Jinja2Templates(directory="app/templates")


def get_session():
    with SessionLocal() as session:
        yield session


def _group_source_names(
    source_rows: Iterable[tuple[str, str | None, str]],
) -> tuple[list[str], list[str]]:
    github_source_names: set[str] = set()
    job_board_source_names: set[str] = set()

    for source_name, source_key, source_url in source_rows:
        source_hostname = (urlsplit(source_url).hostname or "").lower()
        is_github_source = (source_key or "").startswith("markdown:") or source_hostname in {
            "github.com",
            "raw.githubusercontent.com",
        }
        if is_github_source:
            github_source_names.add(source_name)
        else:
            job_board_source_names.add(source_name)

    job_board_source_names -= github_source_names
    return sorted(github_source_names), sorted(job_board_source_names)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = Query(default="", max_length=100),
    source: str = Query(default="", max_length=100),
    session: Session = Depends(get_session),
):
    return _render_job_board(
        request,
        q=q,
        source=source,
        session=session,
        show_resume_fit=False,
        board_path="/",
    )


@app.get("/resume", response_class=HTMLResponse)
def resume(
    request: Request,
    q: str = Query(default="", max_length=100),
    source: str = Query(default="", max_length=100),
    session: Session = Depends(get_session),
):
    return _render_job_board(
        request,
        q=q,
        source=source,
        session=session,
        show_resume_fit=True,
        board_path="/resume",
    )


def _render_job_board(
    request: Request,
    *,
    q: str,
    source: str,
    session: Session,
    show_resume_fit: bool,
    board_path: str,
) -> HTMLResponse:
    statement = select(Listing).where(visible_listing_condition()).options(selectinload(Listing.sources)).order_by(
        Listing.posted_at.desc().nulls_last(), Listing.first_seen_at.desc(),
    )
    if q:
        term = f"%{q.strip()}%"
        statement = statement.where(or_(Listing.company.ilike(term), Listing.title.ilike(term), Listing.location.ilike(term)))
    if source:
        statement = statement.where(Listing.sources.any(source_name=source))
    listings = session.scalars(statement).all()
    source_rows = session.execute(
        select(
            ListingSource.source_name,
            ListingSource.source_key,
            ListingSource.source_url,
        ).distinct()
    ).all()
    github_source_names, job_board_source_names = _group_source_names(source_rows)
    subscription_notices = {
        "check-email": (
            "success",
            "If this address still needs confirmation, check your inbox for a link.",
        ),
        "invalid": ("error", "Enter a valid email address."),
        "delivery-error": ("error", "We could not send the confirmation email. Please try again."),
        "unavailable": ("error", "Email signup is temporarily unavailable."),
    }
    return templates.TemplateResponse(request, "index.html", {
        "jobs": present_listings(listings),
        "github_source_names": github_source_names,
        "job_board_source_names": job_board_source_names,
        "q": q, "selected_source": source,
        "styles_version": STYLES_VERSION,
        "filters_version": FILTERS_VERSION,
        "show_resume_fit": show_resume_fit,
        "board_path": board_path,
        "subscription_notice": subscription_notices.get(request.query_params.get("subscription", "")),
        "signup_available": bool(
            settings.public_url
            and settings.subscription_token_secret
            and settings.smtp_host
            and settings.smtp_from
        ),
    })


def _redirect_to_signup(status: str) -> RedirectResponse:
    return RedirectResponse(url=f"/?subscription={status}#email-signup", status_code=303)


def _subscription_result(
    request: Request,
    *,
    title: str,
    message: str,
    success: bool,
    token: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(request, "subscription_result.html", {
        "title": title,
        "message": message,
        "success": success,
        "styles_version": STYLES_VERSION,
        "unsubscribe_token": token,
    })


@app.post("/subscribe")
def subscribe(
    email: str = Form(default="", max_length=320),
    session: Session = Depends(get_session),
):
    if not all((
        settings.public_url,
        settings.subscription_token_secret,
        settings.smtp_host,
        settings.smtp_from,
    )):
        return _redirect_to_signup("unavailable")
    try:
        subscriber, raw_token = prepare_confirmation(session, email)
    except ValueError:
        return _redirect_to_signup("invalid")
    except IntegrityError:
        session.rollback()
        subscriber, raw_token = prepare_confirmation(session, email)

    if raw_token is None:
        return _redirect_to_signup("check-email")

    confirmation_url = (
        f"{settings.public_url}/subscribe/confirm?token={quote(raw_token, safe='')}"
    )
    try:
        sent = send_confirmation_email(subscriber.email, confirmation_url)
    except (OSError, smtplib.SMTPException):
        return _redirect_to_signup("delivery-error")
    if not sent:
        return _redirect_to_signup("delivery-error")
    mark_confirmation_sent(session, subscriber)
    return _redirect_to_signup("check-email")


@app.get("/subscribe/confirm", response_class=HTMLResponse)
def confirm_email(
    request: Request,
    token: str = Query(default="", max_length=200),
    session: Session = Depends(get_session),
):
    subscriber = confirm_subscription(session, token) if token else None
    if subscriber is None:
        return _subscription_result(
            request,
            title="Confirmation link expired",
            message="Submit your email again to receive a fresh confirmation link.",
            success=False,
        )
    return _subscription_result(
        request,
        title="Email alerts confirmed",
        message="You’ll receive a digest when newly discovered roles are available.",
        success=True,
    )


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(
    request: Request,
    token: str = Query(default="", max_length=500),
    session: Session = Depends(get_session),
):
    subscriber = find_unsubscribe_subscriber(
        session, token, settings.subscription_token_secret,
    ) if token else None
    if subscriber is None:
        return _subscription_result(
            request,
            title="Unsubscribe link unavailable",
            message="This link is invalid or no longer current.",
            success=False,
        )
    if subscriber.unsubscribed_at is not None:
        return _subscription_result(
            request,
            title="Already unsubscribed",
            message="This address is no longer receiving job alerts.",
            success=True,
        )
    return _subscription_result(
        request,
        title="Unsubscribe from alerts?",
        message="You can sign up again at any time.",
        success=True,
        token=token,
    )


@app.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_email(
    request: Request,
    token: str = Query(default="", max_length=500),
    session: Session = Depends(get_session),
):
    subscriber = unsubscribe(
        session, token, settings.subscription_token_secret,
    ) if token else None
    if subscriber is None:
        return _subscription_result(
            request,
            title="Unsubscribe link unavailable",
            message="This link is invalid or no longer current.",
            success=False,
        )
    return _subscription_result(
        request,
        title="You’re unsubscribed",
        message="This address will no longer receive job alerts.",
        success=True,
    )
