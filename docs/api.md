# API

This document lists every route that exists so far, with request and response examples. The interactive OpenAPI docs are served at `/docs` and the schema at `/openapi.json`.

All application routes are under `/api/v1`. The health routes are not.

## Authentication

| Scheme | Header | Used by |
|---|---|---|
| JWT | `Authorization: Bearer <access token>` | People: admins and members |
| API key | `X-API-Key: hk_...` | Producer applications (used by event intake, which is added later) |

Access tokens come from `POST /api/v1/auth/login`. API keys are created with `POST /api/v1/api-keys`.

There are two roles:

- `admin`: may also manage users.
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
