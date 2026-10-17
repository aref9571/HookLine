# Security

This document describes how Hookline protects passwords, tokens, API keys and endpoint secrets, how roles are checked, how subscriber URLs are checked against server-side request forgery and how deliveries are signed. Later sections are added as the matching features are built.

## Passwords

- Passwords are hashed with bcrypt through the `bcrypt` package (`src/hookline/auth/passwords.py`). Each hash has its own random salt and uses the library's default cost factor of 12. Only the hash is stored, in `users.password_hash`.
- A password must be 12 to 128 characters long. bcrypt only looks at the first 72 bytes of its input, so a password whose UTF-8 encoding is longer than 72 bytes is rejected instead of being silently cut. Both rules live in the `Password` type in `src/hookline/auth/schemas.py`, so every place that accepts a new password applies them the same way. A password with many non-ASCII characters can reach the 72-byte limit before 128 characters.
- `verify_password` returns `False` for input longer than 72 bytes instead of raising an error, so a login with such a password is simply a failed login.
- Login looks up the user by lower-case email. If no user has that email, it still checks the password against a fixed dummy bcrypt hash, so a request for an unknown email takes about as long as one for a known email. Wrong password, unknown email and deactivated account all return the same `401` body, `"Invalid email or password."`, so the response does not reveal which emails exist.
- Passwords are never logged and never returned by the API. The first admin is created with `python -m hookline.cli create-admin --email ...`, which reads the password from `HOOKLINE_ADMIN_PASSWORD` or asks for it twice with a hidden prompt. It never accepts a password as a command-line argument, because arguments are visible in the process list and the shell history.

## Access tokens

- An access token is a JWT signed with HS256 and the secret in `HOOKLINE_JWT_SECRET` (`src/hookline/auth/tokens.py`). It contains `sub` (the user ID), `role`, `type` (`"access"`), `iat`, `exp` and `iss` (`"hookline"`).
- It is valid for `HOOKLINE_ACCESS_TOKEN_MINUTES` minutes, 15 by default. It is sent as `Authorization: Bearer <token>`.
- Decoding accepts only the `HS256` algorithm, so tokens with `alg` set to `none` or to any other algorithm are rejected. It also requires every claim listed above and checks the expiry, the issuer and that `type` is `"access"`. Any problem results in `401` with a `WWW-Authenticate: Bearer` header.
- The application refuses to start if `HOOKLINE_JWT_SECRET` is missing or shorter than 32 characters. The secret is held as a pydantic `SecretStr`, so it is not shown when the settings are printed or when a settings validation error is reported.
- On each request the user is loaded from the database again. A user who was deactivated or deleted gets `401` even while their access token has not expired yet.
- The expiry of access tokens is checked by PyJWT against the system clock. The clock dependency described below is used when tokens are created and for refresh tokens.

## Refresh tokens

- A refresh token is a random string made with `secrets.token_urlsafe(32)` (32 random bytes). It is not a JWT. Only its SHA-256 hex digest is stored, in `refresh_tokens.token_hash`, so a copy of the database does not contain usable tokens. SHA-256 without salt is enough here because the token itself is long and random, unlike a password.
- It is valid for `HOOKLINE_REFRESH_TOKEN_DAYS` days, 7 by default.
- `POST /api/v1/auth/refresh` rotates the token: it locks the stored row with `SELECT ... FOR UPDATE`, checks that it exists, is not revoked and has not expired, marks it revoked and stores a new one, all in one transaction. The client receives a new access token and a new refresh token. The row lock means that two requests with the same token cannot both succeed.
- Reuse detection: if a token that was already revoked is presented again, someone may have copied it. Hookline then revokes every refresh token of that user and returns `401`, so both the attacker and the real user have to log in again.
- `POST /api/v1/auth/logout` revokes the given refresh token and always returns `204`, also when the token is unknown or already revoked.
- Refresh tokens of deactivated users are rejected.

## Roles

- Every user has the role `admin` or `member`. Admin-only routes use the `require_admin` dependency in `src/hookline/auth/dependencies.py`, which builds on `get_current_user` and returns `403` for members.
- The role is read from the user row loaded on each request, not from the `role` claim in the access token. A user who is demoted or promoted gets the new permissions at once, without waiting for the access token to expire.
- An admin cannot deactivate their own account or remove their own admin role (`409`), so an admin cannot lock themselves out by mistake.
- Deactivating a user revokes all of their refresh tokens in the same transaction.

## API keys

- Producer applications authenticate with an API key in the `X-API-Key` header. A key is `hk_` followed by `secrets.token_urlsafe(32)`, so it contains 32 random bytes (256 bits).
- The full key is returned once, when it is created. Hookline stores only its SHA-256 hex digest in `api_keys.key_hash`, plus the first 12 characters in `api_keys.prefix`, so a user can recognise a key in the list without the full key being stored.
- SHA-256 is enough here and bcrypt is not needed. bcrypt is slow on purpose so that guessing a human password from its hash takes a long time. An API key is not chosen by a person: it is 256 bits of random data, so no list of likely values exists and trying every possible key is not feasible, even with a fast hash. A fast hash also matters because the key is checked on every producer request, and it allows looking the key up directly by its hash through the unique index.
- The `get_current_api_key` dependency hashes the received key, loads the key together with its user and returns `401` with `WWW-Authenticate: ApiKey` when the header is missing, the key is unknown or revoked, or its owner is deactivated.
- `last_used_at` is updated at most once a minute per key, so a busy producer does not cause a database write on every request.
- Revoking a key (`DELETE /api/v1/api-keys/{id}`) sets `revoked_at`; the key stops working at once. Keys of other users return `404`, so their IDs cannot be probed.

## Endpoint signing secrets

- Each endpoint gets a signing secret `whsec_` followed by `secrets.token_urlsafe(32)` (32 random bytes). Deliveries are signed with it with HMAC-SHA256, as described in [Verifying signatures](#verifying-signatures).
- The secret is returned only by `POST /api/v1/endpoints` and `POST /api/v1/endpoints/{id}/rotate-secret`. No other route returns it, and it is never logged.
- Hookline must read the secret to sign each delivery, so it cannot be stored as a hash like API keys. It is stored as plain text in `endpoints.secret`. Anyone with read access to the database can read the secrets. Encrypting them at rest with a key kept outside the database is possible future work.
- Rotating replaces the secret at once; the old secret stops being used immediately.

## Server-side request forgery (SSRF)

Users choose the URLs that Hookline sends requests to. Without checks, a user could make Hookline call services that are only reachable from inside its network, such as the database, an admin interface or the cloud metadata service at `169.254.169.254`. `validate_target_url` in `src/hookline/endpoints/url_safety.py` checks every endpoint URL when an endpoint is created and when its URL is changed. A rejected URL returns `400` with the reason in `errors`, for the field `url`.

Rules for the URL itself:

- The scheme must be `https`. When `HOOKLINE_REQUIRE_HTTPS_TARGETS` is `false`, `http` is allowed too.
- A host is required.
- No username or password in the URL (`https://user:pass@host`).
- No fragment (`#...`), because a fragment is never sent to the server and is most likely a mistake.
- At most 2048 characters, and the port must be valid.

Rules for the address, unless `HOOKLINE_ALLOW_PRIVATE_TARGETS` is `true`:

- The name `localhost` and any name ending in `.localhost` are rejected without a DNS lookup.
- An IP address in the URL is checked directly. A host name is resolved with `socket.getaddrinfo`, and the URL is rejected if **any** of the returned addresses is private, loopback, link-local, multicast, reserved or unspecified (checked with the properties of `ipaddress.ip_address`). An IPv6 address that wraps an IPv4 address (`::ffff:10.0.0.5`) is checked as the IPv4 address.
- A host name that does not resolve is rejected.

`HOOKLINE_ALLOW_PRIVATE_TARGETS=true` is meant only for tests and the local demo, where the receiver runs on the same machine. It skips the address rules, but the URL rules still apply.

The resolver is passed in as a function (the FastAPI dependency `get_resolver`, `socket.getaddrinfo` by default), so tests use a fake resolver and never do real DNS lookups.

Limits of these checks:

- DNS can change after the check. A host name can resolve to a public address when the endpoint is saved and to a private address later (DNS rebinding). The same check runs again right before each delivery is sent (`send_delivery` in `src/hookline/deliveries/sender.py`), which makes this much harder, but a short time remains between that check and the moment the HTTP client connects and resolves the name again. Closing that gap fully would mean connecting to the checked address directly.
- Redirects are a separate path to an internal address, so the sender never follows redirects. A `3xx` response counts as a failed attempt with the error `redirect not followed`.
- Only the address ranges known to Python's `ipaddress` module are blocked. Addresses that are public on the internet but reachable only inside a particular network (for example a company's own public range behind a firewall) are not detected.

## Verifying signatures

Every delivery is a `POST` with a JSON body and these headers:

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `User-Agent` | `Hookline/<version>` |
| `Hookline-Event-Id` | The event ID |
| `Hookline-Event-Type` | The event type |
| `Hookline-Attempt` | The attempt number, starting at 1 |
| `Hookline-Signature` | `t=<timestamp>,v1=<signature>` |

The body is compact JSON (no spaces) with the fields `id`, `type`, `created_at` and `data`, where `data` is the event payload:

```json
{"id":"0b6f5c3e-8f7a-4f2e-9a51-3c2d1e0f9a87","type":"order.created","created_at":"2026-10-17T11:59:30+00:00","data":{"order_id":42}}
```

The body is encoded once and the same bytes are signed and sent, so the receiver must check the signature against the raw bytes it received, before parsing the JSON. Parsing and encoding the JSON again can change spaces or key order and break the signature.

How the signature is made (`src/hookline/deliveries/signing.py`):

1. `timestamp` is the time of sending in whole seconds since 1970-01-01 UTC.
2. The signed message is the timestamp as decimal digits, a dot, and then the raw body bytes: `f"{timestamp}.".encode() + body`.
3. `signature` is the lower-case hex HMAC-SHA256 of that message, with the endpoint's signing secret (the full string including `whsec_`, encoded as UTF-8) as the key.
4. The header is `Hookline-Signature: t=<timestamp>,v1=<signature>`.

How a receiver verifies it:

1. Split the header at commas into `name=value` pairs and read `t` and `v1`. Reject the request if either is missing or `t` is not a whole number.
2. Reject the request if `t` is more than 300 seconds away from the receiver's current time. Including the timestamp in the signed message means an attacker cannot change it, and the time limit means a captured request cannot be replayed later.
3. Compute the HMAC-SHA256 of `f"{t}.".encode() + body` with the secret and compare it with `v1` using a constant-time comparison (`hmac.compare_digest` in Python), so the comparison time does not reveal how many characters matched.

`verify_signature` in `src/hookline/deliveries/signing.py` does exactly these steps. Hookline does not call it itself; it exists so that the receiver side is written down as code and tested. The README has a short Python example for receivers that follows the same steps.

Other points for receivers:

- The `v1` prefix names the signature scheme, so a different scheme could be added later without breaking existing receivers.
- A delivery can arrive more than once (for example after a timeout on Hookline's side), with the same `Hookline-Event-Id` and a higher `Hookline-Attempt`. Receivers should use the event ID to ignore duplicates.
- After the secret is rotated, new deliveries are signed with the new secret only.

## Request and payload size

- `BodySizeLimitMiddleware` in `src/hookline/body_limit.py` rejects any request body over `HOOKLINE_MAX_BODY_BYTES` (default 256 KiB) with `413`. A declared `Content-Length` over the limit is rejected before the body is read. A body without a declared length (chunked) is counted while it is read and rejected as soon as it passes the limit, so a client cannot make the API hold an unlimited body in memory.
- The event payload is limited separately to `HOOKLINE_MAX_PAYLOAD_BYTES` (default 64 KiB), measured as compact JSON in UTF-8, because the payload is stored and sent to every matching endpoint.

## Clock

The current time comes from the FastAPI dependency `get_now` in `src/hookline/clock.py`, which returns `datetime.now(UTC)`. Tests replace it to check expiry without waiting.

## Logging

Passwords, password hashes, access tokens, refresh tokens, API keys and all of their hashes are never written to the logs. Log lines about authentication only contain the user ID, for example when refresh token reuse is detected. A test checks the captured logs of a full login, refresh, reuse and logout flow for each of these values, another test does the same for creating and revoking an API key, and a third one checks that endpoint secrets and endpoint URLs are not logged when an endpoint is created or its secret is rotated. Endpoint log lines only contain the endpoint ID and the user ID. Event payloads are never logged; event log lines only contain the event ID and the number of deliveries, and a test checks that neither the payload nor the API key appears in the logs of an intake request. The sender never logs the target URL, the secret, the signature or the body; when a target address is not allowed it logs only the event ID.
