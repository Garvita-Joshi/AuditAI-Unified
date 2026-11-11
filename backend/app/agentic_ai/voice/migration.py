"""Idempotently add voice tables without altering or seeding existing records."""
from sqlalchemy import inspect

from .models import VOICE_TABLES


def upgrade(engine):
    required = {"auth_users", "sourcing_requests", "sourcing_agent_runs", "sourcing_agent_vendors", "sourcing_agent_activities"}
    with engine.begin() as connection:
        existing = set(inspect(connection).get_table_names())
        missing = required - existing
        if missing:
            raise RuntimeError("Initialize the existing AuditAI schema first; missing tables: " + ", ".join(sorted(missing)))
        for table in VOICE_TABLES:
            table.create(connection, checkfirst=True)
    return [table.name for table in VOICE_TABLES]
