"""Feature extraction -- the "signal processing" half of the edge pipeline.

Turns one second of raw voltage/current samples into a compact, physically
meaningful feature vector.  This is exactly the code that would run on the
ESP32 between the ADC and the TFLite interpreter, so it is deliberately built
out of operations a microcontroller can actually afford: one real FFT, a few
dot products, and some per-cycle bookkeeping.

Three families of features are computed:

**Steady state** -- RMS current, real/reactive/apparent power, power factor.
These separate loads by *size*.

**Harmonic** -- the amplitude of each odd harmonic, both as an absolute current
and as a ratio to the fundamental.  These separate loads by *type*: they are
what tells a 95 W television apart from a 75 W fan plus a 20 W lamp.

**Transient** -- per-cycle RMS statistics and the change since the previous
window.  These capture switching events and inrush, which is how classical
event-based NILM detects that *something* just happened.

The vector deliberately contains no time-of-day information.  The classifier
is required to identify appliances from the electrical signal alone; letting it
learn "it is 8 pm, so the television is probably on" would inflate the accuracy
figures without demonstrating any actual disaggregation.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Deque, Iterable

import numpy as np
from scipy.fft import rfft, rfftfreq

from simulator.appliances import MAINS_FREQUENCY_HZ
from simulator.waveform import SAMPLE_RATE_HZ, SAMPLES_PER_WINDOW

#: Odd harmonics tracked by the feature extractor.
HARMONIC_ORDERS: tuple[int, ...] = (3, 5, 7, 9, 11, 13)

#: Samples in one mains cycle -- the unit for per-cycle transient statistics.
SAMPLES_PER_CYCLE: int = int(SAMPLE_RATE_HZ / MAINS_FREQUENCY_HZ)

#: How many consecutive one-second windows the classifier looks at.
#: Eight seconds is long enough to contain a switching transient and short
#: enough to keep the model tiny and the latency low.
SEQUENCE_LENGTH: int = 8


@dataclass
class WindowFeatures:
    """Features extracted from a single one-second acquisition window."""

    # --- steady state ------------------------------------------------- #
    i_rms: float = 0.0
    i_peak: float = 0.0
    i_mean_abs: float = 0.0
    crest_factor: float = 0.0
    form_factor: float = 0.0
    v_rms: float = 0.0
    real_power_w: float = 0.0
    apparent_power_va: float = 0.0
    reactive_power_var: float = 0.0
    power_factor: float = 0.0
    displacement_pf: float = 0.0

    # --- harmonic ------------------------------------------------------ #
    fundamental_a: float = 0.0
    thd: float = 0.0
    harmonic_ratio_3: float = 0.0
    harmonic_ratio_5: float = 0.0
    harmonic_ratio_7: float = 0.0
    harmonic_ratio_9: float = 0.0
    harmonic_ratio_11: float = 0.0
    harmonic_ratio_13: float = 0.0
    harmonic_amp_3: float = 0.0
    harmonic_amp_5: float = 0.0
    harmonic_amp_7: float = 0.0
    harmonic_amp_9: float = 0.0
    harmonic_amp_11: float = 0.0
    harmonic_amp_13: float = 0.0
    spectral_centroid_hz: float = 0.0

    # --- transient ------------------------------------------------------ #
    cycle_rms_std: float = 0.0
    cycle_rms_range: float = 0.0
    inrush_ratio: float = 0.0
    delta_power_w: float = 0.0
    delta_reactive_var: float = 0.0
    delta_i_rms: float = 0.0
    delta_thd: float = 0.0
    event_magnitude: float = 0.0

    #: Energy accumulated during this window, in watt-hours.
    energy_wh: float = 0.0

    def to_vector(self) -> np.ndarray:
        """Ordered numeric vector fed to the classifier."""
        return np.asarray(
            [getattr(self, name) for name in FEATURE_NAMES], dtype=np.float32
        )

    def to_dict(self) -> dict:
        return {k: float(v) for k, v in asdict(self).items()}


#: Field order of the model input vector.  ``energy_wh`` is bookkeeping, not a
#: discriminative feature, so it is excluded from the model input.
FEATURE_NAMES: tuple[str, ...] = tuple(
    name for name in WindowFeatures.__dataclass_fields__ if name != "energy_wh"
)
NUM_FEATURES: int = len(FEATURE_NAMES)


def _harmonic_amplitudes(
    signal: np.ndarray,
    orders: Iterable[int],
) -> tuple[np.ndarray, complex, np.ndarray, np.ndarray]:
    """Return harmonic amplitudes, the complex fundamental, and the spectrum.

    No analysis window is applied.  The acquisition window is exactly fifty
    complete mains cycles, so every harmonic of 50 Hz lands precisely on an FFT
    bin and there is no spectral leakage to suppress.  Applying a Hann window
    here would smear energy across neighbouring bins and make the harmonic
    ratios *less* accurate, not more.
    """
    n = len(signal)
    spectrum = rfft(signal)
    freqs = rfftfreq(n, 1.0 / SAMPLE_RATE_HZ)
    # Single-sided amplitude spectrum.
    amplitude = np.abs(spectrum) * 2.0 / n

    def bin_index(hz: float) -> int:
        return int(round(hz * n / SAMPLE_RATE_HZ))

    fundamental_bin = bin_index(MAINS_FREQUENCY_HZ)
    fundamental_complex = spectrum[fundamental_bin]

    amps = np.asarray(
        [amplitude[bin_index(MAINS_FREQUENCY_HZ * h)] for h in orders],
        dtype=np.float64,
    )
    return amps, fundamental_complex, amplitude, freqs


def extract_features(
    voltage: np.ndarray,
    current: np.ndarray,
    previous: WindowFeatures | None = None,
    window_seconds: float = 1.0,
) -> WindowFeatures:
    """Compute the full feature set for one acquisition window."""
    n = len(current)

    # ------------------------------------------------------------------ #
    # Steady-state / power quantities
    # ------------------------------------------------------------------ #
    i_rms = float(np.sqrt(np.mean(current**2)))
    v_rms = float(np.sqrt(np.mean(voltage**2)))
    i_peak = float(np.max(np.abs(current)))
    i_mean_abs = float(np.mean(np.abs(current)))

    real_power = float(np.mean(voltage * current))
    apparent_power = v_rms * i_rms
    # Q is defined here as the non-active power (includes distortion power),
    # which is what a real single-phase meter reports.
    reactive_power = float(
        np.sqrt(max(apparent_power**2 - real_power**2, 0.0))
    )
    power_factor = real_power / apparent_power if apparent_power > 1e-9 else 0.0

    crest_factor = i_peak / i_rms if i_rms > 1e-9 else 0.0
    form_factor = i_rms / i_mean_abs if i_mean_abs > 1e-9 else 0.0

    # ------------------------------------------------------------------ #
    # Harmonic analysis
    # ------------------------------------------------------------------ #
    amps, i_fundamental, amplitude_spectrum, freqs = _harmonic_amplitudes(
        current, HARMONIC_ORDERS
    )
    _, v_fundamental, _, _ = _harmonic_amplitudes(voltage, ())

    fundamental_a = float(np.abs(i_fundamental) * 2.0 / n / np.sqrt(2.0))
    fundamental_peak = float(np.abs(i_fundamental) * 2.0 / n)

    if fundamental_peak > 1e-9:
        ratios = amps / fundamental_peak
        thd = float(np.sqrt(np.sum(ratios**2)))
    else:
        ratios = np.zeros(len(HARMONIC_ORDERS))
        thd = 0.0

    # Displacement power factor from the phase difference of the fundamentals.
    phase_difference = float(np.angle(i_fundamental) - np.angle(v_fundamental))
    displacement_pf = float(np.cos(phase_difference))

    # Spectral centroid over the harmonic band, a compact "how distorted" scalar.
    band = (freqs >= 25.0) & (freqs <= 700.0)
    band_energy = float(np.sum(amplitude_spectrum[band]))
    spectral_centroid = (
        float(np.sum(freqs[band] * amplitude_spectrum[band]) / band_energy)
        if band_energy > 1e-12
        else 0.0
    )

    # ------------------------------------------------------------------ #
    # Transient / per-cycle statistics
    # ------------------------------------------------------------------ #
    usable = (n // SAMPLES_PER_CYCLE) * SAMPLES_PER_CYCLE
    cycles = current[:usable].reshape(-1, SAMPLES_PER_CYCLE)
    cycle_rms = np.sqrt(np.mean(cycles**2, axis=1))
    cycle_mean = float(np.mean(cycle_rms)) if len(cycle_rms) else 0.0

    if cycle_mean > 1e-9:
        cycle_rms_std = float(np.std(cycle_rms) / cycle_mean)
        cycle_rms_range = float((np.max(cycle_rms) - np.min(cycle_rms)) / cycle_mean)
        # Inrush shows up as the first cycles of the window being much larger
        # than the settled tail.
        head = float(np.max(cycle_rms[: max(1, len(cycle_rms) // 4)]))
        tail = float(np.mean(cycle_rms[-max(1, len(cycle_rms) // 4) :]))
        inrush_ratio = head / tail if tail > 1e-9 else 0.0
    else:
        cycle_rms_std = cycle_rms_range = inrush_ratio = 0.0

    # ------------------------------------------------------------------ #
    # Change since the previous window -- classical NILM event detection
    # ------------------------------------------------------------------ #
    if previous is not None:
        delta_power = real_power - previous.real_power_w
        delta_reactive = reactive_power - previous.reactive_power_var
        delta_i_rms = i_rms - previous.i_rms
        delta_thd = thd - previous.thd
    else:
        delta_power = delta_reactive = delta_i_rms = delta_thd = 0.0

    # A single scalar saying "how much did the load just change", normalised so
    # that switching a 9 W lamp still registers on a 3 kW background.
    denominator = max(abs(real_power), abs(real_power - delta_power), 50.0)
    event_magnitude = float(abs(delta_power) / denominator)

    return WindowFeatures(
        i_rms=i_rms,
        i_peak=i_peak,
        i_mean_abs=i_mean_abs,
        crest_factor=crest_factor,
        form_factor=form_factor,
        v_rms=v_rms,
        real_power_w=real_power,
        apparent_power_va=apparent_power,
        reactive_power_var=reactive_power,
        power_factor=power_factor,
        displacement_pf=displacement_pf,
        fundamental_a=fundamental_a,
        thd=thd,
        harmonic_ratio_3=float(ratios[0]),
        harmonic_ratio_5=float(ratios[1]),
        harmonic_ratio_7=float(ratios[2]),
        harmonic_ratio_9=float(ratios[3]),
        harmonic_ratio_11=float(ratios[4]),
        harmonic_ratio_13=float(ratios[5]),
        harmonic_amp_3=float(amps[0] / np.sqrt(2.0)),
        harmonic_amp_5=float(amps[1] / np.sqrt(2.0)),
        harmonic_amp_7=float(amps[2] / np.sqrt(2.0)),
        harmonic_amp_9=float(amps[3] / np.sqrt(2.0)),
        harmonic_amp_11=float(amps[4] / np.sqrt(2.0)),
        harmonic_amp_13=float(amps[5] / np.sqrt(2.0)),
        spectral_centroid_hz=spectral_centroid,
        cycle_rms_std=cycle_rms_std,
        cycle_rms_range=cycle_rms_range,
        inrush_ratio=inrush_ratio,
        delta_power_w=delta_power,
        delta_reactive_var=delta_reactive,
        delta_i_rms=delta_i_rms,
        delta_thd=delta_thd,
        event_magnitude=event_magnitude,
        energy_wh=real_power * window_seconds / 3600.0,
    )


class FeatureExtractor:
    """Stateful extractor that maintains the sliding window for the model.

    Keeps the previous window (for delta features) and the last
    :data:`SEQUENCE_LENGTH` vectors (for the classifier input tensor).
    """

    def __init__(self, sequence_length: int = SEQUENCE_LENGTH) -> None:
        self.sequence_length = sequence_length
        self._previous: WindowFeatures | None = None
        self._history: Deque[np.ndarray] = deque(maxlen=sequence_length)

    def reset(self) -> None:
        self._previous = None
        self._history.clear()

    @property
    def ready(self) -> bool:
        """True once enough windows have been seen to fill the sequence."""
        return len(self._history) == self.sequence_length

    def process(
        self,
        voltage: np.ndarray,
        current: np.ndarray,
        window_seconds: float = 1.0,
    ) -> WindowFeatures:
        """Extract features for one window and push them into the history."""
        features = extract_features(
            voltage, current, previous=self._previous, window_seconds=window_seconds
        )
        self._previous = features
        self._history.append(features.to_vector())
        return features

    def sequence(self) -> np.ndarray:
        """Model input of shape ``(sequence_length, NUM_FEATURES)``.

        Before the history has filled up, the oldest slot is repeated so that
        inference can start from the very first second instead of showing an
        empty dashboard for eight seconds.
        """
        if not self._history:
            return np.zeros((self.sequence_length, NUM_FEATURES), dtype=np.float32)
        frames = list(self._history)
        while len(frames) < self.sequence_length:
            frames.insert(0, frames[0])
        return np.stack(frames).astype(np.float32)
