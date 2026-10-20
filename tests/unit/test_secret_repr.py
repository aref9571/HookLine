import uuid
from datetime import UTC, datetime

from hookline.api_keys.models import ApiKey
from hookline.api_keys.service import CreatedApiKey
from hookline.auth.service import TokenPair
from hookline.deliveries.sender import DeliveryRequest
from hookline.endpoints.models import Endpoint
from hookline.endpoints.service import EndpointSecret
from hookline.worker.claims import ClaimedDelivery

NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
EVENT_ID = uuid.UUID("0b6f5c3e-8f7a-4f2e-9a51-3c2d1e0f9a87")
SECRET = "whsec_secret-that-must-stay-hidden"
URL = "https://hooks.example.com/hook?token=url-token"
PAYLOAD = {"card": "payload-value"}


def test_delivery_request_repr_hides_url_secret_and_payload() -> None:
    request = DeliveryRequest(
        url=URL,
        secret=SECRET,
        event_id=EVENT_ID,
        event_type="order.created",
        event_created_at=NOW,
        payload=PAYLOAD,
        attempt_number=1,
    )

    text = repr(request)

    assert str(EVENT_ID) in text
    for hidden in (SECRET, "url-token", "payload-value"):
        assert hidden not in text


def test_claimed_delivery_repr_hides_url_secret_and_payload() -> None:
    claimed = ClaimedDelivery(
        delivery_id=uuid.uuid4(),
        attempt_number=1,
        attempt_count=0,
        locked_until=NOW,
        url=URL,
        secret=SECRET,
        event_id=EVENT_ID,
        event_type="order.created",
        event_created_at=NOW,
        payload=PAYLOAD,
    )

    text = repr(claimed)

    assert str(EVENT_ID) in text
    for hidden in (SECRET, "url-token", "payload-value"):
        assert hidden not in text


def test_token_pair_repr_hides_both_tokens() -> None:
    tokens = TokenPair(access_token="access-token-value", refresh_token="refresh-token-value")

    text = repr(tokens)

    assert "access-token-value" not in text
    assert "refresh-token-value" not in text


def test_created_api_key_repr_hides_the_plaintext_key() -> None:
    created = CreatedApiKey(api_key=ApiKey(name="Shop"), plaintext="hk_plaintext-key-value")

    assert "hk_plaintext-key-value" not in repr(created)


def test_endpoint_secret_repr_hides_the_secret() -> None:
    endpoint_secret = EndpointSecret(endpoint=Endpoint(url=URL), secret=SECRET)

    assert SECRET not in repr(endpoint_secret)
