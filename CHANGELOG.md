# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-21

First release.

### Added

- Python package `hookline` with a `src/` layout, configured through `HOOKLINE_` environment variables, and a FastAPI application with OpenAPI docs at `/docs`.
- Health endpoints `GET /health/live` and `GET /health/ready` (`503` when the database cannot be reached).
- PostgreSQL schema for users, refresh tokens, API keys, endpoints, events, deliveries, delivery attempts and rate limit windows, created by the Alembic migrations `0001` to `0003` with check constraints, unique constraints, a partial index for due deliveries and an index for the delivery history of an endpoint.
- Login with HS256 JWT access tokens and random refresh tokens: `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh` with rotation and reuse detection, and `POST /api/v1/auth/logout`.
- `GET /api/v1/users/me`, `admin` and `member` roles, and admin user management with `POST /api/v1/users`, `GET /api/v1/users` and `PATCH /api/v1/users/{id}`.
- `python -m hookline.cli create-admin` to create the first admin user.
- API keys for producer applications: `POST /api/v1/api-keys` (the key is shown once), `GET /api/v1/api-keys` and `DELETE /api/v1/api-keys/{id}`.
- Subscriber endpoints: `POST /api/v1/endpoints` (the signing secret is shown once), `GET /api/v1/endpoints`, `GET`, `PATCH` and `DELETE /api/v1/endpoints/{id}`, and `POST /api/v1/endpoints/{id}/rotate-secret`.
- Event intake `POST /api/v1/events` with an API key: the event and one pending delivery per matching active endpoint are stored in one transaction, with optional idempotency keys (`200` replay with `Idempotent-Replayed: true` for the same body, `409` for a different body).
- `GET /api/v1/events` with filters and `GET /api/v1/events/{id}` with the payload and a summary of its deliveries.
- HMAC-SHA256 signing of every delivery with the `Hookline-Signature: t=<timestamp>,v1=<signature>` header, and a sender that sends compact JSON with the `Hookline-Event-Id`, `Hookline-Event-Type` and `Hookline-Attempt` headers, does not follow redirects and counts only `2xx` as success.
- Delivery worker `python -m hookline.worker`: claims due deliveries with `FOR UPDATE SKIP LOCKED` and a lease, sends them without an open transaction, records every attempt, retries failures with exponential backoff and jitter, marks deliveries `dead` after `HOOKLINE_MAX_ATTEMPTS` attempts or when their endpoint is deactivated, keeps running through a database outage, and stops cleanly on `SIGTERM` or Ctrl+C. Several workers can run at once.
- Delivery history and manual retry: `GET /api/v1/deliveries` with filters, `GET /api/v1/deliveries/{id}` with every attempt, and `POST /api/v1/deliveries/{id}/retry` for `failed` and `dead` deliveries.
- Delivery statistics `GET /api/v1/stats`: deliveries per status, the last 24 hours, the average attempts to success and per-endpoint counts, with an optional `endpoint_id` filter.
- Pagination with `limit` and `offset` on every list route, and RFC 9457 problem details (`application/problem+json`) for every error, with validation errors as `400`.
- One log line per request with the method, path, status and duration.
- `Dockerfile` based on `python:3.12-slim` that runs as a non-root user with a health check, and a Docker Compose stack with `postgres`, a one-off `migrate` step, `api`, `worker` and a demo `receiver` that verifies signatures.
- End-to-end smoke test `scripts/smoke_test.sh`.
- Unit tests, integration tests against PostgreSQL 17 started with Testcontainers, and a GitHub Actions workflow with format check, lint, type check, tests with a minimum coverage of 85%, `shellcheck`, the image build and the smoke test.
- Documentation: README, API, architecture, database, development, security and testing guides, and decision records 0001 to 0006.

### Changed

- The OpenAPI schema documents the problem details body (`Problem`) for the `4XX` and `5XX` responses of every route instead of FastAPI's default `422` validation response, which Hookline never sends.
- The README is complete: architecture, quick starts with and without Docker, API overview, delivery guarantees with the retry schedule, decision records, and limitations.
- `.env.example` is set up for the local Docker demo (`HOOKLINE_ALLOW_PRIVATE_TARGETS=true`, `HOOKLINE_REQUIRE_HTTPS_TARGETS=false`); the application defaults stay strict.

### Security

- Passwords are hashed with bcrypt; passwords must be 12 to 128 characters and at most 72 bytes, and every failed login returns the same `401` and takes about the same time.
- JWTs are decoded with the `HS256` algorithm only, and the application does not start with a JWT secret shorter than 32 characters.
- Refresh tokens and API keys are random values stored only as SHA-256 hashes; reusing a rotated refresh token revokes all refresh tokens of that user.
- Members only see their own resources, and another user's resource returns `404`; roles are read from the database on every request.
- Endpoint URLs are checked against server-side request forgery when they are saved and again before every delivery: `https` only by default, no credentials or fragments, and no host that resolves to a private, loopback, link-local, multicast, reserved or unspecified address.
- Request bodies are limited to `HOOKLINE_MAX_BODY_BYTES` and event payloads to `HOOKLINE_MAX_PAYLOAD_BYTES` (`413`).
- Event intake is rate limited per API key with a fixed one-minute window stored in PostgreSQL (`429` with `Retry-After`).
- Secrets and signatures are compared in constant time; the JWT secret and the database URL are held as secret values; tokens, keys, signing secrets, target URLs and payloads are left out of logs and of the text representation of internal objects.
- `X-Content-Type-Options: nosniff` on every response, `Cache-Control: no-store` on `/api/v1/auth/*` responses, and no CORS.
- The installed dependencies were checked with `pip-audit` on 2026-10-21 with no known vulnerabilities.
