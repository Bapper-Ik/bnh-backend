# Custodian backend

FastAPI + PostgreSQL backend for BNH requisitions. Approval records represent authorisation, never payment.

Development branch: `dev`. Each feature is verified, committed, and pushed before the next begins.

The delivered assembly is `app.vendor_app:create_app`: runtime, accounts, organisation, scoped access and Vendors. Apply migrations through 0010. The working-tree business assembly (`app.main`) is delivered through subsequent feature gates. See [Render setup](docs/render.md) for startup migrations and email configuration.

## Development setup

1. Install Python 3.12 and uv, then run `uv sync --locked`.
2. Configure the ignored `.env` using `.env.example`. Never commit database credentials.
3. Set `DATABASE_URL` to the development database connection with schema-changing permissions. For a new database, run `uv run python -m scripts.provision_database` once to prepare the dedicated `custodian` schema and the compatibility role referenced by historical migrations. It preserves existing roles/credentials and does not rewrite `.env`. Production uses a different database and its own `DATABASE_URL`.
4. Run `uv run alembic upgrade head`.
5. Run `uv run uvicorn app.vendor_app:create_app --factory --host 127.0.0.1 --port 8000`.

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

`uv run uvicorn app.vendor_app:create_app --factory --host 127.0.0.1 --port 8000` adds vendor capture/lookup/version APIs after migration 0009. Vendor creators maintain their own records within active entity membership; a separately authorised maintainer requires vendor:update and vendor:read_sensitive. These fixed grants are not implied by technical administration and are not exposed through a general public permission editor. Bank data is excluded from lookup lists, and every historical version is append-only. No actual vendors or bank details are seeded from the supplied screenshots.

## Browser account access (screens 1–3)

Sign-in, forgot-password and the shared reset/activation page use the real account APIs. Protected invitations create pending named accounts without granting membership or permissions. Pending accounts cannot sign in or act as officeholders. Reset/activation consumes all outstanding links, clears current cookies and revokes existing sessions. Public reset requests return the same response for known and unknown emails and have persisted request limits.

Migration 0010 adds activation state and durable email jobs. Email defaults off; configure Resend and the account-link secret using [the deployment guide](docs/render.md), then enable it. The in-process worker starts automatically and retries with provider idempotency. Local tests capture synthetic mail and mock only the external provider transport; live sender verification and inbox delivery remain deployment checks.
