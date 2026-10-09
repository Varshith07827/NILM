"""SQLAlchemy ORM models (Module 8).

Storage is split into three shapes, each chosen for how it will be read:

``Reading``
    One row per acquisition window.  This is the raw time series behind the
    live charts and the history endpoint.

``EnergyBucket``
    Per-appliance energy accumulated into hourly buckets, upserted as the
    simulation runs.  Reports read from here, so a monthly report is a single
    indexed aggregate query rather than a scan of a million per-second rows.

``ApplianceEvent`` / ``Notification``
    Discrete occurrences, for the timeline and the alert panel.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Reading(Base):
    """One second of metered data plus the model's interpretation of it."""

    __tablename__ = "readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: Real wall-clock time the row was produced.
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    #: Time inside the simulated household.
    sim_time: Mapped[datetime] = mapped_column(DateTime, index=True)

    # --- electrical measurements --------------------------------------- #
    current_a: Mapped[float] = mapped_column(Float)
    voltage_v: Mapped[float] = mapped_column(Float)
    power_w: Mapped[float] = mapped_column(Float)
    reactive_var: Mapped[float] = mapped_column(Float)
    apparent_va: Mapped[float] = mapped_column(Float)
    power_factor: Mapped[float] = mapped_column(Float)
    thd: Mapped[float] = mapped_column(Float)
    peak_current_a: Mapped[float] = mapped_column(Float)

    # --- derived quantities -------------------------------------------- #
    energy_wh: Mapped[float] = mapped_column(Float)
    cumulative_energy_wh: Mapped[float] = mapped_column(Float)
    cost_inr: Mapped[float] = mapped_column(Float)

    # --- model output --------------------------------------------------- #
    #: {appliance_id: estimated watts}
    appliance_power: Mapped[dict] = mapped_column(JSON, default=dict)
    #: {appliance_id: probability}
    appliance_probability: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Appliances above their decision threshold.
    detected: Mapped[list] = mapped_column(JSON, default=list)
    unattributed_w: Mapped[float] = mapped_column(Float, default=0.0)
    inference_ms: Mapped[float] = mapped_column(Float, default=0.0)

    # --- run context ---------------------------------------------------- #
    scenario: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    run_id: Mapped[str] = mapped_column(String(36), index=True)

    __table_args__ = (Index("ix_readings_run_sim", "run_id", "sim_time"),)


class EnergyBucket(Base):
    """Per-appliance energy and cost, accumulated per hour.

    ``appliance_id`` uses the sentinel ``"__total__"`` for whole-house figures
    and ``"__unattributed__"`` for power the model could not assign.
    """

    __tablename__ = "energy_buckets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Hour-truncated simulated timestamp.
    bucket_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    appliance_id: Mapped[str] = mapped_column(String(32), index=True)
    energy_wh: Mapped[float] = mapped_column(Float, default=0.0)
    cost_inr: Mapped[float] = mapped_column(Float, default=0.0)
    #: Seconds within the bucket during which the appliance was detected on.
    runtime_s: Mapped[float] = mapped_column(Float, default=0.0)
    peak_power_w: Mapped[float] = mapped_column(Float, default=0.0)
    run_id: Mapped[str] = mapped_column(String(36), index=True)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "bucket_start", "appliance_id", name="uq_bucket_identity"
        ),
    )


class ApplianceEvent(Base):
    """Switch-on / switch-off events, for the dashboard timeline."""

    __tablename__ = "appliance_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sim_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    appliance_id: Mapped[str] = mapped_column(String(32), index=True)
    appliance_name: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(128), default="")
    power_w: Mapped[float] = mapped_column(Float, default=0.0)
    #: True when the AI independently detected this transition, rather than the
    #: simulator merely reporting it. Lets the demo show detector agreement.
    detected_by_model: Mapped[bool] = mapped_column(Boolean, default=False)
    run_id: Mapped[str] = mapped_column(String(36), index=True)


class Notification(Base):
    """Alerts raised by the rules in :mod:`backend.app.services.notifications`."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sim_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    level: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(96))
    message: Mapped[str] = mapped_column(String(256))
    value: Mapped[float] = mapped_column(Float, default=0.0)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    #: Whether someone has seen it in the notification centre.
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


class Room(Base):
    """A room of the house, as configured from the admin pages."""

    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Device(Base):
    """One appliance placed in a room. See :mod:`simulator.devices`."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type_id: Mapped[str] = mapped_column(String(32), index=True)
    room_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(64))
    #: Signature variant within the type; unique per type.
    variant: Mapped[int] = mapped_column(Integer, default=0)
    #: ``None`` means the catalogue rating.
    rated_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("type_id", "variant", name="uq_device_variant"),
    )


class AdminUser(Base):
    """An account allowed to change the house, the tariff and ratings."""

    __tablename__ = "admin_users"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: ``pbkdf2_sha256$iterations$salt$hash`` -- never the password itself.
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AppSetting(Base):
    """Small persisted settings, e.g. the admin-edited tariff."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
