# 0005: PostgreSQL as the delivery job queue

Status: accepted

## Context

Every delivery row is a job: send one event to one endpoint, retry it later if it fails, and stop after `HOOKLINE_MAX_ATTEMPTS` attempts. The jobs are created by the API in the same transaction as the event. A separate worker process must pick them up, and it must be safe to run several workers at once without two of them sending the same delivery at the same time. A worker can also crash in the middle of a delivery, and that delivery must not be lost.

## Decision

- The `deliveries` table is the queue. There is no separate broker such as Redis, RabbitMQ or Celery.
- A worker claims due deliveries with one query: deliveries that are `pending` or `failed` with `next_attempt_at <= now`, or `in_progress` with an expired lease (`locked_until < now`), ordered by `next_attempt_at, id`, limited to `HOOKLINE_WORKER_BATCH_SIZE`, with `FOR UPDATE OF deliveries SKIP LOCKED`.
- In the same transaction the claimed rows are set to `in_progress` with a lease, `locked_until = now + HOOKLINE_WORKER_LEASE_SECONDS`, and the transaction is committed at once. The worker gets plain data back (URL, secret, event and attempt number), not ORM objects.
- The HTTP request is sent with no database transaction open. Afterwards a new short transaction inserts a `delivery_attempts` row and updates the delivery, but only if it is still `in_progress` with the same `locked_until` this worker set. If the lease was taken over in the meantime, nothing is written and a warning is logged.
- Failed attempts are retried after `min(HOOKLINE_BACKOFF_MAX_SECONDS, HOOKLINE_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))` seconds, multiplied by a random factor between 0.5 and 1.0. After `HOOKLINE_MAX_ATTEMPTS` failed attempts the delivery becomes `dead`.

### How leases work

`SKIP LOCKED` makes a second worker skip rows that another worker is claiming right now, instead of waiting for them. After the claim is committed the row lock is gone, so the lease takes over: a row that is `in_progress` with `locked_until` in the future is not due, so no other worker picks it up. If the worker crashes, the lease runs out and the next claim picks the delivery up again with the next attempt number.

The lease must be longer than one delivery takes. The default lease is 60 seconds and the default request timeout is 10 seconds.

## Alternatives considered

- Redis or RabbitMQ with Celery. This adds a second stateful service to run and monitor, and creating the event and queuing the job could no longer happen in one transaction: the API could commit the event and then fail to queue the job, or queue a job for an event that was rolled back. Keeping both in PostgreSQL removes that problem.
- Polling with a plain `SELECT` and an update afterwards. Two workers would read the same rows and send them twice. `SELECT ... FOR UPDATE` without `SKIP LOCKED` is correct but makes workers wait for each other.
- Holding the row lock for the whole HTTP request. This would keep a transaction open for up to the request timeout for every delivery, tying up database connections, and a hanging receiver would hold locks.

## Consequences

- The delivery guarantee is at least once, not exactly once. If a worker sends a request and crashes, or its lease runs out, before it records the result, the delivery is sent again after the lease expires. A receiver can also answer `2xx` and lose the connection before Hookline reads the answer. Receivers must therefore de-duplicate with the `Hookline-Event-Id` header, which stays the same for every attempt of an event.
- Inside a valid lease a delivery is never sent by two workers; an integration test runs four workers in parallel threads over 50 deliveries and checks that each one has exactly one attempt.
- A worker whose lease expired cannot overwrite a newer result, because its update checks `locked_until`.
- When a worker is asked to stop, it finishes the current delivery and leaves the rest of its batch leased; another worker picks them up when the lease runs out.
- The queue's throughput is limited by PostgreSQL. For this project's scale, polling every `HOOKLINE_WORKER_POLL_SECONDS` seconds with small batches is enough; the partial index `ix_deliveries_due` keeps the claim query fast as delivery history grows.
