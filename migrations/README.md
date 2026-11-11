# Unified schema baseline

This initial integration targets a new, empty PostgreSQL database named `auditai_unified`.
Run `python scripts/init_unified.py` after configuring DATABASE_URL. It registers the expense,
company-account, OTP, procurement, sourcing and agent tables and creates missing tables.
This is an additive baseline initializer, not an upgrade migration for either existing database.
Do not point it at either original database. Subsequent schema upgrades need versioned migrations.
Company data, receipts, models and accounts are not migrated automatically.
