# Custodian backend

FastAPI + PostgreSQL backend for BNH requisitions. Approval records represent authorisation, never payment.

Development branch: `dev`. Each feature is verified, committed, and pushed before the next begins.

The independently delivered CORE-001 foundation starts with `app.runtime:create_app`. The working-tree business assembly (`app.main`) is delivered through subsequent feature gates.

## Development setup

1. Install Python 3.12 and uv, then run `uv sync --locked`.
2. Configure the ignored `.env` using `.env.example`. Never commit database credentials.
3. A PostgreSQL owner configures the dedicated `custodian` schema and `custodian_app` login. For a new setup, `python3 scripts/provision_database.py` creates only these objects using the configured migration connection, and saves the runtime login locally. It refuses to overwrite existing objects or credentials.
4. Run `uv run alembic upgrade head`.
5. Run `uv run uvicorn app.runtime:create_app --factory --host 127.0.0.1 --port 8000`.

The supplied Render development database is shared with existing software. All Custodian tables, including its Alembic version table, live in the **custodian schema**. Existing public tables and migration history are not modified. Runtime credentials must differ from migration credentials. The application checks its role on startup and refuses schema-owner/admin access.

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

The helper creates an isolated cluster in ignored `.state/test`, listening only on loopback port 55439, and random credentials in ignored `.env.test`. It never resets an existing database. Tests require a database name ending in `_test`, migrate it twice, and use the restricted runtime role. They never fall back to the Render development database. Stop the isolated cluster with:

```sh
/usr/lib/postgresql/16/bin/pg_ctl -D .state/test/postgres stop
```

## Schema changes and recovery

Migrations use `MIGRATION_DATABASE_URL`; the service uses `DATABASE_URL`. Only reviewed forward migrations are supported. Do not run destructive downgrade/reset commands against shared databases. Back up the Custodian schema and evidence store before release changes; restore into a separate database and verify before any recovery cutover. A backup/restore drill and protected evidence archive are required release work, not currently claimed.

Application/runtime privileges protect historical records; database and hosting owners are a separate trust boundary. Keep migration credentials out of the API process environment in deployed services.

## Current API

- `GET /api/v1/health/live`: process liveness.
- `GET /api/v1/health/ready`: database connectivity, schema availability, and runtime privilege checks; 503 if unavailable.
- `/docs` and `/openapi.json`: generated API reference.

Business capabilities are tracked in the shared specification; infrastructure readiness is not staff acceptance.

## Accounts and recovery

Run the delivered authentication API with `uv run uvicorn app.auth_app:create_app --factory --host 127.0.0.1 --port 8000`. Create the first configuration operator with `uv run python -m scripts.create_operator`; it prompts privately for a password and refuses a second bootstrap. Approved staff managers provision individual accounts through `POST /api/v1/auth/accounts`; the new account receives no financial appointment.

Recovery uses a controlled operator handoff. After independently verifying the staff member, run `uv run python -m scripts.issue_recovery`. The 30-minute, single-use link is saved in a private mode-0600 file under ignored `.state/recovery`, never printed. Transfer it using your approved private channel, then delete the file. No email delivery or MFA is configured. The browser recovery screen belongs to WEB-001; the implemented redemption endpoint is `POST /api/v1/auth/recover`.

Migration 0006 adds recovery tokens after the already-applied 0004/0005 history. Their schemas are preserved for compatibility; organisation and requisition feature completion is tracked independently. Migrate before running the authentication API. Only isolated local test databases have been migrated to 0006 during feature verification; development release migration must be applied separately.
