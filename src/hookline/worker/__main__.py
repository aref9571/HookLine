import logging
import signal
import threading
from types import FrameType

import httpx2

from hookline.config import Settings, configure_logging
from hookline.database import create_engine_from_settings, create_session_factory
from hookline.worker.runner import run_worker

logger = logging.getLogger("hookline.worker")


def install_stop_handlers(stop_event: threading.Event) -> None:
    def request_stop(signal_number: int, frame: FrameType | None) -> None:
        logger.info("Stop requested, finishing the current delivery")
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    engine = create_engine_from_settings(settings)
    stop_event = threading.Event()
    install_stop_handlers(stop_event)
    try:
        with httpx2.Client() as client:
            run_worker(settings, create_session_factory(engine), client, stop_event)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
