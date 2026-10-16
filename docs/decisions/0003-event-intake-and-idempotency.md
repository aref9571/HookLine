# 0003: Event intake and idempotency keys

Status: accepted

## Context

Producers send events to `POST /api/v1/events`. Networks fail, so a producer that does not get an answer will send the same request again. Without protection, every retry would create a new event and a new set of deliveries, and subscribers would receive the same webhook several times. Retries can also arrive at the same moment, for example from two instances of the producer.

Each event must also become one delivery per matching endpoint. If the event row is saved but the deliveries are not, the event is silently never delivered.

## Decision

- A producer may send an `Idempotency-Key` header: 1 to 100 characters from `A-Z`, `a-z`, `0-9`, `_`, `.`, `:` and `-`. Keys belong to the user who owns the API key, so all keys of one user share the same idempotency keys and two users can use the same key without affecting each other.
- The request body is hashed with SHA-256 over its canonical JSON (`json.dumps(body, sort_keys=True, separators=(",", ":"))`) and stored as `request_hash`. The order of keys in the body does not change the hash.
- The event is inserted with `INSERT ... ON CONFLICT ON CONSTRAINT events_idempotency_uk DO NOTHING RETURNING id`. The unique constraint on `(user_id, idempotency_key)` decides which request wins, so there is no check-then-insert race in application code. A second request with the same key waits for the first transaction to finish and then inserts nothing.
- When nothing was inserted, the existing event is loaded. If its `request_hash` matches, the API answers `200` with the same event ID and the header `Idempotent-Replayed: true`. If it does not match, the key was reused for a different request and the API answers `409`.
- When the event was inserted, the deliveries are created in the same transaction with one `INSERT ... SELECT` over the user's active endpoints whose `event_types` contain the event type or `*`. The event and its deliveries are committed together, so either both exist or neither does.
- A new event returns `201` with the event ID, `created_at` and `delivery_count`.
- The request body is limited to `HOOKLINE_MAX_BODY_BYTES` by a small ASGI middleware, for a declared `Content-Length` and for a body that grows too large while it is read. The payload is limited separately to `HOOKLINE_MAX_PAYLOAD_BYTES`, measured as compact JSON in UTF-8. Both limits answer `413`.

## Consequences

- A producer can safely retry a request with the same key; at most one event and one set of deliveries exist. A test sends the same key from 10 threads at once and checks this.
- Events sent without a key are not deduplicated. PostgreSQL treats NULLs as distinct, so they do not conflict with each other.
- A replayed response reports the number of deliveries the event has now, which can differ from the first response if an endpoint was deleted in between.
- Idempotency keys are kept forever, as long as the event exists. There is no expiry, which keeps the rule simple; expiring old keys would be possible later.
- Intake runs a fixed number of queries (key lookup, event insert, delivery insert), however many endpoints match.
- Endpoints added after an event was accepted do not receive that event.
