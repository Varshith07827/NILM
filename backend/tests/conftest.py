"""Shared pytest fixtures.

The environment must be configured *before* anything imports the application,
because :func:`backend.app.core.config.get_settings` is LRU-cached and the
SQLAlchemy engine is created at module import time from the resulting URL.
Setting these at collection time keeps the test run entirely off the real
database.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_TEST_DIR = Path(tempfile.mkdtemp(prefix="nilm-tests-"))
os.environ.setdefault("NILM_DATABASE_URL", f"sqlite:///{_TEST_DIR.as_posix()}/test.db")
os.environ.setdefault("NILM_REPORTS_DIR", str(_TEST_DIR / "reports"))
os.environ.setdefault("NILM_RECORDINGS_DIR", str(_TEST_DIR / "recordings"))
# Tests drive the simulation explicitly; an autostarted loop would make them
# depend on wall-clock timing.
os.environ.setdefault("NILM_AUTOSTART", "false")

import pytest  # noqa: E402

from simulator.house import VirtualHouse  # noqa: E402
from simulator.scenarios import SimulationMode  # noqa: E402


@pytest.fixture(scope="session")
def test_dir() -> Path:
    return _TEST_DIR


@pytest.fixture
def house() -> VirtualHouse:
    """A deterministic evening-demo house."""
    return VirtualHouse(scenario_id="evening", mode=SimulationMode.DEMO, seed=4242)


@pytest.fixture
def empty_house() -> VirtualHouse:
    """A house with nothing switched on and no autonomous behaviour."""
    return VirtualHouse(scenario_id="custom", mode=SimulationMode.DEMO, seed=7)


@pytest.fixture(scope="session")
def client():
    """FastAPI test client with the application lifespan running."""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client
