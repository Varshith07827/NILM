"""Application configuration.

Every value can be overridden with an environment variable (or a ``.env`` file
in the project root) using the ``NILM_`` prefix, e.g. ``NILM_TARIFF_NAME`` or
``NILM_DATABASE_URL``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings for the NILM backend."""

    model_config = SettingsConfigDict(
        env_prefix="NILM_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- service ------------------------------------------------------- #
    app_name: str = "Edge AI NILM Smart Meter"
    version: str = "1.0.0"
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]

    # --- storage ------------------------------------------------------- #
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'database' / 'nilm.db').as_posix()}"
    reports_dir: Path = PROJECT_ROOT / "reports"
    recordings_dir: Path = PROJECT_ROOT / "database" / "recordings"
    artifact_dir: Path = PROJECT_ROOT / "ai" / "artifacts"

    # --- simulation ---------------------------------------------------- #
    default_scenario: str = "evening"
    default_mode: str = "demo"
    default_speed: int = 1
    #: Windows kept in the in-memory ring buffer for instant chart loads.
    live_buffer_size: int = 3600
    #: Rows buffered before being flushed to SQLite in one transaction.
    persist_batch_size: int = 25
    #: Inference backend: auto | numpy | tflite | heuristic.
    inference_backend: str = "auto"
    #: Start the simulation automatically when the server boots.
    autostart: bool = True

    # --- tariff (Module 7) --------------------------------------------- #
    tariff_currency: str = "INR"
    tariff_currency_symbol: str = "₹"
    #: Which of :data:`TARIFF_PRESETS` is active at startup.
    default_tariff_id: str = "domestic_slab"
    #: Consumption already billed this month, so a fresh demo does not always
    #: start in the cheapest slab.
    monthly_baseline_kwh: float = 0.0

    # --- alert thresholds (Module 14) ---------------------------------- #
    high_power_threshold_w: float = 3000.0
    daily_cost_alert_inr: float = 100.0
    peak_current_alert_a: float = 25.0
    #: Sanctioned load of the connection, for the peak-load gauge.
    sanctioned_load_w: float = 5000.0

    @property
    def database_path(self) -> Path:
        return Path(self.database_url.replace("sqlite:///", ""))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.recordings_dir.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
