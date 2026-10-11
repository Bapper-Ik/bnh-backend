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

The current migration head is **0020**. Startup applies all pending migrations with `alembic upgrade head` before serving requests, using the same `DATABASE_URL` as the application. Deploy the backend before the matching frontend. The configured connection must own the application schema and tables; existing public tables are left untouched.

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

The application supports the fourteen-screen release: account access, dashboard, requisitions, individual/Board approval, vendors, staff, organisation, audit and account security, with shared notifications and private document exports. Email and Cloudinary require their configuration below. See [local development and onboarding](development.md) for first-time setup; health checks do not establish complete workflows or staff acceptance.

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

The document journey introduced migration **0011**; the current release starts `app.main:create_app` after applying all migrations through **0015**. Existing Dockerfiles remain the deployment entrypoints. The frontend image allows bodies up to 11 MB; backend validation defaults to 5 MB per attachment and 10 attachments per requisition (PDF, PNG and JPEG). PDF content is limited to 200 unencrypted pages and images to 20 million pixels. Keep your own Render `BODY_SIZE_LIMIT` override at 11M if you set one; it must exceed the backend file limit.

Configure Cloudinary **only on the backend Render service**, using either:

- `CLOUDINARY_URL`: copy the private API environment URL from your Cloudinary dashboard; or
- `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`: the three corresponding values.

Prefer one configuration method. Use a separate Cloudinary product environment for production where available. Never put these secrets in frontend variables, build arguments, source control or chat. No R2 bucket or scanner is required.

The backend uploads every document as `resource_type=raw`, `type=authenticated`, with a unique public ID and overwrite disabled. It does not return Cloudinary delivery URLs or credentials to the browser. Downloads pass through the application permission checks and use a short-lived private Cloudinary download internally, with size and SHA-256 verification before serving the file. Submission rechecks attached object bytes before freezing the manifest. Cloudinary account owners can still remove/change assets outside the app; such changes must fail retrieval rather than silently replacing signed evidence. Arrange backup/retention separately; this is not a protected external archive.

If credentials are missing, upload controls explain that private storage is unavailable. Other request functions still work, including submission without optional documents. Provider errors produce a real error and do not save a successful attachment record. A database rollback after a provider upload can leave an unreferenced private object; remove such objects only after reconciling against attachment records and frozen revision manifests. Do not configure automatic deletion of this folder.

Cloudinary's account/security settings may restrict PDF delivery. Verify a real private PDF upload and download on the deployed service; do not solve a delivery restriction by making documents public. Local tests use explicit isolated storage fixtures and separately exercise Cloudinary HTTP contracts; they do not prove your Cloudinary account configuration or quotas. Malware scanning is not performed in this release, as requested.

Requisitions save a durable notification intent atomically with signed transitions. Individual approval and Board workspaces are delivered; NOT-001 consumes their notification intents as described below. Account activation/reset emails continue through their existing Resend worker.

References: [Cloudinary upload parameters](https://cloudinary.com/documentation/upload_parameters), [private downloads](https://cloudinary.com/documentation/control_access_to_media).


## HIS-001 history and Audit Log deployment

Deploy the backend `dev` commit before the matching frontend. `scripts/start.sh` applies migration `0014` automatically using the same environment-specific `DATABASE_URL`, then starts Uvicorn. This migration adds indexes only; no new secrets or environment variables are required. Both existing Dockerfiles already include these files.

Audit access is explicit. After activating a named reviewer, an authorised operator can run `python -m scripts.configure_audit_reviewer` in the backend service environment to grant or revoke a particular company UUID. Grant makes the account read-only and refuses active financial appointments. The last company revocation removes the audit capability and never restores write access. Company UUIDs are available from the protected organisation API. Do not use shared staff identities or grant audit visibility merely because someone administers the application.

After deployment, check requester history/filter refresh, an approver's pending assignment, and the permitted reviewer's Audit Log and private-document viewer. Confirm ordinary staff cannot open `/audit` and ordinary requesters cannot open confidential Board evidence. Local synthetic browser checks are not proof of Render deployment or genuine staff acceptance.


## Notification delivery (NOT-001)

Deploy backend `dev` first, then frontend `dev`. The tracked Dockerfiles already include the worker, migration and drawer. `start.sh` applies migration `0015` before Uvicorn using this environment's single `DATABASE_URL`; development and production still use separate databases. Keep `MAIL_ENABLED`, `MAIL_FROM`, `RESEND_API_KEY`, `FRONTEND_ORIGIN` and `ACCOUNT_LINK_SECRET` configured as above. No new secret or worker service is needed.

The notification worker starts with the web application and processes PostgreSQL outbox rows. It creates alerts even with `MAIL_ENABLED=false`; the drawer explicitly says email is off. Alerts created while email is off are not automatically emailed after enabling it. On an initial deployment, historical events older than 24 hours create eligible in-app alerts but skip email, avoiding a flood of old messages. More recent pending events can send when mail is enabled. No reminder/escalation schedule or automatic replacement approver is introduced.

The worker checks the originally assigned person's current account, membership, office, department and request stage. Private Board work also requires both original Secretary/Chairman appointments to remain eligible. Superseded or ineligible task alerts are excluded from lists and counts. Requester updates remain historical; stale outcomes do not send new email. Existing My Tasks is derived from business state and remains available independently of notification delivery. A cancelled delivery is not automatically revived by a later role/configuration change.

Email envelopes and the first-attempt timestamp are committed before the HTTPS call. Each claim has a two-minute lease; a restart recovers an expired claim using the same recipient, sender, origin, versioned message and provider idempotency key. Transient errors retry up to six attempts with exponential delay (30 seconds to 10 minutes, respecting a bounded provider Retry-After). Permanent provider rejection stops retries. A retry stops after 23 hours from the first attempt to stay inside [Resend's documented 24-hour idempotency window](https://resend.com/changelog/idempotency-keys). Provider acceptance is not proof of inbox delivery; end-to-end exactly-once email delivery is not claimed. Keep v1 template rendering stable when introducing future templates, because retries must send identical content.

A stopped or suspended web service cannot run the worker; pending work resumes when it starts. This release does not add an always-on external worker. In-app projection failures roll back the partial alert batch and retry up to six times. Failed jobs remain stored for operator diagnosis; there is no automatic broadcast or manual-resend UI.

For diagnostics in the backend service environment:

```sh
python -m scripts.notification_status
```

This read-only command prints aggregate projection/email states, counts, maximum attempts, safe error codes and earliest scheduling timestamps. It omits addresses, message bodies and staff/request identifiers. Recipient drawers show only their own delivery status and attempts. `notification.projection_failed`, `notification.delivery_failed` and `notification.worker_failed` logs exclude provider bodies and credentials. Investigate failed jobs against these diagnostics and service configuration; do not reset accepted/uncertain delivery rows or their idempotency keys to force a resend.

After deployment, submit a real request using your own account, check the assigned approver's drawer and inbox, complete the authorised action, and check the requester update. Email links require sign-in and never approve directly. Local tests capture synthetic email instead of sending to staff; they do not establish Render deployment or real inbox delivery.

## DOC-001 private PDF exports and bundled fonts

Deploy backend migration `0016` before the matching frontend. Startup already runs migrations. The API process runs the durable export worker; PostgreSQL leases recover interrupted work after two minutes. A failed export never reverses a saved approval. Transient render/storage failures retry up to three attempts; a user may retry a failed export of the same frozen capture. Private Cloudinary storage must be configured using the existing backend credentials.

The owner approved free fonts in place of the earlier proprietary font specification. The backend now bundles **Liberation Serif Regular** (body/footer) and **Liberation Sans Bold** (headings), including their SIL Open Font License notice in `app/assets/fonts/LICENSE.txt`. Fonts are embedded in the PDF and copied into the Docker image. The image build verifies that the non-root application user can load them. No font purchase, Render Secret Files, `PDF_FONT_DIRECTORY` or runtime font download is required. Old font settings/secrets are unused and may be removed.

The renderer records the bundled font profile and content digest. Missing/corrupt bundled assets produce an explicit error; repair/redeploy the image and retry the stored capture. Existing ready PDFs remain downloadable subject to current permissions. Tests and visual checks use the same bundled binaries as the deployment, including long cost tables, signatures, the naira symbol and accented names.

After deployment, generate a requisition PDF and an approved transfer letter, then confirm each private Cloudinary upload/download works as the authorised requester. That live provider check remains a deployment check; local tests use isolated storage and do not claim live verification. The owner explicitly authorised pushing the tested implementation to `dev` before this check.

Export files are authenticated Cloudinary raw assets under `exports/`, delivered only through the authenticated API with digest/size verification. Each export belongs to the identity that requested it; another authorised viewer generates their own permitted projection. Bank access and Board assignments are rechecked for reads/downloads. Export metadata freezes the selected revision/capture, timestamps, template/render/font versions and object/file digests. Signed content and signing times do not change when exported. Preserve these rows and private assets in backups. Interrupted storage publication may leave an unreferenced private object; only reconcile verified unreferenced objects, never delete a referenced ready export.

## DOC-002 signed bank transfer requests

Migration `0017` follows the DOC-001 export migration `0016`. No second database, scanner or payment service is introduced. The existing worker and private Cloudinary configuration handle the letters. The backend image already contains the approved free fonts.

Before staff approve new requests, an authorised administrator opens **Organisation & Authority → Companies → Bank details** and configures the company's debit bank, branch address, account name and account number (optional company address). This release supports one debit account per company. Do not seed real banking details from the sample photograph. Requesters must supply all three beneficiary bank fields on their requisition for a complete transfer letter.

On approval, the signing dialog displays the frozen beneficiary data, current company debit profile and exact amount, and explicitly asks to use this approval signature on the letter. A concurrent profile change invalidates the challenge; review and sign again. Individual approval or unconditional Chairman confirmation commits one private transfer capture with the decision. Secretary submission and conditional/rejected/deferred outcomes create none. The requester opens the approved requisition's **Documents → View transfer letter**, downloads the PDF and prints it using a PDF reader. It contains the actual approver signature/name/date, amount in figures and words, bank accounts and revision reference. It does not execute or confirm payment.

If required banking data is missing, the signing dialog warns before approval and the resulting document entry explains why generation is unavailable. Do not alter a signed capture to repair bank details: complete the source profile before approval or return a request for beneficiary correction. Already approved records are not silently reopened or retroactively signed. Font/storage failures preserve the approval and frozen capture; once configuration is restored, use **Retry PDF**. No live banking data, signature or staff action is created by deployment.

The bundled-font layout is tested locally. After deployment, verify a live private Cloudinary upload/download for a newly approved request; isolated storage tests do not establish that live result. Retain both export metadata and corresponding private objects in backups.


## EVD-001 automatic uploads before saving a draft

Deploy the backend before the frontend. The tracked Docker startup applies migrations 0018 (draft deletion) and 0019 (temporary supporting uploads) automatically using the environment's existing DATABASE_URL. No new secrets or services are required.

New-form uploads are validated and temporarily buffered in PostgreSQL, privately scoped to the active requester/company/form. The existing attachment size limit applies; the attachment count limit also caps all pending files per requester. These bytes expire after 24 hours, are inaccessible after expiry, and are removed by an hourly worker (also run at application startup). On an idle Render instance, cleanup resumes on wake. Saving a draft transfers its exact staged files to authenticated raw Cloudinary assets and removes the temporary bytes in the same database transaction as the draft/attachment/audit metadata. No draft is created solely by selecting a file.

A storage or audit failure preserves the temporary upload and form for retry. Object keys include requester, creation key, file ID and digest, using the adapter's existing overwrite=false behavior to avoid duplicates on retry; see [Cloudinary's duplicate-upload guidance](https://cloudinary.com/documentation/upload_images#avoiding_duplicate_uploads). Already saved documents retain the existing evidence retention rules. An external upload that succeeds before a database rollback can leave an unreferenced private object if the user abandons the retry; automatic deletion of permanent evidence is not introduced.

Verify on the deployed environment: select a PNG/PDF on a new form before Save draft, preview it, save, refresh, and preview/download it again. Also select a file on an existing draft; it must upload without an Upload document button. Local isolated-storage tests do not verify live Cloudinary credentials or account behavior.


## DOA-001 HOD self-approval and department bank setup

Deploy the backend first; its tracked Docker startup applies migration 0020 using the existing DATABASE_URL. Deploy the matching frontend next. No new environment settings or external service are required.

Before an HOD approves an own request, an administrator opens **Organisation & Authority → Departments → Sub-Account** for that company/department and saves the approved debit bank, branch address, account name and exact ten-digit account number. Leading zeroes are preserved. New own-HOD requests from ₦1 through ₦5 million require a separate approval signature and use this sub-account exclusively. Other approvals retain the company debit account. Check the displayed source/beneficiary details before signing; missing details prevent a complete letter and never fall back to another account. Existing signed letters cannot be repaired by editing master bank details.

New submissions use bnh-doa-v2. Already submitted requests retain their old route and bank-source policy. If an old pending request should use the new policy, its requester may use the existing Retract Requisition action only before any approver action, then review and resubmit with a fresh signature. Never alter stored submitted revisions directly.

## REQ-001 three-letter department reference codes

Deploy the matching backend and frontend, then open **Organisation & Authority → Departments → Edit Department** and set each department's Code to three letters, such as FIN, ICT or ADM. Existing departments with longer legacy codes are flagged in the list. Codes are stored uppercase and must be unique within the company. New department creation requires a code too.

New requisitions use `BNH-FIN-000020`-style references with the existing shared database sequence; numbering is not reset. An unconfigured department blocks only new draft creation with a clear administrator-setup message. Saved requests can still be read, edited, submitted and processed. Changing a code never renumbers an existing request or rewrites signed documents. No migration, environment setting or sequence reset is needed for this release.
