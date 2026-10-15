# Security

This document describes how Hookline protects passwords, tokens and API keys, and how roles are checked. Later sections are added as the matching features are built.

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
- The `get_api_key_owner` dependency hashes the received key, loads the key together with its user and returns `401` with `WWW-Authenticate: ApiKey` when the header is missing, the key is unknown or revoked, or its owner is deactivated.
- `last_used_at` is updated at most once a minute per key, so a busy producer does not cause a database write on every request.
- Revoking a key (`DELETE /api/v1/api-keys/{id}`) sets `revoked_at`; the key stops working at once. Keys of other users return `404`, so their IDs cannot be probed.

## Clock

The current time comes from the FastAPI dependency `get_now` in `src/hookline/clock.py`, which returns `datetime.now(UTC)`. Tests replace it to check expiry without waiting.

## Logging

Passwords, password hashes, access tokens, refresh tokens, API keys and all of their hashes are never written to the logs. Log lines about authentication only contain the user ID, for example when refresh token reuse is detected. A test checks the captured logs of a full login, refresh, reuse and logout flow for each of these values, and another test does the same for creating and revoking an API key.
