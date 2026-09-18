"""Electricity tariff modelling (Module 7).

Indian domestic tariffs are *telescopic* slab tariffs: the slabs apply
progressively, like income tax brackets, not as a single rate chosen by total
consumption.  A household that uses 250 units does not pay the 201-500 rate on
all 250 units; it pays the first slab's rate on the first band, the second
slab's rate on the next, and so on.

That has a consequence the dashboard has to respect: **the cost of one extra
unit depends on how much has already been consumed this month.**  So the cost
attributed to each second of energy uses the *marginal* rate at the current
running monthly total, and the monthly bill is recomputed telescopically.  A
naive ``kWh * flat_rate`` would disagree with the real bill by a wide margin in
exactly the months a consumer cares about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import inf


@dataclass(frozen=True)
class TariffSlab:
    """One band of a telescopic tariff.

    ``up_to_kwh`` is the *upper* boundary of the band; ``None`` means the band
    runs to infinity.
    """

    up_to_kwh: float | None
    rate_inr: float

    @property
    def upper(self) -> float:
        return inf if self.up_to_kwh is None else float(self.up_to_kwh)


@dataclass(frozen=True)
class Tariff:
    """A named tariff: a fixed monthly charge plus telescopic energy slabs."""

    id: str
    name: str
    description: str
    slabs: tuple[TariffSlab, ...]
    fixed_charge_inr: float = 0.0
    currency: str = "INR"
    currency_symbol: str = "₹"

    # ------------------------------------------------------------------ #

    def energy_charge(self, monthly_kwh: float) -> float:
        """Telescopic energy charge for a whole month's consumption."""
        if monthly_kwh <= 0.0:
            return 0.0
        total = 0.0
        lower = 0.0
        for slab in self.slabs:
            if monthly_kwh <= lower:
                break
            band = min(monthly_kwh, slab.upper) - lower
            if band > 0.0:
                total += band * slab.rate_inr
            lower = slab.upper
            if lower == inf:
                break
        return total

    def monthly_bill(self, monthly_kwh: float) -> float:
        """Full bill including the fixed charge."""
        return self.fixed_charge_inr + self.energy_charge(monthly_kwh)

    def marginal_rate(self, monthly_kwh: float) -> float:
        """Rate that applies to the *next* unit at this consumption level."""
        lower = 0.0
        for slab in self.slabs:
            if monthly_kwh < slab.upper:
                return slab.rate_inr
            lower = slab.upper
        return self.slabs[-1].rate_inr if self.slabs else 0.0

    def cost_of(self, kwh: float, monthly_kwh_so_far: float) -> float:
        """Cost of ``kwh`` consumed on top of ``monthly_kwh_so_far``.

        Computed as the difference of two telescopic bills, so an increment
        that straddles a slab boundary is priced correctly rather than being
        charged entirely at one rate.
        """
        if kwh <= 0.0:
            return 0.0
        return self.energy_charge(monthly_kwh_so_far + kwh) - self.energy_charge(
            monthly_kwh_so_far
        )

    #: Below this monthly consumption the fixed charge dominates and the
    #: "average rate per unit" becomes an absurd number (a 50 rupee standing
    #: charge over 0.001 units is 50,000 rupees a unit). Report the marginal
    #: rate instead until enough has been consumed for the average to mean
    #: something.
    EFFECTIVE_RATE_MIN_KWH: float = 1.0

    def effective_rate(self, monthly_kwh: float) -> float:
        """Average rupees per unit actually paid at this consumption."""
        if monthly_kwh < self.EFFECTIVE_RATE_MIN_KWH:
            return self.marginal_rate(monthly_kwh)
        return self.monthly_bill(monthly_kwh) / monthly_kwh

    def slab_breakdown(self, monthly_kwh: float) -> list[dict]:
        """Per-band consumption and charge, for the bill explainer in the UI."""
        rows: list[dict] = []
        lower = 0.0
        for slab in self.slabs:
            band_units = max(0.0, min(monthly_kwh, slab.upper) - lower)
            rows.append(
                {
                    "from_kwh": lower,
                    "to_kwh": None if slab.upper == inf else slab.upper,
                    "rate_inr": slab.rate_inr,
                    "units": band_units,
                    "charge_inr": band_units * slab.rate_inr,
                    "active": lower <= monthly_kwh < slab.upper,
                }
            )
            lower = slab.upper
            if lower == inf:
                break
        return rows

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "fixed_charge_inr": self.fixed_charge_inr,
            "currency": self.currency,
            "currency_symbol": self.currency_symbol,
            "slabs": [
                {"up_to_kwh": slab.up_to_kwh, "rate_inr": slab.rate_inr}
                for slab in self.slabs
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Tariff":
        return cls(
            id=str(data.get("id", "custom")),
            name=str(data.get("name", "Custom Tariff")),
            description=str(data.get("description", "User-defined tariff")),
            slabs=tuple(
                TariffSlab(
                    up_to_kwh=slab.get("up_to_kwh"),
                    rate_inr=float(slab["rate_inr"]),
                )
                for slab in data["slabs"]
            ),
            fixed_charge_inr=float(data.get("fixed_charge_inr", 0.0)),
            currency=str(data.get("currency", "INR")),
            currency_symbol=str(data.get("currency_symbol", "₹")),
        )


# --------------------------------------------------------------------------- #
# Built-in presets
# --------------------------------------------------------------------------- #

TARIFF_PRESETS: tuple[Tariff, ...] = (
    Tariff(
        id="domestic_slab",
        name="Domestic Slab (unsubsidised)",
        description=(
            "A representative unsubsidised domestic slab tariff. Every unit is "
            "chargeable, so the running cost is visible from the first second."
        ),
        slabs=(
            TariffSlab(100, 4.50),
            TariffSlab(200, 6.00),
            TariffSlab(500, 7.50),
            TariffSlab(None, 9.00),
        ),
        fixed_charge_inr=50.0,
    ),
    Tariff(
        id="tneb_domestic",
        name="TNEB Domestic (subsidised)",
        description=(
            "Illustrative Tamil Nadu domestic structure with the first 100 "
            "units free. Shows how a subsidy flattens the early bill."
        ),
        slabs=(
            TariffSlab(100, 0.00),
            TariffSlab(200, 2.35),
            TariffSlab(400, 4.70),
            TariffSlab(500, 6.30),
            TariffSlab(600, 8.40),
            TariffSlab(800, 9.45),
            TariffSlab(1000, 10.50),
            TariffSlab(None, 11.55),
        ),
        fixed_charge_inr=40.0,
    ),
    Tariff(
        id="flat_rate",
        name="Flat Rate",
        description="A single rate for every unit, for easy mental arithmetic.",
        slabs=(TariffSlab(None, 7.50),),
        fixed_charge_inr=0.0,
    ),
    Tariff(
        id="time_of_day",
        name="Commercial Flat (high tariff)",
        description=(
            "A higher flat commercial rate, useful for showing how sensitive "
            "the monthly bill is to the tariff rather than to consumption."
        ),
        slabs=(TariffSlab(None, 11.00),),
        fixed_charge_inr=150.0,
    ),
)

TARIFF_PRESETS_BY_ID: dict[str, Tariff] = {t.id: t for t in TARIFF_PRESETS}


def get_tariff(tariff_id: str) -> Tariff:
    try:
        return TARIFF_PRESETS_BY_ID[tariff_id]
    except KeyError:
        raise KeyError(
            f"Unknown tariff {tariff_id!r}. "
            f"Available: {', '.join(TARIFF_PRESETS_BY_ID)}"
        ) from None


@dataclass
class CostBreakdown:
    """Cost figures shown on the dashboard."""

    today_inr: float = 0.0
    month_inr: float = 0.0
    session_inr: float = 0.0
    projected_month_inr: float = 0.0
    monthly_bill_inr: float = 0.0
    marginal_rate_inr: float = 0.0
    effective_rate_inr: float = 0.0
    per_appliance_inr: dict[str, float] = field(default_factory=dict)
    slab_breakdown: list[dict] = field(default_factory=list)
    tariff_name: str = ""
    currency_symbol: str = "₹"
