# Database

Hookline stores everything in PostgreSQL 17. The schema is defined twice on purpose: as SQLAlchemy models in each feature folder, and as Alembic migrations in `migrations/versions/`. A test runs `alembic check` against a migrated database, so the two cannot drift apart without the test suite failing.

## Conventions

- Every `id` is a `uuid` that PostgreSQL creates with `gen_random_uuid()`, so IDs cannot be guessed from their order and rows can be created by any process without a central counter.
- Every timestamp is `timestamptz` and stored in UTC.
- `created_at` defaults to `now()` in the database. `updated_at` also defaults to `now()`, and SQLAlchemy sets it to `now()` again whenever the row is updated through the ORM.
- Roles and delivery statuses are stored as `varchar` with a check constraint, not as PostgreSQL enum types. Adding a value to a check constraint is a simple migration; changing a PostgreSQL enum type is not. In Python the allowed values are the `StrEnum` classes `UserRole` and `DeliveryStatus`.
- Constraint and index names come from the naming convention in `src/hookline/database.py`, so migrations always create and drop the same names:

| Kind | Pattern | Example |
|---|---|---|
| Primary key | `pk_<table>` | `pk_users` |
| Foreign key | `fk_<table>_<column>_<referred table>` | `fk_events_user_id_users` |
| Unique | `uq_<table>_<columns>` | `uq_deliveries_event_id_endpoint_id` |
| Check | `ck_<table>_<name>` | `ck_users_role` |

  Two names are written by hand: `events_idempotency_uk`, the name the design uses for idempotency, and `uq_users_email_lower`, a unique index on an expression.
- All models are imported in `src/hookline/models.py`. Alembic and the tests import `Base` from there, so every table is registered before the metadata is read.

## Tables

### users

People who log in. Each member owns their own keys, endpoints and events.

| Column | Type | Rules |
|---|---|---|
| id | uuid | primary key |
| email | varchar(254) | not null |
| password_hash | varchar(100) | not null |
| role | varchar(20) | not null, `admin` or `member` |
| is_active | boolean | not null, default true |
| created_at | timestamptz | not null, default now() |

- `ck_users_role` allows only `admin` and `member`, so an unknown role can never be stored, even by a bug in the code.
- `uq_users_email_lower` is a unique index on `lower(email)`. `A@x.com` and `a@x.com` are the same mailbox for login purposes, so they must not become two accounts. Login will look a user up by `lower(email)`, which uses the same index.
- 254 characters is the longest valid email address.

### refresh_tokens

Refresh tokens issued at login. Only the SHA-256 hash of a token is stored, so a copy of the database does not contain usable tokens.

| Column | Type | Rules |
|---|---|---|
| id | uuid | primary key |
| user_id | uuid | not null, references users, on delete cascade |
| token_hash | char(64) | not null, unique |
| expires_at | timestamptz | not null |
| revoked_at | timestamptz | null while the token is usable |
| created_at | timestamptz | not null, default now() |

- `uq_refresh_tokens_token_hash` makes the hash unique and gives the index used to find a token when it is presented.
- `fk_refresh_tokens_user_id_users` cascades, so deleting a user removes their tokens.

### api_keys

Keys that producer applications send in the `X-API-Key` header. Like refresh tokens, only the SHA-256 hash is stored. `prefix` holds the first characters of the key so a user can recognise it in a list.

| Column | Type | Rules |
|---|---|---|
| id | uuid | primary key |
| user_id | uuid | not null, references users, on delete cascade |
| name | varchar(100) | not null |
| prefix | varchar(12) | not null |
| key_hash | char(64) | not null, unique |
| last_used_at | timestamptz | null |
| revoked_at | timestamptz | null while the key is usable |
| created_at | timestamptz | not null, default now() |

- `uq_api_keys_key_hash` makes the hash unique and gives the index used to look up the key on every event request.
- `fk_api_keys_user_id_users` cascades, so deleting a user removes their keys.

### endpoints

Subscriber URLs, the event types each one wants, and the secret used to sign its deliveries.

| Column | Type | Rules |
|---|---|---|
| id | uuid | primary key |
| user_id | uuid | not null, references users, on delete cascade |
| url | varchar(2048) | not null |
| description | varchar(255) | null |
| event_types | text[] | not null, between 1 and 50 entries |
| secret | varchar(64) | not null |
| is_active | boolean | not null, default true |
| created_at | timestamptz | not null, default now() |
| updated_at | timestamptz | not null, default now() |

- `ck_endpoints_event_types_count` checks `cardinality(event_types) BETWEEN 1 AND 50`. An endpoint with no event types would never receive anything, and the upper limit keeps the matching work per event small.
- The signing secret is stored as plain text because the worker needs the original value to compute signatures. Encrypting it at rest is future work.
- `fk_endpoints_user_id_users` cascades, so deleting a user removes their endpoints.

### events

Events submitted by producers. An event is stored once and fans out into one delivery per matching endpoint.

| Column | Type | Rules |
|---|---|---|
| id | uuid | primary key |
| user_id | uuid | not null, references users, on delete cascade |
| api_key_id | uuid | null, references api_keys, on delete set null |
| event_type | varchar(100) | not null |
| payload | jsonb | not null, must be a JSON object |
| idempotency_key | varchar(100) | null |
| request_hash | char(64) | null |
| created_at | timestamptz | not null, default now() |

- `ck_events_payload_is_object` checks `jsonb_typeof(payload) = 'object'`. Receivers always get a JSON object, never a bare list, string or number.
- `events_idempotency_uk` is unique on `(user_id, idempotency_key)`. When a producer retries a request with the same `Idempotency-Key`, the database itself refuses a second event, even if two requests arrive at the same moment. PostgreSQL treats NULLs as distinct, so events sent without a key are not limited. The same key may be used by two different users.
- `request_hash` stores the SHA-256 of the canonical JSON request body, so a reused key with a different body can be detected. How intake uses the constraint is described in [decision 0003](decisions/0003-event-intake-and-idempotency.md).
- `fk_events_api_key_id_api_keys` uses `on delete set null`: revoking and deleting a key must not delete the history of events it sent.
- `fk_events_user_id_users` cascades, so deleting a user removes their events.

### deliveries

One row per event and matching endpoint. This table is also the job queue the worker reads from.

| Column | Type | Rules |
|---|---|---|
| id | uuid | primary key |
| event_id | uuid | not null, references events, on delete cascade |
| endpoint_id | uuid | not null, references endpoints, on delete cascade |
| status | varchar(20) | not null, see the status diagram |
| attempt_count | integer | not null, default 0, at least 0 |
| next_attempt_at | timestamptz | not null |
| locked_until | timestamptz | null unless a worker holds the delivery |
| last_status_code | integer | null |
| last_error | varchar(500) | null |
| created_at | timestamptz | not null, default now() |
| updated_at | timestamptz | not null, default now() |

- `ck_deliveries_status` allows only `pending`, `in_progress`, `succeeded`, `failed` and `dead`.
- `ck_deliveries_attempt_count_not_negative` checks `attempt_count >= 0`.
- `uq_deliveries_event_id_endpoint_id` makes sure an event is delivered to an endpoint at most once as a delivery row, even if delivery creation runs twice.
- Both foreign keys cascade: deleting an event or an endpoint removes its deliveries.
- `status` and `next_attempt_at` have no database default. The code that creates a delivery sets both explicitly.

### delivery_attempts

One row per HTTP request the worker made for a delivery. This is the delivery history.

| Column | Type | Rules |
|---|---|---|
| id | uuid | primary key |
| delivery_id | uuid | not null, references deliveries, on delete cascade |
| attempt_number | integer | not null, at least 1 |
| status_code | integer | null when no response was received |
| error | varchar(500) | null |
| duration_ms | integer | not null, at least 0 |
| response_excerpt | varchar(1000) | null |
| attempted_at | timestamptz | not null |

- `ck_delivery_attempts_attempt_number_positive` checks `attempt_number >= 1`; attempts are counted from one.
- `ck_delivery_attempts_duration_ms_not_negative` checks `duration_ms >= 0`.
- `uq_delivery_attempts_delivery_id_attempt_number` stops the same attempt being recorded twice, and its index serves loading the attempts of one delivery in order.
- In Python, `Delivery.attempts` loads the attempts of a delivery ordered by `attempt_number`.

## Indexes and the queries that use them

| Index | Columns | Used by |
|---|---|---|
| `uq_users_email_lower` | `lower(email)`, unique | Finding a user by email at login |
| `uq_refresh_tokens_token_hash` | `token_hash`, unique | Finding a presented refresh token |
| `uq_api_keys_key_hash` | `key_hash`, unique | Authenticating every event request |
| `events_idempotency_uk` | `(user_id, idempotency_key)`, unique | Finding an earlier event with the same idempotency key |
| `uq_deliveries_event_id_endpoint_id` | `(event_id, endpoint_id)`, unique | Listing the deliveries of one event |
| `ix_deliveries_due` | `next_attempt_at` where `status IN ('pending', 'failed')` | The worker's query for deliveries that are due |
| `ix_deliveries_endpoint_id_created_at` | `(endpoint_id, created_at DESC)` | `GET /api/v1/deliveries?endpoint_id=...`: the delivery history of one endpoint, newest first |
| `uq_delivery_attempts_delivery_id_attempt_number` | `(delivery_id, attempt_number)`, unique | Loading the attempts of one delivery in order |

`ix_deliveries_due` is a partial index: it only contains deliveries the worker may still pick up. Succeeded and dead deliveries, which will be most of the table over time, are not in it, so the worker's query stays fast as history grows.

Primary key indexes are not listed. No other foreign key column has its own index yet; that is enough at this project's size, and an index can be added in a later migration if a query needs it.

## Delivery status

```
pending ──► in_progress ──► succeeded
   │            │  ▲
   │            │  └── in_progress (lease expired, claimed again)
   │            ├──► failed ──► in_progress (next attempt)
   │            │       └──► pending (manual retry)
   │            └──► dead ──► pending (manual retry)
   │
   └──► dead (endpoint disabled)
```

| Status | Meaning |
|---|---|
| `pending` | Created and never tried |
| `in_progress` | Claimed by a worker; the claim expires at `locked_until` |
| `succeeded` | The endpoint answered with a success status |
| `failed` | An attempt failed; the next one is due at `next_attempt_at`, or a manual retry makes it due at once |
| `dead` | The maximum number of attempts was reached, or the endpoint was deactivated before the delivery was sent (`last_error` is `endpoint disabled`); only a manual retry sends it again |

The worker's claim also picks up `in_progress` deliveries whose lease has expired, and a `failed` delivery whose endpoint has been deactivated becomes `dead` the same way as a `pending` one. How the worker moves deliveries between these states is described in [architecture.md](architecture.md#delivery-worker). A manual retry (`POST /api/v1/deliveries/{id}/retry`) sets a `failed` or `dead` delivery back to `pending` and `attempt_count` to `0`; its rows in `delivery_attempts` are kept, and new attempts continue after the highest `attempt_number`.

## Deleting data

| Deleted row | Effect |
|---|---|
| User | Their refresh tokens, API keys, endpoints and events are deleted, and through the events and endpoints their deliveries and attempts |
| API key | Its events stay; their `api_key_id` becomes NULL |
| Endpoint | Its deliveries and their attempts are deleted |
| Event | Its deliveries and their attempts are deleted |
| Delivery | Its attempts are deleted |

## Migrations

| Revision | Content |
|---|---|
| `0001` | Enables the `pgcrypto` extension |
| `0002` | Creates the tables above with their constraints and indexes |

Each migration has a `downgrade` that removes exactly what its `upgrade` created. The tests downgrade to `0001` and to `base`, check that no application table is left, and upgrade again.
