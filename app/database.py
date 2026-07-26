from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def create_tables() -> None:
    from app import models  # noqa: F401

    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            # Web and worker start concurrently. Serializing schema setup also
            # protects create_all's check-then-create sequence for new tables.
            connection.execute(text(
                "SELECT pg_advisory_xact_lock(hashtext('cs_new_grad_scraper_schema'))"
            ))
        Base.metadata.create_all(connection)
        columns = {column["name"] for column in inspect(connection).get_columns("listings")}
        missing_columns = {
            "posted_at": "DATE",
            "scope_decision": "VARCHAR(30)",
            "timing_explicit": "BOOLEAN",
            "exact_posted_date": "BOOLEAN",
            "is_open": (
                "BOOLEAN NOT NULL DEFAULT TRUE"
                if engine.dialect.name == "postgresql"
                else "BOOLEAN NOT NULL DEFAULT 1"
            ),
            "closed_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
            "fit_confidence": "INTEGER",
            "fit_reasoning": "TEXT",
            "resume_fit_confidence": "INTEGER",
            "resume_fit_reasoning": "TEXT",
            "fit_selected_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
            "fit_evaluated_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
            "fit_evaluation_failed_at": (
                "TIMESTAMP WITH TIME ZONE"
                if engine.dialect.name == "postgresql"
                else "DATETIME"
            ),
            "fit_evaluation_error": "VARCHAR(255)",
            "fit_model": "VARCHAR(100)",
        }
        for column_name, column_type in missing_columns.items():
            if column_name in columns:
                continue
            if engine.dialect.name == "postgresql":
                statement = f"ALTER TABLE listings ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
            else:
                statement = f"ALTER TABLE listings ADD COLUMN {column_name} {column_type}"
            connection.execute(text(statement))

        source_columns = {
            column["name"]
            for column in inspect(connection).get_columns("listing_sources")
        }
        source_missing_columns = {
            "source_key": "VARCHAR(150)",
            "source_external_id": "VARCHAR(255)",
            "source_posted_at": "DATE",
            "first_seen_at": (
                "TIMESTAMP WITH TIME ZONE"
                if engine.dialect.name == "postgresql"
                else "DATETIME"
            ),
            "last_seen_at": (
                "TIMESTAMP WITH TIME ZONE"
                if engine.dialect.name == "postgresql"
                else "DATETIME"
            ),
            "consecutive_misses": "INTEGER NOT NULL DEFAULT 0",
            "is_active": (
                "BOOLEAN NOT NULL DEFAULT TRUE"
                if engine.dialect.name == "postgresql"
                else "BOOLEAN NOT NULL DEFAULT 1"
            ),
            "closed_at": (
                "TIMESTAMP WITH TIME ZONE"
                if engine.dialect.name == "postgresql"
                else "DATETIME"
            ),
        }
        for column_name, column_type in source_missing_columns.items():
            if column_name in source_columns:
                continue
            if engine.dialect.name == "postgresql":
                statement = (
                    "ALTER TABLE listing_sources "
                    f"ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
                )
            else:
                statement = (
                    f"ALTER TABLE listing_sources ADD COLUMN {column_name} {column_type}"
                )
            connection.execute(text(statement))

        connection.execute(text(
            "UPDATE listing_sources "
            "SET source_key = :source_key "
            "WHERE source_key IS NULL AND source_name = :source_name"
        ), {
            "source_key": "markdown:speedyapply-2027-swe",
            "source_name": "SpeedyApply 2027 SWE",
        })
        connection.execute(text(
            "UPDATE listing_sources "
            "SET source_key = :source_key "
            "WHERE source_key IS NULL AND source_name = :source_name"
        ), {
            "source_key": "markdown:vansh-new-grad-2027",
            "source_name": "Vansh New Grad 2027",
        })
        connection.execute(text(
            "UPDATE listing_sources "
            "SET first_seen_at = COALESCE(first_seen_at, CURRENT_TIMESTAMP), "
            "last_seen_at = COALESCE(last_seen_at, CURRENT_TIMESTAMP)"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_listing_source_key "
            "ON listing_sources (listing_id, source_key)"
        ))
