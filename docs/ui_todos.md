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

## ORG-001 — `/api/v1/organisation`

All endpoints require a current staff session; mutations require trusted Origin and CSRF. Commands reject extra fields; all IDs are UUIDs. There is no public role/threshold editor. Configuration errors are 422 `VALIDATION_FAILED`; missing resources 404 `RESOURCE_NOT_AVAILABLE`; capability/self-grant denial 403 `ACCESS_DENIED`; ambiguous/replacement/Board-conflict cases 409 `AUTHORITY_ASSIGNMENT_BLOCKED`. Mandatory audit failure returns a safe persistence error. No file/evidence endpoint is added.

- `GET /entities` (`organisation:manage`): list `{id,name,code,active,kind}`; `POST /entities`: `{name,code?,kind?:holding|subsidiary}`, 201 entity. Missing codes receive stable generated IDs. `PATCH /entities/{id}`: `{name?,active?}`, returns directory entry. Deactivation makes current authority non-actionable without deleting history.
- `GET /departments?entity_id=...` (`organisation:manage`): scoped company directory entries `{id,name,code,active}`; `POST /departments`: `{entity_id,name,code?}`, 201; `PATCH /departments/{id}`: `{name?,active?}`. Duplicate company/name or company/code is rejected on creation.
- `GET /staff` (`staff:manage`): safe `{id,name,email,active}` entries, limited to 200. `POST /staff`: controlled provisioning `{name,email,initial_password}`, 201 staff entry with no granted role. `PATCH /staff/{identity_id}`: `{name?,active?}`. Disabled accounts lose all sessions; existing signatures/references remain.
- `GET /memberships`: current user's active company/department choices `{entity_id,entity_name,department_id,department_name}` only. `POST /memberships` (`organisation:manage`): `{identity_id,entity_id,department_id}` creates or transfers membership, returning that shape with 201; an operator cannot transfer themselves, and an active HOD must be revoked first. `PATCH /memberships/{identity_id}/{entity_id}`: `{active}`; same protected capability. No office is automatically created or reassigned.
- `GET /offices?entity_id=...` (`office_assignment:manage`): returns current and historical appointment records `{id,identity_id,entity_id,department_id,role,active,valid_from,valid_until,authorisation_reference}`. Dates alone do not imply active status.
- `POST /offices` (same permission): `{identity_id,entity_id,department_id?,role,authorisation_reference,valid_from?,valid_until?}`. Roles: hod/chief_of_staff/md/secretary/chairman. HOD department must match membership; other offices omit it. Dates require timezone offsets; end must follow start. Current active record must be revoked before replacement. Concurrent operators cannot create an ambiguous office. Returns 201 appointment.
- `POST /offices/{id}/revoke`: no body, returns inactive appointment; repeated revoke is idempotent and does not duplicate success audit. Original scheduled dates remain, with revocation timestamp in audit.

Configuration APIs serialise sensitive account/appointment changes with database row/scope locks and database uniqueness. They do not accept financial status, approval authority overrides, or client-selected permissions. Administration UI is WEB-001; do not imply that staff configuration confers approval authority. Historical request text remains the submitted snapshot even when the directory changes.

## IAM-002 — `/api/v1/access`

Every endpoint requires a current individual session. Identity, office, entity and reviewer scope come from the server. GETs are read-only; the review-grant mutation also requires exact Origin and CSRF. Unknown/unauthorised record IDs consistently return 404 RESOURCE_NOT_AVAILABLE. Mutating eligibility failures return 403 ACCESS_DENIED; self-approval is 409 SELF_APPROVAL_PROHIBITED. Never treat a client-edited capability list as authorisation.

- `GET /requisitions?limit=25&offset=0`: scope before counting/pagination, limit 1–100, offset >=0; returns `{items:[{requisition_id,actions,read_only}],total,limit,offset}`. No bank data/content is returned. Actions are safe current eligibility hints; every later mutation rechecks them.
- `GET /requisitions/{id}`: same capability shape for an accessible record. More senior officers and technical admins receive no implicit access.
- `GET /attachments/{id}`: authorised metadata `{id,requisition_id,filename,media_type,validation_state}` only. No storage key, object version, signed URL, public upload, or binary transfer is exposed. Private Board evidence requires a current Secretary/Chairman role on the relevant Board case. File validation/transfer arrives with EVD-001.
- `POST /review-grants`: `office_assignment:manage`; `{identity_id,entity_id,active?:true}`. Cannot self-grant; target must be active; revoke financial appointments first. Activating the grant makes the account read-only and grants visibility only in the explicit entity. Revocation keeps the account read-only. Identical retries do not duplicate change events. Returns the grant input shape. 422 for unavailable directory configuration, 409 for conflicting financial appointments; no financial capabilities are accepted in the body.

Backend consumers must use `request_scope` for lists/counts, `get_scoped_request` for details, `require_action` for transitions, and `require_attachment` before file access. `project_content` returns the safe snapshot and `redacted_fields`; display redacted bank data as restricted, not unknown or verified. Signature capture also requires its exact business intent to be authorised; a generic signature capability never permits signing as another person. There is no permission-management editor or financial override endpoint.
