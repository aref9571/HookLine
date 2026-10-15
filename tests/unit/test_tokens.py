import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from hookline.auth.tokens import (
    create_access_token,
    decode_access_token,
    hash_token,
    new_refresh_token,
)
from hookline.config import Settings
from hookline.errors import UnauthorizedError

SECRET = "unit-test-secret-with-more-than-32-characters"
OTHER_SECRET = "another-secret-with-more-than-32-characters"
USER_ID = uuid.UUID("2f1d8b5e-4c1a-4f7e-9a51-3c0f6f1e2d44")


def make_settings(secret: str = SECRET) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@127.0.0.1:1/db", jwt_secret=secret)


def encode_claims(claims: dict[str, object], secret: str = SECRET) -> str:
    return jwt.encode(claims, secret, algorithm="HS256")


def valid_claims(now: datetime) -> dict[str, object]:
    return {
        "sub": str(USER_ID),
        "role": "admin",
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "iss": "hookline",
    }


def test_access_token_round_trips() -> None:
    settings = make_settings()
    token = create_access_token(USER_ID, "member", datetime.now(UTC), settings)

    claims = decode_access_token(token, settings)

    assert claims.user_id == USER_ID
    assert claims.role == "member"


def test_access_token_has_the_expected_claims() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    token = create_access_token(USER_ID, "admin", now, make_settings())

    claims = jwt.decode(token, options={"verify_signature": False})

    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    assert claims == {
        "sub": str(USER_ID),
        "role": "admin",
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "iss": "hookline",
    }


def test_access_token_lifetime_follows_the_settings() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    settings = make_settings().model_copy(update={"access_token_minutes": 5})
    token = create_access_token(USER_ID, "admin", now, settings)

    claims = jwt.decode(token, options={"verify_signature": False})

    assert claims["exp"] - claims["iat"] == 300


def test_decode_rejects_an_expired_token() -> None:
    issued = datetime.now(UTC) - timedelta(minutes=16)
    token = create_access_token(USER_ID, "admin", issued, make_settings())

    with pytest.raises(UnauthorizedError):
        decode_access_token(token, make_settings())


def test_decode_rejects_a_token_signed_with_another_secret() -> None:
    token = create_access_token(USER_ID, "admin", datetime.now(UTC), make_settings(OTHER_SECRET))

    with pytest.raises(UnauthorizedError):
        decode_access_token(token, make_settings())


def test_decode_rejects_a_token_of_another_type() -> None:
    claims = valid_claims(datetime.now(UTC))
    claims["type"] = "refresh"

    with pytest.raises(UnauthorizedError):
        decode_access_token(encode_claims(claims), make_settings())


def test_decode_rejects_an_unsigned_token_with_alg_none() -> None:
    token = jwt.encode(valid_claims(datetime.now(UTC)), None, algorithm="none")

    with pytest.raises(UnauthorizedError):
        decode_access_token(token, make_settings())


def test_decode_rejects_a_token_from_another_issuer() -> None:
    claims = valid_claims(datetime.now(UTC))
    claims["iss"] = "someone-else"

    with pytest.raises(UnauthorizedError):
        decode_access_token(encode_claims(claims), make_settings())


@pytest.mark.parametrize("missing_claim", ["sub", "role", "type", "iat", "exp", "iss"])
def test_decode_rejects_a_token_without_a_required_claim(missing_claim: str) -> None:
    claims = valid_claims(datetime.now(UTC))
    del claims[missing_claim]

    with pytest.raises(UnauthorizedError):
        decode_access_token(encode_claims(claims), make_settings())


def test_decode_rejects_a_subject_that_is_not_a_uuid() -> None:
    claims = valid_claims(datetime.now(UTC))
    claims["sub"] = "not-a-uuid"

    with pytest.raises(UnauthorizedError):
        decode_access_token(encode_claims(claims), make_settings())


def test_decode_rejects_a_role_that_is_not_a_string() -> None:
    claims = valid_claims(datetime.now(UTC))
    claims["role"] = 1

    with pytest.raises(UnauthorizedError):
        decode_access_token(encode_claims(claims), make_settings())


@pytest.mark.parametrize("token", ["", "not-a-token", "a.b.c"])
def test_decode_rejects_malformed_tokens(token: str) -> None:
    with pytest.raises(UnauthorizedError):
        decode_access_token(token, make_settings())


def test_new_refresh_tokens_are_random_and_url_safe() -> None:
    first = new_refresh_token()
    second = new_refresh_token()

    assert first != second
    assert len(first) >= 43
    assert all(character.isalnum() or character in "-_" for character in first)


def test_hash_token_returns_sha256_hex() -> None:
    hashed = hash_token("abc")

    assert hashed == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert len(hashed) == 64
