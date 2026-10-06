# Verified delivery notes

## CORE-001 — foundation verification, 2026-10-06

The feature is being delivered independently from existing incomplete business modules. `app.runtime:create_app` supplies the PostgreSQL runtime and safe health endpoints; `app.main` composes the existing business work separately.

- Schema/migration: `custodian`, migration `0001`; UUID identity, UTC creation timestamps, integer versions. No public-schema changes.
- Permissions: runtime login cannot own schema/tables or have superuser/role/database creation privileges; migration credentials are separate.
- Events: startup logs `runtime.configuration_validation.success` or `.failure` without credentials. Durable business events belong to AUD-001.
- Verification: `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/mypy app`, `.venv/bin/pytest -q --tb=short` passed; 92 tests in the full working tree. Tests include a newly created local database migrated twice, record preservation, new app/engine/client reconnect, API rollback, denied elevated runtime role, missing secrets, and safe readiness failure.
- Release: no public identity mutation endpoint; test-only CRUD routes stay in tests. No recovery/backup, evidence archive, business-feature, Docker-build, deployment, or genuine staff acceptance claim.
- Isolated staged checkout: Ruff, formatting, mypy, and 11 foundation tests passed against a fresh local database. Feature commit message: `feat(CORE-001): deliver verified PostgreSQL runtime foundation`; target: backend `origin/dev`. Remote delivery must be verified before advancement.

## Existing unfinished work

Authentication, organisation, authority, requisitions, signing, history, browser screens, and deployment configuration exist to varying degrees. These remain under assessment against their feature blocks. They are not included as completed features in the foundation commit. Container builds were interrupted while registry image downloads stalled; neither Docker image has been verified yet.
