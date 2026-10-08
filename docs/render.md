# Deploy the backend on Render

Create a **Web Service** from this repository, select branch **dev** and runtime **Docker**, and use `./Dockerfile` with build context `.`. Leave Docker Command empty; the image starts Uvicorn on Render's `PORT`. Alternatively, import this repository's `render.yaml` and review the service settings.

Set these environment variables in Render:

| Variable | Value |
| --- | --- |
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | The PostgreSQL connection for this environment, with permission to run migrations and access application tables. Render `postgresql://` URLs and `postgresql+asyncpg://` are accepted. Set it privately. |
| `DATABASE_SSL` | `true` |
| `COOKIE_SECURE` | `true` |
| `ALLOWED_ORIGINS` | JSON array containing the actual frontend URL, e.g. `["https://YOUR-FRONTEND.onrender.com"]` (no trailing slash). |

Health check: `/api/v1/health/ready`.

The approval release requires schema **0012**; startup applies it before serving requests. It adds the list of prior attachments excluded from a correction, preserving the original signed evidence. Deploy the backend before the matching frontend. No new environment variables are required. The last separately verified deployed vendor schema was **0009**. The supplied development database was upgraded from 0005 to 0009 to resolve the deployed session-query failure. Startup now runs `alembic upgrade head` before Uvicorn, using `DATABASE_URL`. Existing public tables remain untouched. The application now accepts the same schema-owner connection as migrations, as explicitly approved.

As requested, `/app/scripts/start.sh` requires only `DATABASE_URL` and runs `alembic upgrade head` on each start. If migration fails, the process exits without starting Uvicorn. Uvicorn uses that same connection. Remove the obsolete `MIGRATION_DATABASE_URL` setting; it is not read. If `DATABASE_URL` currently names the restricted `custodian_app` login, replace it with this environment's schema-owner connection before redeploying. Set `DATABASE_SSL=true` for Render. Do not put credentials in Docker build arguments or Git. Use one service instance while startup migrations run; multiple simultaneous migrations are not coordinated by this shell script.

The image starts `app.main:create_app`, the committed feature assembly, without production reload.

## Separate development and production databases

Use one database per environment and one connection variable per service:

| Environment | Backend `DATABASE_URL` |
| --- | --- |
| Development | Your development PostgreSQL database connection. |
| Production | A different production PostgreSQL database connection. |

Changing `ENVIRONMENT` does not switch databases. Set each service's URL explicitly; keep frontend origins and `BACKEND_URL` paired with the corresponding environment. Never reuse the development database as production or point tests at either deployed database. The local `.env.test` database is disposable verification infrastructure, not another deployment requirement.

For a brand-new database, run `python -m scripts.provision_database` once with that database's `DATABASE_URL`, then start normally. This creates the `custodian` schema and, if absent, a non-login compatibility role required by historical grants. It leaves existing roles, credentials and public tables intact. Existing configured databases need no repeated provisioning. The connection needs schema ownership for migrations and, on first provisioning only if the compatibility role is absent, permission to create that role.

The owner approved running the application with schema-changing permissions. Existing history triggers remain, but the shared owner credential can modify those protections; restricted-runtime privilege isolation is no longer a deployment guarantee.

## First sign-in

There is no public registration or default password. Create the first configuration operator once, either from the backend's Render shell or locally against the same development database:

```sh
python -m scripts.create_operator
```

For a local virtual environment, use `.venv/bin/python -m scripts.create_operator`. The command prompts privately for the password and refuses to bootstrap once accounts already exist. This account has technical configuration permissions, not financial approval authority. Vendor creation also requires an active company/department membership. A new operator without membership sees the setup-needed state; Staff & Access (screen 11) is available to authorised operators; Organisation & Authority (screen 12) manages real companies and departments. Staff & Access handles configured staff membership.

## Local container

```sh
docker build -t custodian-backend .
docker run --rm -p 8000:10000 --env-file .env custodian-backend
```

The Docker context excludes all environment files, local database files, tests and Git metadata. The final image runs as a non-root user and installs locked runtime dependencies only.

This release includes screens 1–3 (sign-in, forgot password, reset/activation), screen 10 (Vendors), screen 11 (Staff & Access), and screen 12 (Organisation & Authority). Email requires the configuration below. The remaining screens in the fourteen-screen inventory are unfinished. Health checks do not establish complete workflows or staff acceptance.

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

After deploying both services and configuring mail, use your own provisioned account to request a reset, confirm inbox delivery, complete it, and sign in again. Authorised staff managers can issue and resend invitations through the `/staff` drawer. It uses the protected invitation APIs; email-disabled deployments show unavailable invitation controls. New invitees receive no automatic membership or authority. Live provider credentials, domain verification and inbox delivery have not been verified by the local test suite.

## Requisition documents with Cloudinary

This release starts `app.main:create_app` and applies migration **0011** before serving requests. Existing Dockerfiles remain the deployment entrypoints. The frontend image allows bodies up to 11 MB; backend validation defaults to 5 MB per attachment and 10 attachments per requisition (PDF, PNG and JPEG). PDF content is limited to 200 unencrypted pages and images to 20 million pixels. Keep your own Render `BODY_SIZE_LIMIT` override at 11M if you set one; it must exceed the backend file limit.

Configure Cloudinary **only on the backend Render service**, using either:

- `CLOUDINARY_URL`: copy the private API environment URL from your Cloudinary dashboard; or
- `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`: the three corresponding values.

Prefer one configuration method. Use a separate Cloudinary product environment for production where available. Never put these secrets in frontend variables, build arguments, source control or chat. No R2 bucket or scanner is required.

The backend uploads every document as `resource_type=raw`, `type=authenticated`, with a unique public ID and overwrite disabled. It does not return Cloudinary delivery URLs or credentials to the browser. Downloads pass through the application permission checks and use a short-lived private Cloudinary download internally, with size and SHA-256 verification before serving the file. Submission rechecks attached object bytes before freezing the manifest. Cloudinary account owners can still remove/change assets outside the app; such changes must fail retrieval rather than silently replacing signed evidence. Arrange backup/retention separately; this is not a protected external archive.

If credentials are missing, upload controls explain that private storage is unavailable. Other request functions still work, including submission without optional documents. Provider errors produce a real error and do not save a successful attachment record. A database rollback after a provider upload can leave an unreferenced private object; remove such objects only after reconciling against attachment records and frozen revision manifests. Do not configure automatic deletion of this folder.

Cloudinary's account/security settings may restrict PDF delivery. Verify a real private PDF upload and download on the deployed service; do not solve a delivery restriction by making documents public. Local tests use explicit isolated storage fixtures and separately exercise Cloudinary HTTP contracts; they do not prove your Cloudinary account configuration or quotas. Malware scanning is not performed in this release, as requested.

Requisitions are routed and a durable notification intent is saved atomically. Email delivery for requisition events and the individual approval/Board workspaces remain later journeys. Account activation/reset emails continue through Resend.

References: [Cloudinary upload parameters](https://cloudinary.com/documentation/upload_parameters), [private downloads](https://cloudinary.com/documentation/control_access_to_media).
