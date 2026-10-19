from datetime import UTC, datetime

import pytest

from hookline.rate_limit.service import (
    RateLimitResult,
    rate_limit_headers,
    seconds_left_in_window,
    window_start_for,
)

WINDOW_START = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)


def test_window_start_is_the_time_truncated_to_the_minute() -> None:
    now = datetime(2030, 1, 1, 12, 0, 42, 123456, tzinfo=UTC)

    assert window_start_for(now) == WINDOW_START


@pytest.mark.parametrize(
    ("second", "microsecond", "expected"),
    [(0, 0, 60), (0, 1, 60), (30, 0, 30), (59, 0, 1), (59, 999999, 1)],
)
def test_seconds_left_in_window_are_between_1_and_60(
    second: int, microsecond: int, expected: int
) -> None:
    now = WINDOW_START.replace(second=second, microsecond=microsecond)

    assert seconds_left_in_window(now, WINDOW_START) == expected


def test_rate_limit_headers_show_limit_and_remaining_requests() -> None:
    result = RateLimitResult(allowed=True, limit=120, remaining=7, retry_after_seconds=12)

    assert rate_limit_headers(result) == {"X-RateLimit-Limit": "120", "X-RateLimit-Remaining": "7"}
