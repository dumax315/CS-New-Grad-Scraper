from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal, create_tables
from app.models import Listing, ListingSource


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
    year: int | None = Query(default=None, ge=2020, le=2100),
    session: Session = Depends(get_session),
):
    statement = select(Listing).options(selectinload(Listing.sources)).order_by(
        Listing.posted_at.desc().nulls_last(), Listing.first_seen_at.desc(),
    )
    if q:
        term = f"%{q.strip()}%"
        statement = statement.where(or_(Listing.company.ilike(term), Listing.title.ilike(term), Listing.location.ilike(term)))
    if source:
        statement = statement.where(Listing.sources.any(source_name=source))
    if year:
        statement = statement.where(Listing.graduation_year == year)
    listings = session.scalars(statement).all()
    source_names = session.scalars(select(ListingSource.source_name).distinct().order_by(ListingSource.source_name)).all()
    years = session.scalars(select(Listing.graduation_year).where(Listing.graduation_year.is_not(None)).distinct().order_by(Listing.graduation_year.desc())).all()
    return templates.TemplateResponse(request, "index.html", {
        "listings": listings, "source_names": source_names, "years": years,
        "q": q, "selected_source": source, "selected_year": year,
    })
