from pathlib import Path
from backend.app import config

def test_runtime_files_stay_inside_unified_project():
    root=Path(__file__).resolve().parents[1]
    assert config.PROJECT_ROOT==root
    assert config.TRAINED_MODELS_DIR==root/'backend'/'trained_models'
    assert config.DATA_DIR==root/'data'
