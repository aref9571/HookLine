# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Python package `hookline` with a `src/` layout and `pyproject.toml`.
- Configuration loading from `HOOKLINE_` environment variables (`HOOKLINE_APP_NAME`, `HOOKLINE_LOG_LEVEL`).
- FastAPI application factory with logging setup and OpenAPI docs at `/docs`.
- Liveness endpoint `GET /health/live`.
- Unit tests for the liveness endpoint, the docs pages and configuration.
- Ruff, mypy and pytest configuration.
- GitHub Actions workflow running format check, lint, type check and tests with coverage.
- Architecture overview and the first architecture decision record.
- Required `HOOKLINE_DATABASE_URL` setting; the application does not start without it.
- SQLAlchemy engine and per-request database connection dependency, with a constraint naming convention for migrations.
- Alembic setup that reads the database URL from the settings, and the first migration `0001` enabling the `pgcrypto` extension.
- Readiness endpoint `GET /health/ready`, returning `503` when the database is unreachable.
- RFC 9457 problem details for all error responses, including `400` for validation errors, `404`, `405`, `503` and a generic `500`.
- Docker Compose file with a local PostgreSQL 17 service.
- Integration tests against PostgreSQL 17 started with Testcontainers.
- Development guide and the decision record for synchronous SQLAlchemy.
- SQLAlchemy models for users, refresh tokens, API keys, endpoints, events, deliveries and delivery attempts.
- Migration `0002` creating these tables with their check constraints, unique constraints, the case-insensitive email index, the partial index for due deliveries and the delivery history index.
- Integration tests for every check constraint, unique constraint and delete rule of the schema.
- Database documentation with the delivery status diagram.
- Required `HOOKLINE_JWT_SECRET` setting (at least 32 characters) and the optional `HOOKLINE_ACCESS_TOKEN_MINUTES` and `HOOKLINE_REFRESH_TOKEN_DAYS` settings.
- Password hashing with bcrypt, with passwords limited to 12 to 128 characters and at most 72 bytes.
- HS256 JWT access tokens and random refresh tokens stored as SHA-256 hashes.
- `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh` with refresh token rotation and reuse detection, and `POST /api/v1/auth/logout`.
- `GET /api/v1/users/me` for the logged-in user.
- `python -m hookline.cli create-admin` to create the first admin user.
- Security documentation for passwords and tokens.
- `admin` and `member` role checks; members get `403` on admin routes.
- Admin user management: `POST /api/v1/users`, `GET /api/v1/users` and `PATCH /api/v1/users/{id}`. Admins cannot deactivate or demote themselves, and deactivating a user revokes their refresh tokens.
- Pagination with `limit` and `offset` and a common page response for list routes.
- API keys: `POST /api/v1/api-keys` returns the key once, `GET /api/v1/api-keys` lists the caller's keys, `DELETE /api/v1/api-keys/{id}` revokes a key. Only the SHA-256 hash of a key is stored.
- Authentication of producer requests with the `X-API-Key` header.
- API documentation in `docs/api.md`, and security documentation for roles and API keys.
- Settings `HOOKLINE_REQUIRE_HTTPS_TARGETS` (default `true`) and `HOOKLINE_ALLOW_PRIVATE_TARGETS` (default `false`).
- Endpoint URL checks against server-side request forgery: scheme, host, credentials, fragment and length rules, and rejection of `localhost` and of hosts that resolve to private, loopback, link-local, multicast, reserved or unspecified addresses.
- Endpoint management: `POST /api/v1/endpoints` returns the signing secret once, `GET /api/v1/endpoints` (own endpoints, or all for admins, with an `is_active` filter), `GET`, `PATCH` and `DELETE /api/v1/endpoints/{id}`, and `POST /api/v1/endpoints/{id}/rotate-secret` returns a new secret once.
- Security documentation for endpoint secrets and the SSRF checks.
- Settings `HOOKLINE_MAX_BODY_BYTES` (default 262144) and `HOOKLINE_MAX_PAYLOAD_BYTES` (default 65536).
- Request body size limit: bodies over `HOOKLINE_MAX_BODY_BYTES` get `413`, for a declared `Content-Length` and for bodies that grow too large while they are read.
- Event intake: `POST /api/v1/events` with an API key stores the event and creates one pending delivery per matching active endpoint in one transaction, and returns `201` with `delivery_count`. Payloads over `HOOKLINE_MAX_PAYLOAD_BYTES` get `413`.
- Idempotency keys for event intake: the same `Idempotency-Key` and body returns `200` with `Idempotent-Replayed: true`, a different body returns `409`.
- `GET /api/v1/events` with `event_type`, `created_after` and `created_before` filters, and `GET /api/v1/events/{id}` with the payload and a delivery summary.
- Decision record 0003 for event intake and idempotency.
- Setting `HOOKLINE_DELIVERY_TIMEOUT_SECONDS` (default 10).
- HMAC-SHA256 payload signing with the `Hookline-Signature: t=<timestamp>,v1=<signature>` header, and a tested `verify_signature` function that shows how receivers check it.
- Delivery sender: signs and sends one delivery as compact JSON with the `Hookline-Event-Id`, `Hookline-Event-Type`, `Hookline-Attempt` and `Hookline-Signature` headers, does not follow redirects, counts only `2xx` as success, keeps the first 1000 characters of the response, turns timeouts and connection errors into failed results, and checks the target URL again before sending.
- Signature verification guide in `docs/security.md`, a Python receiver example in the README, and decision record 0004 for payload signing.
- Settings `HOOKLINE_MAX_ATTEMPTS` (default 8), `HOOKLINE_BACKOFF_BASE_SECONDS` (10), `HOOKLINE_BACKOFF_MAX_SECONDS` (3600), `HOOKLINE_WORKER_BATCH_SIZE` (10), `HOOKLINE_WORKER_POLL_SECONDS` (2) and `HOOKLINE_WORKER_LEASE_SECONDS` (60).
- Exponential backoff with jitter for failed deliveries.
- Delivery worker `python -m hookline.worker`: claims due deliveries with `FOR UPDATE SKIP LOCKED` and a lease, recovers deliveries whose lease expired, sends them without an open transaction, records every attempt, retries failures, marks deliveries `dead` after the maximum number of attempts or when their endpoint is deactivated, ignores results from a worker whose lease was taken over, and stops cleanly on `SIGTERM` or Ctrl+C.
- Decision record 0005 for the PostgreSQL job queue, and a "Delivery worker" section in the architecture documentation.
- Delivery history: `GET /api/v1/deliveries` with `status`, `endpoint_id`, `event_id`, `created_after` and `created_before` filters (members see the deliveries of their own endpoints, admins all), and `GET /api/v1/deliveries/{id}` with the endpoint URL, the event type and every attempt in order.
- Manual retry: `POST /api/v1/deliveries/{id}/retry` requeues a `failed` or `dead` delivery for a fresh run of attempts and keeps its old attempts; other statuses and deactivated endpoints get `409`, and of two simultaneous retries only one succeeds.
- API documentation for events and deliveries, including how attempt numbers continue after a retry.
- Delivery statistics: `GET /api/v1/stats` with deliveries per status, events received, succeeded and dead deliveries, success rate and average attempts to success over the last 24 hours, and the succeeded and dead counts of up to 50 endpoints; members see their own data, admins all, with an optional `endpoint_id` filter.
- Setting `HOOKLINE_RATE_LIMIT_PER_MINUTE` (default 120).
- Migration `0003` creating the `rate_limit_windows` table.
- Per-API-key rate limiting on `POST /api/v1/events` with a fixed one-minute window counted by one atomic upsert: `429` with `Retry-After` over the limit, and `X-RateLimit-Limit` and `X-RateLimit-Remaining` headers on successful responses.
- The worker deletes rate limit windows older than one hour, at most once a minute.
- Decision record 0006 for rate limiting.
- Request logging: one line per request with the method, path, status code and duration, without query strings, headers or bodies.
- `X-Content-Type-Options: nosniff` on every response and `Cache-Control: no-store` on `/api/v1/auth/*` responses.
- CI fails when test coverage is below 85%.
- Threat model, secret handling, response headers, dependency check and known limitations in `docs/security.md`, and a new testing guide in `docs/testing.md`.

### Changed

- The API key dependency is now `get_current_api_key` and returns the key itself, so event intake can store which key sent an event.
- httpx2 is now a runtime dependency, because the delivery sender uses it.
- The worker decides when a delivery is `dead` from `attempt_count` (attempts since creation or the last manual retry) instead of the attempt number, and the retry delay is based on the same count.
- `HOOKLINE_DATABASE_URL` is held as a secret value, so the database password is not shown when the settings are printed.
- Internal objects that carry tokens, keys, signing secrets, target URLs or payloads leave them out of their text representation.
- Reusing an idempotency key compares the stored request hash in constant time.

### Fixed

- The worker no longer stops when the database is unavailable; it logs a warning and tries again after the poll interval.
