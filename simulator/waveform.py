"""Mains waveform synthesis.

This is the layer that stands in for the SCT-013 current clamp and the ESP32
ADC.  Rather than inventing an RMS number directly, we synthesise the actual
50 Hz current waveform sample by sample and then *measure* it exactly the way
firmware would.  Every downstream number (RMS, real power, power factor, THD)
therefore falls out of the signal instead of being asserted.

Signal model
------------
Voltage (assumed stiff and near-sinusoidal, with a little grid distortion and
a resistive sag proportional to total load current)::

    v(t) = sqrt(2) * V_rms * [ cos(wt) + sum_h d_h * cos(h*wt + psi_h) ]

Current drawn by one appliance::

    i(t) = A * sum_h c_h * cos(h * (wt - phi))

    A = sqrt(2) * I_rms / ||c||

Summing the harmonics in phase at ``wt = phi`` reproduces the peaky,
pulse-shaped current of a capacitor-input rectifier when the ``c_h`` are large,
and degenerates to a clean lagging sinusoid when they are small.  The
normalisation by ``||c||`` guarantees that the synthesised waveform has exactly
the intended RMS value, and it can be shown that

    mean(v * i) = V_rms * I_rms * PF_displacement * PF_distortion
                = V_rms * I_rms * PF_total

so the waveform is consistent with the appliance nameplate by construction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .appliances import (
    MAINS_FREQUENCY_HZ,
    NOMINAL_VOLTAGE_V,
    ApplianceSpec,
)

# --------------------------------------------------------------------------- #
# Acquisition parameters -- these mirror what the proposed ESP32 firmware does
# --------------------------------------------------------------------------- #

#: ADC sampling rate.  2 kHz = 40 samples per mains cycle, putting Nyquist at
#: 1 kHz.  The catalogue models harmonics up to the 13th (650 Hz), so this rate
#: resolves every modelled component without aliasing while staying well within
#: what an ESP32 ADC + DMA front end can sustain.
SAMPLE_RATE_HZ: int = 2000

#: One analysis window = one second = 50 complete mains cycles.
WINDOW_SECONDS: float = 1.0
SAMPLES_PER_WINDOW: int = int(SAMPLE_RATE_HZ * WINDOW_SECONDS)

#: Equivalent Thevenin source resistance of the supply, used to model the
#: voltage sag caused by the house's own load current.
GRID_IMPEDANCE_OHM: float = 0.35

#: Background distortion already present on the incoming supply.
GRID_HARMONICS: dict[int, float] = {3: 0.012, 5: 0.018, 7: 0.008}

#: RMS noise floor of the current sensor chain (clamp + burden + ADC), in amps.
#: An SCT-013-030 into a 12-bit ADC realistically lands around here.
SENSOR_NOISE_FLOOR_A: float = 0.008

ANGULAR_FREQ: float = 2.0 * math.pi * MAINS_FREQUENCY_HZ


@dataclass(frozen=True)
class HarmonicKernel:
    """Pre-computed per-appliance waveform basis.

    Building the harmonic orders and coefficients once per appliance and
    reusing them every window keeps the hot loop to a single matrix product.
    """

    orders: np.ndarray  # shape (H,), int
    coefficients: np.ndarray  # shape (H,), float
    phase_rad: float
    norm: float

    @classmethod
    def from_spec(cls, spec: ApplianceSpec) -> "HarmonicKernel":
        orders = [1] + sorted(spec.harmonics)
        coefficients = [1.0] + [spec.harmonics[h] for h in sorted(spec.harmonics)]
        return cls(
            orders=np.asarray(orders, dtype=np.float64),
            coefficients=np.asarray(coefficients, dtype=np.float64),
            phase_rad=spec.phase_angle_rad,
            norm=spec.harmonic_norm,
        )

    def synthesise(self, t: np.ndarray, rms_current_a: float) -> np.ndarray:
        """Return the instantaneous current for a given RMS amplitude."""
        if rms_current_a <= 0.0:
            return np.zeros_like(t)
        theta = ANGULAR_FREQ * t - self.phase_rad
        # (H, 1) * (1, N) -> (H, N) -> sum over harmonics
        angles = self.orders[:, None] * theta[None, :]
        wave = self.coefficients[:, None] * np.cos(angles)
        amplitude = math.sqrt(2.0) * rms_current_a / self.norm
        return amplitude * wave.sum(axis=0)


def time_axis(start_time_s: float, n_samples: int = SAMPLES_PER_WINDOW) -> np.ndarray:
    """Absolute time axis for one acquisition window.

    Time is absolute (not reset per window) so the mains phase runs
    continuously across window boundaries, exactly as it does in reality.
    """
    return start_time_s + np.arange(n_samples, dtype=np.float64) / SAMPLE_RATE_HZ


def synthesise_voltage(
    t: np.ndarray,
    rms_voltage_v: float = NOMINAL_VOLTAGE_V,
) -> np.ndarray:
    """Instantaneous mains voltage including realistic background distortion."""
    theta = ANGULAR_FREQ * t
    wave = np.cos(theta)
    for order, amplitude in GRID_HARMONICS.items():
        # A fixed phase offset per order keeps the distortion looking organic.
        wave = wave + amplitude * np.cos(order * theta + 0.4 * order)
    return math.sqrt(2.0) * rms_voltage_v * wave


def sagged_voltage_rms(
    total_current_a: float,
    nominal_v: float = NOMINAL_VOLTAGE_V,
    drift_v: float = 0.0,
) -> float:
    """Supply voltage after the house's own load pulls it down.

    ``drift_v`` carries the slow wander of the distribution transformer tap and
    of neighbouring loads, which the caller evolves as a random walk.
    """
    return nominal_v + drift_v - GRID_IMPEDANCE_OHM * total_current_a


def inrush_gain(
    elapsed_s: float,
    spec: ApplianceSpec,
) -> float:
    """Multiplier applied to steady current during the switch-on transient.

    Decays exponentially with a time constant of ``decay_cycles`` mains cycles.
    """
    if elapsed_s < 0.0:
        return 1.0
    tau = spec.startup.decay_cycles / MAINS_FREQUENCY_HZ
    if tau <= 0.0:
        return 1.0
    excess = spec.startup.multiplier - 1.0
    if excess <= 0.0:
        return 1.0
    return 1.0 + excess * math.exp(-elapsed_s / tau)


def inrush_gain_vector(
    t: np.ndarray,
    switch_on_time_s: float,
    spec: ApplianceSpec,
) -> np.ndarray:
    """Vectorised :func:`inrush_gain` across a whole acquisition window.

    Resolving the transient *within* the window matters: a refrigerator's
    locked-rotor inrush lasts only a few hundred milliseconds, so a per-second
    scalar would smear away the single most recognisable feature it has.
    """
    excess = spec.startup.multiplier - 1.0
    if excess <= 0.0:
        return np.ones_like(t)
    tau = spec.startup.decay_cycles / MAINS_FREQUENCY_HZ
    elapsed = t - switch_on_time_s
    gain = np.ones_like(t)
    active = elapsed >= 0.0
    gain[active] = 1.0 + excess * np.exp(-elapsed[active] / tau)
    return gain


def sensor_noise(
    n_samples: int,
    rng: np.random.Generator,
    scale_a: float = SENSOR_NOISE_FLOOR_A,
) -> np.ndarray:
    """Additive white noise representing the analogue front end."""
    return rng.normal(0.0, scale_a, size=n_samples)
