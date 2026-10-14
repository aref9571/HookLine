from sqlalchemy.orm import Session

from hookline.config import Settings
from hookline.database import (
    NAMING_CONVENTION,
    Base,
    create_engine_from_settings,
    create_session_factory,
)
from tests.conftest import UNREACHABLE_DATABASE_URL


def test_base_metadata_uses_the_naming_convention() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_engine_uses_the_configured_url() -> None:
    engine = create_engine_from_settings(Settings(database_url=UNREACHABLE_DATABASE_URL))

    assert engine.url.render_as_string(hide_password=False) == UNREACHABLE_DATABASE_URL
    engine.dispose()


def test_session_factory_creates_sessions_bound_to_the_engine() -> None:
    engine = create_engine_from_settings(Settings(database_url=UNREACHABLE_DATABASE_URL))
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        assert isinstance(session, Session)
        assert session.get_bind() is engine
    engine.dispose()
