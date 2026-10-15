import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from hookline.config import Settings
from hookline.models import Base

UNREACHABLE_DATABASE_URL = "postgresql+psycopg://hookline:hookline@127.0.0.1:1/hookline"
TEST_JWT_SECRET = "test-jwt-secret-with-at-least-32-characters"
ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"


def pytest_configure(config: pytest.Config) -> None:
    os.environ.setdefault("HOOKLINE_DATABASE_URL", UNREACHABLE_DATABASE_URL)
    os.environ.setdefault("HOOKLINE_JWT_SECRET", TEST_JWT_SECRET)


def alembic_config() -> Config:
    return Config(str(ALEMBIC_CONFIG_PATH))


def truncate_all_tables(engine: Engine) -> None:
    tables = Base.metadata.sorted_tables
    if not tables:
        return
    preparer = engine.dialect.identifier_preparer
    table_list = ", ".join(preparer.format_table(table) for table in tables)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE " + table_list + " RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with (
        PostgresContainer("postgres:17", driver="psycopg") as postgres,
        pytest.MonkeyPatch.context() as monkeypatch,
    ):
        url = postgres.get_connection_url()
        monkeypatch.setenv("HOOKLINE_DATABASE_URL", url)
        command.upgrade(alembic_config(), "head")
        yield url


@pytest.fixture(scope="session")
def db_engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_database(db_engine: Engine) -> Iterator[None]:
    yield
    truncate_all_tables(db_engine)


@pytest.fixture
def db_session(db_engine: Engine, clean_database: None) -> Iterator[Session]:
    with Session(db_engine) as session:
        yield session


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(database_url=database_url)


@pytest.fixture
def client(settings: Settings, clean_database: None) -> Iterator[TestClient]:
    from hookline.main import create_app

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


@pytest.fixture
def client_without_database() -> Iterator[TestClient]:
    from hookline.main import create_app

    app = create_app(Settings(database_url=UNREACHABLE_DATABASE_URL))
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()
