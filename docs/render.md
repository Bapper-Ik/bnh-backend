# Deploy the backend on Render

Create a **Web Service** from this repository, select branch **dev** and runtime **Docker**, and use `./Dockerfile` with build context `.`. Leave Docker Command empty; the image starts Uvicorn on Render's `PORT`. Alternatively, import this repository's `render.yaml` and review the service settings.

Set these environment variables in Render:

| Variable | Value |
| --- | --- |
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | Copy the **restricted runtime** connection from the local ignored `bnh-backend/.env`. It starts with `postgresql+asyncpg://custodian_app:`. |
| `MIGRATION_DATABASE_URL` | The migration-owner PostgreSQL connection, using `postgresql+asyncpg://`. Set this privately in Render. Keep `DATABASE_URL` restricted. |
| `DATABASE_SSL` | `true` |
| `COOKIE_SECURE` | `true` |
| `ALLOWED_ORIGINS` | JSON array containing the actual frontend URL, e.g. `["https://YOUR-FRONTEND.onrender.com"]` (no trailing slash). |

Health check: `/api/v1/health/ready`.

The account-access release requires schema **0010**; startup applies it before serving requests. The last separately verified deployed vendor schema was **0009**. The supplied development database was upgraded from 0005 to 0009 to resolve the deployed session-query failure. Startup now runs `alembic upgrade head` before Uvicorn, using the separately configured migration connection. Existing public tables remain untouched. Do **not** use the original database-owner connection as the API runtime connection: startup rejects elevated privileges.

As requested, `/app/scripts/start.sh` requires `MIGRATION_DATABASE_URL` and runs `alembic upgrade head` on each start. If migration fails, the process exits without starting Uvicorn. The script then removes `MIGRATION_DATABASE_URL` from the web process environment; `DATABASE_URL` remains the restricted runtime connection. Set `DATABASE_SSL=true` for Render. Do not put credentials in Docker build arguments or Git. Use one service instance while startup migrations run; multiple simultaneous migrations are not coordinated by this shell script.

The image starts `app.vendor_app:create_app`, the committed feature assembly, without production reload.

## First sign-in

There is no public registration or default password. Create the first configuration operator once, either from the backend's Render shell or locally against the same development database:

```sh
python -m scripts.create_operator
```

For a local virtual environment, use `.venv/bin/python -m scripts.create_operator`. The command prompts privately for the password and refuses to bootstrap once accounts already exist. This account has technical configuration permissions, not financial approval authority. Vendor creation also requires an active company/department membership. A new operator without membership sees the setup-needed state; staff and organisation management screens are still being implemented. Existing organisation APIs handle configured staff membership.

## Local container

```sh
docker build -t custodian-backend .
docker run --rm -p 8000:10000 --env-file .env custodian-backend
```

The Docker context excludes all environment files, local database files, tests and Git metadata. The final image runs as a non-root user and installs locked runtime dependencies only.

This release includes screens 1–3 (sign-in, forgot password, reset/activation) and screen 10 (Vendors). Email requires the configuration below. The remaining screens in the fourteen-screen inventory are unfinished. Health checks do not establish complete workflows or staff acceptance.

Reference: [Render Docker deployments](https://render.com/docs/docker), [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/).

## Account email configuration

The account-access implementation uses Resend over HTTPS. Set these privately on the **backend** service before enabling email:

| Variable | Value |
| --- | --- |
| `MAIL_FROM` | An email address on your verified Resend sending domain. |
| `RESEND_API_KEY` | A Resend key permitted to send from that domain. |
| `ACCOUNT_LINK_SECRET` | A separately generated random secret of at least 32 characters; keep it stable across restarts and instances. |
| `FRONTEND_ORIGIN` | Exact frontend origin, e.g. `https://bnh-ui.onrender.com`, also present in `ALLOWED_ORIGINS`, with no trailing slash. |
| `MAIL_ENABLED` | `true` after the above are configured. The blueprint defaults to `false`. |

The service rejects incomplete enabled-email settings at startup. With email disabled, forgot-password and invitation requests return a clear 503 instead of pretending that mail was sent. Existing sign-in and controlled operator recovery remain available.

The application starts its durable email worker automatically. Issuing a link, recording its audit event, and queueing the email commit together. Pending jobs survive restarts; competing workers lock jobs, retry up to six attempts, and reuse the same provider idempotency key and message. Expired, consumed, superseded, disabled-account or mismatched jobs are cancelled. Provider acceptance is recorded separately from failures; it is not proof of inbox delivery. Do not enable HTTP body logging for account endpoints/provider requests.

Links expire after 30 minutes and are single use. Raw links are reconstructed in memory from the private link secret and a random token identifier; neither raw tokens nor message bodies are stored in the jobs table. Rotating the secret cancels unsent jobs that no longer match; previously sent unexpired links still redeem against their stored hash. Request fresh links after rotation. Keep the key out of frontend settings, Docker build arguments and source control.

After deploying both services and configuring mail, use your own provisioned account to request a reset, confirm inbox delivery, complete it, and sign in again. Invitation issuance currently uses the protected `/api/v1/auth/invitations` API; the Staff & Access Management drawer is a later screen. New invitees receive no automatic membership or authority. Live provider credentials, domain verification and inbox delivery have not been verified by the local test suite.
