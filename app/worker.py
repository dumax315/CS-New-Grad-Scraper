import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal, create_tables
from app.emailer import send_new_jobs_digest
from app.ingestion import run_ingestion
from app.models import Listing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def scrape_and_notify() -> None:
    try:
        with SessionLocal() as session:
            is_initial_run = session.scalar(select(func.count(Listing.id))) == 0
            if is_initial_run:
                logger.info("Initial load detected; running baseline scrape before scheduling begins")
            else:
                logger.info("Running scheduled scrape")
            new_listings = run_ingestion(session)
        sent = send_new_jobs_digest(new_listings) if (settings.send_initial_digest or not is_initial_run) else False
        logger.info("Ingestion completed: %s new listings; digest sent=%s", len(new_listings), sent)
        if is_initial_run and not new_listings:
            logger.warning("Initial load produced no stored listings; check the fetch and parser logs above")
    except Exception:
        logger.exception("Ingestion failed")


def main() -> None:
    create_tables()
    # An initial run establishes the baseline immediately without flooding the mailbox.
    scrape_and_notify()
    scheduler = BlockingScheduler(timezone=ZoneInfo(settings.timezone))
    scheduler.add_job(scrape_and_notify, "cron", hour="8,20", minute=0, id="github-job-scrape", replace_existing=True)
    logger.info("Worker started; scheduled for 08:00 and 20:00 %s", settings.timezone)
    scheduler.start()


if __name__ == "__main__":
    main()
