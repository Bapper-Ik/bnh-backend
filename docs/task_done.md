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
- Verification: full backend suite 97 passed; isolated staged feature checkout 24 passed; Ruff, formatting, and mypy passed in both. Feature commit: `feat(AUD-001): complete transactional append-only audit infrastructure`; target `origin/dev`, verified before advancement.
