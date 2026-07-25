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
