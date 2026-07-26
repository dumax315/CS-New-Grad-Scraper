from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, or_

from app.models import Listing


def visible_listing_condition(
    today: date | None = None,
    *,
    lifecycle_visibility: bool = True,
):
    cutoff_date = (today or date.today()) - timedelta(days=365)
    cutoff_time = datetime.combine(cutoff_date, time.min, tzinfo=timezone.utc)
    freshness_condition = or_(
        Listing.posted_at >= cutoff_date,
        and_(Listing.posted_at.is_(None), Listing.first_seen_at >= cutoff_time),
    )
    if not lifecycle_visibility:
        return freshness_condition
    return and_(Listing.is_open.is_(True), freshness_condition)


def visible_listing_order():
    return (
        Listing.posted_at.desc().nulls_last(),
        Listing.first_seen_at.desc(),
        Listing.id.desc(),
    )
