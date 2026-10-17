import hashlib
import hmac
from datetime import datetime

SIGNATURE_VERSION = "v1"
DEFAULT_TOLERANCE_SECONDS = 300


def sign(secret: str, timestamp: int, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def build_signature_header(secret: str, timestamp: int, body: bytes) -> str:
    return f"t={timestamp},{SIGNATURE_VERSION}={sign(secret, timestamp, body)}"


def parse_signature_header(header: str) -> tuple[int, str] | None:
    values: dict[str, str] = {}
    for part in header.split(","):
        name, separator, value = part.strip().partition("=")
        if not separator or not value:
            return None
        values[name] = value
    if "t" not in values or SIGNATURE_VERSION not in values:
        return None
    if not (values["t"].isascii() and values["t"].isdigit()):
        return None
    return int(values["t"]), values[SIGNATURE_VERSION]


def verify_signature(
    secret: str,
    header: str,
    body: bytes,
    now: datetime,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
) -> bool:
    parsed = parse_signature_header(header)
    if parsed is None:
        return False
    timestamp, signature = parsed
    if abs(int(now.timestamp()) - timestamp) > tolerance_seconds:
        return False
    expected = sign(secret, timestamp, body)
    return hmac.compare_digest(expected.encode(), signature.encode())
