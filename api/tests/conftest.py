from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    storage_dir = tmp_path / "sources"
    storage_dir.mkdir()
    db_path = tmp_path / "verify.db"

    monkeypatch.setattr("app.config.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("app.config.settings.storage_dir", str(storage_dir))
    monkeypatch.setattr("app.config.settings.verifier_instance_id", "test-verifier")

    from app.database import Base, get_engine, init_db

    init_db(reset=True)
    Base.metadata.drop_all(bind=get_engine())
    Base.metadata.create_all(bind=get_engine())

    # Reset the in-memory write rate limiter so per-IP windows don't leak
    # across tests (otherwise later submits in a run get 429 instead of 202).
    from app.main import _verify_limiter

    _verify_limiter._hits.clear()
    return tmp_path


@pytest.fixture
def example_tarball() -> bytes:
    from tests.helpers import load_example_tarball

    return load_example_tarball(ROOT)
