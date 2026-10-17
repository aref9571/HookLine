from datetime import UTC, datetime, timedelta

import pytest

from hookline.deliveries.signing import build_signature_header, sign, verify_signature

SECRET = "whsec_test-secret"
TIMESTAMP = 1760000000
BODY = b'{"id":"1","data":{}}'
EXPECTED_SIGNATURE = "b1e52a491abdb9c0e0bd30a5bbd8160a83671d86ce2a5585886c2069a7e0514a"
SIGNED_AT = datetime.fromtimestamp(TIMESTAMP, UTC)


def test_sign_produces_the_known_hmac_sha256_signature() -> None:
    assert sign(SECRET, TIMESTAMP, BODY) == EXPECTED_SIGNATURE


def test_signature_changes_with_the_timestamp() -> None:
    assert sign(SECRET, TIMESTAMP + 1, BODY) != EXPECTED_SIGNATURE


def test_signature_header_contains_timestamp_and_signature() -> None:
    header = build_signature_header(SECRET, TIMESTAMP, BODY)

    assert header == f"t={TIMESTAMP},v1={EXPECTED_SIGNATURE}"


def test_verify_accepts_a_correct_header() -> None:
    header = build_signature_header(SECRET, TIMESTAMP, BODY)

    assert verify_signature(SECRET, header, BODY, SIGNED_AT)


def test_verify_accepts_a_header_within_the_tolerance() -> None:
    header = build_signature_header(SECRET, TIMESTAMP, BODY)

    assert verify_signature(SECRET, header, BODY, SIGNED_AT + timedelta(seconds=300))


def test_verify_rejects_a_wrong_secret() -> None:
    header = build_signature_header(SECRET, TIMESTAMP, BODY)

    assert not verify_signature("whsec_other-secret", header, BODY, SIGNED_AT)


def test_verify_rejects_a_changed_body() -> None:
    header = build_signature_header(SECRET, TIMESTAMP, BODY)

    assert not verify_signature(SECRET, header, b'{"id":"2","data":{}}', SIGNED_AT)


def test_verify_rejects_an_expired_timestamp() -> None:
    header = build_signature_header(SECRET, TIMESTAMP, BODY)

    assert not verify_signature(SECRET, header, BODY, SIGNED_AT + timedelta(seconds=301))


def test_verify_rejects_a_timestamp_too_far_in_the_future() -> None:
    header = build_signature_header(SECRET, TIMESTAMP, BODY)

    assert not verify_signature(SECRET, header, BODY, SIGNED_AT - timedelta(seconds=301))


def test_verify_uses_the_given_tolerance() -> None:
    header = build_signature_header(SECRET, TIMESTAMP, BODY)
    now = SIGNED_AT + timedelta(seconds=60)

    assert verify_signature(SECRET, header, BODY, now, tolerance_seconds=60)
    assert not verify_signature(SECRET, header, BODY, now, tolerance_seconds=59)


@pytest.mark.parametrize(
    "header",
    [
        "",
        "garbage",
        f"v1={EXPECTED_SIGNATURE}",
        f"t={TIMESTAMP}",
        f"t=,v1={EXPECTED_SIGNATURE}",
        f"t=abc,v1={EXPECTED_SIGNATURE}",
        f"t=-{TIMESTAMP},v1={EXPECTED_SIGNATURE}",
        f"t=²,v1={EXPECTED_SIGNATURE}",
        f"t={TIMESTAMP},v1=",
        f"t={TIMESTAMP};v1={EXPECTED_SIGNATURE}",
        f"t={TIMESTAMP},v1=é{EXPECTED_SIGNATURE[1:]}",
        f"t={TIMESTAMP},v0={EXPECTED_SIGNATURE}",
    ],
)
def test_verify_rejects_a_malformed_header(header: str) -> None:
    assert not verify_signature(SECRET, header, BODY, SIGNED_AT)


def test_verify_accepts_spaces_after_the_comma() -> None:
    header = f"t={TIMESTAMP}, v1={EXPECTED_SIGNATURE}"

    assert verify_signature(SECRET, header, BODY, SIGNED_AT)
