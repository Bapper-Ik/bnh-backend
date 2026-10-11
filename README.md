# Custodian Backend

FastAPI and PostgreSQL backend for Brendan Nicholas Holdings' requisition and approval system. Development branch: `dev`. Python: 3.12; dependencies are locked with uv.

**Start here: [Clone, Set Up and Develop](docs/development.md).** The guide covers both repositories, local PostgreSQL, migrations, first-login credentials, external services, tests and the delivery workflow. Keep `bnh-backend` and `bnh-ui` as sibling directories.

## Run the Complete Application

After configuring your local `.env` and completing first-time provisioning in the guide:

```bash
uv sync --locked
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

Use `app.main:create_app`; older partial application factories are retained for tests. The current migration head is `0020`; always migrate to `head`. One `DATABASE_URL` serves migrations and the application in each environment, while development and production use separate databases.

Readiness: `http://127.0.0.1:8000/api/v1/health/ready`. API documentation: `http://127.0.0.1:8000/docs`. There are no default accounts or passwords; the guide explains the one-time operator bootstrap.

## What the Backend Supports

Authentication and account recovery; staff, company and department administration; scoped vendors and bank details; persistent requisition drafts and signed revisions; direct approval routing and the HOD self-approval exception; Board recording/confirmation; private supporting documents; notifications and audit/history; requisition PDFs and signed bank transfer letters.

New requisition references use administrator-selected three-letter department codes, for example `BNH-FIN-000020`. Existing references remain unchanged. Approval authorises expenditure; the application does not execute or confirm a bank payment.

## Documentation

- [Development and onboarding guide](docs/development.md)
- [Render deployment and operations](docs/render.md)
- [Engineering and delivery instructions](AGENTS.md)
- [Fourteen-screen scope](docs/reference/ui_scrrens.md)
- [Feature requirements and tracker](docs/reference/implementation_pan.md)
- [Approval policy recap](docs/reference/recap.md)
- [Current integration notes](docs/reference/ui_todos.md)
- [Delivery and verification history](docs/reference/task_done.md)

Email uses Resend; private files and generated documents use Cloudinary. PDF fonts are bundled. Live provider behavior and staff acceptance remain separate from local verification. MFA, malware scanning and automated backup/recovery are not implemented as part of this release.
