# 0006: Fixed-window rate limiting in PostgreSQL

Status: accepted

## Context

Producer applications send events with an API key. A broken or misbehaving producer could send thousands of events per second, fill the database and keep the worker busy for everybody else. Each API key therefore needs a limit on `POST /api/v1/events`, `HOOKLINE_RATE_LIMIT_PER_MINUTE` requests per minute (default 120). The limit must hold when the API runs in several processes, and the project has no Redis or other shared cache.

## Decision

- A table `rate_limit_windows` with the primary key `(api_key_id, window_start)` and a `request_count`, added in migration `0003`. `window_start` is the request time truncated to the minute.
- Every intake request with a valid key runs one statement:

  ```sql
  INSERT INTO rate_limit_windows (api_key_id, window_start, request_count)
  VALUES (:key, :window_start, 1)
  ON CONFLICT (api_key_id, window_start)
  DO UPDATE SET request_count = rate_limit_windows.request_count + 1
  RETURNING request_count
  ```

  The returned count is compared with the limit. PostgreSQL locks the row while it updates it, so two requests at the same moment get two different counts and the limit cannot be passed by racing.
- The count is committed in its own short transaction before the event is created. A rejected request is still counted, and an event that fails and is rolled back does not undo its count.
- A request over the limit gets `429` with `Retry-After` set to the seconds left in the current minute. Successful responses carry `X-RateLimit-Limit` and `X-RateLimit-Remaining`.
- Old windows are deleted by the worker with one `DELETE ... WHERE window_start < now - 1 hour`, at most once per minute, so the table stays small without a separate job.

## Alternatives considered

- Sliding window log (one row per request, counting the rows of the last 60 seconds). Exact, but it writes a row for every request and needs a count over many rows each time.
- Sliding window counter (weighting the previous window by how much of it overlaps the last 60 seconds). Smooths the edges, but the formula is harder to explain and test, and the limit becomes an estimate.
- Token bucket. Allows controlled bursts, but needs the last refill time and a fractional token count per key, and more arithmetic inside the statement.
- An in-memory counter in each API process. Simple and fast, but every process would have its own count, so the real limit would grow with the number of processes, and it would reset on restart.
- Redis. The usual choice for rate limits, but the project keeps all state in PostgreSQL (see [decision 0005](0005-postgres-job-queue.md)).

## Consequences

- Bursts at window edges: a producer can send the full limit in the last second of one minute and again in the first second of the next, so up to twice the limit can arrive within about two seconds. For protecting the service from runaway producers this is acceptable; it is the price of one row and one statement per key and minute.
- Every intake request writes to the database twice (the counter and the event). At this project's scale that is fine; a very busy deployment would move the counter to Redis.
- Windows are based on the clock of the API process. Several API processes with clocks that differ by a few seconds could each start the new minute at a slightly different moment.
- The counter row of a busy key is a hot row: concurrent requests of the same key wait for each other briefly on its row lock. Different keys never block each other.
- Requests without a valid API key are not rate limited by this mechanism; they are rejected with `401` before the counter runs.
