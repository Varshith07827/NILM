"""Appliance-level power attribution.

Classification tells you *which* appliances are running.  It does not tell you
how much each one is drawing, and on a dashboard that is the number people
actually care about.  This module closes that gap.

The trick is to work with **complex harmonic phasors** rather than magnitudes.
Kirchhoff's current law applies per harmonic, so at every harmonic order the
individual appliance currents add as phasors::

    I_h(total) = sum_i  a_i * I_h(appliance i at rated power)

RMS magnitudes emphatically do *not* add like that -- two 1 A loads in
quadrature draw 1.41 A together, not 2 A -- which is why naive "subtract the
known loads" approaches drift.  Working in the complex plane makes the whole
problem exactly linear in the unknown scale factors ``a_i``.

With seven harmonic orders (1, 3, 5, ... 13) each contributing a real and an
imaginary equation, there are fourteen linear constraints on at most twelve
unknowns, so the system is overdetermined and can be solved robustly by
non-negative least squares.  Non-negativity matters physically: an appliance
cannot draw negative current, and without that constraint the solver happily
cancels one appliance against another to fit sensor noise.

The classifier's probabilities enter as a Tikhonov prior: appliances the model
is unsure about are penalised, so they only get assigned power if the harmonic
evidence genuinely demands it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.fft import rfft
from scipy.optimize import nnls

from simulator.appliances import (
    APPLIANCE_CATALOGUE,
    APPLIANCE_IDS,
    APPLIANCES_BY_ID,
    MAINS_FREQUENCY_HZ,
    NOMINAL_VOLTAGE_V,
)
from simulator.waveform import SAMPLE_RATE_HZ

#: Harmonic orders used to build the linear system.
DISAGGREGATION_ORDERS: tuple[int, ...] = (1, 3, 5, 7, 9, 11, 13)

#: Strength of the "trust the classifier" prior.
PRIOR_STRENGTH: float = 0.25

#: Appliances assigned less than this are folded into the unattributed bucket.
#: An absolute floor rather than a fraction of the total: a 9 W lamp is a real
#: detection whether the house is drawing 100 W or 4 kW, and a percentage
#: threshold would silently discard every small appliance the moment the air
#: conditioner starts.
MIN_REPORTED_W: float = 0.5


def _unit_phasors(spec) -> np.ndarray:
    """Complex harmonic phasors drawn by one appliance at rated power.

    Mirrors the synthesis model in :mod:`simulator.waveform`: the appliance
    current is ``A * sum_h c_h cos(h * (wt - phi))``, so harmonic ``h`` has peak
    amplitude ``A * c_h`` and phase ``-h * phi``.
    """
    amplitude = math.sqrt(2.0) * spec.rms_current_a / spec.harmonic_norm
    phase = spec.phase_angle_rad

    phasors = np.zeros(len(DISAGGREGATION_ORDERS), dtype=np.complex128)
    for index, order in enumerate(DISAGGREGATION_ORDERS):
        coefficient = 1.0 if order == 1 else spec.harmonics.get(order, 0.0)
        if coefficient == 0.0:
            continue
        phasors[index] = amplitude * coefficient * np.exp(-1j * order * phase)
    return phasors


#: Signature matrix, built once: column i is appliance i at rated power.
UNIT_PHASOR_MATRIX: np.ndarray = np.stack(
    [_unit_phasors(spec) for spec in APPLIANCE_CATALOGUE], axis=1
)

#: Real-valued stacking of the same matrix: [Re; Im], shape (2H, N).
UNIT_DESIGN_MATRIX: np.ndarray = np.concatenate(
    [UNIT_PHASOR_MATRIX.real, UNIT_PHASOR_MATRIX.imag], axis=0
)

RATED_POWER_W: np.ndarray = np.asarray(
    [spec.rated_power_w for spec in APPLIANCE_CATALOGUE], dtype=np.float64
)


@dataclass
class Attribution:
    """Result of one disaggregation step."""

    #: Estimated real power per appliance id, in watts.
    power_w: dict[str, float] = field(default_factory=dict)
    #: Estimated share of the total, 0..1.
    share: dict[str, float] = field(default_factory=dict)
    #: Power the model could not attribute to any detected appliance.
    unattributed_w: float = 0.0
    #: Total measured real power for the window.
    total_w: float = 0.0
    #: Residual of the least-squares fit, in amps.
    residual_a: float = 0.0

    @property
    def attributed_w(self) -> float:
        return sum(self.power_w.values())


def measured_phasors(current: np.ndarray) -> np.ndarray:
    """Extract the complex harmonic phasors of the aggregate current.

    Returns peak-amplitude phasors, matching the convention used for the
    appliance signature matrix.
    """
    n = len(current)
    spectrum = rfft(current)
    phasors = np.zeros(len(DISAGGREGATION_ORDERS), dtype=np.complex128)
    for index, order in enumerate(DISAGGREGATION_ORDERS):
        frequency = MAINS_FREQUENCY_HZ * order
        bin_index = int(round(frequency * n / SAMPLE_RATE_HZ))
        if bin_index < len(spectrum):
            phasors[index] = spectrum[bin_index] * 2.0 / n
    return phasors


def disaggregate(
    current: np.ndarray,
    total_power_w: float,
    voltage_rms: float,
    probabilities: dict[str, float],
    thresholds: dict[str, float] | None = None,
    prior_strength: float = PRIOR_STRENGTH,
) -> Attribution:
    """Split the measured power across the appliances the classifier detected.

    Parameters
    ----------
    current:
        Raw aggregate current samples for the window.
    total_power_w:
        Real power measured for the window; the attribution is rescaled to sum
        to this so the dashboard's pie chart always adds up to the meter.
    voltage_rms:
        Supply voltage, used to correct nameplate currents for sag.
    probabilities:
        Per-appliance detection probability from the classifier.
    thresholds:
        Per-appliance decision thresholds; appliances below their threshold are
        excluded from the candidate set entirely.
    """
    thresholds = thresholds or {}
    candidates = [
        aid
        for aid in APPLIANCE_IDS
        if probabilities.get(aid, 0.0) >= thresholds.get(aid, 0.5)
    ]

    if not candidates or total_power_w <= 1.0:
        return Attribution(
            power_w={},
            share={},
            unattributed_w=max(total_power_w, 0.0),
            total_w=max(total_power_w, 0.0),
        )

    indices = [APPLIANCE_IDS.index(aid) for aid in candidates]

    # Voltage sag scales every appliance's current down together.
    sag = voltage_rms / NOMINAL_VOLTAGE_V
    design = UNIT_DESIGN_MATRIX[:, indices] * sag
    target = measured_phasors(current)
    target_stacked = np.concatenate([target.real, target.imag])

    # Tikhonov prior, centred on the classifier's own confidence.
    #
    # Centring at zero (the obvious choice) is actively harmful here: two loads
    # with similar harmonic signatures -- an LED lamp and a tube light, say --
    # are nearly collinear columns, and a zero-centred penalty resolves that
    # ambiguity by driving the smaller one to exactly zero and letting the
    # larger one absorb its current. The appliance is then reported as detected
    # but drawing nothing, which is worse than either answer alone.
    #
    # Centring at the confidence instead encodes the right belief: "if the
    # model is 95% sure this is running, expect it near its rated draw, but let
    # the harmonic evidence override that." The penalty is weighted by each
    # appliance's own column norm so a 9 W lamp and a 1.5 kW compressor are
    # nudged with equal *relative* force rather than in raw amps.
    confidence = np.asarray(
        [probabilities.get(aid, 0.0) for aid in candidates], dtype=np.float64
    )
    column_norms = np.linalg.norm(design, axis=0)
    weights = prior_strength * np.maximum(column_norms, 1e-9)

    augmented_design = np.vstack([design, np.diag(weights)])
    augmented_target = np.concatenate([target_stacked, weights * confidence])

    solution, residual = nnls(augmented_design, augmented_target)

    # Convert scale factors into watts.
    powers = solution * RATED_POWER_W[indices] * sag

    attributed = float(powers.sum())
    if attributed <= 1e-6:
        return Attribution(
            power_w={},
            share={},
            unattributed_w=max(total_power_w, 0.0),
            total_w=max(total_power_w, 0.0),
            residual_a=float(residual),
        )

    # Rescale so the parts sum to the measured whole.  The correction is capped:
    # if the fit is wildly off, the difference is reported as unattributed
    # rather than smeared across appliances to fake a perfect balance.
    ratio = total_power_w / attributed
    clamped_ratio = float(np.clip(ratio, 0.6, 1.4))
    powers = powers * clamped_ratio
    attributed = float(powers.sum())
    unattributed = max(total_power_w - attributed, 0.0)

    power_map: dict[str, float] = {}
    for aid, watts in zip(candidates, powers):
        if watts < MIN_REPORTED_W:
            unattributed += float(watts)
            continue
        power_map[aid] = float(watts)

    total = max(total_power_w, 1e-9)
    return Attribution(
        power_w=power_map,
        share={aid: watts / total for aid, watts in power_map.items()},
        unattributed_w=float(unattributed),
        total_w=float(total_power_w),
        residual_a=float(residual),
    )


def signature_table() -> list[dict]:
    """Human-readable dump of the signature matrix, for the docs and the UI."""
    rows = []
    for index, spec in enumerate(APPLIANCE_CATALOGUE):
        phasors = UNIT_PHASOR_MATRIX[:, index]
        rows.append(
            {
                "id": spec.id,
                "name": spec.name,
                "rated_power_w": spec.rated_power_w,
                "harmonics": {
                    f"h{order}": {
                        "magnitude_a": float(abs(phasors[i]) / math.sqrt(2.0)),
                        "phase_deg": float(np.degrees(np.angle(phasors[i]))),
                    }
                    for i, order in enumerate(DISAGGREGATION_ORDERS)
                    if abs(phasors[i]) > 1e-9
                },
            }
        )
    return rows


def appliance_thresholds(thresholds: np.ndarray | None) -> dict[str, float]:
    """Map a threshold vector onto appliance ids."""
    if thresholds is None:
        return {aid: 0.5 for aid in APPLIANCE_IDS}
    return {aid: float(t) for aid, t in zip(APPLIANCE_IDS, thresholds)}


def rated_power(appliance_id: str) -> float:
    return APPLIANCES_BY_ID[appliance_id].rated_power_w
