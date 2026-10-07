# Custodian backend instructions

## Scope and source of truth

This directory is the backend for **Custodian by Brendan**, BNH's requisitions and Delegation of Authority system. Implementation is underway. Inspect the repository and recorded verification before assuming a capability is complete.

Read these references before implementing a feature:

- `../docs/implementation_pan.md`: detailed requirements, stable feature IDs, acceptance criteria, and canonical implementation-status tracker.
- `../docs/recap.md`: authority matrix and Board workflow.
- `../docs/features.md`: scope summary, not a second tracker.
- `../docs/1.jpeg` through `4.jpeg`: form fields only; the old approval path is superseded. `5.jpeg` defines visual standards and `6.jpeg` contains section 5.1.

The user's latest explicit decisions take precedence. This file replaces the missing backend AGENTS.md referenced by the specification. References there to an existing scaffold, Python 3.14, mandatory Result/CrudUtil wrappers, route decorators, a dependency-policy script, and a develop/merge/push process are obsolete. Preserve product requirements, not absent mechanisms. Raise genuine business-policy conflicts rather than inventing resolutions.

## Release scope: fourteen screens

The latest user scope is `../docs/ui_scrrens.md` (the supplied filename has a typo). It is authoritative for release surfaces and supported functionality. In standalone clones use `docs/reference/ui_scrrens.md`. Build exactly these reusable screen templates:

1. Sign In
2. Forgot Password
3. Set Password / Activate Account
4. Dashboard
5. Requisitions
6. Create / Edit Requisition
7. Requisition Details & Review
8. My Tasks / Approval Inbox
9. Board Resolution Workspace
10. Vendors
11. Staff & Access Management
12. Organisation & Authority
13. Audit Log
14. My Account & Security

Use drawers/dialogs for vendor details and edits, invitations, appointments, department edits, and signing; a header drawer for notifications; and a viewer for attachments/generated documents. Reuse screens across roles and request states. No extra applications, screens, workflow builder, contracts, scoring, payments, or unrelated backend modules.

Implement backend capabilities only where they support these screens, their dialogs/viewers, or necessary security, persistence and deployment. Older requirements explain fields and business rules within this boundary; they do not expand it. Preserve the fixed authority rules and Secretary/Chairman separation. Map work to these screen numbers in the existing tracker. Existing backend completion does not imply screen completion. Continue the one-feature test → commit → push gate on `dev`; finish each connected screen journey before moving on.

## Mandatory feature delivery gate

The project owner's latest instruction is authoritative: implement **one feature at a time**, finish it fully, pass all required tests, then **commit and push before starting the next feature**. This replaces earlier guidance that treated publishing as optional. Routine commits and pushes to the configured project remotes are authorised; do not repeatedly ask permission to proceed.

1. **Select and assess.** Use the stable feature IDs and dependency order in `../docs/implementation_pan.md`. Select the next incomplete journey within the fourteen-screen scope and its necessary prerequisites; do not advance unrelated legacy-spec features. Read its complete deliverables and acceptance criteria, inspect existing code in both repositories, and record the actual gaps. Announce the current feature and what will establish completion.
2. **Implement the whole feature.** Complete its required backend, frontend, migrations, permissions, audit events, configuration, and error handling as applicable. Keep work within that feature and its necessary prerequisites. A feature is not complete merely because an endpoint, screen, or happy path exists.
3. **Verify.** Run all configured repository checks and the feature's required unit, integration, security, concurrency, and browser checks as applicable. Exercise the connected frontend/backend when the feature has a user journey. Fix failures and rerun affected checks. Skipped tests, missing services, untested acceptance criteria, and screenshots alone do not satisfy the gate.
4. **Document and review.** Update the existing feature block in the canonical tracker, `../docs/ui_todos.md`, and `../docs/task_done.md` with actual behaviour, commands/results, remaining limitations, and release implications. Inspect the exact changes to be committed; exclude secrets, local state, test artifacts, and unrelated unfinished work. Do not mark a feature Implemented while required deliverables or acceptance criteria remain incomplete.
5. **Commit and push.** Create a focused commit whose message includes the feature ID in every affected repository, then push to its configured remote and intended branch. Use the owner-requested `dev` branch for development and push to `origin/dev`. Do not merge into `master`/`main` automatically, force-push, or rewrite history. Verify the push succeeded and the remote branch contains the intended commit. Both repositories must pass this gate for a feature that spans them; an unaffected repository needs no empty commit.
6. **Close and advance.** Report the completed feature, verification results, and commit/remote references. Only then begin the next feature. A failed check, incomplete acceptance criterion, failed commit, or failed push leaves the current feature open. Diagnose and fix it; if external input or access is required, report the exact blocker without starting another feature or weakening the gate.

### Existing work and interruptions

- Preserve all existing partial implementation and user changes. Audit it against the feature criteria; do not delete or rebuild working code to create an artificial clean start.
- Several features may already have partial code. That does not authorise continuing them in parallel or labelling a broad initial commit as multiple completed features. Isolate the current feature's deliverable and necessary dependencies; leave unrelated work unstaged.
- Do not commit a broken or incomplete snapshot as a completed feature to satisfy the push requirement. If a clean, self-contained feature commit cannot be made from the existing work, explain the concrete dependency and resolve it within the current gate.
- A user-requested interruption changes the active work as directed. Preserve the unfinished feature's status and resume it before selecting a new feature, unless the user explicitly changes the order or scope.
- Deployment, independent recovery verification, and genuine staff acceptance retain their own criteria. Do not substitute local tests, fabricated records, or developer signatures for external acceptance.

## Stack and structure

- Use Python 3.12 as the initial baseline, FastAPI, Pydantic v2, SQLAlchemy 2 with asynchronous sessions, PostgreSQL, and Alembic migrations.
- Manage Python/dependencies with uv. Commit `pyproject.toml`, `uv.lock`, and `.python-version`; use `uv sync --locked` for reproducible installation.
- Build a modular monolith, not microservices or a general workflow engine. Add domains as needed rather than scaffolding empty future modules.
- Use `app/main.py` for assembly and `app/core/` for configuration, database/session setup, authentication primitives, and domain error handling.
- Use `app/<domain>/` for identity, organisation, vendors, requisitions, authority, approvals, board, evidence, audit, and notifications as implemented. Domain files may include `models.py`, `schemas.py`, `service.py`, `router.py`, and `cruds.py` when a distinct query layer helps.
- Routes are thin. Services own business transitions and transactions. Query helpers never commit independently. Do not recreate generic CrudUtil/Result/decorator frameworks solely to satisfy the superseded notes.
- Put Alembic files under `migrations/` and tests under `tests/<domain>/`.
- Use Ruff for lint/format, mypy for types, and pytest with async support. Document actual setup and commands in the backend README.

## Fixed authority policy

Amounts are NGN; upper limits are inclusive:

| Requester | ₦1–₦5,000,000 | >₦5,000,000–₦100,000,000 | >₦100,000,000–₦500,000,000 | >₦500,000,000 |
| --- | --- | --- | --- | --- |
| Ordinary staff | Own department's HOD | Chief of Staff | MD | Board |
| HOD | Chief of Staff | Chief of Staff | MD | Board |
| Chief of Staff | MD | MD | MD | Board |
| MD | Board | Board | Board | Board |

- Route directly using the higher of the amount requirement and the requester's office-based minimum. There is no sequential HOD → Chief of Staff → MD chain.
- Derive identity, department, entity membership, and appointments from trusted server records, not browser-selected roles or editable profile fields.
- No self-approval, including another account belonging to the same person.
- Only the eligible assigned officeholder may act. Seniority does not grant substitute authority. Check current privileges when the decision commits.
- Missing, inactive, ambiguous, or self-signing assignments block the affected action. Never invent substitutes or absent-officer escalation rules.
- Preserve the policy version and route explanation per submission. No editable approval-threshold administration screen in v1.

Board cases require an actual meeting resolution. The Company Secretary records the outcome, attaches evidence, signs, and submits it. A different individual serving as Board Chairman confirms and signs that exact record or returns it for correction. The Chairman must also differ from the requester. Confirmation preserves the meeting's actual outcome: approval, rejection, deferment, or conditional approval. Unresolved conditions remain a hold; later resolutions follow the same process. No online voting, invented quorum calculation, or unilateral Board approval.

## Money, revisions, and transactions

- Use Decimal and PostgreSQL NUMERIC, never binary floats for money. API monetary values are decimal strings. Reject non-finite values and unsupported currencies.
- Quantities are positive with at most four decimal places; unit prices are nonnegative with at most two. Round each line HALF_UP to two places, then sum. Submission totals must be at least ₦1. Tax/delivery uses explicit cost lines; do not invent tax rates. Recompute totals server-side.
- Freeze submitted revisions, vendor/bank snapshots, attachments, declarations, routing, and signatures. Master-data changes never rewrite previous requests. Account numbers remain strings with leading zeroes preserved.
- Returned requests create successor revisions, fresh signatures, and recalculated routing. Returning a Board record to the Secretary does not open the financial request for edits. Never silently reopen approved/rejected revisions.
- Implement explicit actions using the specification's lifecycle, not writable status/approver fields.
- Commit a business transition, mandatory audit events, and durable delivery intent atomically. An audit failure rolls back the business transition.
- Use expected versions and row locking or equivalent database concurrency controls. Persist idempotency outcomes scoped to actor/operation and bound to payload. Identical retries return the recorded result; different content under the same key conflicts. Never duplicate a signed decision.

## Authentication, authorisation, and evidence

- Provision individual staff accounts by invitation/controlled onboarding. No public sign-up or shared office accounts. Use vetted credential/session libraries, persisted revocation, and expiring single-use recovery tokens.
- Prefer opaque server sessions in HttpOnly, Secure production cookies. Protect cookie-authenticated mutations against CSRF and check allowed origins. Never put credentials in browser storage or staff listings.
- Register fixed `resource:action` permissions centrally. Enforce capability plus record/entity scope on every read/write, search/count, attachment, export, and decision.
- Technical administrators are not financial approvers or unrestricted evidence readers. Protect officeholder appointments separately and prohibit self-grants.
- Signing requires fresh authentication, explicit intent, and capture bound to the actor and exact server content/version. Challenges expire and are single-use; consume them transactionally with the decision. Never automatically apply a saved signature or claim legal certification.
- Keep files private with configurable size/type limits, content validation, safe download names, and the configured malware-check mechanism. Unready evidence cannot be submitted. Authorise object access before issuing short-lived download URLs.
- The owner explicitly approved a single DATABASE_URL for migrations and the application in each environment, including schema-changing runtime permissions. Development and production must use different databases. Preserve append-only audit/signed-evidence triggers and prevent cascade deletion. The shared schema-owner credential can alter or disable protections; do not claim database-enforced isolation from the application credential. Restricted-role tests remain regression coverage for historical grants, not proof of the deployed privilege boundary.
- Document the separate infrastructure-owner trust boundary and protected archive/retention configuration; do not claim absolute immutability from application controls.
- Keep secrets out of source control, logs, fixtures, and screenshots. Provide placeholders in `.env.example`. Redact bank data, signature payloads, and credentials. Do not reuse personal data from the supplied form as seeds.
- Store server timestamps in UTC; display explicit Africa/Lagos context. Meeting dates remain separate from recording/signing timestamps.

## API and operation

- Use `/api/v1` and typed Pydantic models. Reject extra fields on business commands to prevent protected-field mass assignment.
- Use one documented error shape with `code`, safe `message`, optional field errors, and request ID. Preserve the specification's error meanings with appropriate HTTP statuses. No exposed tracebacks.
- Expose OpenAPI for frontend type generation. Scope before pagination/counts. Keep sensitive fields out of broad summaries.
- Use durable outbox/jobs for email, exports, and archives. Retry safely. Notification failure never fabricates an approval or removes in-app work items.
- The owner explicitly requires `scripts/start.sh` to run `alembic upgrade head` before Uvicorn using the same DATABASE_URL as the application. Fail startup if migration fails. MIGRATION_DATABASE_URL is no longer used. This supersedes earlier separate-credential and separate-release-only guidance. Never point development or isolated tests at the production database.
- Require durable PostgreSQL and private evidence storage for production. Document migrations, readiness, workers, backup/isolated restore, and evidence archival. Verify before claiming deployment or protection.
- Approved means authorised, not paid. No payment execution, legacy approval stages, ledgers, or operational Modules 2–4 in this release.

## Delivery and verification

- Implement stable feature IDs in dependency order with meaningful tests and documentation. Keep changes cohesive.
- Follow the mandatory feature delivery gate above. Verify the configured Git remote and branch before committing; preserve unrelated changes. A missing or failing remote blocks advancement to the next feature.
- Put endpoint-consumption notes in `../docs/ui_todos.md` and verified delivery notes in `../docs/task_done.md`, creating these when there is work to record. Update the existing feature blocks in `../docs/implementation_pan.md`; no competing tracker.
- Mark Implemented only after applicable checks actually pass. Distinguish code, testing, deployment, and staff acceptance. Record genuine external blockers precisely and continue independent authorised work.
- Test kobo boundaries, requester floors, wrong-department/cross-entity access, identity-based self-approval, revoked appointments, revision changes, stale/replayed signatures, and concurrent decisions.
- Use real PostgreSQL integration for transactions, migrations, runtime privileges, audit immutability, and races; SQLite/mocks do not prove these guarantees. Cover Board outcomes, corrections, and Secretary/Chairman separation.
- Once configured, checks are `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app`, and `uv run pytest`. Document integration prerequisites; skipped/unavailable integration is not a pass.
- Three genuine staff-operated resolved requisitions are a human acceptance gate. Never fabricate records, impersonate staff, or count fixtures toward it.
