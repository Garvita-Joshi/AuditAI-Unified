# AuditAI Unified integration

## Sources and ownership

Foundation: Garvita-Joshi/AuditAI (expense API, behavioral model v2, OCR, maker/checker rules,
orange-and-black frontend). Procurement: local AuditAI-main, published as AuditProcurement
commit 7511e29 (purchasing, approvals, supplier CRM, sourcing, SMTP/IMAP, sandbox payment).
Original folders were not changed by integration.

## Workflow

OTP -> provisioned company identity -> expense workspace OR procurement workspace.
Expenses: claim + receipt -> local OCR -> behavioral scoring -> maker -> independent checker.
Procurement: existing PO/new need -> details -> privacy -> approval map -> sourcing drafts ->
automatic RFQ outreach -> quotes -> final human choice -> departmental approvals -> PO ->
invoice match -> optional procurement anomaly assessment -> finance -> PayPal sandbox (USD only).
INR approvals retain the 100,000 threshold; INR PayPal checkout remains blocked.

## Identity

Company AuthUser is the single identity. Procurement's User is an alias, not another table.
OTP JWT/refresh and company password login authenticate the same provisioned account.
Password login remains for backwards compatibility; the UI uses OTP.
Expense roles remain in `roles`; procurement assignment uses `role` set by provision_user.py.
Claim owners/contributors cannot review; maker and checker must differ. No public self-provisioning.
Live OTP requires SMTP. AUTH_DEBUG_OTP defaults false. No old credentials were copied.

## Models and data

Expense behavioral pipeline from AuditAI remains intact. Procurement imports its own legacy
AE architecture under procurement/autoencoder.py, preventing a class collision.
No trained bundles were imported. Missing bundles must be reported as unavailable.
The GitHub clone contains its original tracked sample files; none were loaded into a database.
No company workbook/catalog or original runtime database has been migrated.

## External services

No existing .env was copied and no messages/calls/payments were triggered during integration.
Sourcing sends initial RFQs automatically to stored company vendor contacts after shortlisting.
Email approval is not required. Each attempt is logged; repeated start/sync requests skip sent
messages. Failed messages have an explicit retry action. Missing and unverified contacts need
correction before outreach. Final supplier selection, purchase approval, and payment remain
human decisions. Inbox updates use authenticated API polling.
Sarvam is not connected. Configure and test it separately before enabling calls.

## Setup

1. Create a NEW PostgreSQL database `auditai_unified`.
2. Create a virtual environment and install requirements.txt. For CPU PyTorch install torch
   separately if your installer rejects the repository's historical torch index directive.
3. Copy .env.example to .env and set DATABASE_URL, COMPANY_EMAIL_DOMAINS, JWT secret and SMTP.
4. Run `python scripts/init_unified.py` (schema only).
5. Provision real accounts with `python scripts/provision_user.py --email name@company.com
   --employee-id EMP001 --roles employee,manager`. This prompts for a password and sets both role fields.
6. Start `uvicorn backend.app.main:app --host 127.0.0.1 --port 8002`.
7. In frontend: `npm ci`; `API_PROXY_TARGET=http://127.0.0.1:8002 npm run dev -- --host 127.0.0.1 --port 5190`.
8. Open http://127.0.0.1:5190, authenticate by OTP. Procurement is a navigation link.

For isolated local inspection only, a new SQLite database may be used. Production target is PostgreSQL.
Do not run the inherited seeding/training scripts against company data without review.

## Validation and remaining configuration

Existing audit tests: 35 passed / 3 skipped. Procurement: 15 passed / 1 skipped.
New OTP integration test verifies one account accesses both modules while scoring remains role-gated.
Frontend production build passes. External-service delivery and PostgreSQL deployment still require
configuration and live verification. Model availability is not implied by a successful build.

Final combined run: **51 passed, 4 skipped**. Preview backend health and orange/black OTP login were checked at ports 8002/5190. Preview database is empty SQLite under /tmp and contains no migrated company records.

## Existing setup connection (2026-11-02)

The existing PostgreSQL login cannot CREATE DATABASE. The development runtime therefore uses
`.runtime/unified.db` (isolated SQLite), not either original database. A PostgreSQL administrator
must create an owned `auditai_unified` database before deployment. The original DB was only read.
Imported 15 existing accounts with their procurement roles preserved; linked directory employee IDs
only by exact email. Only 1 account matched the supplied employee directory. No guessed head-role
assignments were made and no new audit maker/checker privileges were granted.
Copied the company workbook export (40 employees, 10 department heads, 14 vendors, 42 offers).
Configured the catalog explicitly to the 42 workbook offers, excluding synthetic fallback offers.
Copied local SMTP/Gemini configuration to ignored `.env` with mode 0600 and a new JWT secret.
Verified sourcing SMTP authentication without sending a message. OTP delivery itself remains
unverified until the user requests a code. No old OTPs, sessions, purchases, sourcing runs or payment
history were imported. Existing accounts use OTP; random unusable initial password values were set.
Procurement model bundle copied and inference checked (score returned). Corrected PROJECT_ROOT
so model/data paths resolve inside this folder. Expense `pipeline_v2.joblib` was not found locally;
expense scoring remains unavailable until a compatible bundle is supplied or approved training runs.
Source company data, runtime database, secrets and copied model are ignored by Git.

## AuditAI upstream refresh — commit 8c62504 (2026-11-02)

Fetched origin/main and integrated the updated audit source, schema/service additions,
orange/black audit UI, audit profiles, workspace settings, shared review queue, policy/master-data
checks, transfer cycle detection, reconciliation, record evidence and behavioral model changes.
Preserved unified OTP/JWT login (including port-465 fix), procurement API/UI, company account model,
local credentials/data, procurement model and readable dark procurement surfaces.
Upstream audit.db, test.db, dataset archives, training artifacts and database snapshots were not
installed as the runtime database. Packaged download samples and small upstream test fixtures were
restored as files only; no sample records were imported into the migrated company database.
Upstream developer OTP endpoints remain opt-in and disabled (AUDITAI_DEV_OTP unset).
One upstream OCR/model integration test was made self-contained with a tiny temporary test bundle;
this does not install a live expense model or train on company data.
Validation: 149 backend tests passed / 3 skipped; 21 frontend tests passed; production build passed.
Backend restarted at 8002 and exposes 113 OpenAPI paths, including audit and procurement sections.
Frontend stays at 5190. Browser inspection was unavailable during final verification; source/build,
frontend tests, backend tests and live API schema were verified. No external email/call/payment ran.
A pre-update backup is at /tmp/auditai-unified-before-update-1793638343.tar.gz.
