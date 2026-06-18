from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, List, Sequence, Tuple

from tests.stubs import DeckNode, QFileDialog, QPainter, QPalette, QRect


class SequenceDB:
    def __init__(self, all_rows: Sequence[Tuple[Any, ...]] = (), first_rows: List[Any] | None = None) -> None:
        self.all_rows = list(all_rows)
        self.first_rows = list(first_rows or [])
        self.first_calls: List[Tuple[str, Tuple[Any, ...]]] = []
        self.all_calls: List[Tuple[str, Tuple[Any, ...]]] = []

    def all(self, query: str, *params: Any):
        self.all_calls.append((query, params))
        return list(self.all_rows)

    def first(self, query: str, *params: Any):
        self.first_calls.append((query, params))
        if self.first_rows:
            return self.first_rows.pop(0)
        return None


def seed_progress_counts(mod, done: int = 2, remain: int = 8) -> None:
    for bucket in (
        mod.doneCount,
        mod.remainCount,
        mod.totalCount,
        mod.rawDoneCount,
        mod.rawRemainCount,
        mod.rawTotalCount,
        mod.actionableRevCount,
        mod.actionableLrnCount,
        mod.actionableNewCount,
        mod.buriedRevCount,
        mod.buriedLrnCount,
        mod.buriedNewCount,
    ):
        bucket.clear()

    mod.doneCount[1] = float(done)
    mod.remainCount[1] = float(remain)
    mod.rawDoneCount[1] = done
    mod.rawRemainCount[1] = remain
    mod.actionableNewCount[1] = 4
    mod.actionableLrnCount[1] = 3
    mod.actionableRevCount[1] = max(0, remain - 7)
    mod.buriedNewCount[1] = 1
    mod.buriedLrnCount[1] = 0
    mod.buriedRevCount[1] = 0


def setup_progress_update(mod, config=None) -> None:
    mod._apply_config(config or {})
    mod.mw.col.db = SequenceDB(
        first_rows=[
            (3, 1, 1, 2, 1, 0, 12),  # today
            (3, 0, 0, 3, 1, 0, 15),  # yesterday
        ]
    )
    root = DeckNode(0, [DeckNode(1)])
    mod.mw.col.sched._deck_tree = root
    mod.mw.col.sched.day_cutoff = 1000
    seed_progress_counts(mod)
    mod.initPB()
    mod.updatePB()


def test_config_coercion_and_normalization(addon_module):
    mod = addon_module

    assert mod._coerce_bool("true", False) is True
    assert mod._coerce_bool("0", True) is False
    assert mod._coerce_bool(None, True) is True
    assert mod._coerce_int("5", 1) == 5
    assert mod._coerce_float("1.5", 0.1) == 1.5
    assert mod._normalize_dimension(10) == "10px"
    assert mod._normalize_dimension("25%") == "25%"

    mod._apply_config(
        {
            "progress_bar_enabled": "false",
            "max_width": 12,
            "time_warning_minutes": "30",
            "use_system_timezone": "false",
            "tz": -3,
        }
    )

    assert mod.progress_bar_enabled is False
    assert mod.maxWidth == "12px"
    assert mod.time_warning_minutes == 0
    assert mod.settings.mode == "stats"
    assert mod.settings.use_system_timezone is False
    assert mod.settings.tz == -3
    assert "time_warning_minutes" not in mod.settings.raw_config


def test_mode_and_theme_validation(mw):
    from addon import config as addon_config

    addon_config.apply_config(
        mw,
        {
            "mode": "nope",
            "theme": "dark",
            "appearance": {
                "day": {"text": "#111111", "background": "#eeeeee", "foreground": "#123456", "border_radius": 0},
                "night": {"text": "#ffffff", "background": "#222222", "foreground": "#abcdef", "border_radius": 0},
            },
        },
    )

    assert addon_config.settings.mode == "stats"
    assert addon_config.settings.theme == "dark"
    assert addon_config.settings.active_theme.background == "#222222"


def test_queue_counts_for_node_caps_and_excludes_buried(addon_module):
    mod = addon_module
    mod.mw.col.db = SequenceDB(first_rows=[(10, 5, 2, 1, 2, 6)])

    child = DeckNode(2)
    node = DeckNode(1, [child])
    node.review_count = 5
    node.learn_count = 3
    node.new_count = 4

    assert mod._queue_counts_for_node(node) == (5, 3, 2, 1, 2, 6)


def test_legacy_warning_config_is_ignored(addon_module):
    mod = addon_module
    setup_progress_update(
        mod,
        {
            "warnings_enabled": True,
            "pace_warnings_enabled": True,
            "time_warning_minutes": 1,
            "again_warning_percent": 1,
            "retention_warning_percent": 100,
        },
    )

    assert mod.warnings_enabled is False
    assert mod.pace_warnings_enabled is False
    assert "warnings_enabled" not in mod.settings.raw_config
    assert "pace_warnings_enabled" not in mod.settings.raw_config
    assert "⚠" not in mod.progressBar.format()
    bar_colors = {role: color.name() for role, color in mod.progressBar.palette().colors.items()}
    settings_colors = {role: color.name() for role, color in mod.settings.palette.colors.items()}
    assert bar_colors == settings_colors


def test_progress_modes_change_visible_label(addon_module):
    mod = addon_module

    setup_progress_update(mod, {"mode": "simple"})
    simple_label = mod.progressBar.format()
    assert simple_label == "2/10 (20%)"
    assert "ETA" not in simple_label
    assert "Again" not in simple_label

    setup_progress_update(mod, {"mode": "time_left"})
    time_label = mod.progressBar.format()
    assert "ETA" in time_label
    assert "spent" in time_label
    assert "Again" not in time_label

    setup_progress_update(mod, {"mode": "stats"})
    stats_label = mod.progressBar.format()
    assert "ETA" in stats_label
    assert "Again" in stats_label
    assert "Retention" in stats_label
    assert (" " + "T" + "R") not in stats_label


def test_history_export_writes_expected_rows(tmp_path: Path, addon_module):
    mod = addon_module
    mod.mw.pm.profile = {
        mod.HISTORY_PROGRESS_KEY: [
            {
                "day": 1,
                "cards": 5,
                "avg_seconds": 1.234,
                "again": 10.5,
                "retention": 80.0,
                "super_mature_retention": 50.0,
            }
        ]
    }

    dialog = mod.SessionHistoryDialog(mod.mw)
    output_path = tmp_path / "history.csv"
    QFileDialog.next_path = str(output_path)
    dialog._export_csv()

    with output_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == [
        "day",
        "cards",
        "avg_seconds",
        "again_percent",
        "retention_percent",
        "super_mature_retention",
    ]
    assert rows[1] == [mod.history.format_history_day(1), "5", "1.23", "10.50", "80.00", "50.00"]


def test_segmented_progress_bar_paints_remaining_segments():
    from addon.ui import progress_bar as progress_ui

    palette = QPalette()
    bar = progress_ui.SegmentedProgressBar(
        {"new": progress_ui.QColor("#111"), "learning": progress_ui.QColor("#222"), "review": progress_ui.QColor("#333")}
    )
    bar.setSegmentData(3, 2, 1, 0.25)

    painter = QPainter()
    bar._draw_segments_horizontal(painter, QRect(0, 0, 100, 10), palette)

    assert len(painter.filled) >= 3
    assert any(fill[1].name() == "#111" for fill in painter.filled)


def test_progress_bar_keyboard_activation_and_accessibility(addon_module):
    from addon.ui import progress_bar as progress_ui
    from tests.stubs import QEvent, Qt

    mod = addon_module
    mod._apply_config({})
    mod.initPB()

    calls: List[str] = []
    progress_ui.set_click_handler(lambda: calls.append("opened"))

    assert progress_ui.progressBar._focus_policy == Qt.FocusPolicy.StrongFocus
    assert progress_ui.progressBar._accessible_name == "Progress Bar Time Left"
    assert "deck breakdown" in progress_ui.progressBar._accessible_description

    key_event = QEvent(QEvent.Type.KeyPress, key=Qt.Key.Key_Return)
    assert progress_ui.interaction_filter.eventFilter(progress_ui.progressBar, key_event) is True

    space_event = QEvent(QEvent.Type.KeyPress, key=Qt.Key.Key_Space)
    assert progress_ui.interaction_filter.eventFilter(progress_ui.progressBar, space_event) is True
    assert calls == ["opened", "opened"]


def test_settings_dialog_is_lightweight(addon_module):
    mod = addon_module

    dialog = mod.ProgressBarConfigDialog(mod.mw)
    dialog._apply_compact_mode(600)

    assert dialog._minimum_width == 420
    assert dialog._compact_layout_active is False
    assert dialog.mode_combo.currentData() == "stats"
    assert dialog.dock_area_combo.currentData() == "top"
    assert dialog.theme_combo.currentData() == "auto"
    assert dialog.shortcut_field.value()


def test_tools_menu_only_exposes_progress_bar_settings(addon_module):
    mod = addon_module

    assert [action.text for action in mod.mw.form.menuTools.actions] == ["Progress Bar Settings"]


def test_legacy_ctrl_shortcut_is_normalized_on_macos(mw, monkeypatch):
    from addon import config as addon_config

    monkeypatch.setattr(addon_config.sys, "platform", "darwin")
    addon_config.apply_config(mw, {"toggle_shortcut": "Ctrl+G"})

    assert addon_config.settings.toggle_shortcut == "Meta+G"
    assert addon_config.settings.raw_config["toggle_shortcut"] == "Meta+G"


def test_smoke_progress_bar_initialization(addon_module):
    mod = addon_module
    mod.mw.col.db = SequenceDB(first_rows=[None, None])
    mod.mw.col.sched._deck_tree = DeckNode(0, [])

    mod.initPB()
    mod.updatePB()

    assert mod.progressBar is not None
    parent = mod.progressBar.parentWidget()
    assert parent is None or parent.objectName() == "pbDock"
    assert mod.progressBar._event_filters


def test_deck_breakdown_populates_rows(addon_module):
    mod = addon_module
    dialog = mod.DeckBreakdownDialog(mod.mw)

    dialog.update_rows(
        [
            {
                "name": "Parent",
                "deck_id": 1,
                "actionable": (1, 2, 3),
                "buried": (0, 1, 0),
                "eta": "N/A",
                "children": [],
            }
        ]
    )

    assert dialog._tree._items[0].text(0) == "Parent"
    assert dialog._tree._items[0].text(1) == "6 (N 1 · L 2 · R 3)"


def test_profile_close_persistence_records_counts(addon_module):
    mod = addon_module
    mod.totalCount[1] = 1.0
    mod.rawTotalCount[1] = 1
    mod.doneCount[1] = 1.0
    mod.rawDoneCount[1] = 1
    mod.mw.col.sched.day_cutoff = 86400
    mod.mw.col.db = SequenceDB(first_rows=[None])

    mod._on_profile_will_close()

    assert mod.mw.pm.profile[mod.PERSISTED_PROGRESS_KEY]["data"]["1"]["raw_total"] == 1
