"""Create the unified schema in a NEW database; never imports or seeds records."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.main import app  # registers models
from backend.app.db import Base, engine
if __name__ == '__main__':
    Base.metadata.create_all(engine)
    print('Unified schema initialized. No records imported or seeded.')
