# Verified delivery notes

## CORE-001 — foundation verification, 2026-10-06

The feature is being delivered independently from existing incomplete business modules. `app.runtime:create_app` supplies the PostgreSQL runtime and safe health endpoints; `app.main` composes the existing business work separately.

- Schema/migration: `custodian`, migration `0001`; UUID identity, UTC creation timestamps, integer versions. No public-schema changes.
- Permissions: runtime login cannot own schema/tables or have superuser/role/database creation privileges; migration credentials are separate.
- Events: startup logs `runtime.configuration_validation.success` or `.failure` without credentials. Durable business events belong to AUD-001.
- Verification: `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/mypy app`, `.venv/bin/pytest -q --tb=short` passed; 92 tests in the full working tree. Tests include a newly created local database migrated twice, record preservation, new app/engine/client reconnect, API rollback, denied elevated runtime role, missing secrets, and safe readiness failure.
- Release: no public identity mutation endpoint; test-only CRUD routes stay in tests. No recovery/backup, evidence archive, business-feature, Docker-build, deployment, or genuine staff acceptance claim.
- Isolated staged checkout: Ruff, formatting, mypy, and 11 foundation tests passed against a fresh local database. Feature commit message: `feat(CORE-001): deliver verified PostgreSQL runtime foundation`; target: backend `origin/dev`. Verified remote commit: backend `82428f4ef8560007a815d2ba1d858280bd485df5` on `origin/dev`. Frontend dev workflow commit: `53fdd7020ae0ed95b8a50bfceba9f2aa4a55531b`, also verified on `origin/dev`.

## Existing unfinished work

Authentication, organisation, authority, requisitions, signing, history, browser screens, and deployment configuration exist to varying degrees. These remain under assessment against their feature blocks. They are not included as completed features in the foundation commit. Container builds were interrupted while registry image downloads stalled; neither Docker image has been verified yet.

## AUD-001 — transactional audit infrastructure

- Schema/migration: `0002`, append-only `custodian.audit_events` and mutable delivery status in `custodian.outbox_items`; restricted actor/event foreign keys.
- Service: `record_event` participates in the caller's transaction and durably queues archive intent. `audited_transaction` rolls back a rejected business operation before separately recording `access.denied.failure`; errors and request bodies are excluded. IDs supplied to this internal service must be from trusted server context.
- Envelope: UUID/time, actor/type, resource/type, entity/department, office, revision/resolution, outcome, correlation, unique event key, policy and digest. Digests are SHA-256 format; changed-field names use a closed vocabulary. Registry rejects duplicate/unknown actions. Domain features populate their applicable snapshots and wire failure recording at their own boundaries.
- Protection: runtime can SELECT/INSERT events, never UPDATE/DELETE/TRUNCATE or disable the trigger. Archive attempts/status updates do not edit events. Audit/outbox failure rolls back business writes. Duplicate concurrent action keys can commit only one transition.
- No public audit-write or generic audit administration endpoint. Read APIs belong to HIS-001. Database/hosting owners remain a separate trust boundary; pending archive intent is not proof of external protected delivery.
- Verification: full backend suite 97 passed; isolated staged feature checkout 24 passed; Ruff, formatting, and mypy passed in both. Feature commit: `feat(AUD-001): complete transactional append-only audit infrastructure`; verified remote `origin/dev` commit `eacfa9a91baee2893c7fc954cf67b1f9c1266df7`.

## IAM-001 — individual authentication and session lifecycle

- Delivery entry point: `app.auth_app:create_app` includes only runtime and authentication. Existing organisation/requisition work remains separately composed by uncommitted `app.main` until its gates pass.
- Accounts: Argon2 password hashes, unique identity/email, active flag, server permissions. `/auth/accounts` requires `staff:manage`, grants no permissions to a new account, and rejects role/permission mass assignment. First-operator CLI serialises bootstrap and validates email.
- Sessions: hashed opaque cookie/CSRF tokens, HttpOnly/SameSite session cookies, secure production configuration; current account checks and account locks serialise sensitive actions with deactivation/revocation. Logout revokes one session; self revoke ends all sessions; staff managers can revoke another account's sessions. Login and fresh-authentication attempts each have persisted five-failure/15-minute throttles.
- Recovery: operator CLI verifies the supplied email and issues a random token only for an active account. Hash-only storage, 30-minute expiry, superseding issuance, single-use consumption under row locks; successful recovery revokes all sessions. Operator must verify the staff member's identity before handoff. The private link file is mode 0600 under ignored `.state/recovery`; token/password never goes into logs or ordinary account responses. No email transport or MFA is claimed.
- Migrations: account/session schema `0003` and recovery schema `0006`. Existing migrations `0004`/`0005` are retained as required historical dependencies because they were already applied to the shared development database; their inclusion is not a claim that organisation/requisition features are complete. No applied migration is rewritten.
- Events: identity.created; auth.signed_in/signed_out/failed/reauthenticated/sessions_revoked/recovery_issued/recovered/recovery_failed. Failure outcomes persist without credentials; audit insertion failure prevents session issuance.
- Verification: Ruff, format check, mypy, full backend suite (109 passed), including distinct identities, malicious extra fields, inactive/expired/revoked sessions, CSRF/origin denial, failed and successful reauthentication, recovery replay/expiry/replacement/concurrent use, and atomic login failure. Isolated staged checkout: 40 tests passed; Ruff, formatting, and mypy passed. Feature commit: `feat(IAM-001): complete individual accounts recovery and session controls`; verify `origin/dev` before advancement.
