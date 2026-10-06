**I should have made the screen count explicit, boss. My proposed first-release scope is 14 screens: 3 account-access screens and 11 application screens.**

The file I gave you grouped the interface into broad feature blocks instead of defining a screen-by-screen inventory. That left too much for the coding agent to decide. The feature count is **not** the screen count. :chatgpt-content-reference{index="0"} :chatgpt-content-reference{index="1"}

## The proposed 14 screens

| # | Screen | What it contains |
|---|---|---|
| **1** | **Sign In** | Staff authentication, any required verification step, and access to password recovery. |
| **2** | **Forgot Password** | Request a secure password-reset link. |
| **3** | **Set Password / Activate Account** | One reusable screen for accepting an invitation or setting a replacement password through a valid link. No public registration. |
| **4** | **Dashboard** | Role-appropriate request counts, outstanding tasks, recent activity, and shortcuts. **One shared dashboard**, not a separate implementation for every role. |
| **5** | **Requisitions** | Searchable, filterable request list. “My Requests,” drafts, pending, approved, rejected, and returned are filters or tabs—not separate screens. Wider visibility requires explicit permission. |
| **6** | **Create / Edit Requisition** | Requester information, vendor details, scope, cost lines, attachments, declaration, and submission. Creating a request, editing a draft, and correcting a returned request reuse this form. |
| **7** | **Requisition Details & Review** | Complete request, total, required authority, status, documents, signatures, and approval history. The assigned HOD, Chief of Staff, or MD reviews and acts **on this same screen**. |
| **8** | **My Tasks / Approval Inbox** | Work requiring the current user’s action. Individual approvals open screen 7; Secretary recording and Chairman sign-off tasks open screen 9. |
| **9** | **Board Resolution Workspace** | The Secretary records the meeting resolution and uploads evidence. The Chairman reviews and signs off or returns it. **One screen with different permitted actions**, preserving two separate identities and responsibilities. |
| **10** | **Vendors** | Basic reusable vendor/contact/bank records for requisitions. Add, edit, and detail views use drawers. No contract management, vendor scoring, or payment processing. |
| **11** | **Staff & Access Management** | Staff invitations, account status, department membership, and controlled role/officeholder assignments. No unrestricted self-granting of financial authority. |
| **12** | **Organisation & Authority** | Company entities, departments, and assigned officeholders, organised into tabs. The agreed authority matrix is visible **read-only**, not an editable workflow builder. |
| **13** | **Audit Log** | Restricted, searchable history of recorded actions, with links to the relevant requests and evidence. No edit or delete controls. |
| **14** | **My Account & Security** | Personal account details, password/security controls, and sessions where supported. Staff cannot change their own department or approval authority here. |

## What does **not** need another screen

**Approving, rejecting, returning, and signing** should use focused dialogs from the relevant request or Board workspace. They do not need individual pages.

**Notifications** should appear in a header drawer. **Attachments and generated documents** should open in a viewer. **Adding a vendor, inviting staff, assigning an officeholder, and editing a department** should use drawers or dialogs within their management screens.

The Board workspace can have distinct Secretary and Chairman views without becoming two applications. Likewise, the HOD, Chief of Staff, and MD can use the same approval interface while the backend enforces their different authority.

**That is the proposed count: 14 reusable screen templates—not 14 screens for every user, and not one screen per feature.** The development file should have mapped every feature to these screens, with the fields, actions, permissions, and states specified explicitly.