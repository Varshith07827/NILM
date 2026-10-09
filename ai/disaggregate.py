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
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.fft import rfft
from scipy.optimize import nnls

from ai.device_tracker import SameTypeTracker
from simulator.appliances import (
    APPLIANCE_CATALOGUE,
    APPLIANCE_IDS,
    APPLIANCES_BY_ID,
    MAINS_FREQUENCY_HZ,
    NOMINAL_VOLTAGE_V,
    ApplianceSpec,
)
from simulator.waveform import SAMPLE_RATE_HZ

#: Harmonic orders used to build the linear system.
DISAGGREGATION_ORDERS: tuple[int, ...] = (1, 3, 5, 7, 9, 11, 13)

#: Strength of the "trust the classifier" prior.
PRIOR_STRENGTH: float = 0.25

#: How firmly the devices of one type are held to that type's total when the
#: total is split between them (see :meth:`DeviceDisaggregator.solve`).
SPLIT_STRENGTH: float = 1.0

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


def unit_column(spec: ApplianceSpec) -> np.ndarray:
    """One appliance at rated power as a real design-matrix column [Re; Im]."""
    phasors = _unit_phasors(spec)
    return np.concatenate([phasors.real, phasors.imag])


class DeviceDisaggregator:
    """Splits the measured power across individual devices.

    Works in two layers. A steady-state solve, one column per catalogue
    *type*, decides how much of each type is running -- the same robust fit
    the single-device house always used. Where a type has several devices in
    the house, :class:`~ai.device_tracker.SameTypeTracker` then decides which
    of them are on from their switching events, and the type's total is
    shared between those by rating.

    Stateful: it carries device on/off state from window to window, so call
    :meth:`solve` once per window, in order.
    """

    def __init__(self, specs: Sequence[ApplianceSpec]) -> None:
        self.specs = list(specs)
        self.ids = [spec.id for spec in self.specs]
        self.kinds = [spec.kind for spec in self.specs]
        rows = 2 * len(DISAGGREGATION_ORDERS)
        phasor_columns = (
            np.stack([_unit_phasors(spec) for spec in self.specs], axis=1)
            if self.specs
            else np.zeros((len(DISAGGREGATION_ORDERS), 0), dtype=np.complex128)
        )
        self.design = (
            np.concatenate([phasor_columns.real, phasor_columns.imag], axis=0)
            if self.specs
            else np.zeros((rows, 0))
        )
        self.rated_w = np.asarray(
            [spec.rated_power_w for spec in self.specs], dtype=np.float64
        )
        self.tracker = SameTypeTracker(self.ids, self.kinds, phasor_columns)

    def _which_devices(
        self,
        design: np.ndarray,
        target: np.ndarray,
        target_stacked: np.ndarray,
        indices: list[int],
        groups: list[str],
        members: list[list[int]],
        type_scale: np.ndarray,
        sag: float,
        detected_kinds: set[str],
        multi: set[str],
    ) -> np.ndarray:
        """Advance the tracker one window; the on-mask over every device.

        For types with several devices, a steady-state split -- each type held
        to its stage-1 total, shared by signature alone -- gives the tracker a
        tie-break when it has to correct its count, and the rounded stage-1
        total gives the count itself.
        """
        if not multi:
            return self.tracker.update(target, sag, detected_kinds, {}, {})

        column_norms = np.linalg.norm(design, axis=0)
        split_rows = np.zeros((len(groups), len(indices)))
        split_target = np.zeros(len(groups))
        for row, (cols, scale) in enumerate(zip(members, type_scale, strict=True)):
            weight = SPLIT_STRENGTH * max(float(column_norms[cols].mean()), 1e-9)
            split_rows[row, cols] = weight
            split_target[row] = weight * scale
        split, _ = nnls(
            np.vstack([design, split_rows]),
            np.concatenate([target_stacked, split_target]),
        )
        hint = {indices[col]: float(value) for col, value in enumerate(split)}
        expected = {
            kind: int(round(float(scale)))
            for kind, scale in zip(groups, type_scale, strict=True)
            if kind in multi
        }
        return self.tracker.update(target, sag, detected_kinds, expected, hint)

    def solve(
        self,
        current: np.ndarray,
        total_power_w: float,
        voltage_rms: float,
        probabilities: dict[str, float],
        thresholds: dict[str, float] | None = None,
        prior_strength: float = PRIOR_STRENGTH,
    ) -> Attribution:
        """Split the measured power across the devices of the detected types.

        Parameters
        ----------
        current:
            Raw aggregate current samples for the window.
        total_power_w:
            Real power measured for the window; the attribution is rescaled to
            sum to this so the dashboard's pie chart always adds up to the meter.
        voltage_rms:
            Supply voltage, used to correct nameplate currents for sag.
        probabilities:
            Per-type detection probability from the classifier.
        thresholds:
            Per-type decision thresholds; devices whose type is below its
            threshold are excluded from the candidate set entirely.
        """
        thresholds = thresholds or {}
        detected_kinds = {
            kind
            for kind in set(self.kinds)
            if probabilities.get(kind, 0.0) >= thresholds.get(kind, 0.5)
        }
        indices = [i for i, kind in enumerate(self.kinds) if kind in detected_kinds]

        # Voltage sag scales every appliance's current down together.
        sag = voltage_rms / NOMINAL_VOLTAGE_V
        target = measured_phasors(current)

        if not indices or total_power_w <= 1.0:
            # The tracker still sees every window, or it would miss switches.
            self.tracker.update(target, sag, set(), {}, {})
            return Attribution(
                power_w={},
                share={},
                unattributed_w=max(total_power_w, 0.0),
                total_w=max(total_power_w, 0.0),
            )

        design = self.design[:, indices] * sag
        target_stacked = np.concatenate([target.real, target.imag])

        # Stage 1 -- how much of each type -- with one column per type, the
        # mean signature of its devices, and a Tikhonov prior centred on the
        # classifier's own confidence.
        #
        # Centring at zero (the obvious choice) is actively harmful here: two
        # loads with similar harmonic signatures -- an LED lamp and a tube
        # light, say -- are nearly collinear columns, and a zero-centred
        # penalty resolves that ambiguity by driving the smaller one to exactly
        # zero and letting the larger one absorb its current. The appliance is
        # then reported as detected but drawing nothing, which is worse than
        # either answer alone.
        #
        # Centring at the confidence instead encodes the right belief: "if the
        # model is 95% sure this is running, expect it near its rated draw, but
        # let the harmonic evidence override that." The penalty is weighted by
        # each column's norm so a 9 W lamp and a 1.5 kW compressor are nudged
        # with equal *relative* force rather than in raw amps.
        #
        # (No nnls call here sees zero columns -- the early return guards it.
        # SciPy 1.16's nnls corrupts the heap on an (m, 0) matrix.)
        kinds = [self.kinds[index] for index in indices]
        groups = list(dict.fromkeys(kinds))
        members = [[col for col, k in enumerate(kinds) if k == kind] for kind in groups]

        type_design = np.stack([design[:, cols].mean(axis=1) for cols in members], axis=1)
        type_weights = prior_strength * np.maximum(np.linalg.norm(type_design, axis=0), 1e-9)
        confidence = np.asarray([probabilities.get(k, 0.0) for k in groups], dtype=np.float64)
        type_scale, residual = nnls(
            np.vstack([type_design, np.diag(type_weights)]),
            np.concatenate([target_stacked, type_weights * confidence]),
        )

        solution = np.zeros(len(indices))
        multi = {kind for kind, cols in zip(groups, members, strict=True) if len(cols) > 1}
        on = self._which_devices(
            design, target, target_stacked, indices, groups, members, type_scale,
            sag, detected_kinds, multi,
        )
        for kind, cols, scale in zip(groups, members, type_scale, strict=True):
            if kind not in multi:
                solution[cols[0]] = scale
                continue
            # ``scale`` counts "average devices" of this type; share that
            # current between the devices that are on, by rating.
            rated = self.rated_w[[indices[c] for c in cols]]
            running = [c for c in cols if on[indices[c]]]
            if not running:
                continue
            total_w = scale * float(rated.mean())
            running_rated = float(self.rated_w[[indices[c] for c in running]].sum())
            for col in running:
                solution[col] = total_w / running_rated

        # Convert scale factors into watts.
        powers = solution * self.rated_w[indices] * sag

        attributed = float(powers.sum())
        if attributed <= 1e-6:
            return Attribution(
                power_w={},
                share={},
                unattributed_w=max(total_power_w, 0.0),
                total_w=max(total_power_w, 0.0),
                residual_a=float(residual),
            )

        # Rescale so the parts sum to the measured whole.  The correction is
        # capped: if the fit is wildly off, the difference is reported as
        # unattributed rather than smeared across appliances to fake a perfect
        # balance.
        ratio = total_power_w / attributed
        clamped_ratio = float(np.clip(ratio, 0.6, 1.4))
        powers = powers * clamped_ratio
        attributed = float(powers.sum())
        unattributed = max(total_power_w - attributed, 0.0)

        power_map: dict[str, float] = {}
        for index, watts in zip(indices, powers, strict=True):
            if watts < MIN_REPORTED_W:
                unattributed += float(watts)
                continue
            power_map[self.ids[index]] = float(watts)

        total = max(total_power_w, 1e-9)
        return Attribution(
            power_w=power_map,
            share={aid: watts / total for aid, watts in power_map.items()},
            unattributed_w=float(unattributed),
            total_w=float(total_power_w),
            residual_a=float(residual),
        )


#: The catalogue house: one device per type, ids equal to the type ids.
CATALOGUE_DISAGGREGATOR = DeviceDisaggregator(APPLIANCE_CATALOGUE)


def disaggregate(
    current: np.ndarray,
    total_power_w: float,
    voltage_rms: float,
    probabilities: dict[str, float],
    thresholds: dict[str, float] | None = None,
    prior_strength: float = PRIOR_STRENGTH,
) -> Attribution:
    """Split the measured power across the catalogue appliances detected.

    The single-device-per-type case of :class:`DeviceDisaggregator`.
    """
    return CATALOGUE_DISAGGREGATOR.solve(
        current,
        total_power_w=total_power_w,
        voltage_rms=voltage_rms,
        probabilities=probabilities,
        thresholds=thresholds,
        prior_strength=prior_strength,
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
