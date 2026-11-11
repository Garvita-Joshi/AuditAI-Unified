# Procurement calling — Phase 2 backend foundation

This extends the existing AuditAI procurement workspace. Its eventual interface
is **Vendor → Call progress**, next to the existing email pages. There is no
second procurement application or Streamlit dashboard.

## What is implemented

- Authenticated, owner-scoped RFQ and shortlisted-vendor lookups.
- Prepared call records, frozen purchase requirements, and the existing
  `AuditAI-R<run_id>-V<shortlisted_vendor_record_id>` email tracking reference.
- Quotation fields with original responses, exact normalized values, and
  `CONFIRMED`, `UNKNOWN`, `NOT_PROVIDED`, or `NEEDS_VERIFICATION` status.
- Missing-field detection, currency/budget review flags, manual corrections,
  optimistic version checks, and an audit record of each supplied/corrected field.
- Owner-entered transcripts and callback requests, with duplicate prevention.
- A call activity timeline in the existing sourcing activity table.
- Additive schema initialization for SQLite and PostgreSQL.

The selected voice platform is **Dograh**. There is deliberately **no dialing endpoint, Dograh network client, webhook,
background calling job, or automatic callback execution** in this phase.
Setting `VOICE_CALLS_ENABLED=true` cannot enable a call. No paid service or real
call is needed to verify the foundation. Transcript/quotation inputs in this
phase are manual evidence, not claims that a real conversation took place.

## Relationship to existing data

RFQs reuse `sourcing_requests`; vendors reuse `sourcing_agent_vendors` and its
catalog contact snapshot. Access requires both the request and its sourcing run
to belong to the authenticated account. A global administrator role does not
implicitly grant access to another company's/requester's phone records.

Voice statuses are separate from email statuses. Preparing a call cannot change
an email from sent to pending, dispatch an RFQ, choose a winner, approve a
purchase, create a PO, or authorize payment.

The new tables are:

| Table | Purpose |
| --- | --- |
| `procurement_voice_calls` | Vendor/request link, call state, provider reference, requirements snapshot |
| `procurement_voice_quotations` | One quotation per call, status and edit version |
| `procurement_voice_quotation_fields` | Required fields, original words, normalized values, confirmation evidence |
| `procurement_voice_quotation_audit` | Old/new field snapshots, actor, source, reason, timestamp |
| `procurement_voice_transcripts` | Speaker, message, message key, timestamp and call offset |
| `procurement_voice_callbacks` | Requested future callback time and reason; no automatic dialing |
| `procurement_voice_operations` | Idempotency receipts for repeated mutation requests |

Fields live in a child table instead of fixed quotation columns so each field
can retain its own uncertainty, response and confirmation evidence. This does
not create duplicate vendor/RFQ master datasets. The requirements snapshot
preserves existing line items. This phase records quotation fields at request
level; itemized price-basis extraction and conversation logic are later work.

## Data rules

Money is submitted as exact decimal strings, not JSON floating-point values.
`unit_price` and quantities allow up to four decimal places; total, shipping and
tax amounts allow up to two. Values cannot be negative or non-finite. Currency
is a three-letter code. Expected delivery dates use `YYYY-MM-DD`.

Unknown/unprovided values remain null. In particular, shipping and taxes never
default to zero, and warranty/payment terms are never fabricated. A confirmed
field requires the original response and a confirmation-evidence note. A
complete quotation still requires the existing human purchase approval chain.
No exchange rates or assumptions about tax/shipping inclusion are applied.

Mutation operations use an `idempotency_key` of 8–128 letters, numbers, dots,
underscores, colons or hyphens. Reuse the key only for a retry of the same
operation/data. Reusing it for different data returns 409. Only one open call
record is allowed per shortlisted vendor record. This prevents repeated clicks
from creating multiple prepared attempts.

Edits require the latest quotation `version` and a nonempty reason. Stale edits
return 409. Transcript message keys cannot be reused with different content.
All API writes commit their data, audit and idempotency receipt together.

## API

All routes use existing company authentication and start with `/api/v1/voice`.
New records contain UUID identifiers; `request_id` and `agent_vendor_id` refer
to the existing integer IDs, not a vendor's catalog code.

| Method and suffix | Behaviour |
| --- | --- |
| `GET /config` | Phase/storage information; live calling is always false |
| `GET /rfqs/{request_id}` | Existing saved requirements |
| `GET /rfqs/by-reference?reference=...` | Resolve the existing email/RFQ tracking reference |
| `GET /rfqs/{request_id}/required-fields` | Required quotation field names |
| `GET /rfqs/{request_id}/vendors` | Shortlisted vendors from existing sourcing runs |
| `GET /rfqs/{request_id}/vendors/{vendor_record_id}` | Owner-authorized contact details |
| `POST /calls/drafts` | Save a call preview; does not place a call |
| `GET /calls` | Own calls; optional `request_id`, `limit`, `offset` |
| `GET /calls/{call_id}` | Prepared/current call record |
| `POST /calls/{call_id}/cancel` | Cancel an unstarted preview, with reason and idempotency key |
| `GET /calls/{call_id}/timeline` | This call's events |
| `GET, POST /calls/{call_id}/transcript` | Read/append owner-entered transcript evidence |
| `GET, POST /calls/{call_id}/callbacks` | Read/record future callback requests |
| `POST /quotations` | Create one quotation for a call |
| `GET /quotations` | Own quotations; optional `request_id`, `limit`, `offset` |
| `GET /quotations/{quotation_id}` | Field values, uncertainty and missing fields |
| `PATCH /quotations/{quotation_id}/fields` | Correct one field, with version and reason |
| `GET /quotations/{quotation_id}/audit` | Field-change history |

Call draft request:

```json
{
  "request_id": 123,
  "agent_vendor_id": 456,
  "idempotency_key": "prepare-call-unique-key"
}
```

Quotation field example (use a real authorized call ID in the envelope):

```json
{
  "name": "unit_price",
  "value": "950.00",
  "original_response": "Unit price is nine hundred and fifty rupees.",
  "status": "NEEDS_VERIFICATION"
}
```

Use the API documentation at `http://127.0.0.1:8000/docs`, authorize with the
existing login token, and expand **procurement voice foundation**. Creating a
draft is optional; visiting the docs/configuration does not create records.
The React Call progress screen is intentionally unchanged until the UI phase.

## Database setup and preservation

The running local app remains on its configured database. No claims, accounts,
vendor catalogs, sourcing runs or email history are moved or reset.

The normal backend startup registers and creates missing voice tables. To apply
only these additive tables to an already initialized AuditAI database:

```sh
cd /Users/garvita16/Desktop/Projects/AuditAI-Unified
.venv-model/bin/python scripts/init_voice.py
```

The initializer refuses to create a standalone second RFQ/vendor system if the
existing sourcing/account tables are missing. It does not alter old columns,
drop tables, or seed data. Running it again preserves existing records.

For PostgreSQL, use the project's existing `psycopg2-binary` dependency and an
explicit driver, for example:

```dotenv
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@127.0.0.1:5433/auditai_unified
```

Do not simply switch an existing SQLite deployment to an empty PostgreSQL
database: that would make saved records appear missing. Copying and reconciling
the full existing database is a separate migration, not performed here.

## Tests

SQLite checks and existing procurement/email regressions:

```sh
cd /Users/garvita16/Desktop/Projects/AuditAI-Unified
.venv-model/bin/python -m pytest -q tests/test_voice_foundation.py tests/test_automatic_rfq_dispatch.py tests/test_sourcing_mail_delivery.py tests/test_procurement.py
```

To additionally run the voice tests against local PostgreSQL, set
`VOICE_TEST_POSTGRES_URL` to a development database using the explicit
`postgresql+psycopg2` driver. The test account must be able to create a schema.
Tests create a unique `test_voice_<uuid>` schema and remove only that schema
afterward. They never use the database's existing application tables.

Tests cover authenticated access, cross-owner isolation, saved snapshots,
idempotency conflicts, transaction rollback, unknown fields, confirmation
evidence, exact money, stale-edit rejection, audit history, transcript replay,
callback timezones, repeatable schema initialization and persistence across DB
sessions. HTTP/SMTP attempts fail the tests. No vendor calls or emails are sent.

## Later phases

Phase 3 adds Hinglish conversation rules and validated procurement tools, tested
without phone calls. Phase 4 adds the isolated Dograh client, authenticated
webhooks and explicitly authorized calling. Phase 5 integrates the existing
React Call progress page. Future credentials are placeholders in `.env.example`;
the real `.env` has not been changed.

## Dograh connection plan

Dograh handles speech and telephony; AuditAI keeps request/vendor authorization,
validated backend tools, quotation evidence, audit history, and human purchase
approval. Use hosted Dograh or a separately hosted instance. Configure:

- `DOGRAH_BASE_URL`: the API origin (`https://api.dograh.com` for hosted Dograh).
- `DOGRAH_API_KEY`: a private Dograh API key; backend only.
- `DOGRAH_TRIGGER_PATH`: path/UUID copied from the agent's API Trigger node.
  This is different from the workflow's Agent UUID.
- `DOGRAH_WEBHOOK_TOKEN`: an AuditAI-defined secret to configure in custom
  authentication headers for future HTTP tools/webhooks. This is not a claim
  that Dograh provides a particular built-in signature format.
- `PUBLIC_API_BASE_URL`: an address Dograh can reach for future callbacks.

Dograh's documented trigger routes use `X-API-Key` authentication, a
`phone_number`, and optional `initial_context`. Production triggers run the
published workflow. A test trigger selects the draft workflow: **it can still
place a real phone call**, so it must never replace our mock/no-dial tests.

AuditAI will pass authorized RFQ/vendor context to Dograh, receive validated
HTTP tool requests and configured result webhooks, and store the returned run
reference in the existing generic `provider_call_id` field. Historical records
retain their original provider label. Existing previews for another provider
must be cancelled before preparing a Dograh preview.

Actual connection still requires a configured Dograh agent, telephony provider
and authorized number. This change does not install Dograh, provision telephony,
enable billing, change live secrets, or call external APIs. Self-hosting is an
option, but telephony, inference and hosting costs depend on the chosen setup.

Verified official references:

- [API Trigger](https://docs.dograh.com/voice-agent/api-trigger)
- [API keys](https://docs.dograh.com/configurations/api-keys)
- [HTTP tools](https://docs.dograh.com/voice-agent/tools/http-api)
- [Webhook node](https://docs.dograh.com/voice-agent/webhook)
- [Agent UUID vs trigger path](https://docs.dograh.com/configurations/agent-uuid)
