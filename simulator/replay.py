"""Recording and replay of simulation runs (Replay Mode).

A recording stores the *appliance amplitude track* -- for every simulated
second, how much of its rated power each appliance was drawing -- rather than
the raw waveform.

That choice matters.  Storing 2000 float samples per second would be about
16 KB/s; storing twelve floats is about 100 bytes/s, a 150x saving.  More
importantly, replaying the amplitude track through the *same* synthesis code
regenerates the waveform exactly, which means a replayed demo exercises the
full pipeline -- waveform synthesis, feature extraction, inference,
disaggregation -- rather than replaying a cached answer.  If the model is
retrained, the same recording will show the new model's behaviour on identical
input.

Format is JSON Lines: one header object, then one frame object per second.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from simulator.appliances import APPLIANCE_IDS

RECORDING_VERSION = 1
RECORDING_SUFFIX = ".nilm.jsonl"


@dataclass
class RecordingHeader:
    """Metadata describing how a recording was produced."""

    version: int
    name: str
    scenario_id: str
    mode: str
    seed: int
    created_at: str
    appliance_ids: list[str]
    frame_count: int = 0
    duration_s: float = 0.0
    start_sim_time: str = ""

    def to_dict(self) -> dict:
        return {"type": "header", **self.__dict__}

    @classmethod
    def from_dict(cls, data: dict) -> "RecordingHeader":
        payload = {k: v for k, v in data.items() if k != "type"}
        return cls(**payload)


@dataclass
class RecordingFrame:
    """One simulated second."""

    sim_time: str
    scales: dict[str, float]

    def to_dict(self) -> dict:
        # Rounded to four decimals: below that the difference is far under the
        # sensor noise floor and only inflates the file.
        return {
            "t": self.sim_time,
            "s": [round(self.scales.get(aid, 0.0), 4) for aid in APPLIANCE_IDS],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RecordingFrame":
        return cls(
            sim_time=data["t"],
            scales={aid: float(v) for aid, v in zip(APPLIANCE_IDS, data["s"])},
        )


class Recorder:
    """Writes a recording to disk as the simulation runs."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._handle = None
        self._header: RecordingHeader | None = None
        self._path: Path | None = None
        self._frames = 0

    @property
    def is_recording(self) -> bool:
        return self._handle is not None

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def frame_count(self) -> int:
        return self._frames

    def start(
        self,
        name: str,
        scenario_id: str,
        mode: str,
        seed: int,
        start_sim_time: datetime,
    ) -> Path:
        """Begin a new recording, returning the file it will be written to."""
        self.stop()
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_")
        safe = safe or "recording"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._path = self.directory / f"{safe}-{stamp}{RECORDING_SUFFIX}"

        self._header = RecordingHeader(
            version=RECORDING_VERSION,
            name=name,
            scenario_id=scenario_id,
            mode=mode,
            seed=seed,
            created_at=datetime.now().isoformat(timespec="seconds"),
            appliance_ids=list(APPLIANCE_IDS),
            start_sim_time=start_sim_time.isoformat(),
        )
        self._handle = self._path.open("w", encoding="utf-8")
        self._handle.write(json.dumps(self._header.to_dict()) + "\n")
        self._frames = 0
        return self._path

    def append(self, sim_time: datetime, scales: dict[str, float]) -> None:
        if self._handle is None:
            return
        frame = RecordingFrame(sim_time=sim_time.isoformat(), scales=scales)
        self._handle.write(json.dumps(frame.to_dict()) + "\n")
        self._frames += 1

    def stop(self) -> Path | None:
        """Close the file and stamp the final frame count into the header."""
        if self._handle is None:
            return None
        self._handle.close()
        self._handle = None

        path, header = self._path, self._header
        if path is not None and header is not None and path.exists():
            header.frame_count = self._frames
            header.duration_s = float(self._frames)
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[0] = json.dumps(header.to_dict())
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._path = None
        self._header = None
        return path


@dataclass
class Recording:
    """A loaded recording, ready to play back."""

    header: RecordingHeader
    frames: list[RecordingFrame] = field(default_factory=list)
    path: Path | None = None

    def __len__(self) -> int:
        return len(self.frames)

    @classmethod
    def load(cls, path: Path | str) -> "Recording":
        path = Path(path)
        header: RecordingHeader | None = None
        frames: list[RecordingFrame] = []

        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if payload.get("type") == "header":
                    header = RecordingHeader.from_dict(payload)
                else:
                    frames.append(RecordingFrame.from_dict(payload))

        if header is None:
            raise ValueError(f"{path} has no header line -- not a valid recording")
        header.frame_count = len(frames)
        header.duration_s = float(len(frames))
        return cls(header=header, frames=frames, path=path)

    def to_summary(self) -> dict:
        return {
            "name": self.header.name,
            "file": self.path.name if self.path else "",
            "scenario_id": self.header.scenario_id,
            "mode": self.header.mode,
            "seed": self.header.seed,
            "created_at": self.header.created_at,
            "frame_count": self.header.frame_count,
            "duration_s": self.header.duration_s,
            "start_sim_time": self.header.start_sim_time,
        }


class RecordingPlayer:
    """Cursor over a recording, with optional looping."""

    def __init__(self, recording: Recording, loop: bool = True) -> None:
        self.recording = recording
        self.loop = loop
        self.cursor = 0

    @property
    def finished(self) -> bool:
        return not self.loop and self.cursor >= len(self.recording)

    @property
    def progress(self) -> float:
        if not len(self.recording):
            return 1.0
        return min(1.0, self.cursor / len(self.recording))

    def reset(self) -> None:
        self.cursor = 0

    def next_frame(self) -> RecordingFrame | None:
        """Return the next frame, wrapping around if looping."""
        if not self.recording.frames:
            return None
        if self.cursor >= len(self.recording.frames):
            if not self.loop:
                return None
            self.cursor = 0
        frame = self.recording.frames[self.cursor]
        self.cursor += 1
        return frame

    def __iter__(self) -> Iterator[RecordingFrame]:
        while True:
            frame = self.next_frame()
            if frame is None:
                return
            yield frame


def list_recordings(directory: Path | str) -> list[dict]:
    """Summarise every recording in a directory, newest first."""
    directory = Path(directory)
    if not directory.exists():
        return []
    summaries = []
    for path in sorted(directory.glob(f"*{RECORDING_SUFFIX}")):
        try:
            summaries.append(Recording.load(path).to_summary())
        except (ValueError, json.JSONDecodeError, OSError):
            # A half-written recording from an interrupted run should not stop
            # the rest of the list from being usable.
            continue
    summaries.sort(key=lambda item: item["created_at"], reverse=True)
    return summaries
