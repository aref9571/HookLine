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
