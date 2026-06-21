from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Sequence, Tuple

from tests.stubs import QApplication, DeckNode, QFileDialog, QPainter, QPalette, QRect


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
    assert mod.settings.display_location == "review_and_home"
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


def test_display_location_validation_defaults_to_review_and_home(mw):
    from addon import config as addon_config

    addon_config.apply_config(mw, {"display_location": "home"})

    assert addon_config.settings.display_location == "review_and_home"
    assert addon_config.settings.raw_config["display_location"] == "review_and_home"
    assert "display_location 'home' invalid; using review_and_home." in addon_config.validation_errors


def test_config_persistence_uses_packaged_addon_id(mw):
    from addon import config as addon_config

    addon_config.apply_config(mw, {"mode": "simple"})

    assert mw.addonManager.get_calls[-1] == "1511983907"
    assert [name for name, _ in mw.addonManager.write_calls] == ["1511983907", "1511983907"]


def test_settings_dialog_save_uses_packaged_addon_id(addon_module):
    mod = addon_module

    dialog = mod.ProgressBarConfigDialog(mod.mw)
    dialog.progress_bar_enabled_cb.setChecked(False)
    dialog._save_and_close()

    assert dialog._accepted is True
    assert mod.mw.addonManager.write_calls
    assert all(name == "1511983907" for name, _ in mod.mw.addonManager.write_calls)


def test_settings_dialog_save_avoids_obsolete_addon_id(addon_module):
    mod = addon_module

    dialog = mod.ProgressBarConfigDialog(mod.mw)
    dialog.progress_bar_enabled_cb.setChecked(False)
    dialog._save_and_close()

    assert dialog._accepted is True
    assert "1097423555" not in [name for name, _ in mod.mw.addonManager.write_calls]


def test_smtr_is_hidden_by_default_and_can_be_enabled(addon_module):
    mod = addon_module

    setup_progress_update(mod, {"mode": "stats"})

    assert "SMTR" not in mod.progressBar.format()
    assert mod.settings.raw_config["show_super_mature_retention"] is False

    setup_progress_update(mod, {"mode": "stats", "show_super_mature_retention": True})
    assert "SMTR" in mod.progressBar.format()
    assert mod.settings.raw_config["show_super_mature_retention"] is True


def test_settings_dialog_saves_smtr_checkbox(addon_module):
    mod = addon_module

    dialog = mod.ProgressBarConfigDialog(mod.mw)
    dialog.show_smtr_cb.setChecked(True)
    dialog._save_and_close()

    assert dialog._accepted is True
    assert mod.mw.addonManager.config["show_super_mature_retention"] is True


def test_settings_dialog_saves_display_location(addon_module):
    mod = addon_module

    dialog = mod.ProgressBarConfigDialog(mod.mw)
    assert dialog.display_location_combo.currentData() == "review_and_home"

    dialog.display_location_combo.setCurrentIndex(dialog.display_location_combo.findData("review"))
    dialog._save_and_close()

    assert dialog._accepted is True
    assert mod.mw.addonManager.config["display_location"] == "review"


def test_theme_resolution_controls_bar_and_dialog_palettes(addon_module):
    mod = addon_module
    from aqt.theme import theme_manager

    theme_manager.night_mode = True
    mod._apply_config({"theme": "auto"})
    assert mod.settings.active_theme.background == "rgba(39, 40, 40, 1)"
    assert mod.settings.active_theme.foreground == "#3399cc"
    assert mod._ui_palette()["window_bg"] == "#0b1220"
    assert mod._ui_palette()["helper_text"] == "#a5b2c5"

    mod._apply_config({"theme": "light"})
    assert mod.settings.active_theme.background == "#e7edf3"
    assert mod.settings.active_theme.foreground == "#12a8cc"
    assert mod._ui_palette()["window_bg"] == "#f7f9fc"
    assert mod._ui_palette()["muted_row_text"] == "#7a8699"
    assert "summary_bg" in mod._ui_palette()
    assert "segment_new" in mod._ui_palette()

    theme_manager.night_mode = False
    mod._apply_config({"theme": "dark"})
    assert mod.settings.active_theme.background == "rgba(39, 40, 40, 1)"
    assert mod._ui_palette()["window_bg"] == "#0b1220"
    assert mod._ui_palette()["card_bg"] == "#111827"
    assert mod._ui_palette()["muted_row_text"] == "#64748b"
    assert "summary_bg" in mod._ui_palette()
    assert "segment_review" in mod._ui_palette()

    settings_dialog = mod.ProgressBarConfigDialog(mod.mw)
    history_dialog = mod.SessionHistoryDialog(mod.mw)
    assert "#0b1220" in settings_dialog.styleSheet()
    assert history_dialog._palette["window_bg"] == "#0b1220"


def test_release_polish_styles_are_applied(addon_module):
    mod = addon_module

    mod._apply_config({"theme": "light"})
    dialog = mod.ProgressBarConfigDialog(mod.mw)
    row = mod.SettingRow("Mode", "Pick a display mode.", dialog.mode_combo, mod._ui_palette("light"))

    assert "font-weight: 600;" in mod.settings.default_stylesheet
    assert "min-height: 22px;" in mod.settings.default_stylesheet
    assert "#111827" in mod.settings.default_stylesheet
    assert "#12a8cc" in mod.settings.default_stylesheet
    assert "min-height: 20px;" in dialog.styleSheet()
    assert "border-color: #5b8def;" in dialog.styleSheet()
    assert row.styleSheet() == "border-bottom: 1px solid #e4eaf2;"
    assert "min-height: 20px;" in dialog.shortcut_field._editor.styleSheet()


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
    assert progress_ui.progressBar._accessible_name == "Progress_Bar_Reforged"
    assert "deck breakdown" in progress_ui.progressBar._accessible_description

    key_event = QEvent(QEvent.Type.KeyPress, key=Qt.Key.Key_Return)
    assert progress_ui.interaction_filter.eventFilter(progress_ui.progressBar, key_event) is True

    space_event = QEvent(QEvent.Type.KeyPress, key=Qt.Key.Key_Space)
    assert progress_ui.interaction_filter.eventFilter(progress_ui.progressBar, space_event) is True
    assert calls == ["opened", "opened"]


def test_progress_bar_tooltip_includes_deck_breakdown_hint(addon_module):
    from addon.ui import progress_bar as progress_ui
    from tests.stubs import QHelpEvent, QToolTip

    mod = addon_module
    setup_progress_update(mod)

    assert progress_ui.progressBar.toolTip() == "Click for full Deck Breakdown."
    assert "Cards completed:" not in progress_ui.progressBar.toolTip()

    event = QHelpEvent(pos=SimpleNamespace(x=lambda: 0))
    assert progress_ui.progress_tooltip_filter.eventFilter(progress_ui.progressBar, event) is True
    assert QToolTip.last_text == "Click for full Deck Breakdown."

    mod.setScrollingPB()
    assert progress_ui.progressBar.toolTip() == "Click for full Deck Breakdown."
    assert "Anki is updating the collection" not in progress_ui.progressBar.toolTip()


def _prepare_state_change_counts(mod) -> None:
    mod.mw.col.db = SequenceDB(first_rows=[None, None])
    mod.mw.col.sched._deck_tree = DeckNode(0, [DeckNode(1)])
    mod.mw.col.sched.day_cutoff = 1000
    mod.mw.col.decks.current = lambda: {"id": 1}


def test_display_location_default_shows_on_deck_browser(addon_module):
    mod = addon_module
    _prepare_state_change_counts(mod)

    mod._apply_config({})
    mod.afterStateChangeCallBack("deckBrowser", "review")

    assert mod.settings.display_location == "review_and_home"
    assert mod.progressBar is not None
    assert mod.currDID is None


def test_display_location_review_only_hides_on_deck_browser(addon_module):
    mod = addon_module
    _prepare_state_change_counts(mod)

    mod._apply_config({"display_location": "review"})
    mod.initPB()
    assert mod.progressBar is not None

    mod.afterStateChangeCallBack("deckBrowser", "review")

    assert mod.progressBar is None
    assert mod.currDID is None


def test_display_location_review_only_shows_on_review(addon_module):
    mod = addon_module
    _prepare_state_change_counts(mod)

    mod._apply_config({"display_location": "review"})
    mod.afterStateChangeCallBack("deckBrowser", "review")
    assert mod.progressBar is None

    mod.afterStateChangeCallBack("review", "deckBrowser")

    assert mod.progressBar is not None
    assert mod.currDID == 1


def test_progress_bar_disabled_removes_for_any_display_location(addon_module):
    mod = addon_module
    _prepare_state_change_counts(mod)

    mod._apply_config({"display_location": "review_and_home"})
    mod.initPB()
    assert mod.progressBar is not None

    mod._apply_config({"progress_bar_enabled": False, "display_location": "review_and_home"})
    mod.afterStateChangeCallBack("review", "deckBrowser")

    assert mod.progressBar is None


def test_settings_dialog_is_lightweight(addon_module):
    mod = addon_module

    dialog = mod.ProgressBarConfigDialog(mod.mw)
    dialog._apply_compact_mode(600)

    assert dialog._minimum_width == 420
    assert dialog._compact_layout_active is False
    assert dialog.display_location_combo.currentData() == "review_and_home"
    assert dialog.mode_combo.currentData() == "stats"
    assert dialog.dock_area_combo.currentData() == "top"
    assert dialog.theme_combo.currentData() == "auto"
    assert dialog.show_smtr_cb.isChecked() is False
    assert dialog.shortcut_field.value()


def test_settings_dialog_donate_button_opens_buy_me_a_coffee(addon_module):
    from tests.stubs import QDesktopServices

    mod = addon_module
    dialog = mod.ProgressBarConfigDialog(mod.mw)

    assert dialog._donate_btn.toolTip() == "Donate to support the creator"
    assert dialog._donate_btn._accessible_name == "Buy Me a Coffee"
    assert dialog._donate_btn._icon.path.endswith("assets/buy_me_a_coffee.png")

    dialog._donate_btn.clicked()

    assert QDesktopServices.last_url.toString() == "https://www.buymeacoffee.com/caleblee78f"


def test_package_builder_includes_donate_asset():
    from scripts import package_addon

    packaged_paths = {path.relative_to(package_addon.ADDON_DIR).as_posix() for path in package_addon._iter_package_files()}

    assert "assets/buy_me_a_coffee.png" in packaged_paths


def test_package_builder_manifest_uses_canonical_addon_id(tmp_path):
    from scripts import package_addon

    output = package_addon.build_package(tmp_path / "progress_bar_time_left.ankiaddon", mod_time=123)

    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))

    assert manifest["package"] == "1511983907"


def test_tools_menu_only_exposes_progress_bar_settings(addon_module):
    mod = addon_module

    assert [action.text for action in mod.mw.form.menuTools.actions] == ["Progress Bar Settings"]


def test_legacy_ctrl_shortcut_is_normalized_on_macos(mw, monkeypatch):
    from addon import config as addon_config

    monkeypatch.setattr(addon_config.sys, "platform", "darwin")
    addon_config.apply_config(mw, {"toggle_shortcut": "Ctrl+G"})

    assert addon_config.settings.toggle_shortcut == "Meta+G"
    assert addon_config.settings.raw_config["toggle_shortcut"] == "Meta+G"
    assert addon_config.validation_errors == []


def test_legacy_ctrl_shortcut_does_not_show_startup_tooltip(monkeypatch):
    import importlib
    import sys

    from tests.stubs import install_stubs

    install_stubs({"toggle_shortcut": "Ctrl+G"})
    for name in [
        "addon.reviewer_progress_bar",
        "addon.config",
        "addon.history",
        "addon.ui.progress_bar",
    ]:
        sys.modules.pop(name, None)

    import addon.config as addon_config

    monkeypatch.setattr(addon_config.sys, "platform", "darwin")
    mod = importlib.import_module("addon.reviewer_progress_bar")

    assert mod.settings.toggle_shortcut == "Meta+G"
    assert not hasattr(mod.mw, "_last_tooltip")


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
    assert dialog._tree._items[0].text(1) == ""
    assert dialog._tree._headers == ["Deck", "Due Today", "Buried", "ETA"]
    assert dialog._tree._items[0].toolTip(1) == "Due today: 6; New 1, Learning 2, Review 3"
    assert dialog._summary_card._title_label.text() == "Parent Today"
    assert dialog._summary_card._main_label.text() == "6 cards due today · 1 buried · Finish estimate: No ETA yet"
    assert dialog._summary_card.toolTip() == ""
    assert dialog._summary_card._chip_labels["new"].text() == "New 1"
    assert dialog._summary_card._segment_bar._counts == (1, 2, 3)
    assert dialog._sort_combo._items[1][0] == "Most due today"


def test_deck_breakdown_summary_aggregates_top_level_rows(addon_module):
    mod = addon_module

    summary = mod._build_breakdown_summary(
        [
            {
                "name": "One",
                "actionable": (2, 0, 4),
                "buried": (1, 0, 0),
                "eta": "09:30 AM",
                "children": [{"name": "Child", "actionable": (99, 0, 0), "buried": (0, 0, 0)}],
            },
            {
                "name": "Two",
                "actionable": (0, 1, 3),
                "buried": (0, 2, 0),
                "eta": "10:30 AM",
                "children": [],
            },
        ]
    )

    assert summary["title"] == "All Decks Today"
    assert summary["actionable"] == (2, 1, 7)
    assert summary["buried"] == (1, 2, 0)
    assert summary["main"] == "10 cards due today · 3 buried · Finish estimate: No ETA yet"


def test_deck_breakdown_summary_handles_zero_and_buried_only(addon_module):
    mod = addon_module

    summary = mod._build_breakdown_summary(
        [
            {
                "name": "Quiet",
                "actionable": (0, 0, 0),
                "buried": (1, 0, 2),
                "eta": "N/A",
                "children": [],
            }
        ]
    )

    assert summary["title"] == "Quiet Today"
    assert summary["main"] == "0 cards due today · 3 buried · Finish estimate: No ETA yet"
    assert "Buried: 3" in summary["clipboard"]


def test_deck_breakdown_hide_empty_keeps_non_empty_descendants(addon_module):
    mod = addon_module
    dialog = mod.DeckBreakdownDialog(mod.mw)

    dialog.update_rows(
        [
            {
                "name": "Parent",
                "actionable": (0, 0, 0),
                "buried": (0, 0, 0),
                "eta": "N/A",
                "children": [
                    {
                        "name": "Child Work",
                        "actionable": (1, 0, 0),
                        "buried": (0, 0, 0),
                        "eta": "08:00 AM",
                        "children": [],
                    }
                ],
            },
            {"name": "Empty", "actionable": (0, 0, 0), "buried": (0, 0, 0), "eta": "N/A", "children": []},
            {"name": "Active", "actionable": (0, 0, 2), "buried": (0, 0, 0), "eta": "09:00 AM", "children": []},
        ]
    )

    assert dialog._hide_empty is True
    assert dialog._hide_empty_cb.isChecked() is True
    assert [item.text(0) for item in dialog._tree._items] == ["Parent", "Active"]

    dialog._hide_empty_cb.setChecked(False)

    assert [item.text(0) for item in dialog._tree._items] == ["Parent", "Empty", "Active"]

    dialog._hide_empty_cb.setChecked(True)

    assert [item.text(0) for item in dialog._tree._items] == ["Parent", "Active"]
    assert dialog._tree._items[0].children[0].text(0) == "Child Work"


def test_deck_breakdown_columns_auto_fit_then_become_interactive(addon_module):
    from tests.stubs import QHeaderView

    mod = addon_module
    dialog = mod.DeckBreakdownDialog(mod.mw)
    dialog.update_rows(
        [
            {
                "name": "Short",
                "actionable": (84, 5, 187),
                "buried": (5, 0, 5),
                "eta": "10:55 AM",
                "children": [],
            }
        ]
    )

    expected_width = sum(dialog._tree._column_widths.values()) + mod._BREAKDOWN_DIALOG_FRAME_WIDTH

    assert dialog._minimum_width == mod._BREAKDOWN_DIALOG_MIN_WIDTH
    assert dialog._minimum_width < 960
    assert dialog._width == expected_width
    assert dialog._tree._resized_columns == [0, 1, 2, 3]
    assert 170 <= dialog._tree._column_widths[0] <= 320
    assert 240 <= dialog._tree._column_widths[1] <= 310
    assert 220 <= dialog._tree._column_widths[2] <= 290
    assert 110 <= dialog._tree._column_widths[3] <= 135
    assert dialog._tree._column_widths[3] >= 110
    assert dialog._tree.header()._section_resize == {
        0: QHeaderView.ResizeMode.Interactive,
        1: QHeaderView.ResizeMode.Interactive,
        2: QHeaderView.ResizeMode.Interactive,
        3: QHeaderView.ResizeMode.Interactive,
    }


def test_deck_breakdown_auto_fit_can_shrink_to_smaller_content(addon_module):
    mod = addon_module
    dialog = mod.DeckBreakdownDialog(mod.mw)

    dialog.update_rows(
        [
            {
                "name": "A Very Long Parent Deck Name That Should Hit The Deck Column Cap",
                "actionable": (123456, 98765, 43210),
                "buried": (99999, 88888, 77777),
                "eta": "11:55 PM (+12d)",
                "children": [],
            }
        ]
    )
    wide_width = dialog._width

    dialog.request_auto_fit()
    dialog.update_rows(
        [
            {
                "name": "Short",
                "actionable": (1, 0, 0),
                "buried": (0, 0, 0),
                "eta": "N/A",
                "children": [],
            }
        ]
    )

    expected_width = sum(dialog._tree._column_widths.values()) + mod._BREAKDOWN_DIALOG_FRAME_WIDTH
    assert dialog._width == expected_width
    assert dialog._width < wide_width


def test_deck_breakdown_reopen_reused_dialog_shrinks_to_content(addon_module):
    mod = addon_module
    mod._latest_breakdown_rows = [
        {
            "name": "Short",
            "actionable": (1, 0, 0),
            "buried": (0, 0, 0),
            "eta": "N/A",
            "children": [],
        }
    ]

    mod._open_deck_breakdown_dialog()
    dialog = mod._deck_breakdown_dialog
    dialog.resize(1200, 620)

    mod._open_deck_breakdown_dialog()

    expected_width = sum(dialog._tree._column_widths.values()) + mod._BREAKDOWN_DIALOG_FRAME_WIDTH
    assert dialog._width == expected_width
    assert dialog._width < 1200


def test_deck_breakdown_rgba_colors_are_valid_for_painting(addon_module):
    mod = addon_module

    color = mod._qcolor_from_css("rgba(148, 163, 184, 0.16)")

    assert color.name() == "(148, 163, 184)"
    assert color.alpha_f == 0.16


def test_deck_breakdown_row_prominence_uses_primary_and_muted_text(addon_module):
    mod = addon_module
    mod._apply_config({"theme": "light"})
    dialog = mod.DeckBreakdownDialog(mod.mw)
    dialog._hide_empty_cb.setChecked(False)
    dialog.update_rows(
        [
            {"name": "Active", "actionable": (1, 0, 0), "buried": (0, 0, 0), "eta": "09:00 AM", "children": []},
            {"name": "Empty", "actionable": (0, 0, 0), "buried": (0, 0, 0), "eta": "N/A", "children": []},
        ]
    )

    palette = mod._ui_palette("light")
    active, empty = dialog._tree._items
    assert active._foregrounds[0].color.name() == palette["primary_text"]
    assert empty._foregrounds[0].color.name() == palette["muted_row_text"]


def test_deck_breakdown_sort_modes_reorder_siblings(addon_module):
    mod = addon_module
    dialog = mod.DeckBreakdownDialog(mod.mw)
    rows = [
        {"name": "Alpha", "actionable": (1, 0, 0), "buried": (0, 0, 0), "eta": "11:00 AM", "children": []},
        {"name": "Bravo", "actionable": (0, 0, 3), "buried": (0, 0, 0), "eta": "09:00 AM", "children": []},
        {"name": "Charlie", "actionable": (0, 2, 0), "buried": (0, 0, 0), "eta": "N/A", "children": []},
    ]

    dialog.update_rows(rows)
    dialog._sort_combo.setCurrentIndex(dialog._sort_combo.findData("actionable"))

    assert [item.text(0) for item in dialog._tree._items] == ["Bravo", "Charlie", "Alpha"]

    dialog._sort_combo.setCurrentIndex(dialog._sort_combo.findData("eta"))

    assert [item.text(0) for item in dialog._tree._items] == ["Bravo", "Alpha", "Charlie"]


def test_deck_breakdown_copy_summary_writes_clipboard(addon_module):
    mod = addon_module
    dialog = mod.DeckBreakdownDialog(mod.mw)
    dialog.update_rows(
        [
            {
                "name": "Parent",
                "actionable": (1, 2, 3),
                "buried": (0, 1, 0),
                "eta": "10:31 AM",
                "children": [],
            }
        ]
    )

    dialog._summary_card._copy_summary()

    assert QApplication.clipboard().text() == (
        "Parent Today\n"
        "6 cards due today · 1 buried · Finish estimate: 10:31 AM\n"
        "New 1 · Learning 2 · Review 3\n"
        "Buried: 1 (New 0 · Learning 1 · Review 0)"
    )


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
