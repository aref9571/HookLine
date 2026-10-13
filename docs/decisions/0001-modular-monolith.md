# 0001: Modular monolith with an API process and a worker process

Status: accepted

## Context

Hookline has two different jobs. It must accept events quickly over HTTP, and it must send those events to subscriber endpoints that may be slow, down or returning errors. Sending must be retried over minutes or hours without blocking anyone who is submitting events.

The project is built and maintained by one developer, so the design must be easy to run, test and explain.

## Decision

Hookline is one Python package with feature folders (`users`, `api_keys`, `endpoints`, `events`, `deliveries` and so on) and two entry points:

- the API, a FastAPI application served by uvicorn, which stores events and creates delivery rows;
- the worker, a separate process that claims due deliveries from PostgreSQL and sends them.

Both processes share the same code and the same PostgreSQL database. There are no separate services and no message broker.

## Consequences

- One codebase, one set of models and one test suite cover both processes.
- Slow subscribers only affect the worker, never the API.
- Workers can be scaled by starting more worker processes.
- The database is the single point of coordination, so the queue design must make concurrent claiming safe.
- If the project ever needed to scale far beyond one database, the worker could be split out later, but that is not needed now.
