# Saved procurement workspace

Purchase records use the configured SQLAlchemy database. The current local setup uses the on-disk SQLite database `.runtime/unified.db`, with an absolute `DATABASE_URL` in the project's private `.env`. Keep that database and the uploaded document directory when restarting or moving the project. A browser cache is not the source of truth.

## Records

* `sourcing_requests`: owner, typed JSON requirements (including all line items and privacy answers), messages, version and creation time.
* `sourcing_workspaces`: request ID, last explicitly saved form step, generated approval graph, and update time. This additive table is created at application startup; existing records are retained.
* `sourcing_contract_documents`: request/owner ID, document kind, original filename, storage key, size and timestamp. The file bytes remain in the existing document storage directory.
* `sourcing_agent_runs`, `sourcing_agent_vendors`, `sourcing_agent_activities`: existing supplier drafts, replies, send status and activity history.
* `procurement_requests`, approval steps/subtasks, orders, invoices, payments and events: existing submitted/approved purchase records and their evidence.

## Save and reopen

Typing updates local React state. **Save draft** or **Next** commits a full validated JSON snapshot and step to the database, with optimistic version checking. Closing and reopening a saved row uses `?newRequest=new&requestId=<id>&intakeStep=<step>`. Refreshing that URL loads the same owner-scoped record rather than creating a blank draft. Unsaved typing is deliberately not recovered.

The dashboard reads both authorized purchase requests and the current user's saved sourcing briefs. Empty drafts created on opening a form stay out of the overview until they contain saved input. Sourcing and purchase IDs have distinct SR/PR labels. Reopening reads the existing agent run and graph; it does not start a new sourcing run. The existing inbox synchronization behavior in the vendor workspace continues unchanged.

Changing a saved purchase requirement invalidates the stored generated graph so a stale plan is not restored. Regeneration saves the replacement graph. Documents and agent history are retained.

## Analytics

All four cards derive from saved records. Awaiting approval counts submitted purchase requests; sourcing drafts are not approval decisions. Approved commitments sum INR approvals only, with other currencies explicitly excluded instead of silently converted. The bar chart uses PO approval timestamps, with clearly labeled creation-week fallback for older approvals lacking that timestamp. No synthetic trend data is inserted.

## Verification

`tests/test_sourcing_persistence.py` saves to a temporary file-backed SQLite database, closes the server and engine, starts a fresh application, and verifies requirements, privacy answers, documents, workflow and agent run restoration. It also checks owner isolation and stale-save rollback. Frontend persistence tests verify no per-keystroke save, explicit JSON saving, reopening without duplicates, and StrictMode initialization. Test adapters block external mail/LLM actions.
