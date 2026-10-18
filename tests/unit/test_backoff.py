import pytest

from hookline.deliveries.backoff import next_delay_seconds

BASE = 10
MAXIMUM = 3600


@pytest.mark.parametrize(
    ("attempt_number", "full_delay"),
    [
        (1, 10),
        (2, 20),
        (3, 40),
        (4, 80),
        (5, 160),
        (6, 320),
        (7, 640),
        (8, 1280),
        (9, 2560),
        (10, 3600),
    ],
)
def test_delay_doubles_each_attempt_and_jitter_keeps_half_to_all_of_it(
    attempt_number: int, full_delay: int
) -> None:
    assert next_delay_seconds(attempt_number, BASE, MAXIMUM, 0) == full_delay / 2
    assert next_delay_seconds(attempt_number, BASE, MAXIMUM, 1) == full_delay


def test_delay_is_capped_at_the_maximum() -> None:
    assert next_delay_seconds(30, BASE, MAXIMUM, 1) == MAXIMUM
    assert next_delay_seconds(30, BASE, MAXIMUM, 0) == MAXIMUM / 2


def test_random_fraction_scales_the_delay_between_the_bounds() -> None:
    assert next_delay_seconds(1, BASE, MAXIMUM, 0.5) == 7.5
    assert next_delay_seconds(3, BASE, MAXIMUM, 0.25) == 25
