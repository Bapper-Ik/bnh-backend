# Endpoint integration notes

## CORE-001 — runtime

- `GET /api/v1/health/live`: public process liveness; no inputs or business permission; `200 {"status":"alive"}`.
- `GET /api/v1/health/ready`: public dependency readiness; no inputs or business permission; checks PostgreSQL connectivity, schema availability and restricted runtime privileges. `200 {"status":"ready"}` or `503 {"status":"unavailable"}`. No database credentials or internals in responses.
- Both return `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and a generated `X-Request-ID`. No mutation, pagination, expected version or idempotency key applies.
- Monitoring should retry unavailable readiness. Liveness/readiness do not establish authentication, business feature completion, or human acceptance.
- No staff-facing UI is required by this foundation feature. OpenAPI is exposed through FastAPI's `/openapi.json` and `/docs`.

## AUD-001 — internal event infrastructure

No public endpoint is added. Business services call `record_event` inside their transaction, using a registered action and trusted actor/resource/scope identifiers. `event_key` supplies database uniqueness for a business operation; callers separately provide API payload binding/replay behaviour. `AuditDetails` rejects unknown fields and arbitrary digest/changed-field content. Mandatory event or archive-intent failure must roll back the action and return a safe persistence error; never show successful approval after that failure.

`audited_transaction` supplies an internal rollback-plus-denial-record path for expected `DomainError` failures. It does not swallow a failed denial audit. History UI and archive delivery status are separate later features; no audit mutation UI is authorised.

## IAM-001 — `/api/v1/auth`

All commands reject extra fields. Mutations require a configured exact `Origin`; session-authenticated mutations additionally require `X-CSRF-Token` matching the readable `custodian_csrf` cookie. Session tokens remain HttpOnly. Never put either password or recovery token in localStorage or logs. Safe errors contain `code`, `message`, and `request_id` (422 can include field errors). No pagination or client-selected roles are accepted.

- `POST /login`: `{email,password}`; returns `UserView {id,account_id,name,email,permissions}` and two cookies. Invalid/disabled credentials: 401 `AUTHENTICATION_REQUIRED`; persisted throttling: 429 `RATE_LIMITED`. Successful session lifetime defaults to eight hours. UI redirects to workspace only after success.
- `GET /me`: current individual `UserView`, 401 for missing/expired/revoked/disabled access. UI signs out on 401. Permissions are display hints; backend remains authoritative.
- `POST /logout`: no body; revoke current session, clear cookies, return `{message}`.
- `POST /reauthenticate`: `{password}`; updates only this session's server authentication timestamp after password verification. Throttles independently of sign-in; errors never refresh authentication. Signing requires this fresh context.
- `POST /accounts`: protected `staff:manage`; `{name,email,initial_password}` (password 12–1024 chars). Returns 201 `UserView` with empty permissions. Existing email/invalid name: 422; unauthorised operator: 403. No office/membership assignment here.
- `POST /sessions/revoke`: no body; revoke all sessions of the current account, clear cookies, return `{message}` and return UI to sign-in.
- `POST /accounts/{identity_id}/revoke-sessions`: `staff:manage`; trusted UUID path, no body; 404 when absent. Returns `{message}`. This grants no financial role.
- `POST /recover`: no existing session required; `{token,password}`; validate token/expiry/current active account atomically, consume all account recovery tokens, update password, revoke sessions, return `{message}`. Invalid, expired, replaced, or used token: 400 `RECOVERY_INVALID` with one generic message. Concurrent redemption permits one success. UI should read the token from the URL fragment, clear it from browser history, submit once, and direct the user to sign in. Tokens must never be sent in URLs/query strings to the API.

Recovery issuance is a trusted operator command (`python -m scripts.issue_recovery`), not public account discovery. There is no configured email/MFA service to advertise. WEB-001 supplies the browser recovery screen. Recovery and login share atomic business/audit transactions; persistence errors cannot be presented as success. Database token locks handle replay; these endpoints do not use client idempotency keys.
