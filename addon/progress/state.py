"""Mutable per-profile state for the progress-bar controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProgressState:
    """State that must be discarded when Anki changes profiles or days."""

    remaining: Dict[int, float] = field(default_factory=dict)
    completed: Dict[int, float] = field(default_factory=dict)
    total: Dict[int, float] = field(default_factory=dict)
    raw_remaining: Dict[int, int] = field(default_factory=dict)
    raw_completed: Dict[int, int] = field(default_factory=dict)
    raw_total: Dict[int, int] = field(default_factory=dict)
    actionable_review: Dict[int, int] = field(default_factory=dict)
    actionable_learning: Dict[int, int] = field(default_factory=dict)
    actionable_new: Dict[int, int] = field(default_factory=dict)
    buried_review: Dict[int, int] = field(default_factory=dict)
    buried_learning: Dict[int, int] = field(default_factory=dict)
    buried_new: Dict[int, int] = field(default_factory=dict)
    current_deck_id: Optional[int] = None
    main_window_state: Optional[str] = "deckBrowser"
    restored_day_stamp: Optional[int] = None
    progress_restored: bool = False
    last_snapshot: Optional[Dict[str, Any]] = None
    last_persisted_ts: float = 0.0
    latest_breakdown_rows: List[Dict[str, Any]] = field(default_factory=list)
    latest_breakdown_summary: Optional[Dict[str, Any]] = None
    last_cards_per_minute: Optional[float] = None

    def reset_for_profile(self) -> None:
        for counts in (
            self.remaining, self.completed, self.total,
            self.raw_remaining, self.raw_completed, self.raw_total,
            self.actionable_review, self.actionable_learning, self.actionable_new,
            self.buried_review, self.buried_learning, self.buried_new,
        ):
            counts.clear()
        self.current_deck_id = None
        self.main_window_state = "profileManager"
        self.progress_restored = False
        self.restored_day_stamp = None
        self.last_snapshot = None
        self.last_persisted_ts = 0.0
        self.latest_breakdown_rows = []
        self.latest_breakdown_summary = None
        self.last_cards_per_minute = None
