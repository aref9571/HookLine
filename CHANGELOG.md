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
