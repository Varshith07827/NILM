"""Training data generation.

The classifier is trained on data produced by the same simulator that feeds the
live dashboard, which is the honest arrangement for a synthetic project: the
model never sees the per-appliance breakdown at inference time, only the
aggregate waveform, exactly as a real meter would.

Two kinds of episode are mixed:

* **Random-combination episodes** (majority) switch appliances on and off with
  no regard for plausibility.  These exist purely for coverage -- without them
  the model would never see a microwave and a washing machine running together
  and would quietly learn the household's habits instead of its electrical
  signatures.
* **Scenario episodes** replay the real behavioural profiles, so the model also
  sees the correlated, realistic combinations it will meet in the demo.

Labels are multi-label: for each of the twelve appliances, whether it is
*actually drawing power* in the final second of the sequence.  Note the
distinction from "switched on at the socket" -- a refrigerator between
compressor cycles is switched on but is not drawing, and the model is expected
to say so.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from ai.features import NUM_FEATURES, SEQUENCE_LENGTH, FeatureExtractor
from simulator.appliances import APPLIANCE_IDS, NUM_APPLIANCES
from simulator.house import VirtualHouse
from simulator.scenarios import SCENARIOS, SimulationMode


@dataclass
class DatasetConfig:
    """Knobs for dataset generation."""

    total_windows: int = 60_000
    episode_length_s: int = 400
    seed: int = 20240501
    #: Fraction of episodes that use unconstrained random appliance combinations.
    random_episode_fraction: float = 0.65
    #: Per-second probability of toggling an appliance in a random episode.
    toggle_probability: float = 0.035
    #: Fraction of the generated data held out for validation.
    validation_split: float = 0.2


@dataclass
class Dataset:
    """Feature stream plus labels, before sequence assembly."""

    #: (N, NUM_FEATURES) raw per-window features.
    features: np.ndarray
    #: (N, NUM_APPLIANCES) multi-label targets.
    labels: np.ndarray
    #: (N, NUM_APPLIANCES) true per-appliance power, kept for evaluation.
    powers: np.ndarray
    #: (N,) episode index, so sequences never straddle an episode boundary.
    episodes: np.ndarray

    def __len__(self) -> int:
        return len(self.features)


def _run_episode(
    house: VirtualHouse,
    rng: np.random.Generator,
    length_s: int,
    randomise: bool,
    toggle_probability: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Simulate one episode and return (features, labels, powers)."""
    extractor = FeatureExtractor()
    features = np.empty((length_s, NUM_FEATURES), dtype=np.float32)
    labels = np.zeros((length_s, NUM_APPLIANCES), dtype=np.float32)
    powers = np.zeros((length_s, NUM_APPLIANCES), dtype=np.float32)

    if randomise:
        # Start from a random subset so the episode does not always begin empty.
        for aid in APPLIANCE_IDS:
            if rng.random() < 0.35:
                house.set_appliance(aid, True)
                house.states[aid].switched_on_at = -float(rng.uniform(20.0, 600.0))

    for step in range(length_s):
        if randomise and rng.random() < toggle_probability * NUM_APPLIANCES:
            aid = str(rng.choice(APPLIANCE_IDS))
            house.set_appliance(aid, not house.states[aid].socket_on)

        window = house.step(1.0)
        window_features = extractor.process(window.voltage, window.current)
        features[step] = window_features.to_vector()
        truth = window.ground_truth
        for idx, aid in enumerate(APPLIANCE_IDS):
            labels[step, idx] = 1.0 if truth.drawing[aid] else 0.0
            powers[step, idx] = truth.power_w[aid]

    return features, labels, powers


def generate_dataset(config: DatasetConfig | None = None, verbose: bool = True) -> Dataset:
    """Generate the full feature stream."""
    config = config or DatasetConfig()
    rng = np.random.default_rng(config.seed)

    n_episodes = max(1, config.total_windows // config.episode_length_s)
    scenario_pool = [s for s in SCENARIOS if s.id not in {"custom", "vacation"}]

    all_features: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []
    all_powers: list[np.ndarray] = []
    all_episodes: list[np.ndarray] = []

    started = time.perf_counter()
    for episode in range(n_episodes):
        randomise = rng.random() < config.random_episode_fraction
        if randomise:
            scenario_id, mode = "custom", SimulationMode.DEMO
        else:
            scenario_id = str(rng.choice([s.id for s in scenario_pool]))
            mode = SimulationMode.SIMULATION

        house = VirtualHouse(
            scenario_id=scenario_id,
            mode=mode,
            seed=int(rng.integers(0, 2**31 - 1)),
        )
        features, labels, powers = _run_episode(
            house,
            rng,
            config.episode_length_s,
            randomise,
            config.toggle_probability,
        )
        all_features.append(features)
        all_labels.append(labels)
        all_powers.append(powers)
        all_episodes.append(np.full(len(features), episode, dtype=np.int32))

        if verbose and (episode + 1) % 10 == 0:
            done = (episode + 1) * config.episode_length_s
            rate = done / (time.perf_counter() - started)
            remaining = (n_episodes * config.episode_length_s - done) / rate
            print(
                f"  episode {episode + 1}/{n_episodes}  "
                f"{done:,} windows  {rate:,.0f} win/s  eta {remaining:.0f}s",
                flush=True,
            )

    dataset = Dataset(
        features=np.concatenate(all_features),
        labels=np.concatenate(all_labels),
        powers=np.concatenate(all_powers),
        episodes=np.concatenate(all_episodes),
    )
    if verbose:
        elapsed = time.perf_counter() - started
        print(
            f"  generated {len(dataset):,} windows in {elapsed:.1f}s "
            f"({len(dataset) / elapsed:,.0f} windows/s)"
        )
    return dataset


def build_sequences(
    dataset: Dataset,
    sequence_length: int = SEQUENCE_LENGTH,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Assemble sliding-window sequences without crossing episode boundaries.

    The leading edge of each episode is padded by repeating its first frame,
    which is exactly what :meth:`ai.features.FeatureExtractor.sequence` does
    while its history is still filling up.  Training on the same padding the
    runtime produces means the very first seconds after a restart are not a
    distribution shift for the model.
    """
    sequences: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    powers: list[np.ndarray] = []

    for episode in np.unique(dataset.episodes):
        mask = dataset.episodes == episode
        features = dataset.features[mask]
        episode_labels = dataset.labels[mask]
        episode_powers = dataset.powers[mask]

        padding = np.repeat(features[:1], sequence_length - 1, axis=0)
        padded = np.concatenate([padding, features])
        windows = np.lib.stride_tricks.sliding_window_view(
            padded, sequence_length, axis=0
        )
        # sliding_window_view yields (N, NUM_FEATURES, sequence_length)
        sequences.append(np.ascontiguousarray(windows.transpose(0, 2, 1)))
        labels.append(episode_labels)
        powers.append(episode_powers)

    x = np.concatenate(sequences).astype(np.float32)
    y = np.concatenate(labels).astype(np.float32)
    p = np.concatenate(powers).astype(np.float32)
    return x, y, p


def split_by_episode(
    dataset: Dataset, validation_split: float, seed: int = 0
) -> tuple[Dataset, Dataset]:
    """Split train/validation by *episode*, never by window.

    Splitting randomly across windows would put near-identical neighbouring
    seconds on both sides of the split and produce a meaninglessly optimistic
    validation score.
    """
    rng = np.random.default_rng(seed)
    episodes = np.unique(dataset.episodes)
    rng.shuffle(episodes)
    n_validation = max(1, int(len(episodes) * validation_split))
    validation_episodes = set(episodes[:n_validation].tolist())

    is_validation = np.isin(dataset.episodes, list(validation_episodes))

    def subset(mask: np.ndarray) -> Dataset:
        return Dataset(
            features=dataset.features[mask],
            labels=dataset.labels[mask],
            powers=dataset.powers[mask],
            episodes=dataset.episodes[mask],
        )

    return subset(~is_validation), subset(is_validation)


def normalisation_stats(features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-feature mean and standard deviation used to standardise inputs.

    Computed on the training split only and then frozen into the exported
    artefact, so the edge runtime standardises inputs identically.
    """
    mean = features.mean(axis=0).astype(np.float32)
    std = features.std(axis=0).astype(np.float32)
    # Guard against constant features producing division by zero.
    std[std < 1e-6] = 1.0
    return mean, std
