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
