from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500))
    location: Mapped[str] = mapped_column(String(500), default="")
    application_url: Mapped[str] = mapped_column(Text, unique=True)
    salary: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(100), default="Other")
    graduation_year: Mapped[int | None] = mapped_column(nullable=True)
    source_age: Mapped[str] = mapped_column(String(100), default="")
    posted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    scope_decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    timing_explicit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exact_posted_date: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fit_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fit_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_fit_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resume_fit_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    fit_selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fit_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fit_evaluation_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    fit_evaluation_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fit_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sources: Mapped[list["ListingSource"]] = relationship(back_populates="listing", cascade="all, delete-orphan")


class ListingSource(Base):
    __tablename__ = "listing_sources"
    __table_args__ = (UniqueConstraint("listing_id", "source_name", name="uq_listing_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    source_name: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(Text)
    listing: Mapped[Listing] = relationship(back_populates="sources")


class SourceRun(Base):
    __tablename__ = "source_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(150), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    succeeded: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(20))
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmation_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    confirmation_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
