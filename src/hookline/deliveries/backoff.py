def next_delay_seconds(
    attempt_number: int, base: int, maximum: int, random_fraction: float
) -> float:
    delay = min(maximum, base * 2 ** (attempt_number - 1))
    jitter_factor = 0.5 + 0.5 * random_fraction
    return delay * jitter_factor
