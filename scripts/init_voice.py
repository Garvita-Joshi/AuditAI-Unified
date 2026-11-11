"""Add voice tables to an initialized AuditAI DB; creates no application data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.main import app  # Register existing models before resolving FKs.
from backend.app.db import engine
from backend.app.agentic_ai.voice.migration import upgrade


if __name__ == "__main__":
    for table in upgrade(engine):
        print(f"Ready: {table}")
    print("Voice foundation initialized. No calls made, no records seeded.")
