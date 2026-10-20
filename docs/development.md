# Development

This guide explains how to run Hookline and its tests on a development machine. The quickest way to run the whole system is Docker Compose; running the API and the worker directly with Python is described after that.

## Requirements

- Python 3.12 or newer
- Docker with Docker Compose v2, for the Compose stack, the local PostgreSQL and the integration tests

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration and `.env`

Hookline reads its configuration from environment variables that start with `HOOKLINE_`. The application does not read `.env` files itself. Docker Compose reads `.env` for the database credentials and passes the `HOOKLINE_` variables to the Hookline containers; for the Python path below it can be loaded into your shell.

```bash
cp .env.example .env
```

Set `HOOKLINE_JWT_SECRET` in `.env` to a random value of at least 32 characters (see below). Change `POSTGRES_PASSWORD` and use the same password in `HOOKLINE_DATABASE_URL`. `.env` is listed in `.gitignore` and must never be committed.

`.env.example` is made for the local demo: it sets `HOOKLINE_ALLOW_PRIVATE_TARGETS=true` and `HOOKLINE_REQUIRE_HTTPS_TARGETS=false`, so that Hookline may deliver to the demo receiver at `http://receiver:9000/hook`, which is a plain `http` address on the private Docker network. A real deployment must keep the defaults (`false` and `true`), otherwise users could make Hookline send requests to internal services (see [security.md](security.md#server-side-request-forgery-ssrf)).

Load the variables into the current shell:

```bash
set -a
. ./.env
set +a
```

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `HOOKLINE_DATABASE_URL` | yes | none | SQLAlchemy URL, for example `postgresql+psycopg://hookline:change-me@127.0.0.1:5432/hookline` |
| `HOOKLINE_JWT_SECRET` | yes | none | Secret for signing access tokens, at least 32 characters |
| `HOOKLINE_ACCESS_TOKEN_MINUTES` | no | `15` | Lifetime of an access token in minutes |
| `HOOKLINE_REFRESH_TOKEN_DAYS` | no | `7` | Lifetime of a refresh token in days |
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
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | for Compose | none | Credentials of the local PostgreSQL container |
| `RECEIVER_SECRET` | no | empty | Signing secret of the demo endpoint, read only by the demo receiver |

The application refuses to start if `HOOKLINE_DATABASE_URL` or `HOOKLINE_JWT_SECRET` is not set, or if the JWT secret is shorter than 32 characters. Alembic and the command-line tool read the same settings, so they need both variables too. Create a JWT secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The tests set their own placeholder values and do not need these variables.

## Running everything with Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
curl localhost:8000/health/ready
```

`docker-compose.yml` starts these services:

| Service | What it does |
|---|---|
| `postgres` | PostgreSQL 17 with the data in the named volume `postgres-data`, published on `127.0.0.1:5432` |
| `migrate` | Runs `alembic upgrade head` once after PostgreSQL is healthy, then exits |
| `api` | The API (`uvicorn hookline.main:app`) on `127.0.0.1:8000`, started after `migrate` has finished successfully |
| `worker` | The delivery worker (`python -m hookline.worker`), also started after `migrate` |
| `receiver` | The demo receiver from `scripts/demo_receiver.py` on port 9000 inside the Compose network only |

`migrate`, `api` and `worker` use the same image, built from the `Dockerfile`. They read the settings from `.env`; only `HOOKLINE_DATABASE_URL` is set by Compose, from the `POSTGRES_` values, so that it points at the `postgres` service instead of `127.0.0.1`. `api` and `worker` are restarted automatically if they stop with an error. The image runs as the non-root user `hookline` and has a health check that calls `/health/live`.

Create the first admin inside the `api` container:

```bash
docker compose exec api python -m hookline.cli create-admin --email admin@example.com
```

### Trying a delivery with the demo receiver

The demo receiver is a small standard-library HTTP server. It accepts `POST /hook`, checks the `Hookline-Signature` header with the same algorithm as the example in [security.md](security.md#verifying-signatures), answers `204` for a valid signature and `401` otherwise, and prints one line per request with the event ID. It only knows the signing secret through `RECEIVER_SECRET`, and the secret is created by Hookline when the endpoint is created, so the order is:

1. Log in, create an API key and create an endpoint with the URL `http://receiver:9000/hook` (the requests are shown in the README).
2. Put the `secret` from the endpoint response into `.env` as `RECEIVER_SECRET=...` and restart the receiver with `docker compose up -d receiver`.
3. Send an event with the API key, then run `docker compose logs receiver`. It shows `Verified signature for event <id>` once the worker has delivered it.

### Smoke test

`scripts/smoke_test.sh` runs all of these steps automatically and prints `PASS` or `FAIL`. It stops the stack and **deletes its volumes**, including the Compose database, when it ends. See [testing.md](testing.md#end-to-end-smoke-test).

### Stopping

```bash
docker compose down
```

Add `-v` to delete the database volume as well.

## Starting PostgreSQL

To run the API and the worker directly with Python, start only the database:

```bash
docker compose up -d --wait postgres
```

This starts PostgreSQL 17, reachable only from the local machine on `127.0.0.1:5432`. The data is kept in the named volume `postgres-data`. Stop it with `docker compose down`; add `-v` to delete the data as well.

## Running migrations

Alembic reads the database URL from `HOOKLINE_DATABASE_URL`, not from `alembic.ini`.

```bash
alembic upgrade head
alembic downgrade base
alembic check
```

New migrations use readable, numbered revision IDs:

```bash
alembic revision --autogenerate --rev-id 0002 -m "short description"
ruff format migrations
```

Autogenerate puts two comment lines around the generated operations. Delete them before committing, because the project keeps no comments in code.

## Creating the first admin

```bash
python -m hookline.cli create-admin --email admin@example.com
```

The command asks for the password twice without showing it. To run it without a prompt, set `HOOKLINE_ADMIN_PASSWORD` for that one command. The password must be 12 to 128 characters and at most 72 bytes in UTF-8. The command fails if a user with that email already exists.

## Running the API

```bash
uvicorn hookline.main:app --reload
curl localhost:8000/health/live
curl localhost:8000/health/ready
```

`/health/ready` returns `503` if the database cannot be reached. The API docs are at http://localhost:8000/docs.

## Running the worker

```bash
python -m hookline.worker
```

The worker sends pending deliveries and retries failed ones. It needs the same environment variables as the API. Stop it with Ctrl+C or `SIGTERM`; it finishes the delivery it is sending first. Several workers can run at the same time. A local test against a receiver on your own machine needs `HOOKLINE_ALLOW_PRIVATE_TARGETS=true` and `HOOKLINE_REQUIRE_HTTPS_TARGETS=false` for both the API and the worker, as set in `.env.example`.

## Running the checks and tests

```bash
ruff format --check .
ruff check .
mypy src
pytest --cov --cov-report=term-missing
```

Integration tests are marked with `integration`. They start their own PostgreSQL 17 container with Testcontainers, run the migrations and empty the tables after each test, so they do not touch the Compose database. To run only one group:

```bash
pytest -m "not integration"
pytest -m integration
```

CI runs the same checks and fails when total test coverage is below 85% (`pytest --cov --cov-fail-under=85`). CI also has a second job, `docker-smoke`, which runs after these checks have passed: it runs `shellcheck scripts/*.sh`, builds the image and runs `scripts/smoke_test.sh`. How the tests are organised, how Testcontainers is used and how to run smaller subsets is described in [testing.md](testing.md).

## Troubleshooting Docker

- `Cannot connect to the Docker daemon` or similar connection errors in the integration tests mean Docker is not running. Start Docker and run the tests again. The unit tests do not need Docker.
- `port is already allocated` when starting Compose means another program is using port 5432 or 8000. Stop it, or change the host port in `docker-compose.yml` (for 5432 also in `HOOKLINE_DATABASE_URL`).
- If `api` or `worker` keeps restarting, `docker compose logs api` shows why. The most common reason is a `HOOKLINE_JWT_SECRET` shorter than 32 characters, for example the `change-me` placeholder from `.env.example`.
- The database URL is built from `POSTGRES_USER` and `POSTGRES_PASSWORD`, so these values should only contain letters, digits, `-` and `_`; other characters would need URL encoding.
- `set POSTGRES_PASSWORD in .env` means the `.env` file is missing or incomplete. Copy `.env.example` to `.env`.
- If the first test run is slow, Docker is downloading the `postgres:17` image. Later runs reuse it.
