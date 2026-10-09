"""FastAPI application entry point.

Run from the project root::

    python -m uvicorn backend.app.main:app --reload
    # or simply:  python run_backend.py
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.routes import (
    auth,
    cost,
    history,
    house,
    live,
    notifications,
    reports,
    simulation,
    ws,
)
from backend.app.core.config import Settings, get_settings
from backend.app.db.session import init_database, session_scope
from backend.app.services import house_config
from backend.app.services.accounts import admin_exists, bootstrap_admin
from backend.app.services.cost import Tariff
from backend.app.services.pipeline import NILMPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nilm")

settings = get_settings()


def _load_saved_state(settings: Settings) -> tuple[house_config.HouseConfig, dict, dict]:
    """Seed first-run data and read back everything the admin has saved."""
    with session_scope() as session:
        if house_config.seed_if_empty(session):
            logger.info("seeded the default house (a ceiling fan in every room)")
        if bootstrap_admin(session, settings):
            logger.info("admin account %r created from NILM_ADMIN_PASSWORD", settings.admin_username)
        elif not admin_exists(session):
            logger.warning(
                "no admin account yet -- create one with: "
                "python -m backend.manage set-admin-password"
            )
        config = house_config.load_house(session)
        tariff = house_config.get_setting(session, cost.TARIFF_SETTING) or {}
        alerts = house_config.get_setting(session, cost.ALERTS_SETTING) or {}
    return config, tariff, alerts


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the database and the pipeline, and tear them down cleanly."""
    init_database()
    logger.info("database ready at %s", settings.database_path)
    config, saved_tariff, saved_alerts = _load_saved_state(settings)

    pipeline = NILMPipeline(settings, devices=config.devices, rooms=config.rooms)
    if saved_tariff:
        pipeline.set_tariff(Tariff.from_dict(saved_tariff))
    for key, value in saved_alerts.items():
        if hasattr(pipeline.notifier, key):
            setattr(pipeline.notifier, key, value)
            setattr(settings, key, value)
    app.state.pipeline = pipeline
    logger.info(
        "house: %d rooms, %d devices", len(config.rooms), len(config.devices)
    )

    info = pipeline.engine.info()
    if info["model_available"]:
        metrics = info.get("metrics", {})
        logger.info(
            "inference backend=%s  architecture=%s  params=%s  macro-F1=%.3f",
            info["backend"],
            info["architecture"],
            f"{info['parameters']:,}",
            metrics.get("macro_f1", float("nan")),
        )
    else:
        logger.warning("no trained model found: %s", info.get("load_error"))

    if settings.autostart:
        await pipeline.start()
        logger.info(
            "simulation started  scenario=%s  mode=%s  speed=%sx",
            pipeline.scenario_id,
            pipeline.mode.value,
            pipeline.speed,
        )

    try:
        yield
    finally:
        await pipeline.stop()
        pipeline.recorder.stop()
        logger.info("pipeline stopped, buffers flushed")


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Edge AI-based Non-Intrusive Load Monitoring for low-cost smart "
        "metering. A virtual household is simulated at the waveform level; a "
        "MobileNetV3-derived classifier running on a dependency-free NumPy "
        "kernel disaggregates the single aggregate current measurement into "
        "per-appliance power, energy and cost."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(live.router, prefix="/api")
app.include_router(simulation.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(cost.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(house.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(ws.router)


@app.get("/api/health", tags=["meta"])
async def health() -> dict:
    pipeline: NILMPipeline = app.state.pipeline
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "simulation": pipeline.state.value,
        "windows_processed": pipeline.stats.windows_processed,
        "inference_backend": pipeline.engine.backend.value,
    }


@app.get("/", tags=["meta"])
async def root() -> JSONResponse:
    return JSONResponse(
        {
            "name": settings.app_name,
            "version": settings.version,
            "docs": "/docs",
            "websocket": "/ws",
            "dashboard": "run the frontend with: npm run dev (in ./frontend)",
        }
    )
