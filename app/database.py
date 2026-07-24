from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def create_tables() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("listings")}
    missing_columns = {
        "posted_at": "DATE",
        "fit_confidence": "INTEGER",
        "fit_reasoning": "TEXT",
        "fit_selected_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
        "fit_evaluated_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
        "fit_model": "VARCHAR(100)",
    }
    for column_name, column_type in missing_columns.items():
        if column_name in columns:
            continue
        if engine.dialect.name == "postgresql":
            # Web and worker can start at the same time, so each migration must
            # be safe when both attempt it.
            statement = f"ALTER TABLE listings ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
        else:
            statement = f"ALTER TABLE listings ADD COLUMN {column_name} {column_type}"
        with engine.begin() as connection:
            connection.execute(text(statement))
