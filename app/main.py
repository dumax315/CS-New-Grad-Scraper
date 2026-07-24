from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal, create_tables
from app.models import Listing, ListingSource


def visible_listing_condition(today: date | None = None):
    cutoff_date = (today or date.today()) - timedelta(days=365)
    cutoff_time = datetime.combine(cutoff_date, time.min, tzinfo=timezone.utc)
    return or_(
        Listing.posted_at >= cutoff_date,
        and_(Listing.posted_at.is_(None), Listing.first_seen_at >= cutoff_time),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


app = FastAPI(title="New Grad SWE Jobs", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def get_session():
    with SessionLocal() as session:
        yield session


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
    statement = select(Listing).where(visible_listing_condition()).options(selectinload(Listing.sources)).order_by(
        Listing.posted_at.desc().nulls_last(), Listing.first_seen_at.desc(),
    )
    if q:
        term = f"%{q.strip()}%"
        statement = statement.where(or_(Listing.company.ilike(term), Listing.title.ilike(term), Listing.location.ilike(term)))
    if source:
        statement = statement.where(Listing.sources.any(source_name=source))
    listings = session.scalars(statement).all()
    source_names = session.scalars(select(ListingSource.source_name).distinct().order_by(ListingSource.source_name)).all()
    return templates.TemplateResponse(request, "index.html", {
        "listings": listings, "source_names": source_names,
        "q": q, "selected_source": source,
    })
