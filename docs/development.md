# Development

This guide explains how to run Hookline and its tests on a development machine.

## Requirements

- Python 3.12 or newer
- Docker with Docker Compose v2, for the local PostgreSQL and for the integration tests

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration and `.env`

Hookline reads its configuration from environment variables that start with `HOOKLINE_`. The application does not read `.env` files itself. The `.env` file is used by Docker Compose for the database credentials and can be loaded into your shell for the application.

```bash
cp .env.example .env
```

Change `POSTGRES_PASSWORD` in `.env` and use the same password in `HOOKLINE_DATABASE_URL`. `.env` is listed in `.gitignore` and must never be committed.

Load the variables into the current shell:

```bash
set -a
. ./.env
set +a
```

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `HOOKLINE_DATABASE_URL` | yes | none | SQLAlchemy URL, for example `postgresql+psycopg://hookline:change-me@127.0.0.1:5432/hookline` |
| `HOOKLINE_APP_NAME` | no | `Hookline` | Title shown in the API docs |
| `HOOKLINE_LOG_LEVEL` | no | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | for Compose | none | Credentials of the local PostgreSQL container |

The application refuses to start if `HOOKLINE_DATABASE_URL` is not set.

## Starting PostgreSQL

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

## Running the API

```bash
uvicorn hookline.main:app --reload
curl localhost:8000/health/live
curl localhost:8000/health/ready
```

`/health/ready` returns `503` if the database cannot be reached. The API docs are at http://localhost:8000/docs.

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

## Troubleshooting Docker

- `Cannot connect to the Docker daemon` or similar connection errors in the integration tests mean Docker is not running. Start Docker and run the tests again. The unit tests do not need Docker.
- `port is already allocated` when starting Compose means another PostgreSQL is using port 5432. Stop it, or change the host port in `docker-compose.yml` and in `HOOKLINE_DATABASE_URL`.
- `set POSTGRES_PASSWORD in .env` means the `.env` file is missing or incomplete. Copy `.env.example` to `.env`.
- If the first test run is slow, Docker is downloading the `postgres:17` image. Later runs reuse it.
