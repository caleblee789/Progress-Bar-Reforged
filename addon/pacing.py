from __future__ import annotations

from dataclasses import dataclass
import statistics
import time
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass
class PaceEstimate:
    seconds_per_card: float
    cards_per_minute: float
    confidence: str
    variance: float
    samples: int


def _confidence_label(samples: int, variance: float) -> str:
    if samples < 5:
        return "Low"
    if variance < 0.08 and samples >= 15:
        return "High"
    if variance < 0.2 and samples >= 8:
        return "Medium"
    return "Low"


def _safe_mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _trimmed(values: Sequence[float], trim: float = 0.15) -> List[float]:
    if len(values) < 6:
        return list(values)
    ordered = sorted(values)
    n = len(ordered)
    cut = int(n * trim)
    if cut <= 0:
        return ordered
    if cut * 2 >= n:
        return ordered
    return ordered[cut : n - cut]


def estimate_pace(
    strategy: str,
    samples: Sequence[float],
    *,
    segmented_samples: Optional[Sequence[float]] = None,
    ewma_alpha: float = 0.35,
) -> Optional[PaceEstimate]:
    all_samples = [s for s in samples if s > 0]
    if not all_samples:
        return None

    chosen = all_samples
    if strategy == "segmented" and segmented_samples:
        local = [s for s in segmented_samples if s > 0]
        if len(local) >= 3:
            chosen = local

    estimate: Optional[float]
    if strategy == "ewma":
        running = chosen[0]
        for value in chosen[1:]:
            running = ewma_alpha * value + (1 - ewma_alpha) * running
        estimate = running
    elif strategy == "median":
        estimate = statistics.median(chosen)
    elif strategy == "trimmed":
        estimate = _safe_mean(_trimmed(chosen))
    elif strategy == "segmented":
        estimate = statistics.median(chosen)
    else:
        estimate = _safe_mean(chosen)

    if estimate is None or estimate <= 0:
        return None

    if len(chosen) > 1:
        mean = _safe_mean(chosen) or estimate
        stdev = statistics.pstdev(chosen)
        variance = stdev / max(mean, 1e-6)
    else:
        variance = 1.0

    return PaceEstimate(
        seconds_per_card=estimate,
        cards_per_minute=60.0 / estimate,
        confidence=_confidence_label(len(chosen), variance),
        variance=variance,
        samples=len(chosen),
    )


@dataclass
class WarningState:
    active: bool = False
    changed_at: float = -1_000_000_000.0


class StabilizedWarning:
    def __init__(self) -> None:
        self._states: Dict[str, WarningState] = {}

    def evaluate(
        self,
        key: str,
        value: float,
        threshold: float,
        *,
        higher_is_worse: bool,
        hysteresis: float,
        cooldown_s: float,
        now: Optional[float] = None,
    ) -> bool:
        state = self._states.setdefault(key, WarningState())
        timestamp = time.monotonic() if now is None else now

        if higher_is_worse:
            enter = value >= threshold
            exit_cond = value <= max(0.0, threshold - hysteresis)
        else:
            enter = value <= threshold
            exit_cond = value >= threshold + hysteresis

        if not state.active and enter:
            if timestamp - state.changed_at >= cooldown_s:
                state.active = True
                state.changed_at = timestamp
        elif state.active and exit_cond:
            if timestamp - state.changed_at >= cooldown_s:
                state.active = False
                state.changed_at = timestamp

        return state.active


@dataclass
class SessionSample:
    seconds_per_card: float
    deck_key: Tuple[int, ...]
