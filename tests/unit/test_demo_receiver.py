import runpy
from pathlib import Path

from hookline.deliveries.signing import build_signature_header

RECEIVER_PATH = Path(__file__).parents[2] / "scripts" / "demo_receiver.py"
receiver_verify_signature = runpy.run_path(str(RECEIVER_PATH))["verify_signature"]

SECRET = "whsec_test-secret"
TIMESTAMP = 1760000000
BODY = b'{"id":"1","data":{}}'
HEADER = build_signature_header(SECRET, TIMESTAMP, BODY)


def test_receiver_accepts_a_signature_made_by_hookline() -> None:
    assert receiver_verify_signature(SECRET, HEADER, BODY, TIMESTAMP + 10)


def test_receiver_rejects_a_wrong_secret() -> None:
    assert not receiver_verify_signature("whsec_other-secret", HEADER, BODY, TIMESTAMP)


def test_receiver_rejects_a_changed_body() -> None:
    assert not receiver_verify_signature(SECRET, HEADER, BODY + b" ", TIMESTAMP)


def test_receiver_rejects_an_old_timestamp() -> None:
    assert not receiver_verify_signature(SECRET, HEADER, BODY, TIMESTAMP + 301)


def test_receiver_rejects_requests_when_no_secret_is_set() -> None:
    assert not receiver_verify_signature("", HEADER, BODY, TIMESTAMP)


def test_receiver_rejects_a_malformed_header() -> None:
    assert not receiver_verify_signature(SECRET, "garbage", BODY, TIMESTAMP)
