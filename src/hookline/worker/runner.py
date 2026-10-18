import logging
import random
import socket
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx2
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from hookline.clock import get_now
from hookline.config import Settings
from hookline.deliveries.backoff import next_delay_seconds
from hookline.deliveries.models import Delivery, DeliveryAttempt, DeliveryStatus
from hookline.deliveries.sender import DeliveryRequest, DeliveryResult, send_delivery
from hookline.endpoints.url_safety import Resolver
from hookline.worker.claims import ClaimedDelivery, claim_due_deliveries

logger = logging.getLogger(__name__)

NowFunc = Callable[[], datetime]
RandomFunc = Callable[[], float]


def build_request(claimed: ClaimedDelivery) -> DeliveryRequest:
    return DeliveryRequest(
        url=claimed.url,
        secret=claimed.secret,
        event_id=claimed.event_id,
        event_type=claimed.event_type,
        event_created_at=claimed.event_created_at,
        payload=claimed.payload,
        attempt_number=claimed.attempt_number,
    )


def result_values(
    claimed: ClaimedDelivery,
    result: DeliveryResult,
    settings: Settings,
    now: datetime,
    random_fraction: float,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "locked_until": None,
        "last_status_code": result.status_code,
        "last_error": result.error,
    }
    if result.succeeded:
        values["status"] = DeliveryStatus.SUCCEEDED
    elif claimed.attempt_number >= settings.max_attempts:
        values["status"] = DeliveryStatus.DEAD
    else:
        delay = next_delay_seconds(
            claimed.attempt_number,
            settings.backoff_base_seconds,
            settings.backoff_max_seconds,
            random_fraction,
        )
        values["status"] = DeliveryStatus.FAILED
        values["next_attempt_at"] = now + timedelta(seconds=delay)
    return values


def record_result(
    session: Session,
    claimed: ClaimedDelivery,
    result: DeliveryResult,
    values: dict[str, Any],
    now: datetime,
) -> bool:
    updated_id = session.scalar(
        update(Delivery)
        .where(
            Delivery.id == claimed.delivery_id,
            Delivery.status == DeliveryStatus.IN_PROGRESS,
            Delivery.locked_until == claimed.locked_until,
        )
        .values(**values, attempt_count=Delivery.attempt_count + 1, updated_at=now)
        .returning(Delivery.id)
    )
    if updated_id is None:
        session.rollback()
        return False
    session.add(
        DeliveryAttempt(
            delivery_id=claimed.delivery_id,
            attempt_number=claimed.attempt_number,
            status_code=result.status_code,
            error=result.error,
            duration_ms=result.duration_ms,
            response_excerpt=result.response_excerpt,
            attempted_at=now,
        )
    )
    session.commit()
    return True


def process_claimed(
    session_factory: sessionmaker[Session],
    client: httpx2.Client,
    claimed: ClaimedDelivery,
    settings: Settings,
    now_func: NowFunc,
    random_func: RandomFunc,
    resolver: Resolver = socket.getaddrinfo,
) -> None:
    now = now_func()
    result = send_delivery(client, build_request(claimed), now, settings, resolver)
    values = result_values(claimed, result, settings, now, random_func())
    with session_factory() as session:
        recorded = record_result(session, claimed, result, values, now)
    if not recorded:
        logger.warning(
            "Delivery %s attempt %s discarded because its lease was taken over",
            claimed.delivery_id,
            claimed.attempt_number,
        )
        return
    logger.info(
        "Delivery %s attempt %s %s status_code=%s duration_ms=%s",
        claimed.delivery_id,
        claimed.attempt_number,
        values["status"],
        result.status_code,
        result.duration_ms,
    )


def run_once(
    session_factory: sessionmaker[Session],
    client: httpx2.Client,
    settings: Settings,
    stop_event: threading.Event,
    now_func: NowFunc = get_now,
    random_func: RandomFunc = random.random,
    resolver: Resolver = socket.getaddrinfo,
) -> int:
    with session_factory() as session:
        claimed = claim_due_deliveries(
            session, now_func(), settings.worker_batch_size, settings.worker_lease_seconds
        )
    for item in claimed:
        if stop_event.is_set():
            break
        process_claimed(session_factory, client, item, settings, now_func, random_func, resolver)
    return len(claimed)


def run_worker(
    settings: Settings,
    session_factory: sessionmaker[Session],
    client: httpx2.Client,
    stop_event: threading.Event,
    now_func: NowFunc = get_now,
    random_func: RandomFunc = random.random,
    resolver: Resolver = socket.getaddrinfo,
) -> None:
    logger.info("Worker started")
    while not stop_event.is_set():
        claimed_count = run_once(
            session_factory, client, settings, stop_event, now_func, random_func, resolver
        )
        if claimed_count == 0:
            stop_event.wait(settings.worker_poll_seconds)
    logger.info("Worker stopped")
