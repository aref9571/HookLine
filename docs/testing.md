# Testing

This document describes how the tests are organised, how the integration tests get a real PostgreSQL database, how to run a subset, and how coverage is measured. How to install the project and run the other checks is in [development.md](development.md).

## Layout

```
tests/
├── conftest.py      fixtures shared by all tests
├── helpers.py       small setup functions: add_user, log_in, auth_headers
├── unit/            tests that need no database
└── integration/     tests against a real PostgreSQL, marked with "integration"
```

- **Unit tests** (`tests/unit/`) test one module or one route without a database: settings, password hashing, tokens, URL safety, signing, the sender, backoff, the body size limit, the security headers, request logging, error handling, pagination and the worker's behaviour when the database is down. Routes that fail before they reach the database (for example `401` without a token or `400` for an invalid body) are tested here with the `client_without_database` fixture.
- **Integration tests** (`tests/integration/`) go through the real API, the real services and a real PostgreSQL 17: the schema constraints, migrations, authentication, user management, API keys, endpoints, event intake, the worker, delivery history, retry, statistics and rate limiting.

Test files are named after the feature they test, and test functions describe the behaviour they check, for example `test_revoking_another_users_key_returns_404`. They are plain `pytest` functions with the arrange, act and assert steps separated by blank lines.

## Markers

Every module in `tests/integration/` sets `pytestmark = pytest.mark.integration`. The marker is registered in `pyproject.toml`; an unregistered marker name makes pytest print a warning. Apart from `parametrize`, there are no other markers.

## How Testcontainers is used

`tests/conftest.py` defines the database fixtures:

| Fixture | Scope | What it gives |
|---|---|---|
| `database_url` | whole test run | Starts one `postgres:17` container with Testcontainers, sets `HOOKLINE_DATABASE_URL` to it and runs `alembic upgrade head`, so the tests use the same migrations as production |
| `db_engine` | whole test run | A SQLAlchemy engine for that database |
| `clean_database` | each test | Empties every table after the test with one `TRUNCATE ... RESTART IDENTITY CASCADE` |
| `db_session` | each test | A database connection object for arranging data and checking rows directly |
| `settings` | each test | `Settings` pointing at the test database |
| `client` | each test | A FastAPI `TestClient` for an app built with `create_app(settings)` |
| `client_without_database` | each test | A `TestClient` for an app whose database URL points at a closed port, for unit tests |

The container is started once and reused by every integration test, because starting PostgreSQL takes a few seconds. Tables are emptied after each test instead of dropping the schema, which keeps each test independent and fast. The container is removed when the test run ends. Docker must be running for the integration tests; the unit tests do not need it.

`pytest_configure` sets placeholder values for `HOOKLINE_DATABASE_URL` and `HOOKLINE_JWT_SECRET`, because `hookline.main` builds the application when it is imported and both settings are required.

## Keeping tests deterministic

- **Time.** Routes read the time from the `get_now` dependency, which tests replace with a fixed or fake clock (`app.dependency_overrides`). The worker takes a `now_func`. Tests that check expiry or the rate limit window move the clock instead of sleeping.
- **Randomness.** The backoff jitter takes a `random_fraction`, and the worker a `random_func`, so tests know the exact retry time.
- **Network.** No test talks to the internet. Outgoing HTTP goes through `httpx2.MockTransport`, and DNS goes through a fake resolver (the `get_resolver` dependency for the API, a `resolver` argument for the sender and the worker).
- **Concurrency.** The tests for idempotency keys, rate limiting, retries and worker claims start several threads that each use their own database connection and wait on a `threading.Barrier`, so the requests really run at the same time. Each of these tests was checked once against a deliberately broken version of the code (for example without `FOR UPDATE SKIP LOCKED`) to make sure it fails.
- **Processes.** One worker test starts `python -m hookline.worker` as a real subprocess and stops it with `SIGTERM`, with a time limit on the wait. Another runs the same entry point inside the test process with `runpy`.

## Running a subset

```bash
pytest -m "not integration"                    # only the unit tests, no Docker needed
pytest -m integration                          # only the integration tests
pytest tests/integration/test_worker.py        # one file
pytest -k retry                                # tests whose name contains "retry"
pytest tests/unit/test_signing.py::test_verify_accepts_a_correct_header
pytest -W error                                # turn every warning into a failure
```

## Coverage

Coverage is measured with `pytest-cov` over the `hookline` package, with branch coverage turned on in `pyproject.toml`:

```bash
pytest --cov --cov-report=term-missing
```

The report lists the lines and branches that no test reached. CI runs the tests with `--cov-fail-under=85`, so a change that lowers total coverage below 85% fails the build. Coverage only shows which code ran, not whether a test checked the result, so every test also asserts the behaviour it is about. CI runs the integration tests too, because GitHub's `ubuntu-latest` runners have Docker.
