# Custodian backend

FastAPI + PostgreSQL backend for BNH requisitions. Approval records represent authorisation, never payment.

Development branch: `dev`. Each feature is verified, committed, and pushed before the next begins.

The delivered assembly is `app.main:create_app`: runtime, accounts, organisation, scoped access, Vendors, staff administration and requisition creation/submission with private documents. Apply migrations through 0015. Individual approvals, the assigned inbox, returned-request correction and immutable revision/document viewing are delivered. The Board workspace records formal meeting outcomes with independent Secretary and Chairman signatures, correction history and conditional/deferred holds. See [Render setup](docs/render.md) for startup migrations and email configuration.

## Development setup

1. Install Python 3.12 and uv, then run `uv sync --locked`.
2. Configure the ignored `.env` using `.env.example`. Never commit database credentials.
3. Set `DATABASE_URL` to the development database connection with schema-changing permissions. For a new database, run `uv run python -m scripts.provision_database` once to prepare the dedicated `custodian` schema and the compatibility role referenced by historical migrations. It preserves existing roles/credentials and does not rewrite `.env`. Production uses a different database and its own `DATABASE_URL`.
4. Run `uv run alembic upgrade head`.
5. Run `uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000`.

The supplied Render development database is shared with existing software. All Custodian tables, including its Alembic version table, live in the **custodian schema**. Existing public tables and migration history are not modified. As explicitly approved, migrations and the application use the same `DATABASE_URL` and may share schema-owner privileges. Development and production must point to separate databases; switching `ENVIRONMENT` alone does not select a database. Standard `postgresql://`, `postgres://` and `postgresql+asyncpg://` URLs are accepted.

TLS is enabled by `DATABASE_SSL=true` for Render. Local isolated tests explicitly disable TLS. Production requires secure cookies and explicit HTTPS origins. Connection strings and internal errors are never included in health responses.

## Isolated tests

Install PostgreSQL 16 binaries (or set `PG_BIN`), then run:

```sh
python3 scripts/dev_database.py
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

The helper creates an isolated cluster in ignored `.state/test`, listening only on loopback port 55439, and random credentials in ignored `.env.test`. It never resets an existing database. Tests require a database name ending in `_test` and migrate it twice. The test-only `TEST_DATABASE_OWNER_URL` creates/migrates disposable local databases; it is not a deployment setting. Most existing security regressions still exercise the restricted compatibility role, while additional tests start the application with the same owner connection used for migrations and verify history triggers. They never fall back to the Render development database. Stop the isolated cluster with:

```sh
/usr/lib/postgresql/16/bin/pg_ctl -D .state/test/postgres stop
```

## Schema changes and recovery

Migrations and the service both use `DATABASE_URL`. The old `MIGRATION_DATABASE_URL` setting is ignored and can be removed. Only reviewed forward migrations are supported. Do not run destructive downgrade/reset commands against shared databases. Back up the Custodian schema and evidence store before release changes; restore into a separate database and verify before any recovery cutover. A backup/restore drill and protected evidence archive are required release work, not currently claimed.

History triggers continue to reject ordinary update/delete/truncate statements. Because the application now uses schema-changing credentials, those credentials can alter or disable the triggers; runtime privilege isolation is no longer claimed. Keep the single database credential private in each environment.

## Current API

- `GET /api/v1/health/live`: process liveness.
- `GET /api/v1/health/ready`: database connectivity and schema access; 503 if unavailable.
- `/docs` and `/openapi.json`: generated API reference.

Business capabilities are tracked in the shared specification; infrastructure readiness is not staff acceptance.

## Accounts and recovery

Run the delivered authentication API with `uv run uvicorn app.auth_app:create_app --factory --host 127.0.0.1 --port 8000`. Create the first configuration operator with `uv run python -m scripts.create_operator`; it prompts privately for a password and refuses a second bootstrap. Approved staff managers provision individual accounts through `POST /api/v1/auth/accounts`; the new account receives no financial appointment.

Recovery uses a controlled operator handoff. After independently verifying the staff member, run `uv run python -m scripts.issue_recovery`. The 30-minute, single-use link is saved in a private mode-0600 file under ignored `.state/recovery`, never printed. Transfer it using your approved private channel, then delete the file. The same browser reset screen and `POST /api/v1/auth/recover` redeem this link. Pending invitations use the email activation flow instead. MFA is not implemented.

Migration 0006 adds recovery tokens after the already-applied 0004/0005 history. Their schemas are preserved for compatibility; organisation and requisition feature completion is tracked independently. Migrate before running the authentication API. The Render development database was separately verified at 0009; this release adds 0010, applied by the startup script before Uvicorn.

## Organisation configuration

`uv run uvicorn app.org_app:create_app --factory --host 127.0.0.1 --port 8000` runs the delivered runtime, accounts and organisation APIs. Apply migration 0007 first. Approved operators configure real entities, departments, memberships and individual appointments via the protected APIs documented in `docs/ui_todos.md`. No real officeholders are seeded. Appointments have explicit per-entity scope; no automatic group-wide inheritance is inferred. Revoke an existing active appointment before replacement or HOD transfer; historical records remain.

## Record scope and reviewers

Run the delivered scope APIs with `uv run uvicorn app.access_app:create_app --factory --host 127.0.0.1 --port 8000` after migration 0008. The organisation API may explicitly grant entity review access to a different individual through `/api/v1/access/review-grants`. Review accounts are read-only and cannot simultaneously hold an active financial office. Capability and attachment metadata endpoints reveal no storage credentials, public file URLs, or bank details. Upload/download and complete business transitions retain their own feature gates.

## Vendor records

`uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000` adds vendor capture/lookup/version APIs after migration 0009. Vendor creators maintain their own records within active entity membership; a separately authorised maintainer requires vendor:update and vendor:read_sensitive. These fixed grants are not implied by technical administration and are not exposed through a general public permission editor. Bank data is excluded from lookup lists, and every historical version is append-only. No actual vendors or bank details are seeded from the supplied screenshots.

## Browser account access (screens 1–3)

Sign-in, forgot-password and the shared reset/activation page use the real account APIs. Protected invitations create pending named accounts without granting membership or permissions. Pending accounts cannot sign in or act as officeholders. Reset/activation consumes all outstanding links, clears current cookies and revokes existing sessions. Public reset requests return the same response for known and unknown emails and have persisted request limits.

Migration 0010 adds activation state and durable email jobs. Email defaults off; configure Resend and the account-link secret using [the deployment guide](docs/render.md), then enable it. The in-process worker starts automatically and retries with provider idempotency. Local tests capture synthetic mail and mock only the external provider transport; live sender verification and inbox delivery remain deployment checks.

## Staff & Access management (screen 11)

`/api/v1/staff` supplies a protected searchable/paginated directory, account status, memberships and appointment history. The Svelte `/staff` screen uses server-authorised actions and versioned mutation endpoints. An administrator cannot change their own status, membership or appointments through this screen. Department changes require organisation:manage; appointments require office_assignment:manage. Account administration does not grant financial authority, and invitations grant no membership or permissions.

The current release uses app.main and migrations through 0015; staff administration itself introduced no migration beyond 0010. Configure real companies/departments on Organisation & Authority (screen 12) before assigning membership. Email-disabled deployments explicitly show that invitations are unavailable; existing staff management remains usable. Endpoint details are in [integration notes](docs/ui_todos.md).


## Organisation & Authority (screen 12)

`GET /api/v1/organisation/workspace?entity_id=...` supplies the protected company catalogue, selected company's departments and named appointments, current eligibility reasons, missing/conflicting appointments and read-only approval matrix. Requires organisation:manage. The Svelte `/organisation` screen provides Companies, Departments, Officeholders and Approval matrix tabs; create/edit/status actions use drawers. Office assignment stays in Staff & Access with its separate capability.

New workspace PATCH endpoints require expected_version, detect stale changes and reject protected fields. Existing create APIs are reused. Renames detect duplicate names before database writes; company/department scope locks serialize competing updates. Disabled companies cannot receive new departments or re-enabled departments. Disabling retains memberships, appointments and history; re-enabling can restore eligibility, subject to current account, membership and dates. No new migration or environment variable is required. Integration details are in docs/ui_todos.md.

## Board resolution release (BRD-001–003)

Deploy the backend before the matching frontend. The existing Docker startup script runs migration `0013` using the environment's `DATABASE_URL`. No new environment variables are needed; formal Board evidence uses the existing private Cloudinary configuration. Configure a distinct active Secretary and Chairman for the entity in Organisation & Authority before submitting a Board-routed request.

My Tasks includes the Secretary's recording/correction tasks and the Chairman's submitted records. The workspace is `/requisitions/{id}/board`. Only the originally assigned, currently eligible Secretary and Chairman can access it or its formal evidence. Missing/replaced appointments block actions without substitution. Ordinary requesters see the permitted requisition status/history; technical administration does not confer Board access.

The Secretary saves actual meeting details, uploads formal evidence and signs. The Chairman confirms that precise outcome or signs a return with a reason. APPROVE, REJECT, DEFER and CONDITIONAL_APPROVE retain distinct meanings. Conditional/deferred requests remain held during later recording and Chairman review; a later actual resolution needs both fresh signatures. Records returned to the Secretary create successor resolution versions without reopening the requisition.

Schema `0013` protects submitted resolution rows and Chairman decisions against ordinary updates/deletes, and retains evidence digests and both signature records. The schema-owner trust boundary described above still applies. Audit and requisition notification intent commit atomically; notification delivery is provided by NOT-001; protected external archiving remains separate work. Document malware scanning remains deferred by the owner.


## Request history and Audit Log (HIS-001)

Deploy the backend first; Docker startup applies migration `0014` (scoped audit/request indexes) before Uvicorn. Then deploy the frontend from `dev`. No new environment variables are needed. Existing Dockerfiles include the new code and migration.

Requisitions and My Tasks support requester, department, company, vendor, status, inclusive Lagos creation dates and own-request filters. Details show the pending actor or assignment blocker and a paginated chronological timeline with signed-revision links. Board meeting dates, record creation and signatures are separate; Board record/evidence references remain restricted to the assigned eligible Secretary/Chairman. Export timestamps appear only when an actual export feature exists; none are fabricated here.

Screen 13 is `/audit`. It requires explicit `audit:read` and applies existing request/evidence scope before filtering or counting. Technical administrators do not automatically receive Audit Log access or financial decision authority. The screen shows safe action, actor identity/current name, time, outcome and permitted references, never raw audit JSON, storage credentials or signature strokes. Removed documents retain audit entries but no download link. Audit/history read-access events are recorded for the archive but excluded from the paginated activity feed to prevent reads from growing their own result set. Archive delivery remains separate work.

For an authorised company-wide auditor, first provision and activate an individual staff account. A trusted configuration operator can run `python -m scripts.configure_audit_reviewer` in the backend environment and enter the existing email, company UUID and `grant`. The command grants `audit:read`, makes the account read-only, records the change and grants review only for that company. It rejects accounts with active financial appointments. Repeat for another explicitly authorised company if needed. Enter `revoke` to remove that company scope; the last scope removal also removes `audit:read`, and the account remains read-only. No production account is modified by deployment or tests. This controlled command is not a public API or a financial-role selector.

Revocation takes effect on the next backend request. A review grant never grants confidential Board workspace/document access or unrestricted bank access. Paging uses a fixed upper audit timestamp; a refresh starts a new snapshot. General audit actor names follow current profiles; signed timeline names come from preserved evidence. See `docs/ui_todos.md` for API envelopes and filters.


## Notifications (NOT-001)

The workspace header opens a persistent notification drawer. Submission/resubmission, individual approval/rejection/return, Secretary/Chairman handoffs and confirmed Board outcomes produce recipient-scoped alerts. Reading an alert never signs a decision. Completed or invalidated task alerts disappear from the actionable list; requester updates remain available as history and link to the current request.

Migration `0015` adds notifications and retry scheduling. The application materialises existing durable outbox jobs even when email is disabled. Email uses the existing Resend configuration and authenticated application links, without bank details, private evidence or signing payloads. Frozen delivery envelopes, leases, provider idempotency keys and bounded retries survive restarts. No additional service or environment variable is required. See [notification operations](docs/render.md#notification-delivery-not-001) for backlog, retry and deployment limitations.

Authorised deployment operators can run `python -m scripts.notification_status` for aggregate queue states, attempts, safe failure codes and scheduling timestamps. It prints no addresses, message contents or staff/request identifiers and does not mutate jobs.

### WEB-002 dashboard

`GET /api/v1/dashboard` returns current-scope status and own-request counts, up to five latest requisitions, up to five currently assigned tasks, and ten recent permitted business events. Counts and activity use the same request visibility policy as the lists; administration alone grants no financial visibility. Private Board activity requires the original currently eligible Secretary/Chairman. Read-only reviewers receive only their authorised scope, without creation or approval shortcuts. Responses are not cached.

The shared screen at `/` is now the post-login landing page. Deploy this backend before its matching frontend. There is no new migration or environment setting; existing Dockerfiles include the dashboard module. Real request transitions remain on the existing requisition and Board screens.

### My Account & Security (screen 14)

`GET /api/v1/auth/profile` returns the caller's read-only account, company/department memberships and currently eligible office appointments. `GET /api/v1/auth/sessions?limit=20&offset=0` lists only their unexpired, unrevoked sessions, with a current-session flag and server creation/expiry times; no session/CSRF hashes, IP addresses or inferred device descriptions are exposed. Both reads are `no-store`. There is no self-service profile, department or authority editing endpoint.

`POST /api/v1/auth/password` requires `current_password` and a different `new_password` of 12–1024 characters, uses persistent five-failure/15-minute throttling and atomically changes the Argon2 hash, consumes outstanding recovery links, revokes all sessions and records audit events. The caller signs in again. `POST /api/v1/auth/sessions/{id}/revoke`, `/auth/sessions/revoke-others`, and the existing `/auth/sessions/revoke` end one, other, or all own sessions. Mutations require the existing trusted Origin and CSRF cookie/header. Read-only reviewers can secure their own accounts. Session validation rechecks revocation after obtaining the account lock, including requests that waited for another transaction. An audit failure rolls back the security change.

No new migration, environment variable or identity provider is required. Deploy backend before frontend using the existing Dockerfiles. MFA remains unimplemented; this screen does not present an inactive MFA control as working. Device/IP tracking is not collected or claimed.

### Administrator oversight (IAM-002)

An active, activated, writable account holding all three permissions `staff:manage`, `organisation:manage` and `office_assignment:manage` can view requisitions and vendor records across BNH. This applies to current administrators after deployment, including accounts with no department membership; no database update or new environment setting is needed. Partial administrators and read-only reviewers retain their existing scope.

Requisition search, counts, dashboard, current/signed details and public history include this view. Financial actions and My Tasks still require the original assigned office. Oversight-only responses redact structured bank fields unless `vendor:read_sensitive` is explicitly granted; they expose no supporting-document downloads or export capability, and Board workspaces/evidence remain private. Audit Log scope and permission are unchanged. Actual requester and assigned-office access is preserved independently.

`GET /api/v1/vendors/companies` supplies the permitted read catalogue and a per-company `can_create` flag. Administrators can browse inactive companies for historical records. Vendor POST/PATCH and requisition creation still require genuine active membership and existing write checks; viewing does not create membership. `UserView` exposes `is_system_administrator` and `can_create_requisitions`; `RequestView.oversight_only` and `AttachmentPage.access_restricted` explain restricted details without presenting empty files as absent. Deploy backend before frontend with the existing Dockerfiles.
