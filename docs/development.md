# Custodian: Clone, Set Up and Develop

This guide brings up the BNH requisition system from the two `dev` repositories. It covers a local development database, first sign-in, optional services, tests and the feature delivery workflow. Commands use Bash on Linux, macOS or WSL; the isolated PostgreSQL test helper requires local PostgreSQL binaries and must run as a non-root user.

## 1. Prerequisites

| Tool                  | Project requirement                                                                                                                                                      |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Git and GitHub access | Access to both repositories; authenticate with your own GitHub account.                                                                                                  |
| Python                | 3.12, pinned in the backend's `.python-version`.                                                                                                                         |
| uv                    | Python dependency manager; the backend Dockerfile pins uv 0.12.7. Install using the [official uv instructions](https://docs.astral.sh/uv/getting-started/installation/). |
| Node.js and npm       | Node 24.21.0, pinned in `.nvmrc`; the supported range is `>=24.21.0 <25`. [nvm](https://github.com/nvm-sh/nvm#installing-and-updating) can select this version.          |
| PostgreSQL            | Use PostgreSQL 16 for the documented local setup and test helper. See [PostgreSQL installation options](https://www.postgresql.org/download/).                           |
| Docker                | Needed only for the optional container database/deployment commands below.                                                                                               |
| Chromium or Chrome    | Needed for Playwright browser checks, not for starting the application.                                                                                                  |

Resend and Cloudinary credentials are optional for starting the app. They are required for their respective workflows in section 7. There are no default login credentials.

## 2. Clone Both Repositories

Run from the directory where you keep projects:

```bash
mkdir BNH
cd BNH
git clone --branch dev https://github.com/Bapper-Ik/bnh-backend.git
git clone --branch dev https://github.com/Bapper-Ik/bnh-ui.git
```

Keep these exact sibling directory names:

```text
BNH/
  bnh-backend/   # FastAPI, PostgreSQL models, migrations, business rules
  bnh-ui/        # SvelteKit, TypeScript, browser tests
```

Each directory is a separate Git repository with its own `dev` branch and remote. The parent directory does not need to be a repository. If HTTPS authentication fails, obtain repository access and use your configured GitHub credential manager or the equivalent SSH clone URLs; do not place access tokens in commands or files.

Sibling placement matters: the browser runner starts `../bnh-backend`, and the API type generator writes into `../bnh-ui`.

The original workspace also has a shared `docs/` directory. It is not a third repository or a requirement for starting the application. Each clone includes product snapshots under `docs/reference/`. Personal-data screenshots are intentionally not distributed with those snapshots. Read each repository's `AGENTS.md` before changing code.

## 3. Prepare a Local Development Database

Use a fresh database for your local work. Development and production use different databases. Within each environment, migrations and the app share one `DATABASE_URL`; do not introduce `MIGRATION_DATABASE_URL`.

If you already have a local PostgreSQL server, create an empty `custodian_dev` database and a password-authenticated owner account with schema-changing privileges. The first provisioning command also needs permission to create the compatibility role `custodian_app` if it does not exist.

Alternatively, use Docker for PostgreSQL only. In `BNH/bnh-backend`, create an ignored `.env.postgres` file:

```dotenv
POSTGRES_DB=custodian_dev
POSTGRES_USER=custodian_owner
POSTGRES_PASSWORD=REPLACE_WITH_LOCAL_PASSWORD
```

Choose a local password and replace the placeholder. Use that same password in the backend URL in section 4. Then run from `bnh-backend`:

```bash
docker run --name bnh-dev-postgres \
  --env-file .env.postgres \
  -p 127.0.0.1:55438:5432 \
  -v bnh-dev-postgres-data:/var/lib/postgresql/data \
  -d postgres:16

docker exec bnh-dev-postgres pg_isready -U custodian_owner -d custodian_dev
```

Wait until `pg_isready` reports that the server accepts connections. The named volume keeps your development records across container restarts. On later days use `docker start bnh-dev-postgres`; use `docker stop bnh-dev-postgres` to stop it. Do not recreate or remove the volume just to restart the app. Changing `.env.postgres` after the volume is initialized does not change the database's existing password.

The database container's `.env.postgres` initializes PostgreSQL. The application's `.env` supplies its connection; both refer to the same development database. Neither file belongs in Git.

## 4. Configure and Start the Backend

From `BNH/bnh-backend`:

```bash
uv python install 3.12
uv sync --locked
cp .env.example .env
```

Edit `.env` to use your local database:

```dotenv
ENVIRONMENT=development
DATABASE_URL=postgresql://custodian_owner:REPLACE_WITH_LOCAL_PASSWORD@127.0.0.1:55438/custodian_dev
DATABASE_SSL=false
ALLOWED_ORIGINS=["http://localhost:5173"]
COOKIE_SECURE=false
MAIL_ENABLED=false
```

Adjust the host/port/user for an existing PostgreSQL installation. URL-encode special characters in URL credentials. The example is a local HTTP setup: the repository's `.env.example` initially enables database TLS, so explicitly change `DATABASE_SSL` to `false` for the local server above. Keep secrets private and do not copy a production URL into local development.

On a fresh database, provision the schema, migrate and create your first operator:

```bash
uv run python -m scripts.provision_database
uv run alembic upgrade head
uv run alembic current
uv run python -m scripts.create_operator
```

The operator command asks for your email, name and a password of at least 12 characters. It creates a configuration administrator, not a financial approver. It refuses to bootstrap if any account already exists. On an existing development environment, use your provisioned account or ask its administrator for access instead of rerunning bootstrap.

As of this guide's release, the migration head is `0020`. Always use `alembic upgrade head` rather than hard-coding that revision. Tables and migration history are in the `custodian` schema.

Start the complete application and leave this terminal running:

```bash
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

Use `app.main:create_app` for normal development. Older `auth_app`, `org_app` and `access_app` factories are partial assemblies used by some tests, not the full application entry point.

In another terminal, check:

```bash
curl --fail http://127.0.0.1:8000/api/v1/health/ready
```

Interactive API documentation is at `http://127.0.0.1:8000/docs`. A 404 at the backend's `/` path is expected; it is not the frontend or health endpoint.

## 5. Start the Frontend

Open a second terminal in `BNH/bnh-ui`:

```bash
nvm install
nvm use
npm ci
cp .env.example .env
BACKEND_URL=http://127.0.0.1:8000 npm run dev -- --host localhost --port 5173 --strictPort
```

If you do not use nvm, install the pinned Node version using your normal tool and omit the two nvm commands. `npm ci` uses `package-lock.json`; use it for a fresh checkout rather than changing dependency versions with `npm install`.

Open **http://localhost:5173/login** and sign in with the operator credentials you just created. Use `localhost` consistently: switching to `127.0.0.1` changes the browser origin and cookie scope. If you deliberately choose another origin, update backend `ALLOWED_ORIGINS` to match it exactly and restart the backend.

`BACKEND_URL` is a server-side backend origin, without `/api/v1`. The browser calls `/api/v1` on the frontend; `src/hooks.server.ts` proxies those calls to FastAPI. The command above exports the value explicitly because the proxy reads `process.env.BACKEND_URL`. Resend, Cloudinary and database secrets belong only in the backend.

Ctrl+C stops either development server. Your PostgreSQL data remains available on restart.

## 6. Configure the Organisation and Try the Workflow

1. Sign in as the configuration operator and open **Organisation & Authority**.
2. Add a company, then its departments. Each department needs a three-letter code such as `FIN`, `ICT` or `ADM`. Codes are stored uppercase and must be unique within the company. Existing departments with older codes can be corrected through **Edit Department**.
3. With email enabled, use **Staff & Access** to invite individual staff accounts. Activation does not automatically grant a membership, administrative permission or financial office.
4. Assign each staff member their company/department membership. Assign the real HOD, Chief of Staff, MD, Secretary and Chairman as appropriate. Administrators cannot change their own membership/appointments through this screen; a configuration operator can remain a separate administrative account.
5. Configure the company debit account. For HOD self-approval, configure the relevant department **Sub-Account** as well.
6. Sign in as a staff requester, add or select a vendor, create a requisition, save a draft, then review and sign its submission. New references look like `BNH-FIN-000020`; the internal URL ID remains a UUID. A missing department code blocks new draft creation with a setup message, while saved requests remain usable.
7. The assigned approver sees **My Tasks**. Ordinary staff do not see an empty approval inbox. Requesters can track decisions and retrieve permitted PDFs/approved bank transfer letters from requisition details.

Approval routing is direct: ordinary staff requests through ₦5 million go to their HOD; above ₦5 million through ₦100 million go to the Chief of Staff; above ₦100 million through ₦500 million go to the MD; higher amounts go to the Board. Eligible HODs may separately approve their own ₦1–₦5 million requests using their department sub-account. Chief of Staff and MD requester floors still apply. Board outcomes require Secretary recording and independent Chairman confirmation. See `docs/reference/recap.md` and the latest decisions in `AGENTS.md` for the full policy.

Approval is authorisation, not proof of bank payment. Signed records and existing references are not rewritten when master details change.

## 7. Optional External Services

### Email: Resend

Add these values privately to the backend `.env`, then restart it:

```dotenv
MAIL_FROM=access@YOUR_VERIFIED_DOMAIN
RESEND_API_KEY=YOUR_PRIVATE_KEY
ACCOUNT_LINK_SECRET=YOUR_STABLE_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
FRONTEND_ORIGIN=http://localhost:5173
MAIL_ENABLED=true
```

`MAIL_FROM` must be an actual address on your verified sending domain; placeholders will not work. Generate the link secret privately and keep it stable across restarts. `FRONTEND_ORIGIN` must exactly match an entry in `ALLOWED_ORIGINS`, without a trailing slash.

With mail disabled, existing sign-in and organisation administration work, but invitations and public password-reset delivery report unavailable. For a verified existing account, an authorised operator can run `uv run python -m scripts.issue_recovery`; it writes a private recovery-link file in `.state/recovery`. Treat that file as a credential and remove it after the private handoff.

### Private Documents: Cloudinary

Set the backend credential privately and restart:

```dotenv
CLOUDINARY_URL=cloudinary://API_KEY:API_SECRET@CLOUD_NAME
```

Alternatively set `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY` and `CLOUDINARY_API_SECRET`; use one configuration form. The backend stores authenticated private assets and serves authorised downloads. Supporting uploads, stored signing evidence and generated documents need the storage integration. The default attachment limit is 5 MB and ten files, configurable in `.env.example`.

PDF fonts are already bundled in `app/assets/fonts`; no licensed fonts or runtime font downloads are required. Malware scanning is not implemented in this release. Do not place provider credentials in the frontend or replace private storage with public asset links.

The automated browser harness supplies isolated synthetic email/storage, so tests do not require live provider keys. That harness is for local verification, not a production fallback.

## 8. Run the Checks

### Backend and Its Isolated Database

Tests use a separate disposable `.env.test`, never your development or production database. Install PostgreSQL 16 server/client binaries locally even if the development database runs in Docker. The helper defaults to `/usr/lib/postgresql/16/bin`; on another installation set `PG_BIN` to the directory containing `initdb` and `pg_ctl`, and make `psql` available on `PATH`.

From `bnh-backend`, as your normal non-root user:

```bash
uv run python -m scripts.dev_database
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

The helper creates its own cluster under ignored `.state/test` on loopback port **55439** and writes random credentials to ignored `.env.test`. It refuses to overwrite an existing configuration when initializing a new cluster. Running it again starts/reuses that cluster. `pytest` applies migrations automatically using the test-only owner connection in `.env.test`; do not copy `TEST_DATABASE_OWNER_URL` into deployment settings. Avoid concurrent test runs against the same test database.

On the documented Linux installation, stop the test cluster with:

```bash
/usr/lib/postgresql/16/bin/pg_ctl -D .state/test/postgres stop
```

Use the matching `pg_ctl` path for another installation. Start it again with the helper. Do not delete `.state/test` or `.env.test` as routine troubleshooting.

### Frontend and Connected Browser Tests

From `bnh-ui`, with the backend test database migrated above:

```bash
npm run lint
npm run format:check
npm run typecheck
npm run test -- --run
npm run build
npx playwright install chromium
npm run test:e2e
```

On Linux, Playwright may also need browser system dependencies. Follow its installer output; alternatively set `CHROME_PATH` to an already installed Chrome executable. The browser runner starts its own test backend on **8017** and built frontend on **4173**. Both ports must be free. Rebuild the frontend before browser tests after UI changes; the runner serves `build`, not the Vite development server.

The browser fixtures require a loopback database whose name ends in `_test`. They seed synthetic accounts and privately capture mail/storage. Screenshots, fixture credentials and results remain in ignored `test-results/`; do not commit them or reuse those accounts outside the test database.

To run only a relevant journey after the prerequisites are ready:

```bash
npm run test:e2e -- tests/requisitions.e2e.ts
```

## 9. Codebase Map and Daily Development

| Location                                                                 | Responsibility                                                           |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| `bnh-backend/app/main.py`                                                | Complete FastAPI assembly and background workers.                        |
| `bnh-backend/app/core/`                                                  | Configuration, database sessions, shared errors and runtime conventions. |
| `bnh-backend/app/organisation/`, `requisitions/`, `authority/`, `board/` | Directory, lifecycle and approval business rules.                        |
| `bnh-backend/app/evidence/`, `exports/`, `transfers/`                    | Private files, signatures and generated documents.                       |
| `bnh-backend/migrations/versions/`                                       | Alembic schema history; use reviewed forward migrations.                 |
| `bnh-backend/tests/`                                                     | Unit and real-PostgreSQL integration/security tests.                     |
| `bnh-ui/src/routes/`                                                     | The fourteen reusable screens and shared layouts.                        |
| `bnh-ui/src/lib/features/`                                               | Reusable forms, signing, files, administration and review components.    |
| `bnh-ui/src/lib/api/`                                                    | API client and generated OpenAPI/TypeScript contracts.                   |
| `bnh-ui/src/hooks.server.ts`                                             | Same-origin API proxy and frontend health endpoint.                      |
| `bnh-ui/src/lib/styles/`                                                 | Shared visual tokens and styles.                                         |
| `bnh-ui/tests/`                                                          | Connected Playwright journeys.                                           |

Before starting, check both repositories with `git status`, switch to `dev`, and update with `git pull --ff-only` when your work is safely committed. Never discard someone else's changes to obtain a clean checkout.

After pulling backend changes, run `uv sync --locked` and `uv run alembic upgrade head` before starting the API. Run `npm ci` when the frontend lockfile changes.

When backend contracts change, regenerate the frontend files from `bnh-backend` with a valid local `.env`:

```bash
uv run python -m scripts.export_openapi
```

This writes `bnh-ui/src/lib/api/openapi.json` and `schema.ts`. Commit the generated files with the matching feature; do not hand-edit them.

Follow the agreed delivery gate: select one feature using its stable ID in `docs/reference/implementation_pan.md`, complete its connected backend/frontend behavior, run the required checks, update the existing tracker/delivery notes, review the exact diff, then commit and push each affected repository to `origin/dev` before starting the next feature. Do not automatically merge to `main`/`master` or force-push.

If working in the original paired workspace, update the shared `BNH/docs/` originals and mirror the relevant snapshots into each affected repository. In a fresh clone, use the committed snapshots to understand scope and coordinate canonical documentation changes with the project maintainer. `scripts.sync_requirements` needs the original shared docs directory; it is not an installation step.

Useful backend operator tools include `scripts.notification_status` for aggregate delivery state and `scripts.configure_audit_reviewer` for controlled company-scoped audit access. Inspect their prompts and documentation before using them on a shared environment.

## 10. Production Builds and Deployment

From `bnh-ui`, to check the Node production build locally:

```bash
npm run build
BACKEND_URL=http://127.0.0.1:8000 HOST=localhost PORT=5173 node build
```

Stop Vite first so port 5173 is free. The explicit variables avoid relying on automatic `.env` loading in the built Node server. This local command is not a public HTTPS deployment configuration.

Both repositories include a `Dockerfile` and `render.yaml`. Build from each repository root:

```bash
# In bnh-backend
docker build -t bnh-backend .

# In bnh-ui
docker build -t bnh-ui .
```

For deployment details, use `bnh-backend/docs/render.md` and `bnh-ui/docs/render.md`. Deploy both matching `dev` revisions when a feature spans the API and UI. Backend startup runs all pending migrations before Uvicorn. A brand-new database still needs initial schema/compatibility-role provisioning before normal startup.

Production uses its own database, HTTPS frontend origin, secure cookies and private environment values. Configure `DATABASE_SSL` according to the PostgreSQL service (the Render guide uses `true`). The frontend needs only its backend origin; it is a Node web service, not a static site. A container's `127.0.0.1` refers to that container, so use an address reachable from the frontend container when setting `BACKEND_URL`.

## 11. Troubleshooting

| Symptom                                               | What to check                                                                                                                                                                                                                                |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Clone reports not found or permission denied          | GitHub access to both repositories and your configured authentication.                                                                                                                                                                       |
| Node engine warning or frontend install failure       | Run `nvm use` in `bnh-ui`; check `.nvmrc` and `node --version`.                                                                                                                                                                              |
| Python version or locked dependency error             | Use Python 3.12 and `uv sync --locked`; do not regenerate the lockfile merely to bypass setup errors.                                                                                                                                        |
| Database connection or TLS error                      | Confirm local host/port/password and `DATABASE_SSL=false` for the local database above.                                                                                                                                                      |
| `must be owner of table` during migration             | The selected database account must own the existing Custodian objects or have the appropriate ownership role. Ask its database administrator to correct ownership; adding another URL variable does not fix ownership.                       |
| `role custodian_app does not exist`                   | Run initial provisioning with an authorised database account. This compatibility role is referenced by historical migrations.                                                                                                                |
| Sign-in or mutation gets CSRF/origin errors           | Browse the exact configured origin, use `COOKIE_SECURE=false` only for local HTTP, and restart after changing environment values.                                                                                                            |
| Frontend reports unavailable service                  | Check the backend health endpoint, startup logs and server-side `BACKEND_URL`; the backend root 404 is expected.                                                                                                                             |
| Cannot create another bootstrap operator              | Accounts already exist. Use controlled staff administration/recovery; there is no default administrator password.                                                                                                                            |
| No Create Requisition or My Tasks                     | Creation needs active company/department membership. Tasks require the actual eligible approval assignment; administrator status alone does not grant financial authority.                                                                   |
| New draft asks for a department code                  | An administrator must set an exact three-letter code under Organisation & Authority → Departments → Edit Department. Retry Save without discarding the form.                                                                                 |
| Invitation, reset email, upload or export unavailable | Configure the corresponding backend Resend/Cloudinary settings and restart. Provider failures are not replaced with pretend success.                                                                                                         |
| Missing HOD/Chief of Staff/MD or Board assignment     | Configure a unique currently eligible officeholder in the proper scope. The application does not invent substitute approvers.                                                                                                                |
| Transfer letter unavailable after approval            | Check the displayed bank/source details and document job error. HOD self-approval requires the department sub-account; ordinary approvals use the company account. Master-data edits cannot repair an already frozen incomplete instruction. |
| Tests cannot find PostgreSQL or ports are occupied    | Set `PG_BIN`, check `psql`, start the isolated test cluster, and free 8017/4173 before browser tests.                                                                                                                                        |

Do not commit `.env*` secrets, database state, `.venv`, `node_modules`, test results or personal-data screenshots. Local checks establish reproducible code behavior; live provider delivery and real BNH staff acceptance are separate checks.
