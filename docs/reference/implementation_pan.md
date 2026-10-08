> **2026-10-07 database configuration override:** The owner explicitly approved one DATABASE_URL for migrations and the running application, including schema-changing permissions, per environment. Development and production use different databases. This supersedes earlier separate-runtime/migration credential requirements and elevated-role rejection. History triggers remain; the shared owner credential can alter them, so restricted-runtime isolation is not claimed. Local tests retain their own disposable database infrastructure.

> **2026-10-06 scope update:** The owner limits this release to the 14 reusable screens in [ui_scrrens.md](ui_scrrens.md) and the backend functionality required by them. Older sections below supply supporting rules, not permission to add screens or unrelated modules. Backend implementation statuses are not screen-completion claims. Screens 1–3 map to IAM-001 and web access; 4–8 to requisition/authority and web journeys; 9 to Board/evidence; 10 to VEN-001; 11–12 to IAM/ORG; 13 to audit; 14 to identity/session controls. Notifications are a header drawer and evidence/documents a viewer. Each connected journey retains the test, commit and push gate on dev.

# Custodian by Brendan — Platform Feature Specification

> **Engineering-convention update — 2026-10-06:** The project owner has replaced
> the missing/unrelated AGENTS.md instructions referenced below. Use
> [backend instructions](../bnh-backend/AGENTS.md) and
> [frontend instructions](../bnh-ui/AGENTS.md) for the new projects. Their stack,
> structure, API, testing, documentation, and local delivery conventions supersede
> the historical scaffold, helper/decorator, dependency-script, and mandatory
> develop/merge/push assumptions in this document. There is no existing scaffold
> to preserve. The frontend uses Svelte/SvelteKit with TypeScript, per the
> project owner’s explicit choice. Product rules, stable feature IDs, and acceptance criteria remain
> in force. This file remains the detailed feature tracker; features.md is the
> scope summary. Shared delivery notes belong in docs/ui_todos.md and
> docs/task_done.md relative to the workspace root when created. References to
> “today” below are historical planning context, not a newly agreed deadline.

> **Feature delivery gate — 2026-10-06 (latest owner instruction):** Work on one
> feature at a time in dependency order. Complete its deliverables and acceptance
> criteria, pass every required check, update evidence, then commit and push in
> every affected repository before beginning the next feature. Verify each push.
> Failed checks, incomplete acceptance, or a failed push leave the feature open.
> Existing partial work must be preserved and assessed, not claimed complete.
> This rule supersedes earlier optional-publishing guidance; the detailed workflow
> is in both AGENTS.md files. No mandatory develop branch or automatic merge is introduced.

**Implementation focus:** Module 1 — Requisitions & Delegation of Authority Engine.

**Delivery objective:** Complete the agreed software build today using the existing project scaffold. Work sequentially through the executable features below. A same-day target is not permission to omit controls or claim unperformed acceptance tests.

**Repository companion:** The existing `AGENTS.md` remains authoritative for engineering conventions. This file supplies Custodian's product behaviour and feature tracker; it does not replace that file.

**Tracker location:** Save this document at the Custodian path referenced by the repository's `AGENTS.md` as `features.md`. Preserve the uploaded example separately; do not keep an unrelated product's feature specification as the active tracker.

**Initial assessment:** No implementation has been inspected for this specification. Every feature starts as **Not Assessed**. Reuse existing working implementations where they meet these requirements; do not rebuild them merely to produce new code.

---

# 1. Introduction

## 1.1 Purpose

This Platform Feature Specification defines the first-release capabilities, actors, workflows, approval rules, permissions, validations, interfaces, evidence requirements, test cases, and operational acceptance conditions for Custodian by Brendan.

It follows the supplied feature-document pattern: module overview, Feature ID, Feature Name, Description, Implementation Status, Actors, Workflow, required information, Success Outcome, Audit Records, and Module Success Criteria. Acceptance criteria and dependencies are added to make the document executable by a coding agent.

The existing `AGENTS.md` specifies how code, tests, branches, permissions, activity events, and documentation are delivered. This document specifies what the delivered system must do. Read both before implementing the first feature. Do not begin a separate architecture-review exercise: inspect only the existing code needed to implement and test the selected feature.

## 1.2 Product Vision

Custodian is BNH's shared system for requesting, authorising, recording, and auditing procurement/spend requests and, subsequently, contracts, compliance obligations, and capital movements. It is one system with a shared data foundation, not four disconnected applications.

Today's executable scope is the Requisitions & Delegation of Authority Engine. Its purpose is to route each request to the correct authority, prevent unauthorised and self-approval, preserve the evidence behind each decision, and allow real BNH staff to use the deployed application independently.

The system records financial authorisation. It does not execute a payment, prove payment, confirm receipt of goods, or claim a capital draw has occurred.

## 1.3 Implementation Status Tracking

Use these status values exactly, matching the supplied example:

| Status          | Meaning                                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------- |
| Not Assessed    | The current implementation has not been evaluated against this feature.                           |
| Not Implemented | Evaluation confirmed that this feature has not been implemented.                                  |
| In Progress     | Implementation has begun but the feature has not satisfied all completion requirements.           |
| Implemented     | The specified surface is complete, required tests ran and passed, and evidence/docs are recorded. |
| Blocked         | A documented dependency prevents completion; identify the precise dependency and its owner.       |

Never label a feature Implemented because files exist, a mock responds, a test was written but not run, or the required database integration tests were skipped. Backend/service features can be completed before their separately listed browser features; the whole application cannot be called complete until those browser features and the release gate pass.

Maintain Implementation Evidence and Blocker under each feature. Evidence identifies relevant paths, test commands/results, migration identifiers, and the feature commit or release. Use a stable relative evidence record when the commit identifier is not yet available. Keep feature IDs stable.

## 1.4 Scope Lock

**Build today:** individual staff access; controlled organisation and officeholder mapping; scoped permissions; vendor and bank-detail capture; digital requisitions and cost lines; private attachments; deliberate signature capture; exact authority routing; individual decisions; the Secretary–Chairman Board meeting-resolution process; immutable event history; in-app tasks and basic email notifications; greyscale web screens; a generated requisition document; tests; and a deployable persistent system.

**Do not add:** Accounts Verification, CAO/Admin approval, Finance/Payment sign-off, payment execution, finance ledgers, generic sequential multi-approver chains, written Board resolutions, online Board voting, proxy voting, automatic quorum calculations, purchasing portals, SMS/WhatsApp approvals, AI approvals, automated bank verification, public registration, marketplace functionality, a generic workflow designer, microservices, or a new frontend framework where a frontend already exists.

Modules 2–4 are future operational implementations. Their design-document obligation remains separate; Appendix D preserves the known requirements without turning them into today's feature queue.

## 1.5 Requirement Sources and Precedence

**Confirmed business requirements [C]:** Nasir's explicit decisions in this conversation: amount bands; direct routing; HOD/Chief of Staff/MD requester escalation; no legacy approval stages; Board meeting resolutions only; Company Secretary records; Board Chairman gives the final in-system sign-off; the two people must differ; and no self-approval.

**Supplied engagement requirements [B]:** the shared four-module architecture; real multi-user authentication; enforced authority; persistent storage; signature capture; immutable event log; reachable deployment; three genuine staff-operated resolved requisitions before the defence; the all-four-module design pack; and BNH's visual standard.

**Supplied form [F]:** the information fields in the requisition screenshots. The form's blue formatting and old sign-off path do not override the separate greyscale standard or Nasir's explicit workflow decisions. Blank sample fields do not, by themselves, establish whether those fields are mandatory.

**Repository rules [R]:** the uploaded `AGENTS.md`. Preserve its module layout, `Result[T]`, `CrudUtil`, route decorators, central permission registry, mutation-event pattern, test locations, lockfile/dependency policy, feature-branch process, and documentation requirements.

**Implementation defaults [D]:** the explicit design choices below fill technical detail not fixed by the sources. They are proposed first-release implementation decisions, not claims that BNH has already approved them as governance policy. Implement them consistently for development; obtain the listed owner decisions before using affected features in production.

A newer explicit instruction from Nasir may change scope; record that change. Do not infer a new approval policy from sample data, role names, or an old document. A discrepancy with the full ESE-005 specification must be raised and formally resolved, not silently overridden. ESE-005/ESE-008 have not been supplied in full here.

## 1.6 Explicit First-Release Implementation Defaults

| ID   | Proposed implementation default                                                                                                                                           | Boundary / unresolved input                                                                                                |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| D-01 | NGN-only requisitions. Store money exactly to kobo; send monetary JSON values as decimal strings.                                                                         | Other currencies are rejected until a conversion policy is authorised.                                                     |
| D-02 | Positive quantities with up to 4 decimal places; nonnegative unit prices with up to 2 decimals; round each line HALF_UP to 2 decimals, then sum lines.                    | Document precision limits. Negative/discount lines and specialised pricing need a separate decision.                       |
| D-03 | The approval amount is the final explicitly itemised commitment total. Any tax or delivery amount is an explicit cost line; no automatic tax rates.                       | BNH must confirm this total represents the intended commitment before live use; do not invent tax treatment.               |
| D-04 | Self-service requisition submission only. Store `submitted_by` and `requester_id`, equal in the current UI/API.                                                           | On-behalf-of entry is deferred; never route an MD's request using an assistant's lower position.                           |
| D-05 | Reuse current repository authentication. Use private staff invitations or controlled provisioning; no public sign-up.                                                     | Deployment credentials, account recovery, identity-provider setup, and any MFA enforcement need real configuration.        |
| D-06 | Supply a deliberate signing ceremony with fresh authentication, typed signer confirmation, and signature capture; make drawn capture available.                           | BNH accepts the method before live approval. A typed-only accessibility alternative requires an explicit approved setting. |
| D-07 | Use server UTC timestamps; display date/time with explicit Africa/Lagos context in the initial interface.                                                                 | Do not backdate server events to a meeting date. The legal meeting date is a separate field.                               |
| D-08 | Missing/conflicting authority assignments block the affected action. No automatic substitute, self-approval override, or escalation invented from absence.                | BNH must authorise any acting appointment or exception before it is configured.                                            |
| D-09 | Technical state names and API paths below are implementation contracts; reuse an equivalent existing naming convention when documented.                                   | Business meaning, controls, and visible outcomes cannot change merely to fit a helper.                                     |
| D-10 | Conditional Board approval remains on hold. A later formal resolution, again recorded by the Secretary and confirmed by the Chairman, may clear or replace the condition. | No invented fulfilment verifier or unilateral “conditions completed” override.                                             |
| D-11 | Use the supplied field set with the stage-specific validation in Section 3.3. Basic vendor capture is not vendor certification.                                           | Registration/bank-name differences are review information, not proof of wrongdoing or a new Accounts sign-off tier.        |
| D-12 | No public role/policy builder. Seed the fixed permissions/policy; manage named appointments through an explicitly protected process.                                      | Deployment owner approves named officeholders; ordinary administration cannot grant itself financial authority.            |

These defaults do not authorise spending. Until a required production configuration is supplied, the agent may finish the implementation and staging tests but must report the affected live gate as blocked.

## 1.7 Same-Day Execution Contract

Start with the first feature in document order that is not Implemented. Reuse proven scaffold capabilities, make the smallest changes necessary, and finish each feature with its tests and documentation. Do not pause merely to ask permission for the next routine feature. Do not produce another plan instead of implementing when this file is given to the coding agent.

Follow `AGENTS.md`: develop on the owner-requested `dev` branch; deliver one logical feature with implementation/tests/docs/tracker together; pass required verification, then commit and push to `origin/dev` before the next feature. Do not automatically merge into the default branch. Never remove unrelated work or use destructive Git commands to save time. A unavailable remote or divergent branch is a real blocker to the prescribed Git sequence, not permission to claim a push succeeded.

All executable features below support the selected release. Speed comes from reusing the scaffold and excluding future scope, not bypassing decisions, evidence, or tests. The final staff-acceptance feature necessarily involves BNH people and is not completed by an AI agent alone.

Do not start another unfinished feature behind a Blocked feature contrary to `AGENTS.md`. Record the exact failing prerequisite, finish safe work within the current feature, and provide the smallest actionable unblock request. Avoid manufacturing uncertainty about already confirmed thresholds or roles.

---

# 2. User Types

## 2.1 Requesting Staff Member

Creates and signs their own requisitions, maintains drafts, sees the status and history of their own requests, and revises returned requests. Cannot select a financial approver, alter their department to route a request, or approve their own request.

## 2.2 Head of Department (HOD)

Approves eligible requests from their assigned department only when the total is at most ₦5,000,000 and the requester is not themselves. An HOD's own request goes to at least the Chief of Staff; a higher amount can require MD or Board authority.

## 2.3 Chief of Staff

Approves requests routed to that office under the amount/requester matrix across the approved company scope. Their own request goes to at least the MD, or to the Board when the amount requires it. The role does not automatically replace every HOD.

## 2.4 Managing Director (MD)

Approves requests routed to the MD under the amount/requester matrix. Every MD-originated requisition requires Board approval, regardless of amount. The MD cannot change roles to sign their own Board case.

## 2.5 Company Secretary

Records the formal Board meeting resolution and supporting evidence, signs the record, and submits it to the Chairman. The Secretary is the recorder, not the financial approver. Merely uploading evidence does not approve anything.

## 2.6 Board Chairman

Reviews and signs off the Secretary's recorded Board decision or returns that record for correction. Cannot sign their own requisition, perform both Board roles for one case, rewrite the Secretary's submitted evidence, or substitute their unilateral preference for the meeting's recorded outcome.

## 2.7 System Administrator

Maintains permitted technical and staff settings. This role alone has no requisition-approval authority and no ability to alter approval decisions or audit records. Access to confidential records, bank details, and officeholder administration requires separately scoped permissions.

## 2.8 Authorised Read-Only Reviewer

A proposed optional permission bundle for BNH's independent reviewer. Reads only the authorised scope of records and evidence; cannot mutate decisions. Do not create this as an additional approval step or automatically grant it to every administrator.

## 2.9 System Worker

Performs deterministic routing, scheduled/retried notification delivery, evidence-copy jobs, and export generation. Has no discretionary financial decision-making authority. System-generated events have an explicit system actor, never a fabricated staff signature.

---

# 3. Shared Business Contracts

## 3.1 Authority Matrix — Confirmed

| Requester                               | ₦1–₦5,000,000 inclusive | Above ₦5,000,000–₦100,000,000 inclusive | Above ₦100,000,000–₦500,000,000 inclusive | Above ₦500,000,000 |
| --------------------------------------- | ----------------------- | --------------------------------------- | ----------------------------------------- | ------------------ |
| Staff excluding the officeholders below | Own department's HOD    | Chief of Staff                          | MD                                        | Board              |
| HOD                                     | Chief of Staff          | Chief of Staff                          | MD                                        | Board              |
| Chief of Staff                          | MD                      | MD                                      | MD                                        | Board              |
| MD                                      | Board                   | Board                                   | Board                                     | Board              |

The resolver uses `max(amount_required_authority, requester_minimum_authority)` with the order HOD < Chief of Staff < MD < Board. Ordinary staff have no raised requester floor; HODs have a Chief of Staff floor; the Chief of Staff has an MD floor; the MD has a Board floor.

This ordering is only a routing calculation. It does not grant blanket permission for a more senior user to approve a request assigned to somebody else. Exactly ₦5,000,000 is in the HOD amount band; exactly ₦100,000,000 is in the Chief of Staff band; exactly ₦500,000,000 is in the MD band. Zero, values below ₦1, negative values, unsupported currencies, and non-finite money are invalid at submission.

Use all applicable authenticated requester appointments, not a selected browser role. Reject ambiguous scope rather than choose the least restrictive assignment. Match the requester by staff identity, not display name.

## 3.2 Non-Negotiable Invariants

| ID   | Invariant                                                                                                                                     |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| G-01 | No person approves their own requisition, including through a second role or an administrator account mapped to the same staff identity.      |
| G-02 | Routing is direct to the required authority. No HOD → Chief of Staff → MD chain is added.                                                     |
| G-03 | Requester escalation never reduces the authority required by the amount.                                                                      |
| G-04 | A HOD route must use the submitting requester's recorded department and a valid HOD appointment for it.                                       |
| G-05 | Scope and record-level authority are enforced server-side on every read, mutation, attachment, export, and final decision.                    |
| G-06 | Secretary and Chairman are distinct individuals. Secretary recording alone never approves a Board request.                                    |
| G-07 | Chairman confirmation preserves the actual Board outcome, including rejection, deferment, or conditions.                                      |
| G-08 | Financial content, attachments, and signatures of a submitted revision cannot be silently changed.                                            |
| G-09 | A completed business transition and its mandatory audit event are committed consistently; failed auditing cannot leave an unaudited approval. |
| G-10 | No application role can update, delete, truncate, or rewrite historical event entries, signed decisions, or submitted evidence versions.      |
| G-11 | Exact, server-recomputed money determines routing; browser arithmetic and hidden inputs are not authoritative.                                |
| G-12 | Status changes occur through permitted actions, never a generic writable status or authority field.                                           |
| G-13 | Role revocation, stale versions, duplicate clicks, and concurrent requests cannot leave an unauthorised or contradictory decision.            |
| G-14 | Silence, a reminder deadline, an absent approver, or a failed email never counts as approval.                                                 |
| G-15 | Approved is not Paid, Fulfilled, Disbursed, or Capital Drawn. Those stages are outside this release.                                          |
| G-16 | No legacy Accounts Verification, CAO/Admin, or Finance/Payment route is introduced.                                                           |
| G-17 | No dummy production decisions, fabricated staff sign-offs, seeded “genuine” requisitions, or invented Board resolutions.                      |
| G-18 | Secrets, complete bank details, passwords, OTPs, and signature payloads do not appear in routine logs or public responses.                    |

A requester profile or appointment change while a request is pending must not silently lower its required authority. Preserve routing snapshots. If a relevant change invalidates the current assignment, block that action and require a recorded revalidation; never automatically choose a different person from an unapproved fallback list.

## 3.3 Requisition Information and Validation

The following requiredness is a proposed v1 implementation rule [D-11], not inferred from whether sample cells were filled. Drafts may be incomplete. Submission requires the minimum complete request below; BNH must accept its live validation policy.

| Group           | Fields                                                                                                       | Capture / submission rule                                                                                                                                               |
| --------------- | ------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Identity        | Internal UUID, readable requisition reference, created_at, submitted_at, revision number                     | Generated by server; immutable reference; original creation and each submission timestamp remain distinct.                                                              |
| Organisation    | Requesting entity, department, requester_id, submitted_by, requester position snapshot                       | Server-derived/validated. Entity selected only within authorised membership. Current UI has requester = submitted_by.                                                   |
| Vendor          | Vendor name, contact person, phone(s), email, business address, RC number / ID type                          | Vendor name required; other fields explicit nullable values unless BNH's approved policy requires them.                                                                 |
| Payment details | Bank name, account number as a string, account name, beneficiary-information state                           | Either provide all three bank fields or mark details not yet supplied; do not invent values or mark them verified.                                                      |
| Scope           | Description of work/purchase, location, planned start, planned completion, payment terms, warranty/guarantee | Description and location required. Dates if supplied must be consistent. Payment terms may be specified or explicitly not yet agreed; warranty supports Not applicable. |
| Cost lines      | Item description, quantity, unit price, line total, item order                                               | At least one line; quantity > 0; price >= 0; server calculation; final total >= ₦1.                                                                                     |
| Currency/total  | currency=NGN, grand total, calculation/rounding version                                                      | Server-calculated from all commitment lines; reject unsupported currency and hidden client totals.                                                                      |
| Documents       | Attachment identifiers, versions, original filenames, content hashes, access classification                  | Optional except required Board evidence; invalid/unavailable files cannot be submitted. Malware scanning is deferred for this release by owner decision (2026-10-08).                                                 |
| Declaration     | Accepted wording version, explicit consent, signature evidence reference                                     | Required on every submitted revision. An originator declaration is not financial approval.                                                                              |

A payment account can be captured without creating a payment-processing capability. Show missing/unverified information honestly to the approver. Record differences between vendor and beneficiary names as visible information; do not infer wrongdoing or create an unapproved extra sign-off stage.

Do not reject a legitimate past planned start date merely because the sample contains an already-started purchase. Actual service timestamps are still server-generated. The sample reference/date is not a policy for generating new references.

## 3.4 Request Lifecycle — Implementation Contract

| Current state                     | Permitted action and actor                                                                         | Next state / effect                                                                                                      |
| --------------------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| DRAFT                             | Requester saves permitted fields                                                                   | DRAFT, with optimistic version increment.                                                                                |
| DRAFT                             | Requester submits a complete signed request                                                        | PENDING_AUTHORITY or AWAITING_BOARD_RESOLUTION, assigned atomically.                                                     |
| PENDING_AUTHORITY                 | Exact eligible HOD/Chief of Staff/MD signs Approve                                                 | APPROVED for that exact submitted revision.                                                                              |
| PENDING_AUTHORITY                 | Exact eligible authority signs Reject, with reason                                                 | REJECTED for that revision.                                                                                              |
| PENDING_AUTHORITY                 | Exact eligible authority signs Return for revision, with reason                                    | RETURNED_FOR_REVISION; previous submission/decision preserved.                                                           |
| RETURNED_FOR_REVISION             | Requester creates a corrected successor and signs resubmission                                     | Recalculate route; PENDING_AUTHORITY or AWAITING_BOARD_RESOLUTION.                                                       |
| AWAITING_BOARD_RESOLUTION         | Company Secretary signs/submits the formal meeting record                                          | AWAITING_CHAIRMAN_SIGNOFF; preserve submitted resolution version.                                                        |
| AWAITING_CHAIRMAN_SIGNOFF         | Chairman returns resolution record for correction                                                  | AWAITING_BOARD_RESOLUTION; request content unchanged; returned resolution preserved.                                     |
| AWAITING_CHAIRMAN_SIGNOFF         | Chairman signs confirmation of Board APPROVE                                                       | APPROVED, only if evidence is consistent and there are no unresolved conditions.                                         |
| AWAITING_CHAIRMAN_SIGNOFF         | Chairman signs confirmation of Board REJECT                                                        | REJECTED.                                                                                                                |
| AWAITING_CHAIRMAN_SIGNOFF         | Chairman signs confirmation of Board DEFER                                                         | DEFERRED; this is not a completed approval.                                                                              |
| AWAITING_CHAIRMAN_SIGNOFF         | Chairman signs confirmation of Board CONDITIONAL_APPROVE                                           | CONDITIONALLY_APPROVED; hold remains visible.                                                                            |
| DEFERRED / CONDITIONALLY_APPROVED | Secretary initiates a later formal Board-resolution record for the same unchanged request revision | AWAITING_BOARD_RESOLUTION; retain earlier decision and conditions in history until superseded by confirmed new evidence. |
| APPROVED / REJECTED               | Any attempted financial-content edit or generic re-open                                            | Deny. A genuinely new request is a separate record; no erasure or reused approval.                                       |

`submitted_at`, `last_action_at`, `required_authority`, `assigned_actor`, and `actionability_block_reason` are separate attributes. An invalidated appointment can block an action without falsely changing a genuine Board decision into a different state. No automatic timeout transition grants authority.

A Board request needing a material change cannot be silently edited under an existing resolution. Return the Secretary's evidence for correction when the evidence is wrong; use a new linked requisition for a materially changed commitment. General post-approval amendments and cancellation of an authorised commitment are outside the initial release.

## 3.5 Signing and Concurrency Contract

All signing challenges must bind actor identity, action, request UUID, revision, calculated amount, intended outcome, and the relevant Board-resolution version when applicable. Any reason/condition or signed text belongs to the same bound content. The server generates the challenge and validates the exact content at consumption.

Use fresh authentication for the signing ceremony, an explicit statement of intent, and the configured signature-capture method. Challenges expire and are single-use. Reuse a correctly implemented existing repository mechanism. The time window is a documented deployment setting, not an invented BNH governance rule.

Decision commands supply an expected version and an idempotency key. Repeating the identical action with the same key returns the recorded result without another decision. Reusing the key for different content fails. A stale version or conflicting simultaneous decision fails cleanly; it cannot overwrite the winning decision.

Use a database transaction and row/version protection. Signed business records are append-only; a later view can derive current status from recorded decisions, but no mutation endpoint can rewrite the signed row. Authentication, content hashing, and a drawn signature do not justify claiming an externally certified digital signature or legal approval of the mechanism.

## 3.6 Repository Implementation Rules

Follow the uploaded `AGENTS.md` exactly for the existing backend: Python 3.14, FastAPI, asynchronous SQLAlchemy, PostgreSQL, and uv; modules under `app/{module}/`; `Result[T]` for CRUD; `CrudUtil` for database access; `@router` → `@activity_log` → `@auto_transform` for mutation routes; central `resource:action` permissions; module-owned log events/resolvers; tests under `app/tests/{module}/`; and lockfile-only dependency installation with the supplied dependency-update policy.

For a multi-write business transaction, extend/reuse the repository's supported `CrudUtil` transaction capability rather than bypassing it or committing each row separately. A decorator that logs only after a committed approval does not satisfy G-09; integrate its transaction behaviour or use the documented explicit-audit escape hatch when the decorator cannot express the requirement. Do not double-log a single successful transition.

Do not force the previously proposed Next.js stack onto an existing frontend. Preserve its established framework, components, and test conventions. If the frontend repository is not available, complete the backend features and `ui_todos.md`, but mark the later WEB features blocked rather than claim a working browser application exists.

Proposed paths in each feature are resource contracts, not permission to create duplicate endpoints when equivalent routes already exist. Keep response envelopes and schema names consistent with the scaffold and document any mapping in `ui_todos.md`. File-transfer endpoints must use the repository's established secure file mechanism; do not silently drop required decorators on new metadata or business routes.

## 3.7 Feature Execution Index

The groups below are implementation work areas inside the one Custodian system, not additional BNH product modules. Execute in the following order; the same order appears in the feature sections.

| Order | Feature ID | Feature Name                                                            |
| ----- | ---------- | ----------------------------------------------------------------------- |
| 1     | CORE-001   | Persistent Runtime, Migrations, and Shared Record Conventions           |
| 2     | AUD-001    | Transactional, Append-Only Business Event Infrastructure                |
| 3     | IAM-001    | Individual Accounts, Sign-In, Recovery, and Session Lifecycle           |
| 4     | ORG-001    | Entities, Departments, Staff Profiles, and Controlled Appointments      |
| 5     | IAM-002    | Role Capabilities, Record Visibility, and Current-Authority Checks      |
| 6     | VEN-001    | Vendor Capture, Scoped Lookup, and Beneficiary Versions                 |
| 7     | EVD-001    | Private File Handling and Transaction-Bound Signature Capture           |
| 8     | DOA-001    | Authority Policy v1, Direct Routing, and Self-Request Escalation        |
| 9     | REQ-001    | Draft Requisition, Vendor/Scope Capture, and Exact Cost Breakdown       |
| 10    | REQ-002    | Signed Submission, Immutable Revision, and Automatic Assignment         |
| 11    | APR-001    | Eligible Approver Decisions, Returns, and Signed Resubmission           |
| 12    | BRD-001    | Company Secretary Resolution Recording and Submission                   |
| 13    | BRD-002    | Board Chairman Review, Sign-Off, and Outcome Preservation               |
| 14    | BRD-003    | Resolution Corrections, Deferment, and Conditional Holds                |
| 15    | HIS-001    | Requisition Timeline, Decision History, and Authorised Search           |
| 16    | NOT-001    | In-App Work Items, Basic Email Delivery, and Safe Retries               |
| 17    | DOC-001    | Version-Specific Requisition Document and Approval Record Export        |
| 18    | WEB-001    | Greyscale Application Shell, Sign-In, and Restricted Administration     |
| 19    | WEB-002    | Requester Dashboard, Requisition Form, Signing, and History             |
| 20    | WEB-003    | Individual Approver, Secretary, Chairman, and Reviewer Workspaces       |
| 21    | QA-001     | Integrated Policy, Concurrency, Security, and Browser Acceptance Suite  |
| 22    | OPS-001    | Reachable Deployment, Protected Evidence Archive, and Recovery Handover |
| 23    | UAT-001    | Three Genuine Staff-Operated Requisitions and Acceptance Record         |


Do not infer a separate deployment for each work area. No second implementation-status table is maintained here: each feature block is the canonical progress record.


# 4. Persistent Foundation and Audit Infrastructure

## Module Overview

Establish only the common runtime and evidence capabilities required by Module 1. Reuse the existing scaffold. This is not a task to rebuild its architecture or introduce additional services.

---


## Feature ID: CORE-001

### Feature Name

Persistent Runtime, Migrations, and Shared Record Conventions

### Description

Make the existing backend persist its records in PostgreSQL and establish migration, transaction, configuration, identity-reference, and version conventions used by the remaining features. Deliver a reproducible development runtime without generating unrelated product modules.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Runtime/configuration, dedicated custodian schema, restricted application role, migration 0001, shared identity/version conventions, transactional request dependency, and safe health endpoints implemented. Added fresh-database double-migration, retained-data, app/client restart, API rollback, missing-secret, elevated-role rejection, and unavailable-readiness checks. Full working-tree backend suite: 92 passed; Ruff and mypy passed. Isolated staged feature checkout also passed Ruff, formatting, mypy, and all 11 foundation tests against a fresh local database.

**Blocker:** No implementation blocker. Remote delivery is verified before advancing under the dev-branch gate.

**Single-URL update (2026-10-07):** Owner-approved DATABASE_URL now serves migration and application use per environment. Development and production use separate databases. The previous elevated-role rejection is superseded. Full backend 174 tests and isolated staged 105 tests passed with Ruff, formatting and mypy; deployment environment configuration remains operator-supplied.

### Requirement Basis

[B] Persistent storage and one shared system; [R] existing scaffold; [D] runtime/deployment implementation details.

### Dependencies

No preceding feature; reuse the supplied scaffold.

### Actors

Developer/operator and system services. No public business user is needed for bootstrap.

### Workflow

1. Use the existing environment and lockfile instructions; identify the configured PostgreSQL and migration entry points.
2. Add only missing configuration, migration plumbing, shared version identifiers, and durable transaction/job primitives.
3. Bring up a clean database, apply migrations, run the backend, and verify durable writes across restart.
4. Document the reproducible startup command, required non-secret settings, and the database ownership boundary.

### Required Information

Database connection supplied securely; migration/runtime roles; application environment; object-storage interface settings; stable internal UUID and UTC timestamp conventions; row/revision version field; existing authentication identity reference.

### Business Rules and Validations

- The runtime database role is not a superuser or schema owner; migration privileges are separate.
- Production data is not held only in process memory, browser storage, SQLite, or an ephemeral application volume.
- Migrations preserve existing records. Never drop or reset a live database to make a migration pass.
- Use one shared entity/identity namespace; do not create separate staff tables for HODs, Secretary, and Chairman.
- Provide a transaction boundary usable by business writes and audit writes. Expected failures still return Result[T].
- Secrets stay outside source control, fixtures, command output, and generated documentation.

### API and Interface Contract

Use the existing health/readiness endpoints. Public health responses disclose no connection strings, table contents, or internal credentials. Readiness checks persistent dependencies; liveness does not claim business acceptance.

### Delivery Surface

Runtime/configuration, shared primitives, migrations, automated tests, and operator README. No speculative frontend scaffold is required.

### Success Outcome

The scaffold starts reproducibly and supplies persistent, migration-controlled storage for the next feature.

### Audit Records

- `runtime.configuration_validation.success`
- `runtime.configuration_validation.failure`

### Acceptance Criteria

- [x] A fresh test database migrates successfully and a second application of the migration command is safe.
- [x] A persisted test record survives a service restart and browser/client reconnection.
- [x] Missing production secrets cause a clear failure, not fallback to shared hardcoded credentials.
- [x] Transaction rollback is tested; an expected error cannot commit half a business operation.
- [x] Runtime and migration credentials have documented, distinct privileges.

---


## Feature ID: AUD-001

### Feature Name

Transactional, Append-Only Business Event Infrastructure

### Description

Make mandatory business events durable and non-editable by application users from the first business mutation. Reuse the existing activity-log registry/decorator/resolver model and add only the guarantees needed by Custodian.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Append-only audit_events, durable outbox_items, migration 0002, strict event registry and safe typed metadata, and audited_transaction failure path implemented. Added database concurrency, failure rollback, and separate archive delivery-state tests. Full backend suite: 97 passed; isolated staged checkout: 24 passed (foundation and audit), with Ruff, formatting, and mypy passing in both.

**Blocker:** No implementation blocker. External protected archive delivery remains OPS-001.

### Requirement Basis

[B] Immutable event log; [R] activity logging contract; [D] transactional protection and evidence delivery implementation.

### Dependencies

CORE-001

### Actors

System and restricted operators; an authorised reviewer may later read events through HIS-001.

### Workflow

1. Define the canonical event envelope and register module event namespaces without duplicates.
2. Connect event persistence to the same business transaction used for successful transitions.
3. Apply database privileges and protections that prevent the application role updating, deleting, truncating, or cascading away historical events.
4. Create a durable delivery record for any separately protected evidence copy; keep delivery status outside the immutable event row.
5. Exercise successful, failed, and rolled-back actions using synthetic records.

### Required Information

Event UUID; actor identity/type; relevant office/role snapshot; entity and department scope; resource type/UUID; request and revision UUIDs where applicable; action/outcome; server timestamp; correlation and idempotency identifiers; policy version; safe changed-field metadata; evidence/content digest where relevant.

### Business Rules and Validations

- An approval cannot be acknowledged as complete when its mandatory audit event failed to commit.
- Expected rejected attempts use a separate safe failure-event path when the business transaction rolls back; do not label rolled-back changes successful.
- No user-facing edit/delete event endpoint and no generic CRUD exposure for immutable tables.
- Soft-delete, user deactivation, vendor changes, cascades, and housekeeping jobs must not remove decision evidence.
- Historical event content is never mutated to mark it archived; track that in a separate delivery record.
- Content digests are integrity evidence, not a substitute for access controls or retention protection.
- Do not recursively log an event merely because the event itself was logged. Redact secrets and unnecessary financial personal data.

### API and Interface Contract

Internal event-writing service plus repository-native activity decorators. Read APIs are delivered in HIS-001. Do not create a public event-ingestion endpoint that lets clients impersonate staff.

### Delivery Surface

Internal services/decorators, database protections, event registry/resolvers, unit and PostgreSQL integration tests.

### Success Outcome

Business features can produce consistent, attributable append-only histories. The stronger external archive and recovery proof are verified in OPS-001.

### Audit Records

- `audit.integrity_check.success`
- `audit.integrity_check.failure`
- `audit.protection_check.success`
- `audit.protection_check.failure`

### Acceptance Criteria

- [x] Forced audit-insert failure rolls back the associated test transition.
- [x] UPDATE, DELETE, and TRUNCATE attempts through the runtime database role fail.
- [x] Generic administrative endpoints cannot mutate events or linked signed evidence.
- [x] A duplicate business action does not produce duplicate successful decision events.
- [x] Event registry duplicates are rejected and sensitive values are absent from routine event payloads.

---


## Module Success Criteria

Persistent writes, rollback, migration, and append-only runtime-role protections are demonstrated before business mutations rely on them. External archive verification remains explicitly tracked under OPS-001.


# 5. Individual Staff Authentication

## Module Overview

Provide real individual access using the existing identity implementation. There are no shared role accounts and no public registration. Do not add unrelated credential-claiming, identity-verification, or subscription flows from the example document.

---


## Feature ID: IAM-001

### Feature Name

Individual Accounts, Sign-In, Recovery, and Session Lifecycle

### Description

Allow provisioned BNH users to authenticate, end sessions, and recover access through the repository-supported method. Supply a trustworthy actor identity for all later business operations.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Individual Argon2 accounts, protected provisioning, opaque hashed sessions/CSRF, trusted origins, persisted login/reauthentication throttling, expiry/logout/revocation, and operator-assisted single-use recovery implemented. Full backend checks pass, including 109 tests. Isolated staged checkout also passed 40 tests plus Ruff, formatting, and mypy.

**Account-access extension (screens 1–3):** Email reset and protected invitations now use durable Resend jobs, single-use activation/reset links and session revocation. Pending accounts have no automatic authority and cannot sign in before activation. Browser implementation is recorded under WEB-001. Migration 0010 is required. Verification: full backend suite 168 passed; isolated staged release 99 passed with Ruff, formatting and mypy.

**Deployment limitation:** Resend credentials, a verified sender and live inbox delivery remain to be configured/verified in Render; email defaults off and reports unavailable. Controlled operator recovery remains available. MFA is not implemented.

### Requirement Basis

[B] Real individual authentication; [R] existing user/access-control scaffold; [D-05] provisioning and session details.

### Dependencies

CORE-001, AUD-001

### Actors

BNH staff and authorised account administrators; external identity provider only when already configured for this project.

### Workflow

1. Provision or invite a named user through the protected bootstrap/account flow.
2. User activates their own access through the supported method and signs in.
3. Create a session tied to the individual identity and current account status.
4. Support logout, expiry, revocation, and the existing approved recovery mechanism.
5. Record security outcomes without recording credentials or recovery secrets.

### Required Information

Unique staff/person identity; login identifier; account state; identity-provider identifier or securely handled credential record; invitation/recovery-token metadata; session identifiers/expiry; authentication context needed for signing.

### Business Rules and Validations

- Never ship a shared HOD, Secretary, or Chairman login. Synthetic staging users must be visibly non-production.
- Account activation does not allow a user to select their role, department, or approval threshold.
- Inactive/disabled accounts cannot sign in or act through an existing session. Revocation is checked on sensitive actions.
- Invitation/recovery secrets expire, are single-use where appropriate, and are not returned in ordinary administrative list responses.
- Reuse existing abuse protection, credential handling, and MFA rather than invent a new identity stack for the deadline. Missing operational recovery/MFA configuration must be reported, not represented as working.
- Production MFA/security configuration is an operator decision; fresh authentication for signing remains required by the implementation contract even when ordinary session reuse is allowed.

### API and Interface Contract

Reuse existing authentication/session endpoints. Document sign-in, activation/invitation, current-user, logout, recovery, and revocation contracts in ui_todos.md. A unavailable provider is a deployment blocker, not a reason to expose raw credentials.

### Delivery Surface

Authentication APIs, configuration, security tests, and frontend integration guidance. The browser screens are delivered in WEB-001.

### Success Outcome

Each staff action has an authenticated, independently identifiable actor and a managed session.

### Audit Records

- `authentication.login.success`
- `authentication.login.failure`
- `authentication.logout.success`
- `authentication.session_revoke.success`
- `authentication.recovery.success`
- `authentication.recovery.failure`

### Acceptance Criteria

- [x] Different users obtain different identities and cannot inherit another user's session.
- [x] Invalid credentials, inactive accounts, expired sessions, and revoked sessions fail.
- [x] Logout terminates the applicable session according to the existing authentication contract.
- [x] Recovery replay/expiry tests run when recovery is enabled; unconfigured providers are not mocked into production success.
- [x] Sensitive actions receive the current actor and authentication context server-side.

---


## Module Success Criteria

Distinct named users can authenticate and lose access when revoked; no self-service role assignment or shared role credentials exist.


# 6. Organisation and Officeholder Records

## Module Overview

Maintain the holding-company/subsidiary, department, staff, and named appointment relationships required for deterministic routing. Job titles are descriptive; appointments are the authoritative routing input.

---


## Feature ID: ORG-001

### Feature Name

Entities, Departments, Staff Profiles, and Controlled Appointments

### Description

Provide the smallest complete organisational directory needed to identify the requesting department, legal entity, and people occupying the required offices. Use named, scoped appointments rather than hardcoded person names.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Directory metadata and active state, controlled memberships/transfers, account deactivation with session revocation, effective-dated offices, same-person Board separation, exclusive assignment scope locks, and retained historical references implemented. Sixteen organisation tests and the full backend suite (125 tests) pass. Isolated staged checkout also passed all 56 tests plus Ruff, formatting, and mypy.

**Blocker:** No implementation blocker. Actual BNH entities, memberships and officeholders must be supplied by authorised operators; no production fixtures are seeded.

### Requirement Basis

Confirmed business scope plus the explicitly identified implementation defaults in Section 1.6.

### Dependencies

IAM-001

### Actors

Authorised organisation administrator and system; BNH supplies the actual appointment data.

### Workflow

1. Register the approved BNH entity records and departments.
2. Associate each provisioned person with their approved entity/department profile.
3. Record active HOD, Chief of Staff, MD, Secretary, and Chairman appointments with explicit scope and effective dates.
4. Validate uniqueness and conflicts; record who authorised and applied sensitive assignments.
5. Deactivate or replace records without deleting historical references; make affected pending assignments non-actionable until safely revalidated.

### Required Information

Entity UUID/name/code/type and active state; department UUID/entity/name/code; staff UUID/account reference/department/entity membership; office type; scoped entity or explicit group scope; officeholder identity; valid-from/valid-to; authorisation reference; state.

### Business Rules and Validations

- One active HOD per relevant department/scope; one unambiguous applicable holder for each required executive/Board office. Reject overlapping ambiguous records.
- A holding-company appointment is not silently copied to a subsidiary; group-wide scope must be explicit.
- No self-grant of a financial or Board role through profile edits. Ordinary account administration cannot change protected officeholder mappings.
- The initial officeholder seed comes from BNH-approved inputs, not the example form, guessed names, or synthetic test fixtures.
- A person who holds multiple appointments keeps one identity; those appointments cannot bypass G-01 or G-06.
- Historical requester/department/office snapshots survive transfer and deactivation.
- A director/Chairman-originated request has no invented escalation policy. The confirmed matrix applies where its category is established; any resulting self-sign-off remains blocked.
- Protect sensitive assignment actions with a fixed registered permission available only to approved configuration operators; no editable public role builder.

### API and Interface Contract

Proposed resources: /entities, /departments, /staff, /office-assignments. Use fixed permissions such as entity:list, department:manage, staff:manage, office_assignment:manage, each registered centrally. Restrict mutations to approved operators; document the chosen bootstrap permission arrangement.

### Delivery Surface

Models/migrations, protected directory APIs, seed/configuration command, tests, and endpoint guidance. Administration UI is covered by WEB-001.

### Success Outcome

Every eligible request can be resolved to a unique authorised person or an explicit, visible configuration blocker.

### Audit Records

- `organisation.entity_create.success`
- `organisation.department_update.success`
- `staff.profile_update.success`
- `office_assignment.create.success`
- `office_assignment.change.success`
- `office_assignment.change.failure`

### Acceptance Criteria

- [x] Two departments with different HODs resolve correctly.
- [x] Overlapping appointments, invalid entity/department links, and same-person Board-role conflicts are detected.
- [x] A staff profile PATCH cannot change its own office, role, or routing authority.
- [x] A deactivated officeholder cannot use an old session to sign a pending request.
- [x] Historical requests continue to show the appointments and department present at submission.

---


## Module Success Criteria

Approved organisational mappings exist without guessed identities, ambiguous authorities, self-grant paths, or deletion of historical references.


# 7. Scoped Authorisation

## Module Overview

Use the repository permission registry as the capability gate and add resource-specific business eligibility. A resource:action permission is necessary but is not sufficient to approve any arbitrary requisition.

---


## Feature ID: IAM-002

### Feature Name

Role Capabilities, Record Visibility, and Current-Authority Checks

### Description

Implement a consistent server-side access policy for requests, decisions, attachments, exports, and administration. Reuse it in every subsequent route rather than relying on frontend visibility.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Shared scoped SQL predicates and action/evidence guards, fixed capability registry, current-authority checks, safe capability APIs, explicit entity review grants, read-only account mode, bank redaction, and denial audits implemented. Full backend suite passes 131 tests; isolated staged checkout passes all 62 tests, Ruff, formatting, and mypy. Requisition/evidence model contracts are included as required scope inputs; uploads and business transitions retain their separate feature gates.

**Blocker:** No implementation blocker. Later file-transfer/export/business-action APIs must reuse these guards and pass their own integrated feature criteria.

### Requirement Basis

Confirmed business scope plus the explicitly identified implementation defaults in Section 1.6.

### Dependencies

ORG-001

### Actors

All authenticated users; system; authorised configuration operators.

### Workflow

1. Register the fixed Custodian permissions in PERMISSION_REGISTRY.
2. Map approved roles to the minimum capability bundles.
3. Implement reusable resource-scope and office-eligibility checks.
4. Test ownership, department/entity boundaries, deactivation, and privilege changes through direct API/service calls.
5. Expose only safe effective capabilities for the UI to display; retain full enforcement server-side.

### Required Information

Actor identity/current account state; registered permissions; entity/department membership; scoped appointments; request ownership; required authority; assignment; current revision/state; signer/recorder identities.

### Business Rules and Validations

- Requesters read their own requests, not every request in their department.
- HODs see/act on records within their approved department and assigned workflow scope. Executive access is explicitly scoped, never implicitly global.
- Secretary/Chairman Board queues expose relevant Board cases, not unrestricted bank information for all requests.
- Read-only reviewer access is optional and explicitly granted. System Administrator is not a universal financial superuser.
- An administrator cannot use generic model endpoints to change required authority, requester identity, decision, signature, or status.
- List totals, search results, dropdowns, attachment URLs, and exports use the same scope as record details.
- Re-check current privileges at signing time. Do not trust role claims solely because a long-lived token once contained them.

### API and Interface Contract

Use HasPermission at route level plus shared object-scope/business eligibility checks. Proposed capabilities are listed in Appendix A; actual identifiers must be registered in the existing central registry. Permission-management API access alone cannot grant protected financial appointments.

### Delivery Surface

Reusable permission/scope services, registry entries, dependency guards, negative API tests, and documented role/capability mapping.

### Success Outcome

Every later feature can enforce both capability permissions and correct record-level authority.

### Audit Records

- `access.permission_change.success`
- `access.permission_change.failure`
- `access.denied.failure`

### Acceptance Criteria

- [x] Direct API attempts against another staff member's request and another entity's attachment are denied.
- [x] A read-only reviewer cannot decide, record, or amend any request.
- [x] A more senior role cannot arbitrarily approve a lower-tier-assigned request.
- [x] Changing a client-visible role or permission array does not change server authority.
- [x] Sensitive-data projection and authorised lists use consistent scope.

---


## Module Success Criteria

Unauthorised reads and decisions fail at the API/service boundary regardless of UI state or apparent seniority.


# 8. Basic Vendor and Beneficiary Records

## Module Overview

Capture the vendor information needed for a requisition while establishing a reusable counterparty identity for the later contract module. Do not build the full vendor-intelligence product today.

---


## Feature ID: VEN-001

### Feature Name

Vendor Capture, Scoped Lookup, and Beneficiary Versions

### Description

Let an authorised requester select an existing vendor or capture the details needed for a new requisition. Preserve the exact vendor and beneficiary information that a submitted revision used.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Reusable entity-scoped vendors, paginated safe summaries, contact/beneficiary history, all-or-none bank validation, immutable version storage, current-version concurrency and unchanged submitted snapshots implemented. Screen 10 adds scoped search and add/detail/edit drawers with server capabilities, redaction and conflict handling. Full backend 144 tests, isolated staged backend 75 tests, staged frontend 3 unit tests and 1 real-backend browser journey pass; lint, formatting, types and production build pass. Desktop/mobile screenshots inspected. No Render deployment or staff acceptance is claimed.

**Blocker:** No implementation blocker. Request-form lookup integration is WEB-002; creation of a vendor is not beneficiary verification.

### Requirement Basis

[F] Section A vendor/bank fields; [B] shared counterparties; [D-11] requiredness and versioning details.

### Dependencies

IAM-002

### Actors

Requesting staff; authorised vendor administrators; eligible approvers read the submitted snapshot.

### Workflow

1. Search permitted vendor summaries and select a vendor, or create a basic record.
2. Capture contact, registration/identification, address, and bank details as available.
3. Validate formats and all-or-none bank fields; flag incomplete information visibly.
4. Create a versioned vendor/beneficiary snapshot for later requisition submission.
5. Record subsequent master-data changes without modifying earlier request snapshots.

### Required Information

Stable vendor UUID; name; contact person; phone list; email; business address; registration number / identification type; bank name; account number string; account name; completeness state; version identifiers; entity-use permissions.

### Business Rules and Validations

- Basic capture is not a verification certificate. Do not create a verified badge without a real authorised verification record.
- Do not expose all vendor bank accounts in a searchable dropdown. Return only permitted summary fields.
- Account numbers remain strings, preserving leading zeroes. Do not infer unsupported bank validation rules.
- Different vendor/account-holder names are displayed for review; no automatic fraud conclusion or new Accounts stage.
- A bank-detail change never updates a pending or approved requisition in place. A materially changed beneficiary requires fresh request review.
- No automatic merge based solely on similar vendor names; use a stable UUID.
- No vendor deletion may cascade into submitted requests or evidence.

### API and Interface Contract

Proposed resources: GET/POST /vendors, GET/PATCH /vendors/{uuid}, restricted beneficiary-version retrieval. Permissions: vendor:list, vendor:create, vendor:update, vendor:read_sensitive. Ensure normal response schemas do not reveal fields simply because the ORM relation is loaded.

### Delivery Surface

Screen 10 Vendors and its supporting APIs, including search, add/detail/edit drawers, scoped bank access and version conflict handling. Request-form lookup is integrated separately within screen 6 (WEB-002).

### Success Outcome

Staff can capture or reuse vendor information without sacrificing the historical payment-detail snapshot.

### Audit Records

- `vendor.create.success`
- `vendor.update.success`
- `vendor.update.failure`
- `vendor.beneficiary_version_create.success`

### Acceptance Criteria

- [x] Lookup results omit unauthorised bank details.
- [x] Partial bank triples fail or remain explicitly absent according to the agreed schema; no fabricated values.
- [x] Leading zeroes survive save/reload.
- [x] Changing a vendor record does not change an already stored test submission snapshot.
- [x] Duplicate-name vendors are not automatically treated as one counterparty.

---


## Module Success Criteria

Vendor data is reusable, permission-scoped, and historically stable without claiming vendor certification or payment execution.


# 9. Private Attachments and Signing Evidence

## Module Overview

Provide common evidence infrastructure for originator declarations, individual approvals, Secretary records, and Chairman sign-off. Do not treat a pasted signature image as an independently authenticated decision.

---


## Feature ID: EVD-001

### Feature Name

Private File Handling and Transaction-Bound Signature Capture

### Description

Support safe private evidence uploads and a deliberate, server-validated signing ceremony. The signed record identifies the actor and exact content and cannot be silently rebound to another request or decision.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Private Cloudinary authenticated-raw upload/download adapter, scoped metadata and viewer, bounded PDF/PNG/JPEG validation, no-scanner release policy, version invalidation and frozen submission manifests. Fresh-authenticated drawn signing binds identity, declaration, scope, exact content and evidence; signature expiry is rechecked after provider reads. Migration 0011 protects frozen attachment metadata. Private-provider HTTP contracts and errors are tested separately from explicit isolated browser storage fixtures. Exact staged release passed Ruff/format/mypy, 208 backend tests on fresh local PostgreSQL, frontend lint/format/types, six unit tests, production build and all fifteen browser journeys (2026-10-08). Publication is recorded by the feature commits on origin/dev.

**Attachment layout refinement (2026-10-08):** Supporting-document rows use a truncated filename with a full-name tooltip, file icon/type/size, and compact View/Remove actions. Full filenames remain in accessible button labels and the private viewer. Actions align to the right on desktop and beneath the filename on narrow screens, retaining 44px touch targets. Requisition detail grid tracks are allowed to shrink so document rows and cost tables stay within the mobile page. API behavior, confirmation, permission checks and frozen-evidence controls are unchanged.

**Blocker:** Live Cloudinary credentials/account behavior and BNH signature-method acceptance remain deployment/acceptance checks, separate from local implementation verification.

### Requirement Basis

[B] Signature capture and immutable evidence; [F] originator/approval signatures; [D-06] signing implementation requiring BNH acceptance.

### Dependencies

IAM-002

### Actors

Authenticated requesters/approvers/Secretary/Chairman within scope; system storage services.

### Workflow

1. Authorise a scoped upload and validate the allowed file kind, size, content, and filename.
2. Reject unsupported or invalid content; mark a file usable only after server-side type, size, content and filename validation and successful private storage. Malware scanning is deferred for this release; scanner availability is not a readiness or submission gate.
3. Generate a server challenge for the exact signing intent and content digest.
4. Require fresh authentication, explicit consent, signer confirmation, and the configured signature-capture method.
5. Consume the challenge once as part of the business transaction and store immutable signing evidence.
6. Authorise every evidence access; retain the exact object version used by submitted records.

### Required Information

Attachment UUID, scoped owner/resource, safe storage key and immutable object version, original filename, media type, size, digest, validation state; signature evidence UUID; actor; intent; resource/revision; payload digest; auth context; challenge expiry/use metadata; captured representation; signed_at.

### Business Rules and Validations

- Private evidence is not served from a public static directory or predictable public URL.
- Signature capture supports the required drawn representation and explicit signer identity; an approved typed-only alternative must be deliberately configured, never silently substituted.
- No stored signature asset is automatically applied to future decisions. Every signing action requires explicit consent for its bound content.
- An expired, reused, wrong-actor, wrong-action, or wrong-version challenge fails.
- Do not accept a client-supplied content digest as proof of what was reviewed; recompute from the server snapshot.
- No successful upload/validation check is simulated when the configured private storage provider is unavailable. The affected evidence path stays blocked.
- Storage decision (owner, 2026-10-08): use the existing Cloudinary account with authenticated raw assets and application-authorised downloads. Keep credentials on the backend.
- Release decision (owner, 2026-10-08): do not implement or deploy a document malware scanner in this release. Preserve private storage, scoped access, file type/size/content validation, safe download names, hashes and immutable submitted evidence. Record scanning as not performed; do not label files malware-free, scanned or virus-checked. Basic validation does not detect malware. A future scanning feature is deferred, not implemented or a release prerequisite.
- Removing an unused draft attachment may detach it, but evidence referenced by a submitted version cannot be overwritten or removed.
- File validation/signature-method limits are documented settings; do not invent legal certification claims.

### API and Interface Contract

Use repository-native private upload/download mechanisms. Proposed metadata/challenge endpoints: POST /attachments, GET /attachments/{uuid}/access, POST /signing-challenges. Each business action consumes its challenge; there is no public “sign as user” endpoint. Document response wrappers and secure binary-transfer integration.

### Delivery Surface

Private file and signature services/APIs, safe storage integration, validation tests, and UI signing contract. Native capture UI appears in WEB-002/WEB-003.

### Success Outcome

Business workflows can collect private attachments and attributable signature evidence for a precise version.

### Audit Records

- `attachment.upload.success`
- `attachment.upload.failure`
- `attachment.validation.success`
- `attachment.validation.failure`
- `signature.challenge_create.success`
- `signature.capture.success`
- `signature.capture.failure`

### Acceptance Criteria

- [x] Unauthorised download and upload-to-another-request attempts fail.
- [x] Unsupported, oversized, malformed or unavailable uploads cannot enter a signed submission; valid privately stored files do not require malware scanning in this release.
- [x] Attachment state and UI copy distinguish completed basic validation from malware scanning, which is not performed in this release.
- [x] Signature replay, wrong actor, expired authentication, and altered request content fail.
- [x] An authorised signing action binds the intended version and a subsequent file replacement does not change it.
- [x] A missing signature-method approval is reported separately from completed staging implementation.

---


## Module Success Criteria

Only authorised users can use private evidence, and each deliberate signature is bound to its exact content rather than a reusable image alone.


# 10. Delegation of Authority Engine

## Module Overview

Implement the confirmed matrix as a deterministic, independently tested business component. Routing cannot depend on a frontend dropdown, displayed job title, or optional warning.

---


## Feature ID: DOA-001

### Feature Name

Authority Policy v1, Direct Routing, and Self-Request Escalation

### Description

Calculate the required approval authority from the exact NGN total and the requester's verified appointments, then identify the applicable officeholder. Return a clear explanation and policy version with the route.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Exact decimal Authority Policy bnh-doa-v1, inclusive kobo boundaries, all sixteen requester/amount cells, highest-office floor, department-scoped HOD and current assignment checks. Read-only/inactive officeholders are excluded and account/appointment eligibility is locked for decisions. Preview and submission share server rules; immutable revision context preserves offices and routing. tests/authority and tests/requisitions cover the sample total, boundaries, self-request escalation, assignment blockers and forged fields. Exact staged release passed Ruff/format/mypy, 208 backend tests on fresh local PostgreSQL, frontend lint/format/types, six unit tests, production build and all fifteen browser journeys (2026-10-08). Publication is recorded by the feature commits on origin/dev.

**Blocker:** Live Cloudinary credentials/account behavior and BNH signature-method acceptance remain deployment/acceptance checks, separate from local implementation verification.

### Requirement Basis

[C] Exact authority matrix and direct/self-request routing; [D] named policy version and implementation representation.

### Dependencies

ORG-001, IAM-002

### Actors

System; requesters and authorised approvers may view their request's routing explanation.

### Workflow

1. Validate an exact positive submission amount and supported currency.
2. Resolve the amount band using the inclusive boundaries in Section 3.1.
3. Determine the highest applicable requester floor: HOD→Chief of Staff; Chief of Staff→MD; MD→Board.
4. Select the higher required authority, scope it to the correct company/department, and resolve the unique appointment.
5. Apply identity and assignment conflict checks, returning a typed blocker where needed.
6. Return the immutable policy identifier, routing reason, authority, scope, and assignment result.

### Required Information

Server-validated amount; currency; requester/person UUID; applicable requester-appointment snapshot; department/entity; current officeholder mappings; policy identifier/version; minimum authority and explanation.

### Business Rules and Validations

- Exact user-supplied thresholds are mandatory; no editable threshold settings screen in v1.
- The department matters to the HOD route; it does not alter the Chief of Staff/MD/Board amount bands.
- A HOD's ₦200 million request goes to the MD; a Chief of Staff's ₦600 million request goes to the Board; an MD's ₦1 request goes to the Board.
- Direct routing means no preliminary HOD approval for a ₦25 million staff request.
- The Board result is a collective-authority route; it does not reduce to a shared user. Downstream recording/sign-off uses the Secretary and Chairman.
- Policy versions are preserved per submission. Pending requests cannot be silently rerouted to a lower level by editing an appointment/profile.
- No use of binary floating-point for policy boundaries or conversion of an unsupported currency under NGN thresholds.

### API and Interface Contract

Primary surface is an internal authority resolver. A scoped preview endpoint may return a route explanation but cannot authorise or persist a decision. Submission in REQ-002 always recomputes the route server-side.

### Delivery Surface

Versioned policy definition, pure routing logic plus assignment checks, tests, and module README. No general workflow engine.

### Success Outcome

The exact confirmed authority is returned consistently for every valid amount/requester combination.

### Audit Records

- `authority.route_resolve.success`
- `authority.route_resolve.failure`

### Acceptance Criteria

- [x] All sixteen matrix cells pass parameterised tests.
- [x] Tests include one kobo below, exactly at, and one kobo above every threshold.
- [x] HOD department mismatch and multiple overlapping executive assignments produce explicit denial/blockers.
- [x] Role-switching cannot avoid an MD or HOD requester floor.
- [x] The resolver works in a service test without a browser, and APIs cannot override its result.

---


## Module Success Criteria

Every confirmed amount/requester rule passes independent tests, and invalid/ambiguous routing fails closed without lowering authority.


# 11. Requisition Capture and Submission

## Module Overview

Digitise the supplied BNH requisition content while replacing its legacy approval path. The stored structured record is the source of truth; a generated document is a representation of a specific recorded version.

---


## Feature ID: REQ-001

### Feature Name

Draft Requisition, Vendor/Scope Capture, and Exact Cost Breakdown

### Description

Allow a requester to create, resume, and update a draft containing the supplied form's business information. Calculate the financial commitment consistently and make server-controlled identity/status fields non-writable.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Screens 5–7 support scoped search/status/pagination, incomplete persisted drafts, versioned vendor selection or manual capture, all scope/date/term/cost fields and private attachments. The server supplies identity/department/reference, exact line rounding and totals. Creation retries are idempotent; stale saves preserve UI edits. Tests cover all-field round trips, immutable vendor provenance, restricted-bank omission, concurrent saves, the six-line 71640.00 sample and recovery through a new application/connection pool. Exact staged release passed Ruff/format/mypy, 208 backend tests on fresh local PostgreSQL, frontend lint/format/types, six unit tests, production build and all fifteen browser journeys (2026-10-08). Publication is recorded by the feature commits on origin/dev.

**Blocker:** Live Cloudinary credentials/account behavior and BNH signature-method acceptance remain deployment/acceptance checks, separate from local implementation verification.

**Saved-draft refresh repair (2026-10-08):** The owner requires saved requests to survive refresh before Review & Submit, including when no HOD is appointed. A browser regression reproduced a save/navigation gap: POST committed successfully, but a delayed detail read left the browser at /requisitions/new, so refresh reopened a blank form. Successful creation now replaces that history entry with the saved record's permanent URL through a document navigation; its detail page reloads the persisted API record and confirms Draft saved. The form awaits asynchronous save-completion callbacks. The regression verifies three saved cost lines, refresh during delayed detail loading, history navigation, saved edits and the missing-HOD submission block. The earlier account-switch inference is not treated as the cause. No schema, authority or draft-visibility change is required; verify the updated frontend after deployment.

### Requirement Basis

[F] Requisition header and Sections A–C; [C] replacement approval policy; [D-01–04, D-11] capture and validation choices.

### Dependencies

VEN-001, EVD-001, DOA-001

### Actors

Authenticated requesting staff, including officeholders raising their own requests.

### Workflow

1. Create a draft for the authenticated requester and an authorised entity.
2. Populate department from the controlled profile and allocate a unique readable reference.
3. Select/capture vendor details, scope, dates, terms, warranty, cost lines, and permitted attachments.
4. Validate supplied values and calculate each line and grand total on the server.
5. Save the draft with optimistic concurrency; retrieve it from another session/device.

### Required Information

All Section 3.3 fields; draft row_version; stable requisition UUID/reference; vendor and beneficiary references; item order; explicit missing-information states.

### Business Rules and Validations

- Drafts can be incomplete, but malformed supplied values still fail validation. Submitted states cannot use this draft edit endpoint.
- Choose a stable server-generated reference format using a database-safe sequence; document it as an implementation default. Do not reuse the screenshot's identifier.
- Requester, submitted_by, department eligibility, required authority, decision, totals, and state cannot be overwritten through untrusted generic input.
- Follow D-02: positive quantity, nonnegative unit price, exact per-line rounding, then sum. Include every intended charge as an explicit line under D-03.
- Return computed totals even when the browser already calculated a preview. Reject an inconsistent client total instead of trusting it.
- Preserve account numbers as strings and show unknown terms/details as unknown, not silently verified.
- Duplicate HTTP retries with the same creation key do not create two drafts. Separate intentional new requests get separate references.
- Do not introduce payment-status, Accounts Verification, or CAO/Admin fields.

### API and Interface Contract

Proposed actions: POST /requisitions; GET /requisitions/{uuid}; PUT /requisitions/{uuid}/draft; GET /requisitions with server-enforced actor scope. Reuse the existing paging/filter envelope. Detail responses include computed totals, safe validation feedback, row_version, and server-derived allowed actions.

### Delivery Surface

Models/migrations, schemas, draft APIs, calculation tests, and full endpoint guidance. The form UI is separately verified in WEB-002.

### Success Outcome

A staff member can persist and resume a correctly calculated draft containing BNH's requisition information.

### Audit Records

- `requisition.draft_create.success`
- `requisition.draft_update.success`
- `requisition.draft_update.failure`

### Acceptance Criteria

- [x] Save/reload preserves all form sections, item ordering, and explicit unknown states.
- [x] The sample six unit-quantity costs 2890, 3400, 7450, 1400, 27500, and 29000 total exactly ₦71,640.
- [x] Zero/negative quantity, unsupported precision, non-finite prices, and tampered server-controlled fields fail.
- [x] Two editors using the same stale row_version cannot silently overwrite each other.
- [x] Draft data survives restart and cannot be read/edited by an unrelated requester.

---


## Feature ID: REQ-002

### Feature Name

Signed Submission, Immutable Revision, and Automatic Assignment

### Description

Turn a complete draft into a signed, versioned request routed by Authority Policy v1. Persist the reviewed financial content, declaration, route, and mandatory events consistently.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Signed submission freezes revision content, vendor provenance, identities/scope, requester offices, declaration/authentication evidence, file versions/hashes and policy route. Signature, submission/routing audit and durable notification intent commit atomically. Tests cover retries, races, wrong-actor challenges, expired/stale content, provider failures and rollback. Staff enter PENDING_AUTHORITY directly; low-value MD requests enter AWAITING_BOARD_RESOLUTION without a fabricated Board outcome. Exact staged release passed Ruff/format/mypy, 208 backend tests on fresh local PostgreSQL, frontend lint/format/types, six unit tests, production build and all fifteen browser journeys (2026-10-08). Publication is recorded by the feature commits on origin/dev.

**Blocker:** Live Cloudinary credentials/account behavior and BNH signature-method acceptance remain deployment/acceptance checks, separate from local implementation verification.

### Requirement Basis

[C] routing and no self-approval; [B] signature/evidence and staff use; [F] originator declaration; [D] atomic/versioned implementation.

### Dependencies

REQ-001

### Actors

Authenticated requester and system.

### Workflow

1. Requester reviews the current server-rendered totals, vendor/beneficiary details, scope, and declaration.
2. Validate the submission requirements, current profile, evidence availability, and exact expected draft version.
3. Obtain and consume a signature challenge for this submission and declaration.
4. Create an immutable submitted revision containing the content and attachment/version manifest.
5. Recompute the authority route and persist the assignment and transition to the applicable queue.
6. Write the submission/routing events and durable notification event intent in the same successful transaction.

### Required Information

Draft UUID/expected version; submission idempotency key; signed declaration text/version; signature evidence; content/attachment manifest; policy version; requester/department/office snapshot; total; assigned authority and actor/scope; submitted_at.

### Business Rules and Validations

- The signed declaration is the supplied confirmation that information is correct and work will be completed as specified; any wording change is versioned and approved.
- Submitting an HOD/MD request is not approving it. Originator signature has a distinct intent.
- Failure to resolve a required officeholder prevents submission from falsely entering an actionable queue; return a specific blocker and preserve the draft.
- Freeze all material submitted content. Later master-data edits do not change what was submitted.
- No partial commit where a request is submitted without its required signature, route, or audit event.
- A valid repeated submission key returns the existing result; changed payload under that key fails.
- The Board queue is represented by AWAITING_BOARD_RESOLUTION; no Secretary or Chairman action is fabricated during submission.
- The recorded request amount cannot be changed later merely because a resolution or approver names a different figure.

### API and Interface Contract

POST /requisitions/{uuid}/actions with action=submit, expected_version, idempotency_key, and signing challenge/capture. The server returns the submitted revision, policy version, route explanation, current state, and next actor/office. There is no writable approver_id or submitted_total override.

### Delivery Surface

Submission API/service, immutable revisions, transactional tests, and frontend review/sign contract.

### Success Outcome

A signed, immutable request revision is assigned directly to the correct authority with a traceable routing explanation.

### Audit Records

- `requisition.submit.success`
- `requisition.submit.failure`
- `requisition.route_assign.success`

### Acceptance Criteria

- [x] Incomplete/invalid drafts cannot submit and remain safely editable.
- [x] Signature/content tampering and stale draft versions fail.
- [x] Each requester category enters the correct queue, including a low-value MD request entering the Board queue.
- [x] Forced signature/audit/route persistence failure leaves no partly submitted request.
- [x] Submitted item, beneficiary, requester, and attachment content cannot be patched by any ordinary CRUD endpoint.

---


## Module Success Criteria

Staff can persist a structured draft and submit a signed immutable revision to the exact authority. The legacy paper approval sequence is absent.


# 12. Individual Approval and Request Revision

## Module Overview

Handle HOD, Chief of Staff, and MD decisions without cascading through lower offices. The person reviewing a request is not allowed to rewrite its financial content.

---


## Feature ID: APR-001

### Feature Name

Eligible Approver Decisions, Returns, and Signed Resubmission

### Description

Provide the three individual authorities with a scoped inbox and transaction-bound approve/reject/return actions. Preserve the earlier version and decision when a returned request is corrected and resubmitted.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

Confirmed business scope plus the explicitly identified implementation defaults in Section 1.6.

### Dependencies

REQ-002

### Actors

Assigned HOD/Chief of Staff/MD; requesting staff for corrections; system.

### Workflow

1. Eligible approver retrieves the assigned current revision and its supporting evidence.
2. Server checks live identity, appointment, scope, state, policy, and no-self-approval conditions.
3. Approver selects Approve, Reject, or Return for revision and signs the exact action; rejection/return includes a reason.
4. Commit the permitted transition and immutable decision record with its mandatory event.
5. For a returned request, the requester creates a successor draft/revision with the earlier record preserved.
6. On resubmission, require a new declaration/signature and recompute routing from the revised total and requester policy.

### Required Information

Request UUID/submitted revision/expected version; actor and current appointment; action; reason/comment; signing evidence; idempotency key; signed_at; return history; linked successor revision.

### Business Rules and Validations

- Only the specifically eligible assigned officeholder may act; broad permissions or seniority do not create a substitute.
- No self-approval by identity. No client action can select a different required authority.
- The approver cannot amend the amount or vendor before signing. Return the request instead.
- A return is not a rejection or a completed authorisation. Do not count it as a resolved genuine case.
- The requester can edit only the new working revision after return; the prior signed snapshot remains immutable.
- A request changing from ₦4 million to ₦8 million is rerouted to at least the Chief of Staff and does not keep the HOD's earlier approval.
- Concurrent approve/reject commands and repeat clicks produce at most one valid final decision for a revision.
- No bulk approve-all endpoint in this release. Each decision requires review of its own bound content.

### API and Interface Contract

GET /approvals/inbox; POST /requisitions/{uuid}/decisions with approve|reject|return and version/challenge/idempotency fields; POST /requisitions/{uuid}/revisions for an authorised returned state; reuse draft/submit contracts for the successor. Exclude Board-level decisions from the individual decision route.

### Delivery Surface

Inbox/decision/revision APIs, concurrency tests, and UI integration guidance. Approver pages are delivered in WEB-003.

### Success Outcome

Individual decisions are authorised, signed, and immutable; corrections receive fresh review at the recalculated authority.

### Audit Records

- `approval.approve.success`
- `approval.reject.success`
- `approval.return.success`
- `approval.decision.failure`
- `requisition.revision_create.success`
- `requisition.resubmit.success`

### Acceptance Criteria

- [ ] Correct authority succeeds; wrong department, wrong band, self, inactive officeholder, and stale role fail.
- [ ] Rejection/return without a reason fails.
- [ ] Only one of two conflicting concurrent decisions commits.
- [ ] Identical retries return the original decision without another signature/event.
- [ ] A returned request crossing a threshold goes to the new correct authority with a fresh signed revision.
- [ ] An approved/rejected revision cannot be silently reopened or rewritten.

---


## Module Success Criteria

Eligible individuals can approve, reject, or return their assigned requests, and revised content never inherits unrelated previous authorisation.


# 13. Board Meeting Resolution and Chairman Sign-Off

## Module Overview

Implement the selected two-person recording/sign-off process. It is not online Board voting, written-resolution circulation, or permission for two people to invent a collective Board decision.

---


## Feature ID: BRD-001

### Feature Name

Company Secretary Resolution Recording and Submission

### Description

Let the Company Secretary record the actual Board meeting outcome for an eligible request, attach authenticated supporting evidence, and sign the record for Chairman review.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

[C] Board meetings only, Secretary records, Chairman signs off; [D] metadata and evidence validation without invented legal decision rules.

### Dependencies

APR-001

### Actors

Company Secretary within the relevant Board/entity scope; system.

### Workflow

1. Open a request awaiting a Board resolution and identify the relevant entity/Board.
2. Record the actual meeting date, resolution reference, outcome, authorised amount where relevant, attendance/quorum attestation, and any conditions.
3. Attach the formal resolution or permitted authenticated minutes extract.
4. Check that the recorded scope and amount correspond to the immutable requisition revision; identify discrepancies without changing the request.
5. Secretary reviews and signs the complete resolution-record version.
6. Submit it to AWAITING_CHAIRMAN_SIGNOFF with immutable evidence and a work-item event.

### Required Information

Board case UUID; request/revision; entity/Board identity; meeting date; resolution reference; decision text; outcome enum APPROVE/REJECT/DEFER/CONDITIONAL_APPROVE; amount/currency when authorised; conditions; participant/attendance note; quorum confirmation and basis/reference; evidence attachment/version; recorder identity and signature; recorded_at/submitted_at.

### Business Rules and Validations

- Only the assigned Company Secretary can record/submit; the Chairman cannot impersonate the Secretary.
- The Board meeting date is distinct from the recording timestamp. A future meeting is not recorded as an already-made decision.
- Quorum/participation is an attestation with evidence under BNH policy; the software does not invent a director count, voting majority, or legal validity test.
- Missing mandatory formal evidence prevents submission to the Chairman.
- For an approval/conditional approval, the recorded amount must reconcile to the exact requisition amount. A different commitment requires an explicit new/revised request process, never an overwrite.
- Secretary recording does not produce APPROVED or otherwise finalise the requisition.
- A submitted resolution record is immutable. Corrections use BRD-003.
- Secretary and assigned Chairman identities must differ. Requester-as-Secretary is a recording role, not approval; any declared conflict/BNH restriction must be honoured and not bypassed through another account.

### API and Interface Contract

GET /board-cases?queue=secretary; POST /requisitions/{uuid}/board-resolutions; PATCH /board-resolutions/{uuid}/draft; POST /board-resolutions/{uuid}/submit. Permissions: board_resolution:record and board_resolution:submit plus office/scope checks.

### Delivery Surface

Board case/record APIs, signed evidence model, validation tests, and Secretary-screen guidance.

### Success Outcome

A signed, evidenced Board outcome is ready for an independent Chairman sign-off while the requisition remains unfinalised.

### Audit Records

- `board_resolution.draft_create.success`
- `board_resolution.record_update.success`
- `board_resolution.submit.success`
- `board_resolution.submit.failure`

### Acceptance Criteria

- [ ] Wrong role/scope cannot record or view another Board's confidential evidence.
- [ ] A low-value MD request and an above-₦500-million request reach the same selected Board process.
- [ ] Submitting evidence alone cannot approve the request.
- [ ] Missing evidence, inconsistent amounts, future meeting date, and identical recorder/Chairman identity fail.
- [ ] Meeting date and server recording date are preserved separately.

---


## Feature ID: BRD-002

### Feature Name

Board Chairman Review, Sign-Off, and Outcome Preservation

### Description

Let the Board Chairman review the Secretary's signed record and either confirm it with their own signature or return it for correction. Apply exactly the confirmed Board outcome, not a new unilateral expenditure decision.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

[C] Distinct Secretary/Chairman process and no-self-approval; [D] action naming and state mapping.

### Dependencies

BRD-001

### Actors

Board Chairman in the relevant entity/Board scope; system.

### Workflow

1. Retrieve the immutable requisition revision, Secretary's submitted record, and formal evidence.
2. Check current Chairman appointment, independent identity, no-self-approval, state, evidence versions, and content consistency.
3. Chairman selects Confirm Board decision or Return record for correction.
4. Require explicit signing intent and a fresh challenge for the exact resolution version; return requires a reason.
5. Commit the Chairman action and map the confirmed Board outcome to the requisition state.
6. Notify participants through durable work-item events and preserve both signatures.

### Required Information

Board resolution UUID/version; request revision; Chairman identity/current appointment; confirmation or return action; comment/reason; signing evidence; expected version; idempotency key; signed_at.

### Business Rules and Validations

- Only the currently assigned Chairman may sign. Being MD, a director, administrator, or a previous Chairman is insufficient.
- Chairman must differ from the Secretary recorder and requester. If not, block and await BNH's explicit alternative arrangement; do not automatically substitute a vice-chairman.
- Confirmation of REJECT means REJECTED; confirmation of DEFER means DEFERRED; conditions remain a hold.
- The Chairman cannot directly edit the Secretary's decision text, meeting date, amount, or evidence.
- No approval can be finalised before a Secretary record is signed/submitted.
- No Approve-as-Board action exists on the ordinary APR-001 endpoint.
- Late repeats, stale records, or evidence changed since review fail or return the original idempotent result without duplicate completion.

### API and Interface Contract

GET /board-cases?queue=chairman; POST /board-resolutions/{uuid}/chairman-actions with confirm|return, expected_version, challenge reference, idempotency key, and reason where required. The UI label should clarify “Confirm Board decision” even though the Chairman is the final in-system approver.

### Delivery Surface

Chairman action API/service, immutable confirmations, outcome mapping, tests, and browser integration contract.

### Success Outcome

The exact Board outcome is finalised by the Chairman with two distinct attributable records and no self-approval.

### Audit Records

- `board_resolution.chairman_confirm.success`
- `board_resolution.chairman_return.success`
- `board_resolution.chairman_signoff.failure`

### Acceptance Criteria

- [ ] Secretary cannot confirm their own record; Chairman cannot confirm their own requisition.
- [ ] No submitted Secretary record means no Chairman finalisation.
- [ ] Each of the four resolution outcomes produces the correct request state.
- [ ] Chairman cannot silently edit evidence or turn a rejected resolution into approval.
- [ ] Concurrent confirmations/returns and request replay cannot produce conflicting outcomes.

---


## Feature ID: BRD-003

### Feature Name

Resolution Corrections, Deferment, and Conditional Holds

### Description

Preserve a complete history when the Chairman returns a record, the Board defers a case, or a later resolution changes a conditional outcome. Do not introduce new voting or payment workflows.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

[C] Formal meeting evidence and two-person sign-off; [D-09, D-10] conservative versioning and conditional/deferred handling.

### Dependencies

BRD-002

### Actors

Company Secretary and Board Chairman using the same confirmed roles; requester may view the permitted status/history.

### Workflow

1. For a returned evidence record, Secretary creates a successor resolution-record version referencing the returned version and reason.
2. Correct only the permitted evidence metadata without changing the immutable underlying requisition.
3. Resubmit for fresh Chairman review/signature.
4. For a deferred or conditional case, record a later actual meeting resolution, linked to the prior decision, when one exists.
5. Preserve earlier outcomes and conditions until the later recorded outcome is confirmed.

### Required Information

Predecessor/successor resolution versions; return reason; correction summary; new meeting/resolution details when applicable; condition text; superseded-decision reference; current hold indicator; both new signatures.

### Business Rules and Validations

- A correction to a meeting record is distinguishable from a newly made Board decision.
- A returned resolution does not permit the requester to change its amount under an old Board decision.
- A deferred case is not approved, rejected, or counted as a resolved acceptance request.
- Under D-10, unresolved conditional approval remains held. No ordinary administrator or arbitrary “condition owner” can clear it.
- A later formal resolution follows the full Secretary→Chairman process; no direct status patch.
- Prior signatures remain visible, are not moved onto the successor version, and cannot be deleted.
- Post-approval commercial amendments require a separately authorised workflow and are not silently added today.

### API and Interface Contract

POST /board-resolutions/{uuid}/revisions for returned records; POST /requisitions/{uuid}/board-resolutions for a permitted later resolution. Reuse BRD-001/002 submission/signing; do not add public arbitrary state-change endpoints.

### Delivery Surface

Version/later-resolution actions, state guards, tests, and clarification of the UI correction versus new-decision paths.

### Success Outcome

Corrections and later decisions remain independently evidenced without overwriting history or releasing an unresolved hold.

### Audit Records

- `board_resolution.revision_create.success`
- `board_resolution.revision_create.failure`
- `board_resolution.later_decision_record.success`
- `board_resolution.condition_hold.success`

### Acceptance Criteria

- [ ] Chairman return produces a traceable successor record requiring fresh sign-off.
- [ ] An old Chairman challenge cannot confirm a corrected resolution.
- [ ] Deferred/conditional records never appear as unconditional approval in lists or exports.
- [ ] A later resolution cannot clear a hold without both selected roles completing their actions.
- [ ] A materially changed requisition is rejected from the old resolution-confirmation path.

---


## Module Success Criteria

Secretary recording and Chairman confirmation are distinct, signed actions; all Board outcomes and later corrections remain accurate and traceable, with no native voting or payment stage.


# 14. Request History and Scoped Search

## Module Overview

Expose a clear, truthful record of what happened without granting edit access to that history or exposing confidential Board attachments to every participant.

---


## Feature ID: HIS-001

### Feature Name

Requisition Timeline, Decision History, and Authorised Search

### Description

Provide staff and authorised reviewers with request status, routing reasons, version history, signatures, Board outcomes, and searchable scoped records.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

Confirmed business scope plus the explicitly identified implementation defaults in Section 1.6.

### Dependencies

BRD-003

### Actors

Requester, eligible approvers, Secretary, Chairman, and explicitly authorised reviewer within their permitted scopes.

### Workflow

1. Apply object/list visibility before filtering, pagination, counts, or aggregation.
2. Retrieve current request state and the chronological events/versions that produced it.
3. Show who submitted, required authority and reason, pending actor, completed decisions, and actual timestamps.
4. Expose permitted signing/Board evidence references without leaking restricted meeting documents or bank details.
5. Allow scoped search by reference, requester, department/entity, state, date range, and vendor summary.

### Required Information

Request/revision references; current workflow state; blocked-action explanation; route/policy snapshot; actor display information; event timestamp; decision/return reasons; signature references; resolution references; accessible evidence summaries.

### Business Rules and Validations

- No synthetic approval-history rows for Accounts, CAO/Admin, or Finance/Payment.
- A blank pending action is not displayed as a completed signature.
- Separate submission, meeting, recording, Chairman sign-off, and export times.
- A requester can see the outcome of their request without automatically receiving every confidential Board attachment. Apply evidence-level visibility consistently.
- Counts, autocomplete, history, and direct detail endpoints must not reveal out-of-scope records.
- Expose no event-edit or event-delete operation. Use safe pagination rather than loading the entire history without limits.

### API and Interface Contract

GET /requisitions with scoped filters; GET /requisitions/{uuid}/history; GET /requisitions/{uuid}/revisions/{revision}; restricted GET /audit-events. Use repository pagination/schema envelopes and field-level projections.

### Delivery Surface

Read APIs, indexes appropriate to actual queries, visibility tests, and timeline/search UI contract.

### Success Outcome

Users understand the current status and authorised reviewers can reconstruct the actual decision history.

### Audit Records

- `requisition.history_view.success`
- `requisition.history_view.failure`
- `audit.search.success`
- `audit.search.failure`

### Acceptance Criteria

- [ ] History contains only actual events and preserves previous revisions after corrections.
- [ ] Hidden records cannot be inferred from unscoped totals/search results.
- [ ] Restricted attachments remain restricted even when their parent outcome is visible.
- [ ] Meeting and sign-off timestamps are clearly distinguished.
- [ ] History queries do not mutate signed records or audit events.

---


## Module Success Criteria

Permitted users can reconstruct the actual history and next action without changing evidence or viewing out-of-scope information.


# 15. Notifications and Work Items

## Module Overview

Generate event-driven work items for the same approval workflow. Notifications are not a second approval channel and cannot alter authority.

---


## Feature ID: NOT-001

### Feature Name

In-App Work Items, Basic Email Delivery, and Safe Retries

### Description

Notify the assigned actor and requester about submissions, decisions, returns, Secretary records, and Chairman outcomes using persistent in-app tasks and the configured email service.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

[D] basic communications supporting the agreed operational workflow; no unconfirmed approval/escalation policy.

### Dependencies

HIS-001

### Actors

System worker; current assigned users; requesting staff.

### Workflow

1. Consume the durable event intent created with a business transition.
2. Resolve the current eligible recipient and create a deduplicated in-app notification/work item.
3. Queue a minimal email with a link to the authenticated application when email is configured.
4. Track delivery outcome and retry transient failure using persistent attempts.
5. Allow the actual recipient to read/mark their own notification; preserve business state independently of delivery.

### Required Information

Notification UUID; originating event UUID; recipient identity; channel; template key/version; scoped resource reference; state; attempt count; retry time; safe provider response; read_at.

### Business Rules and Validations

- Email/notification failure does not undo or fabricate a business decision. Undelivered tasks remain visible in-app.
- An email link opens the authenticated application; clicking it never directly signs an approval.
- Notification text does not contain full bank details, signature images, sensitive attachments, or secrets.
- Do not notify the wrong department or a deactivated previous officeholder. Recheck sensitive destination/permission assumptions when sending.
- Avoid duplicate in-app tasks when jobs retry. External email delivery is not claimed exactly-once without provider support; record any retry limitations.
- No SMS, WhatsApp, broadcast campaign builder, push app, marketing preferences, or unagreed reminder/escalation schedule.
- Reading an in-app notification is not acknowledgement of a resolution or an approval action.

### API and Interface Contract

GET /notifications; POST /notifications/{uuid}/read; internal worker/job operations. Administrative delivery diagnostics must expose safe metadata only. No email-reply approval endpoint.

### Delivery Surface

Durable worker/outbox integration, notification APIs, basic templates, retry tests, and deployment configuration.

### Success Outcome

The correct users receive persistent actionable work items, and delivery failures are visible without corrupting workflow state.

### Audit Records

- `notification.create.success`
- `notification.delivery.success`
- `notification.delivery.failure`
- `notification.read.success`

### Acceptance Criteria

- [ ] Submission and Board-record events notify the correct assigned actor.
- [ ] Worker restart does not lose queued jobs.
- [ ] Retry does not create duplicate in-app notifications or multiple decisions.
- [ ] An unauthorised user cannot list/read another recipient's notifications.
- [ ] Missing email configuration is reported honestly; the in-app queue still shows outstanding work.

---


## Module Success Criteria

Task delivery is persistent and scoped; delivery failures and reminders cannot change an approval outcome.


# 16. Generated Requisition and Approval Documents

## Module Overview

Generate a faithful view of stored requisition and decision evidence, using the supplied greyscale document standard rather than reproducing the old form's blue sign-off table.

---


## Feature ID: DOC-001

### Feature Name

Version-Specific Requisition Document and Approval Record Export

### Description

Produce a downloadable PDF or the repository-supported equivalent PDF-rendering workflow for a specified requisition revision, including actual declarations, decisions, and Board evidence references.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

[F] original form content; [B] greyscale typography/page standard; [D] automated version-specific export.

### Dependencies

HIS-001

### Actors

Requester and authorised approvers/reviewers within permitted scope; system renderer.

### Workflow

1. Authorise access to the requested revision and requested detail level.
2. Load the immutable request snapshot and only the permitted decision/evidence fields.
3. Render the form content, declaration, actual approval history, and current outcome at the export time.
4. Store export metadata referencing request/revision, renderer/template version, generation time, and file digest.
5. Provide a private access mechanism and test long multi-page output.

### Required Information

Request UUID/revision; template version; authorised projection; immutable financial fields; originator signature evidence; individual decisions or Secretary/Chairman references; meeting/sign-off times; generated_at; export hash/object reference.

### Business Rules and Validations

- Use A4 and 0.60-inch margins. Body: Garamond 11 pt, justified, #595959. H1: Arial 16 pt bold, #000000. H2: Arial 12 pt bold, #1A1A1A. Footer: Baskerville Old Face 8 pt, #8C8C8C.
- Confirm authorised font availability. No silent font substitutions or distribution of font files. Record any BNH-approved alternative.
- Replace the old approval path with actual generated history. No empty Finance or Accounts signature boxes.
- Display Draft/Rejected/Deferred/Conditional/Approved truthfully; Approved never becomes Paid.
- Use the signature evidence for the exact signed revision, not a current profile signature copied onto old records.
- Exports cannot disclose evidence/bank fields the requesting user is not allowed to access.
- Use a fixed rendering template with escaped content; no arbitrary remote HTML or file loading.
- A document-rendering failure does not undo a valid recorded decision; retry safely and disclose export failure.

### API and Interface Contract

POST /requisitions/{uuid}/exports with permitted revision/projection; GET /exports/{uuid} returns typed metadata/access state. Reuse private file delivery and the existing auto-transform-compatible response convention.

### Delivery Surface

Template/rendering service, private export endpoint/job, document verification tests, and endpoint guidance.

### Success Outcome

A private, accurate, properly formatted record can be generated from the stored version without manual document editing.

### Audit Records

- `requisition.export.success`
- `requisition.export.failure`

### Acceptance Criteria

- [ ] Export totals, reference, revision, declarations, and decision outcomes match stored values.
- [ ] No legacy approval rows or blue visual styling remain.
- [ ] Long descriptions, multiple pages, table headers, footers, and signature blocks render without clipping.
- [ ] A requester cannot use export to obtain a restricted Board attachment or unapproved sensitive fields.
- [ ] Re-export does not mutate signatures or rewrite the historical approval timestamp.

---


## Module Success Criteria

Generated documents match the authoritative stored revision and visual standard, disclose only authorised content, and never fabricate a sign-off.


# 17. Web Interface and Staff Workspaces

## Module Overview

Complete a real browser application on the existing frontend conventions. These are implementation features, not permission to leave production screens wired to fake data. Do not recreate frontend scaffolding that already works.

---


## Feature ID: WEB-001

### Feature Name

Greyscale Application Shell, Sign-In, and Restricted Administration

### Description

Build the shared navigation, sign-in/session experience, and minimum permitted organisation/staff configuration screens. Reuse the project's frontend framework and components.

### Implementation Status

**Status:** Implemented

**Implementation Evidence:** Shared grayscale shell and connected account screens 1–3 are implemented: sign-in, generic forgot-password requests, shared activation/reset, expired/replayed links, password matching, session revocation, safe outage retry and desktop/mobile layout. Five real-backend browser journeys include account access and vendor regression. Isolated frontend lint, formatting, typecheck (zero errors/warnings), three unit tests, build and all five browser journeys passed. Desktop reset and narrow activation layouts were visually inspected. Staff & Access Management (11) now includes protected directory/search, invitation and detail drawers, account status/session controls, department membership and controlled appointment assignment/revocation. Optimistic versions preserve stale edits; self-status/authority changes are blocked and Secretary/Chairman separation is retained. Screen 11 verification: all 182 working backend tests and 113 exact staged release tests passed, including eight new staff cases; staged Ruff, formatting and mypy passed. Exact frontend ESLint, Prettier, typecheck (zero errors/warnings), three unit tests, production build and nine real-backend browser journeys passed. Desktop and mobile list/drawer layouts were inspected. Organisation & Authority (12) is implemented with company/department drawers, versioned updates and enable/disable confirmations, named officeholder status/history and missing/conflicting assignment visibility, and a read-only approval matrix. Screen 12 verification: the exact release passed Ruff, formatting, mypy, all 120 backend tests, frontend ESLint/Prettier/typecheck, three unit tests, production build and all twelve PostgreSQL-backed browser journeys. Full working-source regression in a fresh isolated database passed 189 tests. Desktop and narrow layouts were visually inspected. Screens 1–3, 11 and 12 complete the scoped account-access and restricted-administration journey.

**Deployment / acceptance:** The owner reports email working after enabling it in Render. Screen 12 uses the existing Dockerfiles and startup migrations with no new environment variables or migration. Its deployed operation must be checked after the feature push; genuine staff acceptance remains separate from synthetic browser verification.

### Requirement Basis

[B] independent staff use and supplied visual standard; [D] minimal reusable application shell.

### Dependencies

IAM-001, IAM-002, ORG-001 for the delivered account-access and restricted-administration screens. Notification and document viewers remain within their own later journeys under the fourteen-screen scope.

### Actors

Authenticated staff and authorised administrators.

### Workflow

1. Introduce central design tokens from the supplied palette and reuse existing typography/layout primitives.
2. Wire sign-in, current user, logout, recovery where configured, and session-expiry handling to real APIs.
3. Display navigation/actions based on server-provided capabilities while retaining backend enforcement.
4. Implement the minimum authorised entity, department, staff, and officeholder administration views.
5. Validate responsive behaviour, keyboard access, errors, loading states, and restricted-route navigation.

### Required Information

Current-user response; effective capability/scope summary; organisation APIs; design tokens; field validation/errors; session state; safe environment label for non-production.

### Business Rules and Validations

- Palette: #000000, #1A1A1A, #595959, #8C8C8C, #D9D9D9, #F2F2F2, #FFFFFF. Define centrally; avoid scattered raw colours.
- One clean sans-serif, at most two weights in normal use, no decorative lettering effects.
- Red/amber/green only communicate functional statuses with a label/icon; never use them as decorative branding, charts, navigation, or action-button colours.
- The specification's light labels require contrast review. Record any approved darker-token adjustment rather than silently changing the visual policy.
- No “log in as HOD/MD” or role-impersonation selector in production.
- Do not show future modules as functional screens. Hidden/deferred navigation is preferable to misleading placeholders.
- Administration cannot expose generic edit access to audit, approval, policy thresholds, or protected request state.
- Frontend data is not an access-control boundary; API denial must render a clear, non-leaking error.

### API and Interface Contract

Consume completed IAM/ORG APIs from ui_todos.md. No new competing authentication API or role-policy contract.

### Delivery Surface

Actual frontend components/routes, integration, accessibility/visual checks, and browser tests. If the frontend repository is unavailable, mark Blocked rather than claiming this surface is implemented.

### Success Outcome

Staff can access a consistent greyscale application with truthful capabilities and restricted administration.

### Audit Records

- `Use the underlying IAM/ORG/access events; record relevant denied access without duplicating every presentation rerender.`

### Acceptance Criteria

- [x] Login/logout/session expiry work against the actual backend.
- [x] Wrong-role deep links show a safe denial and do not expose cached sensitive data.
- [x] No fake production users, simulated permission switching, or static approval totals remain.
- [x] Colour and typography tokens follow the standard; every status has a textual/icon meaning.
- [x] Administration forms cannot self-grant financial authority.

---


## Feature ID: WEB-002

### Feature Name

Requester Dashboard, Requisition Form, Signing, and History

### Description

Deliver the complete self-service browser journey for staff to prepare, sign, submit, track, and correct requisitions using real persisted data.

### Implementation Status

**Status:** In Progress

**Implementation Evidence:** The creation/submission portion of screens 5–7 is delivered: scoped list, reusable create/edit form, vendor lookup, exact totals, route preview, private attachment viewer, keyboard/pointer signing controls and submission history. Three new real-PostgreSQL browser journeys pass alongside twelve earlier journeys, including staff-to-HOD and low-value MD-to-Board paths, stale edits, cancellation, restricted links and session expiry. Desktop and 390px layouts were inspected. Dashboard, returned-request browser workflow and exports remain unfinished; this overall feature remains In Progress. Exact staged release passed Ruff/format/mypy, 208 backend tests on fresh local PostgreSQL, frontend lint/format/types, six unit tests, production build and all fifteen browser journeys (2026-10-08). Publication is recorded by the feature commits on origin/dev.

**Blocker:** Live Cloudinary credentials/account behavior and BNH signature-method acceptance remain deployment/acceptance checks, separate from local implementation verification.

### Requirement Basis

Confirmed business scope plus the explicitly identified implementation defaults in Section 1.6.

### Dependencies

WEB-001

### Actors

Requesting staff, including HOD/Chief of Staff/MD acting as requesters.

### Workflow

1. Show My Requisitions with scoped search, truthful state counts, and the next action.
2. Create/open a draft and enter vendor, scope, cost lines, attachments, and declaration information.
3. Display server totals and the predicted authority explanation; do not offer an approver selector.
4. Review the exact current revision, perform the signing ceremony, and submit.
5. Show the resulting queue/state/history and permitted export.
6. For a returned request, open the successor revision, correct it, re-sign, and display the new route.

### Required Information

Draft/detail/list APIs; server-calculated totals; safe vendor lookups; attachment upload/access; signature challenge and capture; validation feedback; immutable history; document export state.

### Business Rules and Validations

- Current requester and department are not free-text authority controls.
- Show complete cost and known/unknown payment details before signing.
- A UI preview calculation never overrides the backend total.
- Prevent accidental duplicate clicks but still rely on backend idempotency for correctness.
- After an optimistic-concurrency conflict, reload/compare safely; never silently overwrite another revision.
- Material signed content becomes read-only; use the returned-revision workflow rather than generic editing.
- Show that Approved means authorised, not paid. Conditional and deferred states are visually distinct.
- No development fixture or uploaded sample bank account is copied into live request defaults.

### API and Interface Contract

Consume VEN/EVD/REQ/HIS/DOC APIs as documented. Reuse existing form, table, feedback, and file components where they fit the contract.

### Delivery Surface

Requester screens/components, backend integration, responsive checks, and real-browser workflow tests.

### Success Outcome

A real staff member can complete the requester journey independently on their own device.

### Audit Records

- `Use underlying requisition, attachment, signature, history, and export events for actual actions.`

### Acceptance Criteria

- [x] Browser test creates a draft, reloads it, signs/submits, and observes the correct next actor.
- [ ] A returned request is corrected and rerouted when its amount crosses a threshold.
- [ ] Unsafe attachment and invalid field errors are comprehensible and preserve safe draft work.
- [ ] Signature capture is usable by mouse/touch and supports the approved accessibility alternative when configured.
- [x] No request succeeds merely through local state without a successful backend transition.

---


## Feature ID: WEB-003

### Feature Name

Individual Approver, Secretary, Chairman, and Reviewer Workspaces

### Description

Deliver the role-specific browser actions for direct approval and the selected formal Board process. Reuse one request-detail/evidence viewer rather than duplicating the business logic per role.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

Confirmed business scope plus the explicitly identified implementation defaults in Section 1.6.

### Dependencies

WEB-002

### Actors

HOD, Chief of Staff, MD, Company Secretary, Board Chairman, and explicitly authorised reviewer.

### Workflow

1. Load the real scoped inbox for the current officeholder.
2. Review the submitted request, evidence, route reason, and immutable content.
3. Individual approvers sign approve/reject/return actions through APR-001.
4. Secretary records and submits formal meeting evidence through BRD-001.
5. Chairman confirms the recorded outcome or returns the record, using the exact bound evidence version.
6. Expose read-only historical decisions and appropriately restricted search/export for reviewers.

### Required Information

Assigned inbox; current eligibility/allowed actions; request/evidence detail; decision/reason/signature inputs; Secretary record form; Chairman action form; event history; user-facing errors and blocked-action reasons.

### Business Rules and Validations

- Show Secretary and Chairman actions as different responsibilities, not one shared Board Approve button.
- Chairman confirmation text must state the actual Board outcome, including rejection/deferment/conditions.
- A missing or invalid assignment produces a clear blocker; do not offer a client-side bypass.
- Return-to-Secretary correction must not be confused with return-to-requester revision.
- Do not prepopulate a signature or automatically sign when a page is viewed.
- Status colours remain functional; approve/reject action buttons follow the greyscale standard.
- A stale/currently revoked role loses actions and any attempted request is denied server-side.
- Read-only reviewer screens contain no mutation actions and cannot access wider evidence through hidden links.

### API and Interface Contract

Consume APR/BRD/HIS/EVD contracts. UI capability hints never substitute for the backend business checks.

### Delivery Surface

Approver/Secretary/Chairman/reviewer browser surfaces, integration tests, and task-specific user guidance.

### Success Outcome

Each selected role can perform only its own real, signed workflow actions independently of the developer.

### Audit Records

- `Use underlying approval, Board, signature, history, and export events.`

### Acceptance Criteria

- [ ] Browser tests cover direct approval and return/revision with separate real test identities.
- [ ] A Secretary and different Chairman complete the Board workflow; single-person completion fails.
- [ ] Confirmed Board rejection/deferment/conditions are displayed accurately rather than as approval.
- [ ] Wrong role, missing evidence, stale version, self-approval, and insufficient scope produce clear denied actions.
- [ ] Reviewer access and restricted minutes/bank projections match backend permissions.

---


## Module Success Criteria

The actual connected browser application supports independent staff submission and every selected approval route, with no placeholder decisions or legacy approval steps.


# 18. Regression and Security Verification

## Module Overview

Tests belong to each preceding feature. This final gate validates the integrated system and catches failures that isolated happy-path tests miss. It is not the first time security is considered.

---


## Feature ID: QA-001

### Feature Name

Integrated Policy, Concurrency, Security, and Browser Acceptance Suite

### Description

Run the complete acceptance matrix against the release candidate with actual PostgreSQL integration and separate authenticated test identities. Record results and unresolved failures precisely.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

Confirmed business scope plus the explicitly identified implementation defaults in Section 1.6.

### Dependencies

WEB-003

### Actors

Developer/test runner and independent reviewer where available.

### Workflow

1. Assemble representative synthetic fixtures for every role, two departments, relevant entities, and the sixteen matrix cells.
2. Run unit/API tests, explicitly opt into PostgreSQL integration, and record executed versus skipped cases.
3. Run concurrency, signature replay, audit failure, and access-isolation tests.
4. Run connected browser workflows for ordinary and Board requests.
5. Verify greyscale visual behaviour and version-specific generated documents.
6. Record actual commands/results, remaining defects, and whether the release gate passed.

### Required Information

Release identifier; fixture definitions; environment settings without secrets; test commands; collected/executed/passed/failed/skipped counts; test evidence; defect register; required operational acceptance settings.

### Business Rules and Validations

- No acceptance based on tests that were never executed or on a green run where required integration cases skipped.
- No deleting/faking tests, replacing PostgreSQL with in-memory semantics, or changing matrix expectations to force a pass.
- No unauthorised production penetration activity; use the approved isolated test environment.
- Performance statements require a defined workload and actual measurements. Do not claim “enterprise-certified” or a security certification from this test report.
- Any unauthorised approval, self-approval, wrong threshold route, mutable evidence, data loss, or unauthorised sensitive read is release-blocking.
- Fixtures remain synthetic and separated from production; never count these as the three genuine requisitions.

### API and Interface Contract

Exercise actual API/service and browser entry points. Do not introduce public debug routes, test impersonation, or unsecured fixture loaders.

### Delivery Surface

Test suites, reproducible runner instructions, evidence report, and resolved defect verification.

### Success Outcome

The release candidate has an evidence-backed integrated test result and no hidden release-blocking failure.

### Audit Records

- `testing is recorded in the delivery evidence; do not generate fictitious production financial audit events for test assertions.`

### Acceptance Criteria

- [ ] All mandatory scenarios in Appendix B run and pass.
- [ ] The report distinguishes skipped external tests from successful execution.
- [ ] A concurrent approve/reject race and a forced audit failure both preserve invariants.
- [ ] All three Board pathways—approval, rejection/deferment, and correction—are exercised with appropriate identities.
- [ ] A failed mandatory test prevents the feature being marked Implemented.

---


## Module Success Criteria

Mandatory integrated tests actually ran and passed; unexecuted checks and unresolved critical failures remain explicit.


# 19. Deployment, Evidence Protection, and Recovery

## Module Overview

Deploy the tested build to a reachable BNH-approved environment with persistent data, private evidence, controlled credentials, and demonstrated recovery. Local completion does not satisfy the reachable-system requirement.

---


## Feature ID: OPS-001

### Feature Name

Reachable Deployment, Protected Evidence Archive, and Recovery Handover

### Description

Make the tested system independently reachable and verify persistence, access, evidence protection, migrations, backups, and recovery under the real deployment configuration.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

[B] reachable deployment, persistence, and immutable events; [D] stronger evidence protection and tested operational implementation.

### Dependencies

QA-001

### Actors

Authorised deployment operator, BNH infrastructure owner, and independent acceptance user.

### Workflow

1. Obtain approved infrastructure/domain/storage/identity settings and deploy the tested release with HTTPS and private secrets.
2. Apply non-destructive migrations using the migration identity; run the application under restricted runtime credentials.
3. Configure private evidence storage and an independently protected evidence copy with a documented protection/retention policy.
4. Verify application-role denial of event modification and test the chosen archive/retention protection, including failure handling.
5. Back up the database and linked objects, restore them into a separate environment, and check record/evidence links.
6. Demonstrate URL access from another device, restart survival, worker recovery, monitoring, and operator ownership.

### Required Information

Approved environment/region/domain; deploy permissions; non-secret configuration inventory; release/migration identifiers; identity/email setup; private storage/retention settings; backup schedule; agreed recovery objectives; incident/contact ownership.

### Business Rules and Validations

- No local-only URL, public database, embedded secret, shared production role login, or unprotected local-only attachment storage.
- Do not assert absolute immutability from a hash chain. Document which application roles and infrastructure identities can and cannot change each copy.
- Use the approved retention period; do not guess years of legal retention or claim a provider mode was tested when it was not.
- If independently protected archival is asynchronous, show pending/failed delivery explicitly and the tested recovery window. Never mark a bundle protected before acknowledgement. Approval-finalisation evidence must be durably queued; any stricter required protection-before-use gate must fail closed on archive failure.
- A database owner or cloud owner is a separate trust boundary; do not falsely claim ordinary DB grants make those identities technically powerless.
- Restore to an isolated environment. Never overwrite live data as a recovery test.
- Runtime readiness and logs expose no secrets. Failed jobs and evidence archival need visible diagnostics.
- Deployment costs or production writes require the operator's actual permission; a missing credential is a blocker, not something the agent invents.

### API and Interface Contract

Reuse health/readiness and restricted operational diagnostics; no publicly accessible administrative reset, seed, or archive-deletion endpoints.

### Delivery Surface

Deployment configuration/scripts, evidence-storage settings, persistence/protection/recovery proof, and operator handover documentation.

### Success Outcome

BNH can use the deployed release independently, and persistence/evidence protections and recovery are demonstrated rather than assumed.

### Audit Records

- `operations.protection_check.success`
- `operations.protection_check.failure`
- `operations.recovery_check.success`
- `operations.recovery_check.failure`

### Acceptance Criteria

- [ ] An independent device opens the deployed URL and uses a named account.
- [ ] Browser closure, service restart, and worker restart preserve business state and queued work.
- [ ] The actual runtime role cannot edit/delete historical audit/signature records.
- [ ] Archive delivery status and configured retention protection are verified with test objects.
- [ ] A restore preserves at least one complete test request and its exact attachments/signatures/history.
- [ ] Runbook, configuration ownership, monitoring, and secrets handover are complete; no secrets are placed in Markdown.

---


## Module Success Criteria

The tested build is reachable independently, preserves data across restarts, and has demonstrated evidence protection and isolated restoration.


# 20. Genuine Staff Acceptance

## Module Overview

This is a human-operated acceptance gate, not a coding task that can be completed by seeding fixtures. It preserves the engagement brief's evidence requirement while separating software completion from BNH operational use.

---


## Feature ID: UAT-001

### Feature Name

Three Genuine Staff-Operated Requisitions and Acceptance Record

### Description

Demonstrate at least three genuine requisitions raised, routed, and resolved end to end by BNH staff other than the developer. Record the actual outcomes and independent evidence before the defence.

### Implementation Status

**Status:** Not Assessed

**Implementation Evidence:** Not yet recorded.

**Blocker:** None assessed. This does not mean external dependencies are available.

### Requirement Basis

[B] Section 5.1 requirement for at least three genuine, independently staff-operated requisitions.

### Dependencies

OPS-001

### Actors

Actual BNH requesters and applicable approvers; Secretary/Chairman only when genuine Board cases arise; independent acceptance reviewer.

### Workflow

1. BNH identifies at least three real requests and the relevant staff participants.
2. Each requester uses their own account/device to prepare and submit the actual request.
3. The system routes each request; the genuine authorised person or Board process resolves it.
4. Staff/reviewer inspect the signatures, event history, persistence, and outcome independently.
5. Record request references, participants, dates, release version, results, and any unresolved problem.

### Required Information

Three genuine requisition references; actual participant identities; outcomes; action timestamps; evidence references; independent reviewer; deployed release; acceptance date and exceptions.

### Business Rules and Validations

- The developer/agent must not impersonate staff or perform their signatures to make the number reach three.
- Synthetic staging routes validate policy coverage but do not count as genuine requests.
- The three genuine requests do not need to span all monetary tiers; do not invent a high-value Board request.
- Under the conservative v1 acceptance interpretation, Approve or Reject is resolved. Returned, Deferred, or unresolved Conditional Approval is not counted unless BNH explicitly accepts a different definition.
- A real rejected request counts only if that rejection genuinely occurred; do not engineer rejections for demonstration.
- Software can be implemented while this feature remains Blocked awaiting staff; do not claim the full engagement acceptance has then passed.
- No new contractual date is invented from the same-day development goal; the brief's pre-defence evidence condition remains.

### API and Interface Contract

Use the normal production application only. No acceptance-only bypass endpoints or developer impersonation tools.

### Delivery Surface

Human-operated acceptance evidence and final handover status. No new approval tier or workflow engine.

### Success Outcome

Three independently operated genuine cases and their outcomes are evidenced, with BNH's acceptance result recorded.

### Audit Records

- `Use the real submission/approval/Board audit events produced by actual staff actions; never manufacture a separate synthetic success history.`

### Acceptance Criteria

- [ ] Three genuine records exist and were raised/routed/resolved by BNH staff other than the developer.
- [ ] Participants used their own identities and required signing evidence is present.
- [ ] The reviewer can reconstruct each decision from the deployed system.
- [ ] No seeded/demo case is presented as a real financial request.
- [ ] Incomplete staff participation remains visible as a blocker rather than a fabricated Implemented status.

---


## Module Success Criteria

BNH staff have independently completed the three genuine cases and the acceptance evidence is accurate. The agent cannot mark this gate complete from code generation or test fixtures alone.


# 21. Completion and Delivery Reporting

A feature is Implemented only after all of its specified deliverables and tests are complete, `ui_todos.md` contains its endpoint-consumption guidance, `task_done.md` records its behaviour and verification, and the feature tracker reflects the result. Follow the branch/review/merge/push process in `AGENTS.md`; do not mark remote operations successful without actually performing them.

For every delivered endpoint, `ui_todos.md` must identify method/path, registered permission, object-scope constraints, path/query inputs, body, typed response, validation rules, domain errors, state transitions, concurrency/idempotency requirements, and frontend handling notes. A service-only feature should explicitly state that no public endpoint was added.

`task_done.md` must record the feature ID, affected modules, schemas/migrations, permissions, event definitions, tests and actual commands/results, known limitations, decisions, and release/deployment implications. Document the current implementation, not a hypothetical one.

## 21.1 Today's Completion Checkpoints

The coding agent should report progress by actual working milestones: persistent identity/evidence foundation; complete direct-authority path; complete Secretary–Chairman path; connected browser application; passing integrated tests; reachable deployment; and genuine staff acceptance. These milestones are not substitutes for per-feature statuses.

Do not spend time implementing future modules, a design-system editor, broad analytics, or an administrative override tool. Do not replace real controls with TODO comments to meet the clock.

## 21.2 Final Agent Report

The final implementation report must distinguish:

| Area                         | Required reporting                                                                                                      |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Code and migrations          | Exact implemented feature IDs, affected repositories, release/commit references, and remaining code blockers.           |
| Tests                        | Commands actually run, passed/failed/skipped counts, PostgreSQL opt-in result, browser result, and unresolved failures. |
| Deployment                   | Actual reachable environment and verified capabilities, or the exact missing access/configuration preventing it.        |
| Evidence protection/recovery | What protection was tested, trust boundaries, archive delivery status, and the actual restore result.                   |
| Human acceptance             | Real staff participants and genuine request references, or explicit pending status.                                     |
| Wider engagement documents   | Whether the separate full four-module design pack and any unseen requirements have been delivered or remain pending.    |

“Code written,” “tests passed,” “deployed,” and “accepted by BNH” are different claims. Make each only when supported by its own evidence.

---

# Appendix A. Permissions, Data, and API Contracts

## A.1 Proposed Fixed Permission Registry

These `resource:action` names follow `AGENTS.md`. Reuse an existing equivalent name when needed and document the mapping; do not maintain two inconsistent policies. A permission grants capability only when record-level scope and the business rules also pass.

| Capability group     | Proposed permission identifiers                                                                                          | Scope / restrictions                                                                        |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| Organisation         | entity:list, entity:manage, department:list, department:manage                                                           | Approved administration only; relevant entity scope.                                        |
| Staff                | staff:list, staff:manage                                                                                                 | Account/profile management does not grant financial authority.                              |
| Office appointments  | office_assignment:list, office_assignment:manage                                                                         | Protected configuration operators; no self-grant or generic profile-edit bypass.            |
| Vendors              | vendor:list, vendor:create, vendor:update, vendor:read_sensitive                                                         | Permitted use/scope; bank fields require the appropriate sensitive projection.              |
| Requisitions         | requisition:create, requisition:list, requisition:read, requisition:update_draft, requisition:submit, requisition:revise | Own request except explicitly scoped read/review access; submitted content is immutable.    |
| Individual decisions | requisition:approve, requisition:reject, requisition:return                                                              | Exact required current officeholder only; never self; excludes Board-level decisions.       |
| Board records        | board_resolution:read, board_resolution:record, board_resolution:submit, board_resolution:revise                         | Company Secretary within assigned scope for writes.                                         |
| Chairman actions     | board_resolution:confirm, board_resolution:return                                                                        | Current Chairman; different recorder and requester identities; confirmed outcome preserved. |
| Evidence             | attachment:upload, attachment:read, signature:capture                                                                    | Permission plus object ownership/scope and valid bound signing intent.                      |
| History and exports  | audit:list, requisition:export                                                                                           | Explicit read scope; no audit mutation permission exists.                                   |
| Notifications        | notification:list, notification:read                                                                                     | Recipient's own records.                                                                    |

For existing user-management and permission-registration APIs, preserve repository conventions and tightly restrict which seeded financial capabilities are assignable. Do not expose a general permission editor that defeats the fixed officeholder policy.

## A.2 Minimum Data Relationships

| Record                  | Required relationship / behaviour                                                                                   |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Entity                  | BNH holding company or subsidiary; used consistently throughout the suite.                                          |
| Department              | Belongs to an entity; linked to staff membership and a HOD appointment.                                             |
| Staff identity          | One real person identity; linked to authentication account(s) without escaping identity-based self-approval checks. |
| Office appointment      | Office type + person + explicit entity/department/group scope + effective period + authorisation reference.         |
| Authority policy        | Immutable policy identifier/version; amount bands and requester floors from Section 3.1.                            |
| Vendor/counterparty     | Stable reusable identity; contact/registration information; no implicit certification.                              |
| Beneficiary version     | Versioned private bank information; referenced in a submitted request snapshot.                                     |
| Requisition             | Stable reference; requester/entity/department; current working/lifecycle pointers; no generic state override.       |
| Requisition revision    | Immutable submitted content, line totals, vendor/payment snapshot, declaration, document manifest, and policy.      |
| Cost line               | Belongs to a specific draft/revision; exact quantity/rate/calculation; stable display order.                        |
| Route assignment        | Required authority, scope, exact actor where applicable, requester-floor explanation, policy, and revision.         |
| Decision                | Actor + action + exact request revision + intent/reason + signing evidence + server time; append-only.              |
| Board-resolution record | Exact request revision + Board/entity + meeting evidence + Secretary signature; versioned and immutable on submit.  |
| Chairman confirmation   | Exact submitted resolution version + Chairman signature/action; cannot rewrite the resolution.                      |
| Attachment              | Private object version + hash + validation and access metadata; immutable when referenced by submitted evidence.    |
| Signature evidence      | Actor + fresh auth context + explicit intent + exact signed content + capture + timestamp.                          |
| Audit event             | Append-only safe event envelope; protected from application-role mutation and cascade deletion.                     |
| Outbox/work item        | Durable event delivery intent and retry state; separate from immutable event content.                               |
| Export                  | Request/revision/template/projection + generation time + file reference/digest; no new financial decision.          |

Do not build empty contract, compliance, or capital records solely to make this table larger. Preserve stable reference contracts so those later modules can use the same entities, counterparties, approvals, and event history.

Relevant uniqueness/version constraints must be enforced in the database, not only in forms: readable request reference; scoped active-office assignment rules; idempotency scope; final decision per active revision; unique signature challenge consumption; and unique durable event delivery identity. Preserve legitimate later resolution versions instead of incorrectly preventing a second meeting on a deferred case.

## A.3 Standard Decision Command

A decision endpoint consumes the request/resource UUID from its route, plus the expected current revision/version, intended action, reason where required, signature challenge/evidence reference, and idempotency key. The authenticated actor and allowed authority are server-derived. Do not accept a trusted `actor_id`, `approved_by`, `approved_amount`, `required_authority`, or final `status` from the client.

The response includes the actual stored state, request/revision references, decision reference where created, safe next-action explanation, and row/version needed for further interaction. Preserve existing `Result[T]` and `auto_transform` wrappers.

## A.4 Required Error Semantics

| Domain code                  | Meaning / expected client handling                                                                        |
| ---------------------------- | --------------------------------------------------------------------------------------------------------- |
| AUTHENTICATION_REQUIRED      | No valid session; reauthenticate without exposing private request content.                                |
| ACCESS_DENIED                | Authenticated actor lacks capability or scope; no fallback approval action.                               |
| RESOURCE_NOT_AVAILABLE       | Missing or non-visible resource; follow the repository's non-disclosure convention.                       |
| VALIDATION_FAILED            | Invalid/incomplete submitted fields; return safe field errors and preserve the draft.                     |
| UNSUPPORTED_CURRENCY         | Not NGN under D-01; do not apply NGN thresholds.                                                          |
| AUTHORITY_ASSIGNMENT_BLOCKED | Missing/ambiguous/inactive required mapping; show the required office and a safe operational explanation. |
| SELF_APPROVAL_PROHIBITED     | Actor matches the requester identity; no role-switch override.                                            |
| BOARD_SEPARATION_REQUIRED    | Secretary/Chairman identity conflict or incorrect role.                                                   |
| REVISION_CONFLICT            | Stale request/resolution version; reload and review, never silently overwrite.                            |
| IDEMPOTENCY_CONFLICT         | Key was used with different content; do not create a second action.                                       |
| INVALID_STATE_TRANSITION     | Action is not permitted in the current state.                                                             |
| SIGNATURE_INVALID            | Invalid/expired/wrong-bound signing challenge or unacceptable capture; re-review and sign appropriately.  |
| EVIDENCE_NOT_READY           | File validation, formal evidence, or required protection prerequisite is incomplete.                      |
| PERSISTENCE_FAILURE          | Atomic storage failed; no successful decision must be presented.                                          |

Map these to the repository's established safe HTTP/result conventions (typically authentication/forbidden/not-found/validation/conflict/server-failure categories). A backend expected error is returned as Result rather than an uncaught expected exception. Do not expose SQL, credentials, signature material, or private bank information in errors.

---

# Appendix B. Mandatory Test Matrix

## B.1 Monetary Boundaries

Use exact decimal/kobo values. Test ordinary staff and repeat boundary coverage across the elevated requester categories.

| Amount in NGN  | Ordinary-staff amount-band result |
| -------------- | --------------------------------- |
| -1.00          | Reject                            |
| 0.00           | Reject                            |
| 0.99           | Reject                            |
| 1.00           | Own department's HOD              |
| 4,999,999.99   | Own department's HOD              |
| 5,000,000.00   | Own department's HOD              |
| 5,000,000.01   | Chief of Staff                    |
| 99,999,999.99  | Chief of Staff                    |
| 100,000,000.00 | Chief of Staff                    |
| 100,000,000.01 | MD                                |
| 499,999,999.99 | MD                                |
| 500,000,000.00 | MD                                |
| 500,000,000.01 | Board                             |

Test unsupported currency, NaN, Infinity, exponent/decimal inputs under the accepted schema, overflow, more than permitted fractional precision, missing amount, client total manipulation, negative line values, and zero/negative quantity. The money type's documented storage maximum is a technical limit, not a new authority band. Never silently overflow or clamp a value into a lower band.

## B.2 Requester Floors and Department Scope

Use at least two departments with different HODs. Test all sixteen cells of Section 3.1. Specifically include an HOD's ₦1 request to Chief of Staff, HOD's ₦200 million request to MD, Chief of Staff's ₦1 request to MD, Chief of Staff's above-₦500 million request to Board, and MD's ₦1 request to Board.

Test users with multiple appointments, role switching in the browser, stale role claims, department transfer, deactivation, missing HOD, ambiguous Chief of Staff scope, a wrong-department HOD, a more senior person trying to substitute for an assigned lower office, and a single person occupying conflicting offices. No result may reduce the minimum authority or permit self-approval.

## B.3 Signing, Versions, and Races

Test expired/replayed/wrong-actor/wrong-resource/wrong-action challenges; a changed amount after challenge creation; replacement attachment after review; changed resolution text; duplicate network retries; the same idempotency key with altered content; two simultaneous approve/reject commands; Secretary correction while Chairman has an old record; and role revocation between review and signing.

Test a returned ₦4 million request resubmitted as ₦8 million, plus a return remaining in the same band. Old declarations/signatures/history remain immutable; resubmission has its own signature and recalculated route. Approved records cannot be edited by generic CRUD.

## B.4 Board Process

Test Secretary creation without Chairman confirmation; Chairman attempt before Secretary submission; same person for both roles; Chairman as requester; MD requester holding another Board-related role; missing formal evidence; future meeting date; resolution/request amount mismatch; wrong entity; Secretary attempting individual approval; and an ordinary individual-decision endpoint attempting Board approval.

Confirm that APPROVE, REJECT, DEFER, and CONDITIONAL_APPROVE each map to their correct state. Test return-to-Secretary corrections, a later meeting resolution for a deferred case, and a conditional hold that remains held without a subsequent authorised formal outcome. A confirm action cannot transform a rejected Board resolution into approval.

## B.5 Permissions and Evidence Integrity

Exercise every sensitive read/mutation through the API, not only hidden buttons. Test list counts, search, attachment access, export, revision history, and Board minutes for out-of-scope identities. Test an administrator trying to set approved_by/status/authority, grant their own protected office, mutate an event, delete a signer, or cause cascade deletion of evidence.

Run database-role UPDATE/DELETE/TRUNCATE denial checks for protected history. Force audit insertion failure and verify business rollback. Test logging of denied attempts without falsely recording successful state. Verify archive delivery status, configured retention, and failure handling without claiming a hash alone prevents deletion.

## B.6 Persistence, Operational Use, and UI

Restart browser, API service, and worker. Restore a database/attachment backup into a separate environment and confirm exact evidence links. Test private storage access, unsafe files, unavailable email/storage, queued work after retry, and non-destructive migration from the prior schema.

Run browser journeys with separate identities for requester, HOD/Chief of Staff/MD, Secretary, Chairman, and reviewer. Check keyboard navigation, readable validation, responsive layouts, token use, status labels/icons, and version-specific document pagination. Confirm no placeholder or mock mode is enabled for a production deployment.

---

# Appendix C. Acceptance Traceability and External Decisions

## C.1 Section 5.1 Traceability

| Engagement requirement                               | Main feature evidence                                             |
| ---------------------------------------------------- | ----------------------------------------------------------------- |
| Reachable system used independently on staff devices | WEB-001–003, OPS-001, UAT-001                                     |
| Real authentication and enforced role separation     | IAM-001, ORG-001, IAM-002, APR-001, BRD-001–003, QA-001           |
| Locked authority matrix enforced in software         | DOA-001, REQ-002, APR-001, BRD-002, QA-001                        |
| Persistent records after browser/service restart     | CORE-001, REQ-001–002, AUD-001, OPS-001                           |
| Signature capture and immutable event log            | AUD-001, EVD-001, REQ-002, APR-001, BRD-001–003, HIS-001, OPS-001 |
| Three genuine staff-operated resolved requisitions   | UAT-001, with actual records from the deployed workflow           |

These are evidence mappings, not declarations that the features have been implemented.

## C.2 External Inputs That Must Not Be Invented

| Required input / decision                          | Owner / handling                                                                                                                |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Named staff, HODs, executives, Secretary, Chairman | BNH supplies real identities and appointment scope. Use synthetic identities only for testing.                                  |
| Accepted signature and recovery/MFA setup          | BNH/project owner selects the operational method/configuration. Build the mechanism; do not claim legal acceptance from code.   |
| Board formal evidence and relevant entity/Board    | Secretary/Chairman confirm the actual evidence and applicable Board. Do not invent quorum/voting thresholds.                    |
| Missing/absent/conflicted authority                | BNH authorises any acting arrangement. Until then, block affected actions; no automatic substitute.                             |
| Monetary total and field requiredness              | BNH accepts D-01–03 and D-11 before live transactions, or supplies a documented adjustment without changing confirmed bands.    |
| Production infrastructure and retention            | Authorised operator supplies hosting/storage/domain/identity/email access and retention/recovery settings.                      |
| Frontend repository / project placement            | Use the owner's actual workspace and conventions. Never invent the presence of a missing frontend or silently alter AGENTS.md.  |
| Real staff acceptance availability                 | Actual BNH participants perform their own requests and approvals; the developer/agent cannot complete their signatures.         |
| Full ESE-005/ESE-008 and section 5.3 scope         | Obtain the missing source content for the separate full design/engagement deliverables; do not claim unseen content is covered. |

Only the affected production action or delivery gate is blocked by a genuinely missing external input. The agent must not repeatedly reopen already confirmed business decisions or invent providers/credentials to remove a blocker.

---

# Appendix D. Deferred Product Areas and Separate Design Obligation

This appendix is context and design-boundary preservation, not an executable feature queue. Do not add Feature IDs for these areas to today's implementation run or render their screens as operational.

## D.1 Contract & Vendor Registry and Intelligence

The supplied brief says every holding-company and subsidiary contract is tracked regardless of value, renewal alerts occur at 60 days, service-level breach flags occur within 48 hours, and vendor scores cover four dimensions on a rolling three-month period with automatic threshold flags. Internal clients are GC and CFO.

The exact scoring dimensions, weights, trigger anchors, breach inputs, and threshold values are not supplied. Do not invent them. Future records should reference today's shared entities, counterparties, identity, and evidence infrastructure. Today's basic vendor capture does not constitute this completed module.

## D.2 Regulatory & Compliance Calendar

The supplied brief requires obligations across the holding company and subsidiaries, named owners, and alerts at 90, 30, and 7 days. Its stated examples include CAC, FIRS, sector licences, CBN reporting, and DFI covenant tests. These are source examples, not a newly researched statement of current legal obligations. Internal clients are GC and CFO.

Actual obligations, recurrence rules, date anchors, time zones, evidence standards, and escalation owners require the full specification and BNH's instructions. Do not build a generic calendar and mark compliance complete.

## D.3 Capital Deployment Tracker

The brief names committed, deployed, drawn, returned, and available capital, by subsidiary, tranche, and facility, with authority checks on capital draws and a full audit trail. Internal clients are CFO and Chief of Staff.

The state definitions and calculations are not supplied in full. Do not infer that an approved requisition is a draw, a payment, or deployed capital, and do not invent an available-capital formula. Today's authority engine should be reusable through an explicit later integration, not copied with a different threshold matrix.

## D.4 Deferred Board Enhancements

Written resolutions, native director voting, electronic quorum determination, proxy/substitute rules, a general meeting-management product, director-election controls, and a broad conditional-fulfilment system are deferred. No simple majority or unanimity rule is configured merely from a software developer's guess. The initial process remains an actual meeting followed by Secretary recording and Chairman sign-off.

## D.5 Separate Engagement Design Pack

Section 5.2 calls for functional and technical specifications for all four modules, with later modules specified deeply enough for implementation. This Module 1 feature file and the short context above are not a claim that the entire separate design pack is complete.

Preserve that deliverable in the wider project record. The visible section 5.3 heading refers to a module register/comparison matrix, but its detailed instructions were not supplied. Do not assert fulfilment of those unseen requirements.

---

# Appendix E. Source Register and Agent Handoff

## E.1 Source Register

**S1 — Uploaded example `features.md`:** Used for document organisation, feature terminology, implementation-status values, and the feature-block pattern. Its ProvnCert credential, verification, subscription, payment, and institutional business features are not Custodian requirements and are intentionally not copied into the implementation scope.

**S2 — Uploaded `AGENTS.md`:** Source for repository conventions: Python 3.14/FastAPI/async SQLAlchemy/PostgreSQL/uv; the module layout; Result and CrudUtil contracts; route decorators; permissions; activity registries; tests; dependency policy; and sequential feature delivery with ui_todos.md/task_done.md.

**S3 — Nasir's explicit Custodian decisions in this conversation:** Source for the exact amount matrix, direct routing, requester escalation, exclusion of the legacy path, initial Board meeting method, Secretary recorder role, Chairman final sign-off role, and separation of duties. These decisions are written in full in this file so the coding agent does not need the chat history.

**S4 — Engagement screenshots, sections 4 and 5:** Source for the shared four-module system, Module 1 deployment/persistence/authority/signature/audit/staff-use conditions, and the separate all-four-module design-pack requirement. Files supplied in the conversation include “WhatsApp Image 2026-10-02 at 21.43.05.jpeg” and the two “WhatsApp Image 2026-10-04 at 11.14.44/45.jpeg” screenshots.

**S5 — Requisition form screenshots `1.jpeg` through `4.jpeg`:** Source for the header, vendor fields, scope, cost lines, declaration, and historic sign-off layout. The historic approval path is explicitly superseded. Real personal/bank information from the example must not become production seeds.

**S6 — Visual-standard screenshot `5.jpeg`:** Source for the palette, limited status-colour exception, interface type rules, document typography, A4 page size, and margins.

All technical defaults not explicitly present in these sources are identified as proposed implementation choices in this document. No claim is made that the current repository implements any of them or that the full ESE-005/ESE-008 contents have been reviewed.

## E.2 Repository References Supplied by AGENTS.md

| Topic                    | Referenced location                                                 |
| ------------------------ | ------------------------------------------------------------------- |
| Result pattern           | app/core/result.py; app/core/__init__.py                            |
| Auto-transform           | app/utils/dependencies.py                                           |
| Activity logging         | app/activity_log/README.md; app/activity_log/resolvers.py           |
| Central activity events  | app/activity_log/events.py                                          |
| Permission registry      | app/access_control/constants.py; app/access_control/README.md       |
| Schema bases             | app/mixins/schemas.py                                               |
| Database utility         | app/utils/crud_util.py                                              |
| Tests                    | app/tests/{module}/; app/tests/conftest.py                          |
| Dependency update policy | scripts/dependency_policy.py                                        |
| Feature endpoint guide   | ../ui_todos.md at the owner-confirmed Custodian workspace location  |
| Feature completion log   | ../task_done.md at the owner-confirmed Custodian workspace location |

These are references from the uploaded instructions, not a claim that their implementation files were inspected here.

## E.3 Coding-Agent Start Instruction

> Read AGENTS.md and this features.md. Implement Custodian Module 1 against the existing scaffold, starting with the first feature that is not Implemented and proceeding sequentially under the repository's branch, test, documentation, and tracker rules. Reuse existing working capabilities; do not perform an unrelated architecture review or generate another plan. The target is to finish the software build today. Preserve the exact authority matrix, no-self-approval rules, Secretary–Chairman Board process, greyscale standard, persistent storage, and immutable evidence. Do not add deferred modules or legacy approval stages. Continue routine implementation without repeatedly asking to proceed. Report genuine blockers precisely, never invent configuration or acceptance evidence, and distinguish tested code, deployment, and actual BNH staff acceptance in the final report.

---

# Platform Functional Specification Completion

The executable Module 1 scope is complete only when every applicable feature through OPS-001 is implemented and verified, the actual browser application is usable, and the UAT-001 result is recorded truthfully. A pending external staff gate must remain pending even when software work is complete. The separate four-module design obligation remains separately tracked.

This file supplies the product implementation reference and tracker. It does not assert current code completeness, legal certification, production approval, or that the same-day target has already been achieved.
