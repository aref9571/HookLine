import logging
import threading
from datetime import UTC, datetime

import httpx2
import pytest

from hookline.config import Settings
from hookline.database import create_engine_from_settings, create_session_factory
from hookline.worker.runner import run_worker
from tests.conftest import UNREACHABLE_DATABASE_URL


def test_worker_keeps_running_when_the_database_is_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(database_url=UNREACHABLE_DATABASE_URL, worker_poll_seconds=1)
    engine = create_engine_from_settings(settings)
    stop_event = threading.Event()
    clock_calls = 0

    def now_then_stop_on_second_cycle() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls == 2:
            stop_event.set()
        return datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)

    caplog.set_level(logging.WARNING, logger="hookline.worker.runner")
    try:
        with httpx2.Client() as client:
            run_worker(
                settings,
                create_session_factory(engine),
                client,
                stop_event,
                now_func=now_then_stop_on_second_cycle,
            )
    finally:
        engine.dispose()

    warnings = [record.getMessage() for record in caplog.records]
    assert warnings == ["Database is unavailable, trying again after the poll interval"] * 2
    assert "hookline:hookline" not in caplog.text
