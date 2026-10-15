import socket
from collections.abc import Sequence
from typing import Any

import pytest

from hookline.config import Settings
from hookline.endpoints.url_safety import get_resolver, validate_target_url
from hookline.errors import InvalidFieldError
from tests.conftest import UNREACHABLE_DATABASE_URL

PUBLIC_ADDRESS = "93.184.215.14"
PUBLIC_IPV6_ADDRESS = "2606:2800:21f:cb07:6820:80da:af6b:8b2c"

FAKE_DNS = {
    "hooks.example.com": [PUBLIC_ADDRESS],
    "dual.example.com": [PUBLIC_ADDRESS, PUBLIC_IPV6_ADDRESS],
    "internal.example.com": ["10.1.2.3"],
    "mixed.example.com": [PUBLIC_ADDRESS, "192.168.1.20"],
    "mapped.example.com": ["::ffff:127.0.0.1"],
    "empty.example.com": [],
}


def fake_resolver(host: str, port: int | None) -> Sequence[tuple[Any, ...]]:
    if host not in FAKE_DNS:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    return [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 0))
        for address in FAKE_DNS[host]
    ]


def failing_resolver(host: str, port: int | None) -> Sequence[tuple[Any, ...]]:
    raise AssertionError("the resolver must not be called")


def make_settings(require_https: bool = True, allow_private: bool = False) -> Settings:
    return Settings(
        database_url=UNREACHABLE_DATABASE_URL,
        require_https_targets=require_https,
        allow_private_targets=allow_private,
    )


def rejection_message(url: str, settings: Settings | None = None) -> str:
    with pytest.raises(InvalidFieldError) as error:
        validate_target_url(url, settings or make_settings(), fake_resolver)
    assert error.value.errors is not None
    assert error.value.errors[0]["field"] == "url"
    return error.value.errors[0]["message"]


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.example.com/webhook",
        "https://hooks.example.com:8443/webhook?source=hookline",
        "https://dual.example.com",
        "https://93.184.215.14/hook",
        "https://HOOKS.example.com/Webhook",
    ],
)
def test_accepts_public_https_urls(url: str) -> None:
    validate_target_url(url, make_settings(), fake_resolver)


def test_accepts_http_when_https_is_not_required() -> None:
    settings = make_settings(require_https=False)

    validate_target_url("http://hooks.example.com/webhook", settings, fake_resolver)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("ftp://hooks.example.com/webhook", "must use https"),
        ("http://hooks.example.com/webhook", "must use https"),
        ("hooks.example.com/webhook", "must use https"),
        ("https:///webhook", "must include a host"),
        ("https://", "must include a host"),
        (
            "https://user:secret@hooks.example.com/webhook",
            "must not contain a username or password",
        ),
        ("https://user@hooks.example.com/webhook", "must not contain a username or password"),
        ("https://hooks.example.com/webhook#part", "must not contain a fragment"),
        ("https://hooks.example.com/webhook#", "must not contain a fragment"),
        ("https://hooks.example.com:99999/webhook", "must be a valid URL"),
        ("https://hooks.example.com:0/webhook", "must be a valid URL"),
        ("https://[::1/webhook", "must be a valid URL"),
    ],
)
def test_rejects_badly_formed_urls(url: str, message: str) -> None:
    assert rejection_message(url) == message


def test_rejects_ftp_when_https_is_not_required() -> None:
    settings = make_settings(require_https=False)

    assert (
        rejection_message("ftp://hooks.example.com/webhook", settings) == "must use http or https"
    )


def test_rejects_urls_longer_than_2048_characters() -> None:
    base = "https://hooks.example.com/"
    longest = base + "a" * (2048 - len(base))

    validate_target_url(longest, make_settings(), fake_resolver)
    assert rejection_message(longest + "a") == "must be at most 2048 characters"


@pytest.mark.parametrize(
    "url",
    ["https://localhost/webhook", "https://LOCALHOST:8443/webhook", "https://api.localhost/hook"],
)
def test_rejects_localhost_by_name(url: str) -> None:
    with pytest.raises(InvalidFieldError) as error:
        validate_target_url(url, make_settings(), failing_resolver)

    assert error.value.errors == [{"field": "url", "message": "must not point to localhost"}]


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/webhook",
        "https://10.0.0.5/webhook",
        "https://172.16.0.1/webhook",
        "https://192.168.0.10/webhook",
        "https://169.254.169.254/latest/meta-data",
        "https://0.0.0.0/webhook",
        "https://224.0.0.1/webhook",
        "https://240.0.0.1/webhook",
        "https://[::1]/webhook",
        "https://[::]/webhook",
        "https://[fe80::1]/webhook",
        "https://[fd00::1]/webhook",
        "https://[::ffff:10.0.0.5]/webhook",
    ],
)
def test_rejects_private_and_reserved_ip_addresses(url: str) -> None:
    with pytest.raises(InvalidFieldError) as error:
        validate_target_url(url, make_settings(), failing_resolver)

    assert error.value.errors == [
        {"field": "url", "message": "must not point to a private or reserved address"}
    ]


@pytest.mark.parametrize(
    "host", ["internal.example.com", "mixed.example.com", "mapped.example.com"]
)
def test_rejects_hosts_that_resolve_to_a_private_address(host: str) -> None:
    message = rejection_message("https://" + host + "/webhook")

    assert message == "must not point to a private or reserved address"


@pytest.mark.parametrize("host", ["unknown.example.com", "empty.example.com"])
def test_rejects_hosts_that_do_not_resolve(host: str) -> None:
    assert rejection_message("https://" + host + "/webhook") == "host could not be resolved"


def test_rejects_hosts_that_cannot_be_encoded() -> None:
    def resolver_with_bad_name(host: str, port: int | None) -> Sequence[tuple[Any, ...]]:
        raise UnicodeError("label too long")

    with pytest.raises(InvalidFieldError) as error:
        validate_target_url("https://hooks.example.com", make_settings(), resolver_with_bad_name)

    assert error.value.errors == [{"field": "url", "message": "host could not be resolved"}]


def test_allow_private_targets_accepts_local_http_url_without_resolving() -> None:
    settings = make_settings(require_https=False, allow_private=True)

    validate_target_url("http://127.0.0.1:9000/hook", settings, failing_resolver)
    validate_target_url("http://localhost:9000/hook", settings, failing_resolver)


def test_allow_private_targets_still_checks_the_url_format() -> None:
    settings = make_settings(require_https=False, allow_private=True)

    assert rejection_message("http://127.0.0.1:9000/hook#x", settings) == (
        "must not contain a fragment"
    )


def test_default_resolver_is_getaddrinfo() -> None:
    assert get_resolver() is socket.getaddrinfo
