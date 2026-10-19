# API

This document lists every route that exists so far, with request and response examples. The interactive OpenAPI docs are served at `/docs` and the schema at `/openapi.json`.

All application routes are under `/api/v1`. The health routes are not.

## Authentication

| Scheme | Header | Used by |
|---|---|---|
| JWT | `Authorization: Bearer <access token>` | People: admins and members |
| API key | `X-API-Key: hk_...` | Producer applications, for `POST /api/v1/events` |

Access tokens come from `POST /api/v1/auth/login`. API keys are created with `POST /api/v1/api-keys`.

There are two roles:

- `admin`: may also manage users, sees and manages the endpoints of all users, sees the events of all users, and sees and retries the deliveries of all users.
- `member`: manages only their own resources.

A missing or invalid token returns `401` with a `WWW-Authenticate: Bearer` header. A missing, unknown or revoked API key, or a key whose owner is deactivated, returns `401` with `WWW-Authenticate: ApiKey`. A member calling an admin route gets `403`. A resource that does not exist or belongs to someone else returns `404`.

## Errors

Every error uses RFC 9457 problem details with the media type `application/problem+json`. `errors` is present only for validation failures.

```json
{
  "type": "about:blank",
  "title": "Invalid request",
  "status": 400,
  "detail": "One or more fields are invalid.",
  "errors": [{"field": "limit", "message": "Input should be greater than or equal to 1"}]
}
```

## Request size

A request body larger than `HOOKLINE_MAX_BODY_BYTES` (default 262144 bytes) returns `413` with problem details, whether the size is declared in `Content-Length` or the body grows too large while it is read:

```json
{
  "type": "about:blank",
  "title": "Request Entity Too Large",
  "status": 413,
  "detail": "The request body is too large."
}
```

The `title` is the standard reason phrase of the status code from Python's `http.HTTPStatus`.

## Pagination

List routes accept `limit` (1 to 100, default 20) and `offset` (0 or more, default 0). Any other value returns `400`. The response is:

```json
{"items": [], "total": 0, "limit": 20, "offset": 0}
```

`total` is the number of rows across all pages. Lists are ordered newest first by `created_at`, then by `id`, so the order is always the same.

## Routes

| Method | Path | Auth | Success |
|---|---|---|---|
| GET | `/health/live` | none | 200 |
| GET | `/health/ready` | none | 200, or 503 without database |
| POST | `/api/v1/auth/login` | none | 200 |
| POST | `/api/v1/auth/refresh` | none | 200 |
| POST | `/api/v1/auth/logout` | none | 204 |
| GET | `/api/v1/users/me` | JWT | 200 |
| POST | `/api/v1/users` | JWT, admin | 201 |
| GET | `/api/v1/users` | JWT, admin | 200 |
| PATCH | `/api/v1/users/{id}` | JWT, admin | 200 |
| POST | `/api/v1/api-keys` | JWT | 201 |
| GET | `/api/v1/api-keys` | JWT | 200 |
| DELETE | `/api/v1/api-keys/{id}` | JWT | 204 |
| POST | `/api/v1/endpoints` | JWT | 201 |
| GET | `/api/v1/endpoints` | JWT | 200 |
| GET | `/api/v1/endpoints/{id}` | JWT | 200 |
| PATCH | `/api/v1/endpoints/{id}` | JWT | 200 |
| DELETE | `/api/v1/endpoints/{id}` | JWT | 204 |
| POST | `/api/v1/endpoints/{id}/rotate-secret` | JWT | 200 |
| POST | `/api/v1/events` | API key | 201, or 200 for a replay |
| GET | `/api/v1/events` | JWT | 200 |
| GET | `/api/v1/events/{id}` | JWT | 200 |
| GET | `/api/v1/deliveries` | JWT | 200 |
| GET | `/api/v1/deliveries/{id}` | JWT | 200 |
| POST | `/api/v1/deliveries/{id}/retry` | JWT | 200 |
| GET | `/api/v1/stats` | JWT | 200 |

### Health

`GET /health/live` returns `{"status": "ok"}` while the process runs.

`GET /health/ready` runs `SELECT 1` and returns `{"status": "ok"}`, or `503` problem details when the database cannot be reached.

### POST /api/v1/auth/login

```json
{"email": "admin@example.com", "password": "a-long-admin-password"}
```

Response `200`:

```json
{"access_token": "eyJhbGciOi...", "refresh_token": "q3J0...", "token_type": "bearer"}
```

A wrong password, an unknown email and a deactivated account all return the same `401` with `"detail": "Invalid email or password."`.

### POST /api/v1/auth/refresh

```json
{"refresh_token": "q3J0..."}
```

Response `200`: a new token pair in the same shape as login. The old refresh token stops working. An unknown, expired or revoked token returns `401`; presenting a revoked token again also revokes every refresh token of that user.

### POST /api/v1/auth/logout

```json
{"refresh_token": "q3J0..."}
```

Response `204` with no body, also when the token is unknown or already revoked.

### GET /api/v1/users/me

Response `200`:

```json
{
  "id": "6f1c2a52-8e0a-4b8c-9d43-3a7c1f0e2b11",
  "email": "admin@example.com",
  "role": "admin",
  "is_active": true,
  "created_at": "2026-10-15T09:12:44.512318Z"
}
```

### POST /api/v1/users

Admin only. `role` is `admin` or `member`. The email is stored in lower case; the password follows the rules in [security.md](security.md).

```json
{"email": "dev@example.com", "password": "a-long-member-password", "role": "member"}
```

Response `201`:

```json
{
  "id": "0d9c3f8e-2b1a-4e57-8f60-7c4d2a9b1e35",
  "email": "dev@example.com",
  "role": "member",
  "is_active": true,
  "created_at": "2026-10-15T09:20:03.118007Z"
}
```

An email that already exists, in any letter case, returns `409` with `"detail": "A user with this email already exists."`.

### GET /api/v1/users

Admin only. Paginated list of all users, newest first.

```
GET /api/v1/users?limit=2&offset=0
```

Response `200`:

```json
{
  "items": [
    {"id": "0d9c3f8e-2b1a-4e57-8f60-7c4d2a9b1e35", "email": "dev@example.com", "role": "member", "is_active": true, "created_at": "2026-10-15T09:20:03.118007Z"},
    {"id": "6f1c2a52-8e0a-4b8c-9d43-3a7c1f0e2b11", "email": "admin@example.com", "role": "admin", "is_active": true, "created_at": "2026-10-15T09:12:44.512318Z"}
  ],
  "total": 2,
  "limit": 2,
  "offset": 0
}
```

### PATCH /api/v1/users/{id}

Admin only. Both fields are optional; a field that is left out or `null` is not changed.

```json
{"role": "admin", "is_active": false}
```

Response `200`: the updated user in the same shape as `GET /api/v1/users/me`.

- Deactivating a user revokes all of their refresh tokens. Their access tokens stop working at once, because every request loads the user again, and they cannot log in until they are activated again.
- An admin cannot deactivate their own account or change their own role to `member`; both return `409`.
- An unknown ID returns `404`.

### POST /api/v1/api-keys

Any logged-in user. `name` is 1 to 100 characters after surrounding spaces are removed.

```json
{"name": "Shop backend"}
```

Response `201`:

```json
{
  "id": "b7e4a1c9-5f2d-4a8e-9c31-6d0f2e8b7a44",
  "name": "Shop backend",
  "prefix": "hk_Zm9vYmFy",
  "last_used_at": null,
  "revoked_at": null,
  "created_at": "2026-10-15T09:31:27.903114Z",
  "key": "hk_Zm9vYmFyYmF6cXV4LXNvbWUtcmFuZG9tLWNoYXJz",
  "message": "Store this key now. It will not be shown again."
}
```

`key` is the only time the full key is returned. Hookline stores only its SHA-256 hash.

### GET /api/v1/api-keys

Any logged-in user. Paginated list of the caller's own keys, newest first, including revoked ones. Admins also see only their own keys here.

Response `200`:

```json
{
  "items": [
    {
      "id": "b7e4a1c9-5f2d-4a8e-9c31-6d0f2e8b7a44",
      "name": "Shop backend",
      "prefix": "hk_Zm9vYmFy",
      "last_used_at": "2026-10-15T10:02:11.004521Z",
      "revoked_at": null,
      "created_at": "2026-10-15T09:31:27.903114Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### DELETE /api/v1/api-keys/{id}

Any logged-in user, own keys only. Revokes the key by setting `revoked_at`; the row is kept so the key still shows in the list. Response `204` with no body. Revoking a key that is already revoked also returns `204`. A key that does not exist or belongs to someone else returns `404`.

### POST /api/v1/endpoints

Any logged-in user. Registers a subscriber URL for the caller.

```json
{
  "url": "https://hooks.example.com/webhook",
  "description": "Order system",
  "event_types": ["order.created", "order.paid"]
}
```

- `url`: checked against the rules in [security.md](security.md#server-side-request-forgery-ssrf). By default it must use `https` and its host must not resolve to a private, loopback, link-local, multicast, reserved or unspecified address.
- `description`: optional, at most 255 characters.
- `event_types`: 1 to 50 different event types. Each one starts with a lower-case letter or a digit, followed by up to 99 lower-case letters, digits, `_`, `.` or `-`. The single value `["*"]` means all event types; `*` cannot be combined with other types.

Response `201`:

```json
{
  "id": "4f0c2d8e-9b1a-4c7e-8d35-2a6b1e9f0c47",
  "user_id": "0b9d6a3e-1f4c-4e8a-b2d7-5c8e1a3f6d90",
  "url": "https://hooks.example.com/webhook",
  "description": "Order system",
  "event_types": ["order.created", "order.paid"],
  "is_active": true,
  "created_at": "2026-10-15T14:05:12.448210Z",
  "updated_at": "2026-10-15T14:05:12.448210Z",
  "secret": "whsec_Q2hhbmdlLW1lLXRoaXMtaXMtYW4tZXhhbXBsZQ7xK2p",
  "message": "Store this secret now. It will not be shown again."
}
```

`secret` is used to sign deliveries to this endpoint. It is returned only here and by `rotate-secret`.

An unsafe URL returns `400`:

```json
{
  "type": "about:blank",
  "title": "Invalid request",
  "status": 400,
  "detail": "One or more fields are invalid.",
  "errors": [{"field": "url", "message": "must not point to a private or reserved address"}]
}
```

### GET /api/v1/endpoints

Any logged-in user. Paginated list, newest first. Members see their own endpoints, admins see all endpoints. The optional query parameter `is_active=true` or `is_active=false` filters the list. The secret is not included.

Response `200`:

```json
{
  "items": [
    {
      "id": "4f0c2d8e-9b1a-4c7e-8d35-2a6b1e9f0c47",
      "user_id": "0b9d6a3e-1f4c-4e8a-b2d7-5c8e1a3f6d90",
      "url": "https://hooks.example.com/webhook",
      "description": "Order system",
      "event_types": ["order.created", "order.paid"],
      "is_active": true,
      "created_at": "2026-10-15T14:05:12.448210Z",
      "updated_at": "2026-10-15T14:05:12.448210Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### GET /api/v1/endpoints/{id}

Response `200`: one endpoint in the same shape as a list item, without the secret. An endpoint that does not exist, or belongs to another user when the caller is a member, returns `404`.

### PATCH /api/v1/endpoints/{id}

Changes `url`, `description`, `event_types` or `is_active`. Fields that are left out are not changed. For `url`, `event_types` and `is_active`, `null` also means no change; `"description": null` removes the description. A new URL is checked with the same rules as on creation. `updated_at` is set to the current time.

```json
{"event_types": ["order.refunded"], "is_active": false}
```

Response `200`: the updated endpoint, without the secret. Same `404` rule as above.

### DELETE /api/v1/endpoints/{id}

Deletes the endpoint and, through the database, all of its deliveries. Response `204` with no body. Same `404` rule as above.

### POST /api/v1/endpoints/{id}/rotate-secret

Replaces the signing secret with a new one. No request body. Response `200`: the endpoint with the new `secret` and the same `message` as on creation. The old secret is no longer used. Same `404` rule as above.

### POST /api/v1/events

Producer applications, with an API key in `X-API-Key`. A bearer token is not accepted here. Submits an event for the owner of the key.

```json
{
  "event_type": "order.created",
  "payload": {"order_id": 42, "total": "9.99"}
}
```

- `event_type`: starts with a lower-case letter or a digit, followed by up to 99 lower-case letters, digits, `_`, `.` or `-`. `*` is not allowed.
- `payload`: a JSON object. A list, string, number or `null` returns `400`. Its compact JSON encoding may be at most `HOOKLINE_MAX_PAYLOAD_BYTES` (default 65536) bytes in UTF-8; a larger payload returns `413`.
- Optional header `Idempotency-Key`: 1 to 100 characters from `A-Z`, `a-z`, `0-9`, `_`, `.`, `:` and `-`. Any other value returns `400` for the field `Idempotency-Key`.

One `pending` delivery is created for every active endpoint of the same user whose `event_types` contain the event type or `*`. The event and its deliveries are saved in one transaction.

Response `201`:

```json
{
  "id": "7c1e2b3a-5d4f-4a6b-9c8d-0e1f2a3b4c5d",
  "created_at": "2026-10-16T09:30:00.123456Z",
  "delivery_count": 2
}
```

Sending the same `Idempotency-Key` again with the same body returns `200`, the same body as the first response (with the current number of deliveries) and the header `Idempotent-Replayed: true`; no new event or delivery is created. Sending the same key with a different body returns `409`. Idempotency keys are per user: two users may use the same key. The order of keys in the JSON body does not matter. How this works is described in [decision 0003](decisions/0003-event-intake-and-idempotency.md).

#### Rate limiting

Each API key may send at most `HOOKLINE_RATE_LIMIT_PER_MINUTE` (default 120) requests to `POST /api/v1/events` per minute. The minutes are fixed windows that start at second 0 of each clock minute (UTC). Every request with a valid key and a well-formed body is counted, including requests that are rejected later (for example with `413`, `409` or `429`) and idempotent replays. Requests without a valid key (`401`) or with a body that fails validation (`400`) are not counted.

Successful responses (`201` and `200`) carry two headers:

| Header | Meaning |
|---|---|
| `X-RateLimit-Limit` | The number of requests allowed per minute |
| `X-RateLimit-Remaining` | The number of requests left in the current minute |

A request over the limit is not processed and returns `429` with `Retry-After` (the seconds until the next minute starts, from 1 to 60) and the two headers above, with `X-RateLimit-Remaining: 0`:

```json
{
  "type": "about:blank",
  "title": "Too Many Requests",
  "status": 429,
  "detail": "The rate limit for this API key was exceeded. Try again later."
}
```

Other error responses from this route do not carry the rate limit headers. Why a fixed window was chosen, and its weak spot at window edges, is described in [decision 0006](decisions/0006-rate-limiting.md).

### GET /api/v1/events

Any logged-in user. Paginated list, newest first. Members see their own events, admins see all events. The payload is not included in the list.

Optional query parameters:

- `event_type`: only events of this type.
- `created_after`: only events created at or after this time.
- `created_before`: only events created before this time. When both are given, `created_before` must be later than `created_after`, otherwise `400`.

Times are ISO 8601 with a time zone, for example `2026-10-16T09:00:00Z`. A time without a time zone returns `400`.

Response `200`:

```json
{
  "items": [
    {
      "id": "7c1e2b3a-5d4f-4a6b-9c8d-0e1f2a3b4c5d",
      "user_id": "0b9d6a3e-1f4c-4e8a-b2d7-5c8e1a3f6d90",
      "api_key_id": "5a2f8c1d-3e4b-4f6a-8b9c-1d2e3f4a5b6c",
      "event_type": "order.created",
      "idempotency_key": "order-42",
      "created_at": "2026-10-16T09:30:00.123456Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### GET /api/v1/events/{id}

Any logged-in user. The event with its payload and a summary of its deliveries.

Response `200`:

```json
{
  "id": "7c1e2b3a-5d4f-4a6b-9c8d-0e1f2a3b4c5d",
  "user_id": "0b9d6a3e-1f4c-4e8a-b2d7-5c8e1a3f6d90",
  "api_key_id": "5a2f8c1d-3e4b-4f6a-8b9c-1d2e3f4a5b6c",
  "event_type": "order.created",
  "idempotency_key": "order-42",
  "created_at": "2026-10-16T09:30:00.123456Z",
  "payload": {"order_id": 42, "total": "9.99"},
  "deliveries": [
    {
      "id": "1d2c3b4a-6f5e-4d7c-8b9a-0f1e2d3c4b5a",
      "endpoint_id": "4f0c2d8e-9b1a-4c7e-8d35-2a6b1e9f0c47",
      "status": "pending",
      "attempt_count": 0
    }
  ]
}
```

An event that does not exist, or belongs to another user when the caller is a member, returns `404`.

### GET /api/v1/deliveries

Any logged-in user. Paginated list of deliveries, newest first by `created_at`, then by `id`. Members see the deliveries of their own endpoints, admins see all deliveries.

Optional query parameters:

- `status`: one of `pending`, `in_progress`, `succeeded`, `failed` and `dead`. Any other value returns `400`.
- `endpoint_id`: only deliveries to this endpoint.
- `event_id`: only deliveries of this event.
- `created_after`: only deliveries created at or after this time.
- `created_before`: only deliveries created before this time. When both are given, `created_before` must be later than `created_after`, otherwise `400`.

Times use the same ISO 8601 format with a time zone as `GET /api/v1/events`. Filtering by the ID of another user's endpoint or event returns an empty list for a member, not an error.

Response `200`:

```json
{
  "items": [
    {
      "id": "1d2c3b4a-6f5e-4d7c-8b9a-0f1e2d3c4b5a",
      "event_id": "7c1e2b3a-5d4f-4a6b-9c8d-0e1f2a3b4c5d",
      "endpoint_id": "4f0c2d8e-9b1a-4c7e-8d35-2a6b1e9f0c47",
      "status": "failed",
      "attempt_count": 2,
      "next_attempt_at": "2026-10-16T09:31:12Z",
      "locked_until": null,
      "last_status_code": 503,
      "last_error": null,
      "created_at": "2026-10-16T09:30:00.123456Z",
      "updated_at": "2026-10-16T09:30:52.418310Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

- `attempt_count`: the attempts made since the delivery was created or last retried by hand. It decides when the delivery becomes `dead`.
- `next_attempt_at`: when the worker may try a `pending` or `failed` delivery next.
- `locked_until`: the end of the current worker lease while the delivery is `in_progress`, otherwise `null`.
- `last_status_code` and `last_error`: the result of the latest attempt. `last_error` is `null` when the status code explains the failure, and holds a short reason such as `timeout`, `connection error`, `redirect not followed`, `target address not allowed` or `endpoint disabled` otherwise.

### GET /api/v1/deliveries/{id}

Any logged-in user. The delivery in the same shape as a list item, plus the endpoint's URL, the event type and every attempt ordered by `attempt_number`. The payload and the endpoint secret are not included.

Response `200`:

```json
{
  "id": "1d2c3b4a-6f5e-4d7c-8b9a-0f1e2d3c4b5a",
  "event_id": "7c1e2b3a-5d4f-4a6b-9c8d-0e1f2a3b4c5d",
  "endpoint_id": "4f0c2d8e-9b1a-4c7e-8d35-2a6b1e9f0c47",
  "status": "failed",
  "attempt_count": 2,
  "next_attempt_at": "2026-10-16T09:31:12Z",
  "locked_until": null,
  "last_status_code": 503,
  "last_error": null,
  "created_at": "2026-10-16T09:30:00.123456Z",
  "updated_at": "2026-10-16T09:30:52.418310Z",
  "endpoint_url": "https://hooks.example.com/webhook",
  "event_type": "order.created",
  "attempts": [
    {
      "attempt_number": 1,
      "status_code": null,
      "error": "timeout",
      "duration_ms": 10004,
      "response_excerpt": null,
      "attempted_at": "2026-10-16T09:30:01.002113Z"
    },
    {
      "attempt_number": 2,
      "status_code": 503,
      "error": null,
      "duration_ms": 41,
      "response_excerpt": "Service Unavailable",
      "attempted_at": "2026-10-16T09:30:52.418310Z"
    }
  ]
}
```

`response_excerpt` holds at most the first 1000 characters of the receiver's answer. A delivery that does not exist, or belongs to another user's endpoint when the caller is a member, returns `404`.

### POST /api/v1/deliveries/{id}/retry

Any logged-in user, for deliveries they may see. Requeues a `dead` or `failed` delivery so the worker sends it again. No request body.

The delivery is set to `pending` with `next_attempt_at` set to the current time, `locked_until` cleared and `attempt_count` reset to `0`, so it gets a fresh run of up to `HOOKLINE_MAX_ATTEMPTS` attempts. `last_status_code` and `last_error` keep the result of the latest attempt until the next one.

Response `200`: the delivery in the same shape as a list item.

| Situation | Status |
|---|---|
| The delivery is `dead` or `failed` and its endpoint is active | `200` |
| The delivery is `pending`, `in_progress` or `succeeded` | `409`, `"detail": "Only failed or dead deliveries can be retried."` |
| The endpoint is deactivated | `409`, `"detail": "The endpoint is disabled."` |
| The delivery does not exist, or belongs to another user's endpoint for a member | `404` |

The change is made with one `UPDATE ... WHERE status IN ('dead', 'failed')`. When two retries for the same delivery arrive at the same time, only one of them finds the delivery still `dead` or `failed`: one gets `200` and the other `409`.

#### Attempt numbers after a retry

Old attempts stay in the history; a retry never deletes or renumbers them. New attempts continue the numbering: the next `attempt_number` is always the highest existing number for that delivery plus one, never `attempt_count + 1`. For example, a delivery that became `dead` after attempts 1, 2 and 3 and is then retried gets attempt 4 next, with `attempt_count` 1. The `Hookline-Attempt` header sent to the receiver carries the same number. `attempt_count` alone decides when the delivery becomes `dead` again, and the retry delay starts again from `HOOKLINE_BACKOFF_BASE_SECONDS`.

### GET /api/v1/stats

Any logged-in user. Delivery statistics, computed in the database with `GROUP BY` and aggregate queries. Members get the numbers of their own endpoints and events, admins the numbers of all users.

Optional query parameter `endpoint_id` limits every number to one endpoint. For `events_received` this means events that have a delivery to that endpoint. A member who passes the ID of another user's endpoint, or an unknown ID, gets the empty result (zeros, `null` and no endpoints), the same as a list filter that matches nothing. An ID that is not a UUID returns `400`.

Response `200`:

```json
{
  "deliveries_by_status": {
    "pending": 1,
    "in_progress": 0,
    "succeeded": 40,
    "failed": 2,
    "dead": 3
  },
  "last_24_hours": {
    "events_received": 25,
    "deliveries_succeeded": 18,
    "deliveries_dead": 2,
    "success_rate": 0.9
  },
  "average_attempts_to_success": 1.33,
  "endpoints": [
    {
      "id": "3f6b1c2d-7e8f-4a9b-8c1d-2e3f4a5b6c7d",
      "url": "https://hooks.example.com/webhook",
      "succeeded": 18,
      "dead": 2
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `deliveries_by_status` | The number of deliveries in each of the five statuses, all time. A status without deliveries is `0`. |
| `last_24_hours.events_received` | Events created in the last 24 hours. |
| `last_24_hours.deliveries_succeeded`, `deliveries_dead` | Deliveries that are `succeeded` or `dead` and whose `updated_at` is in the last 24 hours, which is when they reached that status. |
| `last_24_hours.success_rate` | `deliveries_succeeded / (deliveries_succeeded + deliveries_dead)`, rounded to 4 decimals, or `null` when no delivery finished in the last 24 hours. |
| `average_attempts_to_success` | The average `attempt_count` of the deliveries that succeeded in the last 24 hours, rounded to 2 decimals, or `null` when there are none. After a manual retry `attempt_count` counts only the attempts since the retry. |
| `endpoints` | For each endpoint, the `succeeded` and `dead` counts of the last 24 hours, including endpoints with no deliveries. At most 50 endpoints, ordered by `dead` from high to low, then by `id`. |

"The last 24 hours" means from 24 hours before the request up to the request.

