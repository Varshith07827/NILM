"""Which of several same-type devices is running: switching-event tracking.

Steady-state disaggregation (:mod:`ai.disaggregate`) is good at "how much fan
is running" and poor at "which fans". Five ceiling fans are a few hundred
milliamps each, a few degrees apart in phase; a 1.2 kW microwave beside them
wanders by more current than a whole fan from one second to the next. In any
single window the fans' differences drown.

At a *switch*, though, everything that kept running cancels. The change in
the current phasors between the window before a switch and the window after
it is the signature of the one device that switched, on its own -- the
classic event-based NILM idea (Hart, 1992). Matching that step against every
device's signature says which fan it was, even with the microwave on.

So this module keeps an on/off state for every device whose type has more
than one device in the house:

1. **Events.** When the measured phasors jump, the step across the jump is
   matched against every device's signature (all types, so the microwave's
   own cycling is attributed to the microwave and ignored). If the best match
   is a tracked device in a consistent state -- an "on" step for a device
   that is off -- that device flips.
2. **Reconciliation.** Events can be missed (two switches in one window) or
   misread. Each window the tracked on-count of a type is compared with the
   count implied by that type's total from the steady-state solve; a
   persistent disagreement is corrected, using the steady-state split to pick
   which devices to switch.

The steady-state split is only a tie-break, never a reason to swap devices
whose count is already right: it is not merely noisy but *biased* (a false
detection of another type pulls on the same devices every window), and
measured on the evaluation scenarios, trusting a running average of it cut
the right-fan rate at night from 79% to 57%.

The type total still comes from the steady-state solve; this module only
decides how it is shared.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

#: A step smaller than this fraction of the smallest tracked device's
#: fundamental current is noise, not a switch.
EVENT_FRACTION: float = 0.5

#: Best match must explain the step to within this relative residual.
MATCH_RESIDUAL: float = 0.35

#: Accepted step amplitude, as a multiple of the device's own signature.
MATCH_SCALE: tuple[float, float] = (0.55, 1.6)

#: Windows the on-count may disagree with the type total before it is fixed.
RECONCILE_WINDOWS: int = 20

#: Windows to wait before the first decision, so it is not made from a window
#: still full of start-up inrush.
SETTLE_WINDOWS: int = 3


class SameTypeTracker:
    """On/off state of devices that share a type with another device."""

    def __init__(
        self,
        ids: Sequence[str],
        kinds: Sequence[str],
        columns: np.ndarray,
    ) -> None:
        """``columns``: complex unit phasors, shape (orders, devices)."""
        self.ids = list(ids)
        self.kinds = list(kinds)
        self.columns = columns
        counts: dict[str, int] = {}
        for kind in self.kinds:
            counts[kind] = counts.get(kind, 0) + 1
        self.tracked = [i for i, kind in enumerate(self.kinds) if counts[kind] > 1]
        self.multi_kinds = sorted({self.kinds[i] for i in self.tracked})
        self.on = np.zeros(len(self.ids), dtype=bool)
        self._norms = np.linalg.norm(columns, axis=0)
        tracked_fundamentals = [abs(columns[0, i]) for i in self.tracked]
        self._event_floor = (
            EVENT_FRACTION * min(tracked_fundamentals) if tracked_fundamentals else np.inf
        )
        self._previous: np.ndarray | None = None
        self._before: np.ndarray | None = None
        self._disagree: dict[str, int] = {}
        self._windows = 0

    @property
    def active(self) -> bool:
        return bool(self.tracked)

    # ------------------------------------------------------------------ #

    def _match(self, step: np.ndarray, sag: float) -> tuple[int, float] | None:
        """The device whose signature best explains ``step``, and its sign."""
        norm = float(np.linalg.norm(step))
        if norm <= 1e-9:
            return None
        best: tuple[float, int, float] | None = None
        for index in range(len(self.ids)):
            column = self.columns[:, index] * sag
            denom = float(np.vdot(column, column).real)
            if denom <= 0.0:
                continue
            scale = float(np.vdot(column, step).real / denom)
            if not MATCH_SCALE[0] <= abs(scale) <= MATCH_SCALE[1]:
                continue
            residual = float(np.linalg.norm(step - scale * column)) / norm
            if best is None or residual < best[0]:
                best = (residual, index, scale)
        if best is None or best[0] > MATCH_RESIDUAL:
            return None
        return best[1], best[2]

    def _apply_events(self, phasors: np.ndarray, sag: float) -> None:
        previous, self._previous = self._previous, phasors
        if previous is None:
            return
        if self._before is not None:
            # The window after a jump: the switch is complete, compare across it.
            match = self._match(phasors - self._before, sag)
            self._before = None
            if match is not None:
                index, scale = match
                if index in self.tracked:
                    self.on[index] = scale > 0
            return
        if np.linalg.norm(phasors - previous) >= self._event_floor:
            self._before = previous

    def _reconcile(
        self,
        kind: str,
        detected: bool,
        expected_on: int,
        split_hint: dict[int, float],
    ) -> None:
        members = [i for i in self.tracked if self.kinds[i] == kind]
        if not detected:
            self.on[members] = False
            self._disagree[kind] = 0
            return
        expected_on = max(1, min(expected_on, len(members)))
        current_on = int(self.on[members].sum())
        if current_on == expected_on:
            self._disagree[kind] = 0
            return
        self._disagree[kind] = self._disagree.get(kind, 0) + 1
        first_decision = self._windows == SETTLE_WINDOWS
        if not first_decision and self._disagree[kind] < RECONCILE_WINDOWS:
            return
        # Keep the devices the steady-state split favours most.
        ranked = sorted(members, key=lambda i: split_hint.get(i, 0.0), reverse=True)
        if current_on < expected_on:
            for index in ranked:
                if current_on == expected_on:
                    break
                if not self.on[index]:
                    self.on[index] = True
                    current_on += 1
        else:
            for index in reversed(ranked):
                if current_on == expected_on:
                    break
                if self.on[index]:
                    self.on[index] = False
                    current_on -= 1
        self._disagree[kind] = 0

    # ------------------------------------------------------------------ #

    def update(
        self,
        phasors: np.ndarray,
        sag: float,
        detected_kinds: set[str],
        expected_on: dict[str, int],
        split_hint: dict[int, float],
    ) -> np.ndarray:
        """Advance one window and return the on-mask over all devices.

        ``expected_on`` is each tracked type's device count implied by its
        steady-state total; ``split_hint`` maps device index to its share from
        the steady-state split, used only to break reconciliation ties.
        """
        self._apply_events(phasors, sag)
        self._windows += 1
        if self._windows >= SETTLE_WINDOWS:
            for kind in self.multi_kinds:
                self._reconcile(
                    kind, kind in detected_kinds, expected_on.get(kind, 0), split_hint
                )
        return self.on.copy()
