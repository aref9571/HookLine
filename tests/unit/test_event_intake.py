import hashlib

import pytest

from hookline.config import Settings
from hookline.errors import ContentTooLargeError
from hookline.events.schemas import EventCreate
from hookline.events.service import check_payload_size, compute_request_hash
from tests.conftest import UNREACHABLE_DATABASE_URL


def settings_with_payload_limit(limit: int) -> Settings:
    return Settings(database_url=UNREACHABLE_DATABASE_URL, max_payload_bytes=limit)


def test_request_hash_does_not_depend_on_key_order() -> None:
    first = EventCreate(event_type="order.created", payload={"a": 1, "b": {"c": 2, "d": 3}})
    second = EventCreate(event_type="order.created", payload={"b": {"d": 3, "c": 2}, "a": 1})

    assert compute_request_hash(first) == compute_request_hash(second)


def test_request_hash_is_sha256_hex_of_the_canonical_body() -> None:
    data = EventCreate(event_type="a", payload={"x": 1})

    expected = hashlib.sha256(b'{"event_type":"a","payload":{"x":1}}').hexdigest()

    assert compute_request_hash(data) == expected


def test_request_hash_changes_when_the_body_changes() -> None:
    original = EventCreate(event_type="order.created", payload={"a": 1})
    other_type = EventCreate(event_type="order.paid", payload={"a": 1})
    other_payload = EventCreate(event_type="order.created", payload={"a": 2})

    hashes = {compute_request_hash(data) for data in [original, other_type, other_payload]}

    assert len(hashes) == 3


def test_payload_at_the_limit_is_allowed() -> None:
    check_payload_size({"a": "xx"}, settings_with_payload_limit(len('{"a":"xx"}')))


def test_payload_over_the_limit_is_rejected() -> None:
    with pytest.raises(ContentTooLargeError) as error:
        check_payload_size({"a": "abc"}, settings_with_payload_limit(len('{"a":"xx"}')))

    assert error.value.status == 413
    assert error.value.detail == "The payload must be at most 10 bytes."


def test_payload_size_counts_utf8_bytes() -> None:
    with pytest.raises(ContentTooLargeError):
        check_payload_size({"a": "éé"}, settings_with_payload_limit(len('{"a":"xx"}')))
