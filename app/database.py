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
    if "posted_at" not in columns:
        if engine.dialect.name == "postgresql":
            # Web and worker can start at the same time, so this migration must
            # be safe when both attempt it.
            statement = "ALTER TABLE listings ADD COLUMN IF NOT EXISTS posted_at DATE"
        else:
            statement = "ALTER TABLE listings ADD COLUMN posted_at DATE"
        with engine.begin() as connection:
            connection.execute(text(statement))
