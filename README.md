# Hookline

Hookline is a webhook delivery service: applications send events to its REST API, and Hookline delivers each event to every subscriber endpoint that wants it, with signed payloads, automatic retries with backoff, a dead-letter state, manual replay and a full delivery history.

[![CI](https://github.com/aref9571/HookLine/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aref9571/HookLine/actions/workflows/ci.yml)

## Why Hookline

Many products, such as Stripe, GitHub and Shopify, notify other systems by sending HTTP requests called webhooks. Doing this well is harder than it looks: receivers go down, requests time out, the same event must not be delivered twice by two workers, receivers must be able to check that a request really came from the sender, and developers need to see what happened to each delivery. Hookline handles these problems in one small, tested service.

## Features

- User accounts with `admin` and `member` roles; members only see and change their own resources, and someone else's resource returns `404`
- Login with a 15-minute JWT access token and a rotating, revocable refresh token with reuse detection
- API keys for producer applications, shown once and stored only as SHA-256 hashes
- Subscriber endpoints with the event types they want and a signing secret
- Event intake with idempotency keys: retrying a request with the same `Idempotency-Key` never creates a second event
- One delivery per matching endpoint for each event, created in the same transaction as the event
- A worker process that claims deliveries from a PostgreSQL queue with `FOR UPDATE SKIP LOCKED`, so several workers can run at once
- Automatic retries with exponential backoff and jitter, and a `dead` state after the maximum number of attempts
- HMAC-SHA256 signatures with a timestamp on every delivery
- Manual retry of failed and dead deliveries
- Delivery history with every attempt: status code, error, duration and the start of the receiver's answer
- Delivery statistics per status, for the last 24 hours and per endpoint
- Per-API-key rate limiting on event intake
- Protection against server-side request forgery (SSRF) on subscriber URLs, checked when an endpoint is saved and again before every delivery
- Request size limits, RFC 9457 problem details for every error, and request logging without secrets
- Health endpoints, a Docker image, a Docker Compose stack with a demo receiver, and CI with an end-to-end smoke test

## Architecture

```
 Producer app -- POST /api/v1/events (X-API-Key) --> +--------------+
 Admin/member -- /api/v1/* (JWT) ------------------> | hookline API | --> PostgreSQL <--+
                                                     |  (uvicorn)   |                   |
                                                     +--------------+                   |
                                                     +--------------+  claim (SKIP LOCKED)
                                                     |   hookline   | ------------------+
                                                     |    worker    | --> HTTPS POST, signed --> Subscriber endpoint
                                                     +--------------+
```

Hookline is a modular monolith: one Python package that runs as two processes, the API and the worker, sharing one PostgreSQL database. The API never sends webhooks. It authenticates users and producers, stores each event and creates one `pending` delivery row per matching endpoint in the same transaction, so an event can never exist without its deliveries. A slow or unreachable subscriber therefore never slows down the API.

The worker never accepts HTTP requests. It claims a small batch of due deliveries with `SELECT ... FOR UPDATE SKIP LOCKED`, gives each one a short lease and commits at once, then sends the signed requests with no transaction open, and records every attempt in a second short transaction. The `deliveries` table is the job queue, so no broker such as Redis or RabbitMQ is needed, and a crashed worker's deliveries are picked up again when their lease runs out. More detail is in [docs/architecture.md](docs/architecture.md).

## Tech stack

- Python 3.12
- FastAPI with synchronous route functions, Pydantic v2 and pydantic-settings
- PostgreSQL 17, SQLAlchemy 2 with psycopg 3, Alembic
- bcrypt for passwords and PyJWT (HS256) for access tokens
- httpx2 for outgoing HTTP requests
- uvicorn
- pytest, pytest-cov, Testcontainers and httpx2 `MockTransport` for tests
- ruff and mypy for code quality
- Docker and Docker Compose v2
- GitHub Actions for CI

## Quick start with Docker

Requirements: Docker with Docker Compose v2, `curl` and `python3`.

Create `.env` from the example and give it a random JWT secret. The application does not start with a secret shorter than 32 characters, so the `change-me` placeholder must be replaced:

```bash
git clone https://github.com/aref9571/HookLine.git
cd HookLine
cp .env.example .env
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
sed -i.bak "s/^HOOKLINE_JWT_SECRET=.*/HOOKLINE_JWT_SECRET=$JWT_SECRET/" .env
rm .env.bak
```

Build and start the stack, wait until the API is ready, and create the first admin:

```bash
docker compose up -d --build
until curl -fs -o /dev/null localhost:8000/health/ready; do sleep 2; done
docker compose exec -e HOOKLINE_ADMIN_PASSWORD=change-this-password api \
  python -m hookline.cli create-admin --email admin@example.com
```

This starts PostgreSQL, runs the migrations once, and starts the API on http://localhost:8000, the delivery worker and a small demo receiver at `http://receiver:9000/hook` inside the Compose network. The receiver checks the signature of every delivery and prints the event ID. Without `HOOKLINE_ADMIN_PASSWORD`, `create-admin` asks for the password.

Log in, create an API key and an endpoint that points at the demo receiver:

```bash
TOKEN=$(curl -fsS -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "admin@example.com", "password": "change-this-password"}' \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['access_token'])")
API_KEY=$(curl -fsS -X POST localhost:8000/api/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name": "local test"}' \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['key'])")
SECRET=$(curl -fsS -X POST localhost:8000/api/v1/endpoints \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"url": "http://receiver:9000/hook", "event_types": ["order.created"]}' \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['secret'])")
```

Restart the receiver with the endpoint's signing secret, wait until it listens again, send an event and look at the result:

```bash
RECEIVER_SECRET=$SECRET docker compose up -d receiver
until docker compose logs receiver | grep -q "Demo receiver listening"; do sleep 1; done
curl -fsS -X POST localhost:8000/api/v1/events \
  -H "X-API-Key: $API_KEY" \
  -H 'Idempotency-Key: order-42' \
  -H 'Content-Type: application/json' \
  -d '{"event_type": "order.created", "payload": {"order_id": 42}}'
sleep 5
docker compose logs receiver
curl -fsS localhost:8000/api/v1/deliveries -H "Authorization: Bearer $TOKEN"
```

The receiver log shows `Verified signature for event <id>`, and the delivery list shows the delivery as `succeeded` with `attempt_count` 1. To keep the secret for later restarts of the receiver, put it into `.env` as `RECEIVER_SECRET`. Stop the stack with `docker compose down`, and add `-v` to delete the database as well.

`scripts/smoke_test.sh` runs these steps automatically and prints `PASS` or `FAIL`. It removes the stack and its volumes, including the database, when it ends.

`.env.example` sets `HOOKLINE_ALLOW_PRIVATE_TARGETS=true` and `HOOKLINE_REQUIRE_HTTPS_TARGETS=false` only for this local demo, because the demo receiver is a plain `http` address on the private Docker network. A production deployment must keep the defaults, `false` and `true`: otherwise any user who can create an endpoint could make Hookline send requests to internal services such as the database or a cloud metadata address. See [docs/security.md](docs/security.md#server-side-request-forgery-ssrf).

## Quick start without Docker

Requirements: Python 3.12 or newer, and Docker with Docker Compose v2 for the database.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
set -a
. ./.env
set +a
```

Replace `change-me` for `HOOKLINE_JWT_SECRET` in `.env` with a random value as shown above before loading it. The application does not read `.env` itself, so the commands above load it into the shell. Docker Compose reads `.env` on its own.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `HOOKLINE_DATABASE_URL` | yes | none | `postgresql+psycopg://...` URL of the database |
| `HOOKLINE_JWT_SECRET` | yes | none | Secret for signing access tokens, at least 32 characters |
| `HOOKLINE_ACCESS_TOKEN_MINUTES` | no | `15` | Lifetime of an access token |
| `HOOKLINE_REFRESH_TOKEN_DAYS` | no | `7` | Lifetime of a refresh token |
| `HOOKLINE_REQUIRE_HTTPS_TARGETS` | no | `true` | Endpoint URLs must use `https`; `false` also allows `http` |
| `HOOKLINE_ALLOW_PRIVATE_TARGETS` | no | `false` | `true` skips the private address checks on endpoint URLs; only for tests and local demos |
| `HOOKLINE_MAX_BODY_BYTES` | no | `262144` | Largest accepted request body in bytes; larger bodies get `413` |
| `HOOKLINE_MAX_PAYLOAD_BYTES` | no | `65536` | Largest accepted event payload in bytes, as compact JSON; larger payloads get `413` |
| `HOOKLINE_DELIVERY_TIMEOUT_SECONDS` | no | `10` | Timeout in seconds for each delivery request |
| `HOOKLINE_MAX_ATTEMPTS` | no | `8` | Attempts before a delivery becomes `dead` |
| `HOOKLINE_BACKOFF_BASE_SECONDS` | no | `10` | Delay before the second attempt, doubled for each later attempt (before jitter) |
| `HOOKLINE_BACKOFF_MAX_SECONDS` | no | `3600` | Longest delay between two attempts (before jitter) |
| `HOOKLINE_WORKER_BATCH_SIZE` | no | `10` | Deliveries a worker claims at once |
| `HOOKLINE_WORKER_POLL_SECONDS` | no | `2` | Seconds a worker waits when nothing is due |
| `HOOKLINE_WORKER_LEASE_SECONDS` | no | `60` | How long a claimed delivery stays reserved for one worker |
| `HOOKLINE_RATE_LIMIT_PER_MINUTE` | no | `120` | Event intake requests allowed per API key and minute; more get `429` |
| `HOOKLINE_APP_NAME` | no | `Hookline` | Title shown in the API docs |
| `HOOKLINE_LOG_LEVEL` | no | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | for Compose | none | Credentials of the PostgreSQL container |
| `RECEIVER_SECRET` | no | empty | Signing secret the demo receiver checks deliveries with |

Start PostgreSQL, run the migrations, create the first admin and start the API:

```bash
docker compose up -d --wait postgres
alembic upgrade head
python -m hookline.cli create-admin --email admin@example.com
uvicorn hookline.main:app --reload
```

In a second shell with the same environment variables, start the worker that sends the deliveries:

```bash
python -m hookline.worker
```

The requests from the Docker section work the same way against this API. An endpoint must point at a receiver that the worker can reach, for example `http://127.0.0.1:9000/hook` with `RECEIVER_SECRET=<secret> python scripts/demo_receiver.py` running in a third shell. More detail is in [docs/development.md](docs/development.md).

## API overview

All application routes are under `/api/v1`. People authenticate with `Authorization: Bearer <access token>`, producer applications with `X-API-Key: hk_...`. List routes accept `limit` (1 to 100, default 20) and `offset` and return `{"items": [], "total": 0, "limit": 20, "offset": 0}`. Every error is an RFC 9457 problem details body with the media type `application/problem+json`; validation errors are `400`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health/live` | none | The process is running |
| GET | `/health/ready` | none | The database is reachable, otherwise `503` |
| POST | `/api/v1/auth/login` | none | Email and password to an access and a refresh token |
| POST | `/api/v1/auth/refresh` | none | Rotate the refresh token and get a new access token |
| POST | `/api/v1/auth/logout` | none | Revoke a refresh token |
| GET | `/api/v1/users/me` | JWT | The logged-in user |
| POST | `/api/v1/users` | JWT, admin | Create a user |
| GET | `/api/v1/users` | JWT, admin | List users |
| PATCH | `/api/v1/users/{id}` | JWT, admin | Change a user's role or deactivate them |
| POST | `/api/v1/api-keys` | JWT | Create an API key, shown once |
| GET | `/api/v1/api-keys` | JWT | List own API keys (prefix only) |
| DELETE | `/api/v1/api-keys/{id}` | JWT | Revoke an own API key |
| POST | `/api/v1/endpoints` | JWT | Create an endpoint, signing secret shown once |
| GET | `/api/v1/endpoints` | JWT | List own endpoints (admins: all) |
| GET | `/api/v1/endpoints/{id}` | JWT | Endpoint details, without the secret |
| PATCH | `/api/v1/endpoints/{id}` | JWT | Change the URL, description, event types or active flag |
| DELETE | `/api/v1/endpoints/{id}` | JWT | Delete an endpoint and its deliveries |
| POST | `/api/v1/endpoints/{id}/rotate-secret` | JWT | New signing secret, shown once |
| POST | `/api/v1/events` | API key | Submit an event, with an optional `Idempotency-Key` header |
| GET | `/api/v1/events` | JWT | List own events (admins: all) |
| GET | `/api/v1/events/{id}` | JWT | Event details with its payload and deliveries |
| GET | `/api/v1/deliveries` | JWT | List deliveries with filters |
| GET | `/api/v1/deliveries/{id}` | JWT | A delivery with all of its attempts |
| POST | `/api/v1/deliveries/{id}/retry` | JWT | Requeue a failed or dead delivery |
| GET | `/api/v1/stats` | JWT | Delivery statistics |

Every route is described with request and response examples in [docs/api.md](docs/api.md). The running API also serves interactive OpenAPI docs at http://localhost:8000/docs and the schema at `/openapi.json`.

## Verifying webhook signatures

Every delivery carries a `Hookline-Signature: t=<timestamp>,v1=<signature>` header. The signature is the hex HMAC-SHA256 of the timestamp, a dot and the raw request body, with the endpoint's signing secret as the key. A receiver checks it against the raw body bytes, before parsing the JSON, and rejects timestamps more than five minutes old:

```python
import hashlib
import hmac
import time


def verify_hookline_signature(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    values = {}
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        values[name] = value
    timestamp = values.get("t", "")
    signature = values.get("v1", "")
    if not timestamp.isdecimal() or not signature:
        return False
    if abs(time.time() - int(timestamp)) > tolerance:
        return False
    message = f"{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())
```

Call it with the endpoint's secret, the `Hookline-Signature` header and the raw request body, and answer `401` when it returns `False`. The full description is in [docs/security.md](docs/security.md#verifying-signatures) and [decision 0004](docs/decisions/0004-payload-signing.md).

## Delivery guarantees

**At least once.** Every delivery is sent until the receiver answers with a `2xx` status or the attempts run out. If a worker crashes, or its lease runs out, after sending a request but before recording the answer, the delivery is sent again. The same event can therefore arrive more than once. Every attempt carries the same `Hookline-Event-Id` header, which receivers use to ignore events they have already processed. Inside a valid lease a delivery is never sent by two workers at the same time.

**Retries and backoff.** Any answer other than `2xx`, a redirect, a timeout or a connection error is a failed attempt. The delay before the next attempt is `min(HOOKLINE_BACKOFF_MAX_SECONDS, HOOKLINE_BACKOFF_BASE_SECONDS * 2 ** (n - 1))` after the `n`-th failed attempt, multiplied by a random factor between 0.5 and 1.0 (jitter), so that many failed deliveries do not all come back at the same moment. With the default settings:

| Attempt | Sent | Delay before it, without jitter | Delay with jitter |
|---|---|---|---|
| 1 | as soon as a worker claims it | none | none |
| 2 | after attempt 1 failed | 10 s | 5 to 10 s |
| 3 | after attempt 2 failed | 20 s | 10 to 20 s |
| 4 | after attempt 3 failed | 40 s | 20 to 40 s |
| 5 | after attempt 4 failed | 80 s | 40 to 80 s |
| 6 | after attempt 5 failed | 160 s | 80 to 160 s |
| 7 | after attempt 6 failed | 320 s | 160 to 320 s |
| 8 | after attempt 7 failed | 640 s | 320 to 640 s |

**Dead letter.** When the eighth attempt (`HOOKLINE_MAX_ATTEMPTS`) also fails, the delivery becomes `dead` and is not sent again on its own. A delivery whose endpoint was deactivated also becomes `dead`, with the error `endpoint disabled`, without being sent.

**Manual retry.** `POST /api/v1/deliveries/{id}/retry` puts a `failed` or `dead` delivery back to `pending` for a fresh run of up to eight attempts, with the delay starting again at the base value. The old attempts stay in the history and the attempt numbers continue from the highest one. Of two retries sent at the same moment, only one succeeds; the other gets `409`.

## Running the tests and checks

```bash
ruff format --check .
ruff check .
mypy src
pytest --cov --cov-report=term-missing
```

Unit tests need nothing else. Integration tests run against a real PostgreSQL 17 that Testcontainers starts in Docker, so Docker must be running; `pytest -m "not integration"` runs only the unit tests. No test uses the network: outgoing HTTP goes through `MockTransport` and DNS through a fake resolver.

CI runs the same checks and fails when test coverage drops below 85% (`--cov-fail-under=85`). A second CI job runs `shellcheck scripts/*.sh`, builds the image and runs the end-to-end smoke test against the Compose stack:

```bash
scripts/smoke_test.sh
shellcheck scripts/*.sh
```

See [docs/testing.md](docs/testing.md) for how the tests are organised and [docs/development.md](docs/development.md) for troubleshooting.

## Design decisions

- [0001: Modular monolith with an API process and a worker process](docs/decisions/0001-modular-monolith.md)
- [0002: Synchronous FastAPI routes and synchronous SQLAlchemy](docs/decisions/0002-synchronous-sqlalchemy.md)
- [0003: Event intake and idempotency keys](docs/decisions/0003-event-intake-and-idempotency.md)
- [0004: Payload signing with HMAC-SHA256](docs/decisions/0004-payload-signing.md)
- [0005: PostgreSQL as the delivery job queue](docs/decisions/0005-postgres-job-queue.md)
- [0006: Fixed-window rate limiting in PostgreSQL](docs/decisions/0006-rate-limiting.md)

Further documentation: [API](docs/api.md), [architecture](docs/architecture.md), [database](docs/database.md), [development](docs/development.md), [security](docs/security.md) and [testing](docs/testing.md).

## Limitations and future work

- **No encryption at rest for endpoint secrets.** Signing secrets are stored in plain text because Hookline needs them to sign deliveries. Encrypting them with a key kept outside the database would be the next step.
- **Fixed-window rate limiting.** Up to twice the limit can arrive around the start of a minute, and requests with an invalid API key are rejected before they are counted. A sliding window, or Redis for a very busy deployment, would smooth this.
- **No dashboard.** Hookline is an API only; delivery history and statistics are read through the API or `/docs`.
- **Single region.** One PostgreSQL database is the queue and the store. Workers scale out, but the database is the limit and a single point of failure.
- **At-least-once delivery.** Receivers must de-duplicate on `Hookline-Event-Id`; exactly-once delivery over HTTP is not possible without the receiver's help.
- **DNS rebinding.** The target address is checked again before every delivery, but a short gap remains between that check and the moment the HTTP client connects.
- **No login throttling.** There is no limit on failed logins per account or address; bcrypt only makes each guess slow. Access tokens stay valid until they expire after logout, at most 15 minutes by default.
- **Local Compose setup.** The Compose stack has no TLS and keeps its configuration in `.env`; a real deployment needs TLS in front of the API and a secret store.

The full list, with the reasons, is in [docs/security.md](docs/security.md#known-limitations).

## License

MIT, see [LICENSE](LICENSE).
