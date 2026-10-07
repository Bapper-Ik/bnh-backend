# Endpoint integration notes

## CORE-001 — runtime

- `GET /api/v1/health/live`: public process liveness; no inputs or business permission; `200 {"status":"alive"}`.
- `GET /api/v1/health/ready`: public dependency readiness; no inputs or business permission; checks PostgreSQL connectivity, schema access. `200 {"status":"ready"}` or `503 {"status":"unavailable"}`. No database credentials or internals in responses.
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

Controlled operator recovery (`python -m scripts.issue_recovery`) remains available for active, already activated accounts. Screens 1–3 now use the reset/activation contracts below. Email requires separately configured Resend credentials and a verified sender; MFA is not implemented. Recovery and login share atomic business/audit transactions; persistence errors cannot be presented as success. Database token locks handle replay; these endpoints do not use client idempotency keys.

## IAM-001 / WEB-001 — screens 1–3 account links

- `POST /api/v1/auth/forgot-password`: public exact-Origin command `{email}`; 202 generic message for eligible, unknown, inactive and per-email throttled accounts. Up to three requests per email/hour and 100 globally/minute; global exhaustion returns 429. Requests within one minute reuse pending issuance without replacing it. Eligible pending accounts receive activation links. Disabled email returns 503 `SERVICE_UNAVAILABLE`.
- `POST /api/v1/auth/link-status`: public exact-Origin command `{token}`; returns `{purpose: "reset" | "activate"}` only. Invalid/expired/consumed/inactive/mismatched tokens return 400 `RECOVERY_INVALID`. It does not consume a link.
- `POST /api/v1/auth/invitations`: requires `staff:manage`, current session, exact Origin and CSRF; `{name,email}` only. Returns 201 `{identity_id,email,status:"invited"}` with no token/password. Creates a pending account without permissions or membership, or replaces an existing pending invitation. Activated/disabled accounts return 409 `INVITATION_CONFLICT`. Disabled email returns 503. Invitation UI belongs to screen 11, not a new screen.
- `POST /api/v1/auth/recover`: handles both reset and activation; consumes all outstanding account links, revokes all sessions, clears cookies, and makes an invited account usable. Pending accounts cannot sign in or act as eligible officeholders before activation. No automatic login or financial authority grant.
- Frontend `/login`, `/forgot-password`, `/recover`: shared grayscale account layout; generic check-email state, real unavailable/invalid/expired states, matching 12–1024 character passwords, show-password toggle and sign-in after success. Fragment token is cleared from URL and browser history metadata before validation; no browser storage persistence. Auth pages use no-store/no-referrer. Backend failure renders a safe retry state.
- Delivery: configure `MAIL_ENABLED`, `MAIL_FROM`, `RESEND_API_KEY`, `ACCOUNT_LINK_SECRET`, `FRONTEND_ORIGIN` per backend `docs/render.md`. Migration 0010 and an automatically started durable worker support retries with stable provider idempotency. Successful queueing/provider acceptance does not establish inbox delivery. Synthetic local capture tests do not send external mail.

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

## VEN-001 — `/api/v1/vendors`

Current entity membership scopes every request. Mutations require a writable account plus Origin/CSRF. Creator owns maintenance; explicit vendor:update and vendor:read_sensitive permissions allow other maintainers only within their membership scope. Ordinary staff/organisation administration does not confer these permissions. No public general permission editor is added.

- `GET ?entity_id=UUID&search=&limit=25&offset=0`: literal name search (wildcards escaped), limit 1–100, offset >=0; `{items:[VendorSummary],total,limit,offset}`. VendorSummary contains id, entity_id, version, name, registration_id, bank_details_state and verification=not_verified. It never includes bank values or beneficiary UUIDs, even for the creator.
- `POST`: `{entity_id,data}` creates a distinct vendor, returns 201 VendorView. Duplicate names remain distinct. Data: required name; optional contact_person, phones (max 10 nonblank strings), email (validated or null), address, registration_id, bank. Bank is null or the complete `{bank_name,account_number,account_name}` triple; do not convert account numbers to numbers.
- `GET /{id}`: VendorView extends summary with version_id, data, beneficiary_version_id, and server-calculated can_update. Show edit only when can_update is true; historic versions are not editable. data.bank/beneficiary_version_id are null when restricted; bank_details_state distinguishes restricted from genuinely unknown. Do not present either as verified. Cross-entity/absent vendor: 404 RESOURCE_NOT_AVAILABLE.
- `PATCH /{id}`: `{expected_version,data}` supplies the full desired next version, returning VendorView. A stale expected version yields 409 REVISION_CONFLICT; preserve edits and ask the user to reload/reconcile. Bank null explicitly records unavailable bank details in the new version. Old bank/contact versions remain unchanged.
- `GET /{id}/versions/{number}`: the same authorised/redacted view of a specific stored version, or 404. Store stable version identifiers in later requisition snapshots; never resolve a historical submission using the mutable vendor current-version pointer.

422 VALIDATION_FAILED covers malformed fields, partial bank data, unknown protected fields and blank names/phones. 403 ACCESS_DENIED covers missing membership/maintenance rights/read-only accounts. Audit/persistence failure is safe 503 with no successful mutation. There is no automated beneficiary validation, name-merging, payment execution, or vendor deletion. WEB-002 integrates lookup/capture with the requisition form and displays restricted/unknown states explicitly.


### Screen 10 delivered interface

`/vendors` provides a membership-scoped company selector, literal name search and pagination, with add/detail/edit in drawers. The server supplies edit eligibility and distinguishes unknown from restricted bank details. A 409 leaves form entries intact and blocks resubmission until the user reloads the latest record. Submitted requisition snapshots stay immutable when vendor masters change. Real browser verification and remaining release limits are recorded in task_done.md. Screen 6 will consume the reusable vendor lookup when its requisition journey is completed.

The latest scope is exactly the 14 templates in `ui_scrrens.md`, plus their dialogs/drawers/viewers and supporting backend. Backend feature completion alone does not complete its screens. The sign-in prerequisite currently opens Vendors; the remaining account-access, dashboard, requisition, Board, administration, audit and security journeys retain their own gates.
