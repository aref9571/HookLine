import runpy
import signal
import sys
import threading
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest

from hookline.config import Settings
from hookline.worker import runner
from hookline.worker.__main__ import install_stop_handlers


@pytest.fixture
def restore_signal_handlers() -> Iterator[None]:
    original_term = signal.getsignal(signal.SIGTERM)
    original_int = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGTERM, original_term)
    signal.signal(signal.SIGINT, original_int)


@pytest.mark.parametrize("signal_number", [signal.SIGTERM, signal.SIGINT])
def test_stop_handlers_set_the_stop_event(
    restore_signal_handlers: None, signal_number: signal.Signals
) -> None:
    stop_event = threading.Event()
    install_stop_handlers(stop_event)

    signal.raise_signal(signal_number)

    assert stop_event.is_set()


def test_running_the_module_starts_the_worker_and_stops_on_sigterm(
    monkeypatch: pytest.MonkeyPatch, restore_signal_handlers: None
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run_worker(
        settings: Settings, session_factory: Any, client: Any, stop_event: threading.Event
    ) -> None:
        signal.raise_signal(signal.SIGTERM)
        calls.append({"settings": settings, "client": client, "stopped": stop_event.is_set()})

    monkeypatch.setattr(runner, "run_worker", fake_run_worker)
    monkeypatch.delitem(sys.modules, "hookline.worker.__main__", raising=False)

    runpy.run_module("hookline.worker", run_name="__main__", alter_sys=True)

    assert len(calls) == 1
    assert isinstance(calls[0]["settings"], Settings)
    assert isinstance(calls[0]["client"], httpx2.Client)
    assert calls[0]["stopped"] is True
