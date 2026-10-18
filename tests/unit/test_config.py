import logging

import pytest
from pydantic import ValidationError

from hookline.config import Settings, configure_logging, get_settings
from hookline.main import create_app


def test_settings_use_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOOKLINE_APP_NAME", raising=False)
    monkeypatch.delenv("HOOKLINE_LOG_LEVEL", raising=False)
    monkeypatch.delenv("HOOKLINE_ACCESS_TOKEN_MINUTES", raising=False)
    monkeypatch.delenv("HOOKLINE_REFRESH_TOKEN_DAYS", raising=False)

    settings = Settings()

    assert settings.app_name == "Hookline"
    assert settings.log_level == "INFO"
    assert settings.access_token_minutes == 15
    assert settings.refresh_token_days == 7


def test_settings_read_database_url_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_DATABASE_URL", "postgresql+psycopg://user:secret@db:5432/hookline")

    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://user:secret@db:5432/hookline"


def test_settings_require_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOOKLINE_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as error:
        Settings()

    assert error.value.errors()[0]["loc"] == ("database_url",)
    assert error.value.errors()[0]["type"] == "missing"


def test_settings_read_log_level_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.log_level == "DEBUG"


def test_settings_reject_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_returns_cached_instance() -> None:
    get_settings.cache_clear()

    assert get_settings() is get_settings()


def test_create_app_uses_given_settings() -> None:
    app = create_app(Settings(app_name="Hookline Test"))

    assert app.title == "Hookline Test"


def test_settings_require_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOOKLINE_JWT_SECRET", raising=False)

    with pytest.raises(ValidationError) as error:
        Settings()

    assert error.value.errors()[0]["loc"] == ("jwt_secret",)
    assert error.value.errors()[0]["type"] == "missing"


def test_settings_reject_jwt_secret_shorter_than_32_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOOKLINE_JWT_SECRET", "s" * 31)

    with pytest.raises(ValidationError) as error:
        Settings()

    assert error.value.errors()[0]["loc"] == ("jwt_secret",)
    assert "s" * 31 not in str(error.value)


def test_settings_accept_jwt_secret_of_32_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_JWT_SECRET", "s" * 32)

    settings = Settings()

    assert settings.jwt_secret.get_secret_value() == "s" * 32
    assert "s" * 32 not in repr(settings)


def test_settings_read_token_lifetimes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_ACCESS_TOKEN_MINUTES", "5")
    monkeypatch.setenv("HOOKLINE_REFRESH_TOKEN_DAYS", "30")

    settings = Settings()

    assert settings.access_token_minutes == 5
    assert settings.refresh_token_days == 30


@pytest.mark.parametrize(
    "variable", ["HOOKLINE_ACCESS_TOKEN_MINUTES", "HOOKLINE_REFRESH_TOKEN_DAYS"]
)
def test_settings_reject_token_lifetimes_below_one(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "0")

    with pytest.raises(ValidationError):
        Settings()


def test_startup_fails_without_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOOKLINE_JWT_SECRET", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        create_app()

    get_settings.cache_clear()


def test_settings_default_to_https_only_and_public_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOOKLINE_REQUIRE_HTTPS_TARGETS", raising=False)
    monkeypatch.delenv("HOOKLINE_ALLOW_PRIVATE_TARGETS", raising=False)

    settings = Settings()

    assert settings.require_https_targets is True
    assert settings.allow_private_targets is False


def test_settings_read_target_rules_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_REQUIRE_HTTPS_TARGETS", "false")
    monkeypatch.setenv("HOOKLINE_ALLOW_PRIVATE_TARGETS", "true")

    settings = Settings()

    assert settings.require_https_targets is False
    assert settings.allow_private_targets is True


def test_settings_default_size_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOOKLINE_MAX_BODY_BYTES", raising=False)
    monkeypatch.delenv("HOOKLINE_MAX_PAYLOAD_BYTES", raising=False)

    settings = Settings()

    assert settings.max_body_bytes == 262144
    assert settings.max_payload_bytes == 65536


def test_settings_read_size_limits_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_MAX_BODY_BYTES", "1000")
    monkeypatch.setenv("HOOKLINE_MAX_PAYLOAD_BYTES", "500")

    settings = Settings()

    assert settings.max_body_bytes == 1000
    assert settings.max_payload_bytes == 500


@pytest.mark.parametrize("name", ["HOOKLINE_MAX_BODY_BYTES", "HOOKLINE_MAX_PAYLOAD_BYTES"])
def test_settings_reject_size_limits_below_one(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "0")

    with pytest.raises(ValidationError):
        Settings()


def test_settings_default_delivery_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOOKLINE_DELIVERY_TIMEOUT_SECONDS", raising=False)

    assert Settings().delivery_timeout_seconds == 10


def test_settings_read_delivery_timeout_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_DELIVERY_TIMEOUT_SECONDS", "3")

    assert Settings().delivery_timeout_seconds == 3


def test_settings_reject_delivery_timeout_below_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_DELIVERY_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValidationError):
        Settings()


WORKER_DEFAULTS = {
    "max_attempts": 8,
    "backoff_base_seconds": 10,
    "backoff_max_seconds": 3600,
    "worker_batch_size": 10,
    "worker_poll_seconds": 2,
    "worker_lease_seconds": 60,
}


def test_settings_default_worker_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in WORKER_DEFAULTS:
        monkeypatch.delenv("HOOKLINE_" + name.upper(), raising=False)

    settings = Settings()

    for name, expected in WORKER_DEFAULTS.items():
        assert getattr(settings, name) == expected


def test_settings_read_worker_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in WORKER_DEFAULTS:
        monkeypatch.setenv("HOOKLINE_" + name.upper(), "5")

    settings = Settings()

    for name in WORKER_DEFAULTS:
        assert getattr(settings, name) == 5


@pytest.mark.parametrize("name", list(WORKER_DEFAULTS))
def test_settings_reject_worker_values_below_one(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv("HOOKLINE_" + name.upper(), "0")

    with pytest.raises(ValidationError):
        Settings()


def test_configure_logging_keeps_http_client_request_lines_out_of_the_logs() -> None:
    configure_logging("DEBUG")

    assert not logging.getLogger("httpx2").isEnabledFor(logging.INFO)
    assert logging.getLogger("httpx2").isEnabledFor(logging.WARNING)
