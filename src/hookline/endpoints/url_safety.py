import ipaddress
import socket
from collections.abc import Callable, Sequence
from typing import Annotated, Any
from urllib.parse import SplitResult, urlsplit

from fastapi import Depends

from hookline.config import Settings
from hookline.errors import InvalidFieldError

MAX_URL_LENGTH = 2048

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int | None], Sequence[tuple[Any, ...]]]


def unsafe_url(message: str) -> InvalidFieldError:
    return InvalidFieldError("url", message)


def split_url(url: str) -> SplitResult:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise unsafe_url("must be a valid URL") from error
    if port == 0:
        raise unsafe_url("must be a valid URL")
    return parts


def check_url_format(url: str, settings: Settings) -> str:
    if len(url) > MAX_URL_LENGTH:
        raise unsafe_url("must be at most 2048 characters")
    parts = split_url(url)
    allowed_schemes = {"https"} if settings.require_https_targets else {"http", "https"}
    if parts.scheme not in allowed_schemes:
        raise unsafe_url("must use " + " or ".join(sorted(allowed_schemes)))
    if not parts.hostname:
        raise unsafe_url("must include a host")
    if "@" in parts.netloc:
        raise unsafe_url("must not contain a username or password")
    if "#" in url:
        raise unsafe_url("must not contain a fragment")
    return parts.hostname


def is_blocked_address(address: IpAddress) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def resolve_addresses(host: str, resolver: Resolver) -> list[IpAddress]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        results = resolver(host, None)
    except (OSError, UnicodeError) as error:
        raise unsafe_url("host could not be resolved") from error
    if not results:
        raise unsafe_url("host could not be resolved")
    return [ipaddress.ip_address(result[4][0]) for result in results]


def validate_target_url(
    url: str, settings: Settings, resolver: Resolver = socket.getaddrinfo
) -> None:
    host = check_url_format(url, settings)
    if settings.allow_private_targets:
        return
    if host == "localhost" or host.endswith(".localhost"):
        raise unsafe_url("must not point to localhost")
    for address in resolve_addresses(host, resolver):
        if is_blocked_address(address):
            raise unsafe_url("must not point to a private or reserved address")


def get_resolver() -> Resolver:
    return socket.getaddrinfo


HostResolver = Annotated[Resolver, Depends(get_resolver)]
