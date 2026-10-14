import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from hookline.models import Base
from tests.conftest import alembic_config

pytestmark = pytest.mark.integration

CORE_TABLES = {
    "users",
    "refresh_tokens",
    "api_keys",
    "endpoints",
    "events",
    "deliveries",
    "delivery_attempts",
}


def current_revision(engine: Engine) -> str | None:
    if not inspect(engine).has_table("alembic_version"):
        return None
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()


def pgcrypto_is_installed(engine: Engine) -> bool:
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = :name"), {"name": "pgcrypto"}
        )
        return result.scalar() == 1


def application_tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_models_define_the_core_tables() -> None:
    assert set(Base.metadata.tables) == CORE_TABLES


def test_migrations_downgrade_to_base_and_upgrade_again(db_engine: Engine) -> None:
    command.downgrade(alembic_config(), "base")

    assert current_revision(db_engine) is None
    assert not pgcrypto_is_installed(db_engine)
    assert application_tables(db_engine) == set()

    command.upgrade(alembic_config(), "head")

    assert current_revision(db_engine) == "0002"
    assert pgcrypto_is_installed(db_engine)
    assert application_tables(db_engine) == CORE_TABLES


def test_core_tables_migration_downgrade_drops_everything_it_created(db_engine: Engine) -> None:
    command.downgrade(alembic_config(), "0001")

    assert current_revision(db_engine) == "0001"
    assert application_tables(db_engine) == set()
    assert pgcrypto_is_installed(db_engine)

    command.upgrade(alembic_config(), "head")

    assert current_revision(db_engine) == "0002"


def test_migrations_match_the_models(db_engine: Engine) -> None:
    command.check(alembic_config())
