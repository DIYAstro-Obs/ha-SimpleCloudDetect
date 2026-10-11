"""Safety evaluation of the add-on: label matching, wait times and the fail-safe for a dead camera.

Plain Python without MQTT, TensorFlow or HTTP, so it can be tested on its own. The caller passes
the current time (seconds) into every call.
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_THRESHOLD = 50.0
MIN_STALE_AFTER = 120.0  # seconds


@dataclass(frozen=True)
class SafeCondition:
    label: str  # lower case, stripped
    threshold: float  # percent


def parse_safe_conditions(raw) -> Tuple[List[SafeCondition], List[str]]:
    """Normalise the `safe_conditions` option.

    Entries are {label, threshold} dicts; a plain string is accepted with the default threshold.
    Returns the usable conditions and one sentence per problem for the log.
    """
    conditions: List[SafeCondition] = []
    problems: List[str] = []
    for entry in raw or []:
        if isinstance(entry, dict):
            label = entry.get("label", "")
            threshold = entry.get("threshold", DEFAULT_THRESHOLD)
        else:
            label, threshold = entry, DEFAULT_THRESHOLD
        label = str(label or "").strip()
        if not label:
            problems.append("an empty label in safe_conditions was ignored")
            continue
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            problems.append(f"threshold {threshold!r} of '{label}' is not a number, using {DEFAULT_THRESHOLD:g}")
            threshold = DEFAULT_THRESHOLD
        conditions.append(SafeCondition(label.lower(), threshold))
    return conditions, problems


def reading_is_safe(status: str, confidence: float, conditions: Iterable[SafeCondition]) -> bool:
    """True if the class is a safe label (exact, case-insensitive) with at least its threshold."""
    wanted = str(status).strip().lower()
    return any(wanted == c.label and confidence >= c.threshold for c in conditions)


def stale_after_for(scan_interval: float) -> float:
    """Seconds without a usable image after which the sky counts as unknown (unsafe)."""
    return max(3 * scan_interval, MIN_STALE_AFTER)


class SafetyTracker:
    """Turns single readings into the reported safe/unsafe state.

    A reading that differs from the reported state starts a timer (safe_wait / unsafe_wait); the
    state is only changed once the same reading has held that long. A reading equal to the
    reported state cancels any timer. Without a usable image for `stale_after` seconds the
    state falls back to unsafe, and any confirmation that spans the gap is void.
    """

    def __init__(self, conditions: List[SafeCondition], safe_wait: float, unsafe_wait: float,
                 stale_after: float, now: float):
        self.conditions = conditions
        self.safe_wait = safe_wait
        self.unsafe_wait = unsafe_wait
        self.stale_after = stale_after
        self.reported: Optional[bool] = None  # None until the first state is released
        self.last_success = now
        self._target: Optional[bool] = None  # reading that waits to be released
        self._since = now

    def on_result(self, status: str, confidence: float, now: float) -> bool:
        """Feed one detection. Returns True if the reported state changed."""
        self.last_success = now
        is_safe = reading_is_safe(status, confidence, self.conditions)
        if is_safe == self.reported:
            self._target = None
            return False
        if self._target != is_safe:
            self._target = is_safe
            self._since = now
        wait = self.safe_wait if is_safe else self.unsafe_wait
        if now - self._since >= wait:
            self.reported = is_safe
            self._target = None
            return True
        return False

    def on_failure(self, now: float) -> bool:
        """A cycle without a usable image. Returns True if the reported state changed."""
        if now - self.last_success < self.stale_after:
            return False
        self._target = None
        if self.reported is False:
            return False
        self.reported = False
        return True

    def snapshot(self, now: float) -> Dict[str, object]:
        """Countdown fields for the web UI."""
        if self._target is None:
            return {"is_pending": False, "pending_target": None, "countdown_total": 0, "countdown_remaining": 0}
        wait = self.safe_wait if self._target else self.unsafe_wait
        return {
            "is_pending": True,
            "pending_target": "safe" if self._target else "unsafe",
            "countdown_total": wait,
            "countdown_remaining": max(0.0, wait - (now - self._since)),
        }
