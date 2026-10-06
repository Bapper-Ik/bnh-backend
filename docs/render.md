# Deploy the backend on Render

Create a **Web Service** from this repository, select branch **dev** and runtime **Docker**, and use `./Dockerfile` with build context `.`. Leave Docker Command empty; the image starts Uvicorn on Render's `PORT`. Alternatively, import this repository's `render.yaml` and review the service settings.

Set these environment variables in Render:

| Variable | Value |
| --- | --- |
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | Copy the **restricted runtime** connection from the local ignored `bnh-backend/.env`. It starts with `postgresql+asyncpg://custodian_app:`. |
| `DATABASE_SSL` | `true` |
| `COOKIE_SECURE` | `true` |
| `ALLOWED_ORIGINS` | JSON array containing the actual frontend URL, e.g. `["https://YOUR-FRONTEND.onrender.com"]` (no trailing slash). |

Health check: `/api/v1/health/ready`.

The vendor release requires migrations through **0009** in the isolated `custodian` schema. The supplied development database was previously at 0005; run `alembic upgrade head` using the migration connection before starting this release. Its original public tables must remain untouched. Do **not** use the original database-owner connection as the API runtime connection: startup rejects elevated privileges.

For this release and future releases, run `alembic upgrade head` in a separate migration/release environment with `MIGRATION_DATABASE_URL` and `DATABASE_SSL=true`. The API start command does not migrate and does not require owner credentials. Do not put database credentials in Docker build arguments or Git.

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

This deploy previews sign-in and screen 10 (Vendors). The remaining screens in the fourteen-screen inventory are unfinished. Health checks do not establish complete workflows or staff acceptance.

Reference: [Render Docker deployments](https://render.com/docs/docker), [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/).
