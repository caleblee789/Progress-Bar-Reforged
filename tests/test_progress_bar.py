from __future__ import annotations

import csv
import json
import sqlite3
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Sequence, Tuple

from tests.stubs import QApplication, DeckNode, QFileDialog, QPainter, QPalette, QRect


def test_progress_state_reset_is_profile_scoped():
    from addon.progress.state import ProgressState

    state = ProgressState()
    state.remaining[1] = 3.0
    state.completed[1] = 2.0
    state.latest_breakdown_rows = [{"name": "Deck"}]
    state.progress_restored = True
    state.main_window_state = "review"

    state.reset_for_profile()

    assert state.remaining == {}
    assert state.completed == {}
    assert state.latest_breakdown_rows == []
    assert state.progress_restored is False
    assert state.main_window_state == "profileManager"


def test_hook_registration_supports_anki_generated_hook_objects():
    from addon.progress.lifecycle import register_once, unregister

    class GeneratedHook:
        def __init__(self) -> None:
            self._hooks = []

        def append(self, callback):
            self._hooks.append(callback)

        def remove(self, callback):
            self._hooks.remove(callback)

    hook = GeneratedHook()

    def first_callback():
        pass

    def replacement_callback():
        pass

    register_once(hook, first_callback, "main_window_did_init")
    register_once(hook, replacement_callback, "main_window_did_init")

    assert hook._hooks == [first_callback]

    unregister(hook, "main_window_did_init")

    assert hook._hooks == []


def test_font_measurement_handles_unicode_and_uses_qt_advance():
    from addon.ui.metrics import horizontal_advance

    class Metrics:
        def horizontalAdvance(self, text):
            return len(text.encode("utf-8"))

    assert horizontal_advance(Metrics(), "漢字 🧠") == len("漢字 🧠".encode("utf-8"))


def _hex_to_rgb(color: str) -> Tuple[float, float, float]:
    assert color.startswith("#") and len(color) == 7
    return tuple(int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))  # type: ignore[return-value]


def _relative_luminance(rgb: Tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)


def _contrast_ratio(foreground: str, background: str) -> float:
    foreground_luminance = _relative_luminance(_hex_to_rgb(foreground))
    background_luminance = _relative_luminance(_hex_to_rgb(background))
    lighter = max(foreground_luminance, background_luminance)
    darker = min(foreground_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _contrast_ratio_over(foreground: str, overlay: str, backdrop: str) -> float:
    match = re.fullmatch(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\)", overlay)
    if match is None:
        return _contrast_ratio(foreground, overlay)
    red, green, blue = (int(match.group(index)) / 255 for index in (1, 2, 3))
    alpha = float(match.group(4))
    backdrop_rgb = _hex_to_rgb(backdrop)
    blended = tuple(
        (channel * alpha) + (backdrop_channel * (1 - alpha))
        for channel, backdrop_channel in zip((red, green, blue), backdrop_rgb)
    )
    foreground_luminance = _relative_luminance(_hex_to_rgb(foreground))
    background_luminance = _relative_luminance(blended)  # type: ignore[arg-type]
    lighter = max(foreground_luminance, background_luminance)
    darker = min(foreground_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


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


class SQLiteDB:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")

    def execute(self, query: str, params: Sequence[Any] = ()) -> None:
        self.connection.execute(query, tuple(params))
        self.connection.commit()

    def all(self, query: str, *params: Any):
        return self.connection.execute(query, params).fetchall()

    def first(self, query: str, *params: Any):
        return self.connection.execute(query, params).fetchone()


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


def setup_progress_update_with_history(
    mod,
    *,
    today_stats: Tuple[int, int, int, int, int, int, int],
    history_records: List[dict],
    config=None,
    done: int = 0,
    remain: int = 8,
) -> None:
    mod._apply_config(config or {"mode": "time_left", "display_location": "review_and_home"})
    mod.mw.pm.profile[mod.HISTORY_PROGRESS_KEY] = list(history_records)
    mod.mw.col.db = SequenceDB(first_rows=[today_stats, None, today_stats])
    mod.mw.col.sched._deck_tree = DeckNode(0, [DeckNode(1)])
    mod.mw.col.sched.day_cutoff = 10 * 86400
    mod.mw.col.decks.current = lambda: {"id": 1}
    seed_progress_counts(mod, done=done, remain=remain)
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
    assert mod.settings.display_location == "review"
    assert "time_warning_minutes" not in mod.settings.raw_config


def test_malformed_config_is_repaired_without_stylesheet_injection(mw):
    from addon import config as addon_config

    settings = addon_config.apply_config(
        mw,
        {
            "appearance": ["invalid"],
            "segment_colors": "invalid",
            "max_width": "20px; color: red",
            "bar_height": "-1px",
            "padding": "1.5em",
            "opacity": "nan",
        },
    )

    assert settings.max_width == ""
    assert settings.bar_height == ""
    assert settings.padding == "1.5em"
    assert settings.opacity == 100
    assert settings.raw_config["appearance"]["day"]["foreground"] == "#0e7490"
    assert settings.raw_config["segment_colors"] == {
        "new": "#378ba5",
        "learning": "#aa7926",
        "review": "#41965a",
    }
    assert "appearance must be an object; using defaults." in addon_config.validation_errors
    assert "segment_colors must be an object; using defaults." in addon_config.validation_errors
    assert addon_config._coerce_float("nan", 2.5) == 2.5


def test_settings_cancel_and_apply_have_standard_persistence_semantics(addon_module):
    mod = addon_module
    mod._apply_config({"mode": "stats"})

    cancelled = mod.ProgressBarConfigDialog(mod.mw)
    cancelled.mode_combo.setCurrentIndex(cancelled.mode_combo.findData("simple"))
    cancelled.reject()
    assert mod.mw.addonManager.config["mode"] == "stats"

    applied = mod.ProgressBarConfigDialog(mod.mw)
    applied.mode_combo.setCurrentIndex(applied.mode_combo.findData("simple"))
    applied._apply_without_closing()
    applied.reject()
    assert mod.mw.addonManager.config["mode"] == "simple"


def test_settings_dialog_maps_legacy_time_left_to_advanced(addon_module):
    mod = addon_module
    mod._apply_config({"mode": "time_left"})

    dialog = mod.ProgressBarConfigDialog(mod.mw)

    assert dialog.mode_combo.currentData() == "stats"
    dialog._apply_without_closing()
    assert mod.mw.addonManager.config["mode"] == "stats"


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


def test_display_location_validation_defaults_to_review(mw):
    from addon import config as addon_config

    addon_config.apply_config(mw, {"display_location": "home"})

    assert addon_config.settings.display_location == "review"
    assert addon_config.settings.raw_config["display_location"] == "review"
    assert "display_location 'home' invalid; using review." in addon_config.validation_errors


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
    assert dialog.display_location_combo.currentData() == "review"

    dialog.display_location_combo.setCurrentIndex(dialog.display_location_combo.findData("review_and_home"))
    dialog._save_and_close()

    assert dialog._accepted is True
    assert mod.mw.addonManager.config["display_location"] == "review_and_home"


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
    assert mod.settings.active_theme.foreground == "#0e7490"
    assert mod._ui_palette()["window_bg"] == "#f7f9fc"
    assert mod._ui_palette()["muted_row_text"] == "#667085"
    assert "summary_bg" in mod._ui_palette()
    assert "segment_new" in mod._ui_palette()

    theme_manager.night_mode = False
    mod._apply_config({"theme": "dark"})
    assert mod.settings.active_theme.background == "rgba(39, 40, 40, 1)"
    assert mod._ui_palette()["window_bg"] == "#0b1220"
    assert mod._ui_palette()["card_bg"] == "#111827"
    assert mod._ui_palette()["muted_row_text"] == "#94a3b8"
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
    assert "#0e7490" in mod.settings.default_stylesheet
    assert "min-height: 20px;" in dialog.styleSheet()
    assert "border-color: #5b8def;" in dialog.styleSheet()
    assert row.styleSheet() == "border-bottom: 1px solid #7c8ba1;"
    assert "min-height: 20px;" in dialog.shortcut_field._editor.styleSheet()


def test_settings_dialog_light_theme_styles_shortcut_and_buttons(addon_module):
    mod = addon_module
    from tests.stubs import QPalette

    mod._apply_config({"theme": "light"})
    dialog = mod.ProgressBarConfigDialog(mod.mw)

    assert "#f7f9fc" in dialog.styleSheet()
    assert "#0b1220" not in dialog.styleSheet()
    assert "#0f172a" not in dialog.shortcut_field._editor.styleSheet()
    assert "QKeySequenceEdit#shortcutRecorder QToolButton" in dialog.shortcut_field._editor.styleSheet()
    assert "QKeySequenceEdit#shortcutRecorder QLineEdit" in dialog.shortcut_field._editor.styleSheet()
    assert "background: #ffffff;" in dialog.shortcut_field._editor.styleSheet()
    assert "QKeySequenceEdit#shortcutRecorder:active" in dialog.shortcut_field._editor.styleSheet()
    assert "background-color: #ffffff;" in dialog.shortcut_field._editor.styleSheet()
    assert dialog.shortcut_field._editor.palette().color(QPalette.ColorRole.Base).name() == "#ffffff"
    assert dialog.shortcut_field._editor.palette().color(QPalette.ColorRole.Text).name() == "#1f2937"
    native_child = dialog.shortcut_field._editor._native_editor_child
    assert native_child.palette().color(QPalette.ColorRole.Base).name() == "#ffffff"
    assert native_child._auto_fill_background is True
    assert "QToolButton#shortcutResetButton" in dialog.shortcut_field._reset_btn.styleSheet()
    assert "background: #f5f7fb;" in dialog.shortcut_field._reset_btn.styleSheet()
    assert "background: #eef2f7;" in dialog.styleSheet()
    for combo in (dialog.display_location_combo, dialog.mode_combo, dialog.dock_area_combo, dialog.theme_combo):
        assert "background: #ffffff;" in combo.styleSheet()
        assert "#0f172a" not in combo.styleSheet()


def test_settings_dialog_cards_primary_action_and_checked_states_use_accent(addon_module):
    mod = addon_module
    mod._apply_config({"theme": "light"})
    dialog = mod.ProgressBarConfigDialog(mod.mw)
    palette = mod._ui_palette("light")

    style = dialog.styleSheet()
    assert "QFrame#settingsHeader" in style
    assert "QFrame#settingsCard" in style
    assert "QFrame#settingsFooter" in style
    assert "QPushButton#primaryButton" in style
    assert f"background: {palette['accent']};" in style
    assert f"border-color: {palette['accent']};" in style
    assert dialog._save_btn.objectName() == "primaryButton"


def test_settings_dialog_auto_theme_rethemes_shortcut_native_palette(addon_module):
    mod = addon_module
    from aqt.theme import theme_manager
    from tests.stubs import QPalette

    theme_manager.night_mode = True
    mod._apply_config({"theme": "auto"})
    dialog = mod.ProgressBarConfigDialog(mod.mw)
    assert dialog.shortcut_field._editor.palette().color(QPalette.ColorRole.Base).name() == "#0f172a"

    theme_manager.night_mode = False
    dialog.apply_theme()
    assert dialog.shortcut_field._editor.palette().color(QPalette.ColorRole.Base).name() == "#ffffff"
    assert "QKeySequenceEdit#shortcutRecorder:focus" in dialog.shortcut_field._editor.styleSheet()
    assert "QKeySequenceEdit#shortcutRecorder:active" in dialog.shortcut_field._editor.styleSheet()


def test_shortcut_recorder_only_records_after_click_and_disarms(addon_module):
    mod = addon_module
    from tests.stubs import QEvent, QKeySequence, Qt

    dialog = mod.ProgressBarConfigDialog(mod.mw)
    field = dialog.shortcut_field
    recorder_filter = field._recorder_filter

    assert field._editor._focus_policy == Qt.FocusPolicy.ClickFocus
    assert field._editor._maximum_sequence_length == 1
    assert recorder_filter.eventFilter(field._editor, QEvent(QEvent.Type.FocusIn)) is True
    assert field._recording_armed is False

    assert recorder_filter.eventFilter(
        field._editor,
        QEvent(QEvent.Type.MouseButtonPress, button=Qt.MouseButton.LeftButton),
    ) is False
    assert field._recording_armed is True
    assert field._record_hint.text() == "Press shortcut keys."

    field._editor.setFocus()
    field._editor.setKeySequence(QKeySequence("Meta+J"))

    assert field._recording_armed is False
    assert field._editor.hasFocus() is False
    assert field._record_hint.text() == "Click, then press keys."
    assert field.value() == "Meta+J"


def test_shortcut_conflicts_include_actions_and_other_shortcuts(addon_module):
    from tests.stubs import QAction, QKeySequence, QShortcut

    mod = addon_module
    action = QAction("Sync")
    action.setShortcut(QKeySequence("Meta+S"))
    other_shortcut = QShortcut(QKeySequence("Meta+K"), mod.mw)

    def find_children(klass):
        if klass is QAction:
            return [action]
        if klass is QShortcut:
            return [mod.progress_ui.toggle_shortcut, other_shortcut]
        return []

    mod.mw.findChildren = find_children
    field = mod.ShortcutField("Meta+G", mod._ui_palette("light"))

    field.set_shortcut("Meta+S")
    assert field.has_conflict() is True
    assert field._warning_label.text() == "Conflicts with Sync."

    field.set_shortcut("Meta+K")
    assert field.has_conflict() is True
    assert field._warning_label.text() == "Conflicts with another shortcut."

    field.set_shortcut(mod.settings.toggle_shortcut)
    assert field.has_conflict() is False


def test_dialog_theme_tokens_keep_text_contrast(addon_module):
    mod = addon_module

    checked_pairs = [
        ("primary_text", "window_bg"),
        ("secondary_text", "window_bg"),
        ("muted_text", "window_bg"),
        ("helper_text", "window_bg"),
        ("summary_title_text", "summary_bg"),
        ("summary_text", "summary_bg"),
        ("button_text", "button_bg"),
        ("checkbox_text", "window_bg"),
        ("muted_row_text", "card_bg"),
        ("eta_muted_text", "card_bg"),
        ("chip_new_text", "chip_new_bg"),
        ("chip_learning_text", "chip_learning_bg"),
        ("chip_review_text", "chip_review_bg"),
        ("accent_text", "accent"),
        ("danger_text", "danger_bg"),
        ("tooltip_text", "tooltip_bg"),
    ]
    for theme in ("light", "dark"):
        palette = mod._ui_palette(theme)
        for foreground_key, background_key in checked_pairs:
            assert _contrast_ratio(palette[foreground_key], palette[background_key]) >= 4.5

        assert _contrast_ratio(palette["disabled_text"], palette["disabled_bg"]) >= 4.5
        assert _contrast_ratio(palette["field_border"], palette["field_bg"]) >= 3.0
        assert _contrast_ratio(palette["button_border"], palette["button_bg"]) >= 3.0
        assert _contrast_ratio(palette["focus_border"], palette["field_bg"]) >= 3.0
        assert _contrast_ratio(palette["scrollbar_handle"], palette["scrollbar_bg"]) >= 3.0
        assert _contrast_ratio(palette["chart_cards"], palette["card_bg"]) >= 3.0
        assert _contrast_ratio(palette["chart_again"], palette["card_bg"]) >= 3.0
        assert _contrast_ratio(palette["chart_retention"], palette["card_bg"]) >= 3.0
        assert _contrast_ratio(palette["danger_text"], palette["card_bg"]) >= 4.5
        for border_key, background_key in (
            ("tab_border", "tab_selected_bg"),
            ("card_border", "card_bg"),
            ("summary_border", "summary_bg"),
            ("chip_border", "chip_muted_bg"),
            ("chip_new_border", "chip_new_bg"),
            ("chip_learning_border", "chip_learning_bg"),
            ("chip_review_border", "chip_review_bg"),
            ("row_divider", "card_bg"),
            ("tooltip_border", "tooltip_bg"),
            ("danger_border", "danger_bg"),
            ("segment_empty", "segment_track"),
            ("segment_new", "segment_track"),
            ("segment_learning", "segment_track"),
            ("segment_review", "segment_track"),
        ):
            if palette[background_key].startswith("rgba"):
                ratio = _contrast_ratio_over(
                    palette[border_key], palette[background_key], palette["card_bg"]
                )
            else:
                ratio = _contrast_ratio(palette[border_key], palette[background_key])
            assert ratio >= 3.0, (theme, border_key, background_key, ratio)
        for accent_background in ("accent", "accent_hover", "accent_pressed"):
            assert _contrast_ratio(palette["accent_text"], palette[accent_background]) >= 4.5
        for danger_background in ("danger_bg", "danger_hover_bg", "danger_pressed_bg"):
            assert _contrast_ratio(palette["danger_text"], palette[danger_background]) >= 4.5
        assert _contrast_ratio_over(
            palette["chip_muted_text"],
            palette["chip_muted_bg"],
            palette["card_bg"],
        ) >= 4.5
        assert _contrast_ratio_over(
            palette["table_selection_text"],
            palette["table_selection_bg"],
            palette["card_bg"],
        ) >= 4.5


def test_shortcut_native_palette_covers_active_inactive_and_disabled_groups(addon_module):
    mod = addon_module
    mod._apply_config({"theme": "light"})
    dialog = mod.ProgressBarConfigDialog(mod.mw)
    palette = dialog.shortcut_field._editor.palette()
    colors = mod._ui_palette("light")

    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        assert palette.color(group, QPalette.ColorRole.Base).name() == colors["field_bg"]
        assert palette.color(group, QPalette.ColorRole.Text).name() == colors["primary_text"]
    assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base).name() == colors["disabled_bg"]
    assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name() == colors["disabled_text"]


def test_history_uses_shared_semantic_theme_and_rethemes_in_place(addon_module):
    mod = addon_module
    mod._apply_config({"theme": "dark"})
    dialog = mod.SessionHistoryDialog(mod.mw)
    dark = mod._ui_palette("dark")

    assert dialog._clear_btn.objectName() == "destructiveButton"
    assert "QPushButton#destructiveButton" in dialog.styleSheet()
    assert "QTableCornerButton::section" in dialog.styleSheet()
    assert "QHeaderView {" in dialog.styleSheet()
    assert dialog.cards_chart._accent.name() == dark["chart_cards"]
    assert dialog.again_chart._accent.name() == dark["chart_again"]
    assert dialog.retention_chart._accent.name() == dark["chart_retention"]
    assert dialog.table._alternating_rows is True
    assert dialog.table._vertical_header.isVisible() is False
    assert dialog._minimum_width == 720
    assert (dialog._width, dialog._height) == (800, 720)

    mod._session_history_dialog = dialog
    mod._apply_config({"theme": "light"})
    light = mod._ui_palette("light")

    assert dialog._palette["window_bg"] == light["window_bg"]
    assert dialog.cards_chart._accent.name() == light["chart_cards"]
    assert dialog.again_chart._accent.name() == light["chart_again"]
    assert dialog.retention_chart._accent.name() == light["chart_retention"]


def test_ui_sources_do_not_embed_unapproved_color_literals():
    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "addon" / "history.py",
        root / "addon" / "reviewer_progress_bar.py",
        root / "addon" / "ui" / "progress_bar.py",
    ]
    pattern = re.compile(r"#[0-9a-fA-F]{6}|rgba?\([^\n)]*\)")
    allowed_examples = {"#ffffff", "#3399cc"}

    for source in sources:
        matches = set(pattern.findall(source.read_text(encoding="utf-8")))
        if source.name == "reviewer_progress_bar.py":
            matches -= allowed_examples
        assert matches == set(), f"Move raw UI colors in {source.name} into theme/config tokens: {sorted(matches)}"


def test_progress_bar_default_segments_match_semantic_palette(addon_module):
    mod = addon_module
    mod._apply_config({})

    assert {name: color.name() for name, color in mod.settings.segment_colors.items()} == {
        "new": "#378ba5",
        "learning": "#aa7926",
        "review": "#41965a",
    }


def test_progress_bar_custom_colors_remain_authoritative(addon_module):
    mod = addon_module
    mod._apply_config(
        {
            "theme": "light",
            "appearance": {
                "day": {
                    "text": "#101010",
                    "background": "#f0f0f0",
                    "foreground": "#123456",
                    "border_radius": 3,
                    "opacity": 100,
                }
            },
            "segment_colors": {"new": "#112233", "learning": "#445566", "review": "#778899"},
        }
    )

    assert mod.settings.active_theme.text == "#101010"
    assert mod.settings.active_theme.background == "#f0f0f0"
    assert mod.settings.active_theme.foreground == "#123456"
    assert {name: color.name() for name, color in mod.settings.segment_colors.items()} == {
        "new": "#112233",
        "learning": "#445566",
        "review": "#778899",
    }


def test_queue_counts_for_node_caps_and_excludes_buried(addon_module):
    mod = addon_module
    mod.mw.col.db = SequenceDB(first_rows=[(10, 5, 2, 1, 2, 6)])

    child = DeckNode(2)
    node = DeckNode(1, [child])
    node.review_count = 5
    node.learn_count = 3
    node.new_count = 4

    assert mod._queue_counts_for_node(node) == (5, 3, 2, 1, 2, 6)


def test_completed_counts_use_historical_answer_state_and_original_deck(addon_module):
    mod = addon_module
    db = SQLiteDB()
    db.execute("create table cards (id integer primary key, did integer, odid integer, type integer, queue integer)")
    db.execute("create table revlog (id integer, cid integer, type integer, lastIvl integer, ease integer, time integer)")
    for row in (
        (1, 10, 0, 2, 2),
        (2, 10, 0, 2, 1),
        (3, 10, 0, 2, 3),
        (4, 99, 10, 3, 2),
    ):
        db.execute("insert into cards values (?, ?, ?, ?, ?)", row)
    for row in (
        (2001, 1, 0, 0, 3, 1000),       # first answer of a new card
        (2002, 2, 0, -60, 3, 1000),     # learning step
        (2003, 3, 2, 1, 1, 1000),       # relearning
        (2004, 4, 1, 10, 3, 1000),      # review from a filtered deck
    ):
        db.execute("insert into revlog values (?, ?, ?, ?, ?, ?)", row)
    mod.mw.col.db = db

    assert mod._done_counts_by_deck_since(1000) == {10: (1, 2, 1)}


def test_queue_counts_respect_limits_and_exclude_suspended_and_buried(addon_module):
    mod = addon_module
    db = SQLiteDB()
    db.execute("create table cards (id integer primary key, did integer, odid integer, type integer, queue integer, due integer)")
    rows = [
        (1, 1, 0, 2, 2, 1),
        (2, 1, 0, 2, 2, 1),
        (3, 1, 0, 2, -1, 1),
        (4, 1, 0, 2, -2, 1),
        (5, 1, 0, 3, 1, 1),
        (6, 1, 0, 0, 0, 1),
        (7, 1, 0, 0, -3, 1),
    ]
    for row in rows:
        db.execute("insert into cards values (?, ?, ?, ?, ?, ?)", row)
    mod.mw.col.db = db
    node = DeckNode(1)
    node.review_count = 1
    node.learn_count = 1
    node.new_count = 2
    mod.mw.col.sched.day_cutoff = 86400

    assert mod._queue_counts_for_node(node) == (1, 1, 1, 1, 0, 1)


def test_buried_counter_excludes_cards_not_due_until_after_today(addon_module):
    mod = addon_module
    db = SQLiteDB()
    db.execute("create table cards (id integer primary key, did integer, odid integer, type integer, queue integer, due integer)")
    rows = [
        (1, 1, 0, 2, -2, 23147),       # overdue review
        (2, 1, 0, 2, -2, 23148),       # review due today
        (3, 1, 0, 2, -2, 23149),       # future review
        (4, 1, 0, 1, -3, 1999999000),  # intraday learning due before cutoff
        (5, 1, 0, 1, -3, 2000001000),  # intraday learning due tomorrow
        (6, 1, 0, 3, -3, 23148),       # day-learning due today
        (7, 1, 0, 3, -3, 23149),       # day-learning due tomorrow
        (8, 1, 0, 0, -2, 1),       # new cards use scheduler eligibility
    ]
    for row in rows:
        db.execute("insert into cards values (?, ?, ?, ?, ?, ?)", row)
    mod.mw.col.db = db
    mod.mw.col.sched.day_cutoff = 2000000000

    node = DeckNode(1)
    node.review_count = 3
    node.learn_count = 3
    node.new_count = 1

    assert mod._queue_counts_for_node(node) == (0, 0, 0, 2, 2, 1)


def test_nested_deck_counts_are_aggregated_once_at_the_selected_root(addon_module):
    mod = addon_module
    db = SQLiteDB()
    db.execute("create table cards (id integer primary key, did integer, odid integer, type integer, queue integer, due integer)")
    for row in ((1, 1, 0, 2, 2, 0), (2, 2, 0, 2, 2, 0), (3, 2, 0, 2, 2, 0)):
        db.execute("insert into cards values (?, ?, ?, ?, ?, ?)", row)
    mod.mw.col.db = db
    child = DeckNode(2)
    child.review_count = 2
    parent = DeckNode(1, [child])
    parent.review_count = 3

    mod.updateCountsForTree(parent, True, {2: (1, 0, 0)})

    assert mod.rawRemainCount[1] == 3
    assert mod.rawRemainCount[2] == 2
    assert mod.rawDoneCount[1] == 1
    assert mod.rawDoneCount[2] == 1


def test_revlog_windows_are_half_open(addon_module):
    mod = addon_module
    db = SQLiteDB()
    db.execute("create table revlog (id integer, cid integer, type integer, lastIvl integer, ease integer, time integer)")
    for row in (
        (1000, 1, 1, 10, 3, 1000),
        (1999, 2, 1, 10, 3, 1000),
        (2000, 3, 1, 10, 3, 1000),
    ):
        db.execute("insert into revlog values (?, ?, ?, ?, ?, ?)", row)
    mod.mw.col.db = db

    stats = mod._revlog_stats_between(1000, 2000, [])
    assert stats[0] == 2


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


def test_eta_uses_history_before_any_cards_today(addon_module):
    mod = addon_module

    setup_progress_update_with_history(
        mod,
        today_stats=(0, 0, 0, 0, 0, 0, 0),
        history_records=[
            {"day": 10, "cards": 100, "avg_seconds": 999.0},
            {"day": 9, "cards": 10, "avg_seconds": 12.0},
            {"day": 8, "cards": 5, "avg_seconds": 6.0},
        ],
    )

    assert round(mod._last_cards_per_minute, 3) == 6.0
    assert "ETA " in mod.progressBar.format()
    assert "ETA N/A" not in mod.progressBar.format()
    assert "previous averages" in mod.progressBar.toolTip()
    assert mod._latest_breakdown_rows[0]["eta"] != "N/A"


def test_eta_uses_history_until_five_cards_today(addon_module):
    mod = addon_module

    setup_progress_update_with_history(
        mod,
        today_stats=(4, 0, 0, 4, 0, 0, 400),
        history_records=[{"day": 9, "cards": 10, "avg_seconds": 10.0}],
    )

    assert round(mod._last_cards_per_minute, 3) == 6.0
    assert "previous averages" in mod.progressBar.toolTip()


def test_eta_uses_today_pace_after_five_cards(addon_module):
    mod = addon_module

    setup_progress_update_with_history(
        mod,
        today_stats=(5, 0, 0, 5, 0, 0, 100),
        history_records=[{"day": 9, "cards": 10, "avg_seconds": 10.0}],
    )

    assert round(mod._last_cards_per_minute, 3) == 3.0
    assert "today's pace" in mod.progressBar.toolTip()


def test_eta_stays_unavailable_without_usable_history_before_threshold(addon_module):
    mod = addon_module

    setup_progress_update_with_history(
        mod,
        today_stats=(4, 0, 0, 4, 0, 0, 80),
        history_records=[
            {"day": 9, "cards": 0, "avg_seconds": 10.0},
            {"day": 8, "cards": 10, "avg_seconds": 0.0},
        ],
    )

    assert mod._last_cards_per_minute is None
    assert "ETA N/A" in mod.progressBar.format()
    assert "enough review history" in mod.progressBar.toolTip()
    assert mod._latest_breakdown_rows[0]["eta"] == "N/A"


def test_simple_home_bar_does_not_show_seeded_eta(addon_module):
    mod = addon_module

    setup_progress_update_with_history(
        mod,
        today_stats=(0, 0, 0, 0, 0, 0, 0),
        history_records=[{"day": 9, "cards": 10, "avg_seconds": 10.0}],
        config={"mode": "simple", "display_location": "review_and_home"},
    )

    assert mod._last_cards_per_minute is not None
    assert "ETA" not in mod.progressBar.format()


def test_stats_zero_done_keeps_full_label_when_initial_width_is_unrealized(addon_module):
    mod = addon_module

    class Metrics:
        def horizontalAdvance(self, text):
            return len(text) * 10

    today_stats = (0, 0, 0, 0, 0, 0, 0)
    setup_progress_update_with_history(
        mod,
        today_stats=today_stats,
        history_records=[{"day": 9, "cards": 10, "avg_seconds": 10.0}],
        config={"mode": "stats", "display_location": "review_and_home"},
    )
    mod.mw.resize(3000, 900)
    mod.progressBar.resize(80, 20)
    mod.progressBar.fontMetrics = lambda: Metrics()
    mod.mw.col.db = SequenceDB(first_rows=[today_stats, None, today_stats])

    mod.updatePB()

    label = mod.progressBar.format()
    assert "done" in label
    assert "Again" in label
    assert "Retention" in label
    assert "ETA " in label
    assert not label.startswith("0/8")


def test_progress_label_falls_back_to_compact_and_minimal_text(addon_module):
    mod = addon_module

    class Metrics:
        def horizontalAdvance(self, text):
            return len(text) * 10

    class Bar:
        def __init__(self, width):
            self._width = width

        def width(self):
            return self._width

        def fontMetrics(self):
            return Metrics()

    full = "Full progress details that do not fit"
    compact = "2/10 (20%) | 8 left"
    minimal = "2/10 | 8 left"

    mod.progress_ui.progressBar = Bar(230)
    assert mod._fit_progress_bar_format(full, compact, minimal) == compact
    mod.progress_ui.progressBar = Bar(120)
    assert mod._fit_progress_bar_format(full, compact, minimal) == minimal
    mod.progress_ui.progressBar = Bar(500)
    assert mod._fit_progress_bar_format(full, compact, minimal) == full


def test_initial_advanced_label_uses_main_window_width_when_bar_width_is_stale(addon_module):
    mod = addon_module

    class Metrics:
        def horizontalAdvance(self, text):
            return len(text) * 10

    class Bar:
        def width(self):
            return 500

        def fontMetrics(self):
            return Metrics()

    full = "18 (7.89%) done  |  210 (92.11%) left  |  19.94 (16.52) s/card  |  16.67% Again  |  86.67% Retention"
    compact = "18/228 (8%)  |  210 left  |  ETA 11:00 AM"
    minimal = "18/228  |  210 left"

    mod._apply_config({"mode": "stats", "dock_area": "top"})
    mod.mw.resize(1600, 900)
    mod.progress_ui.progressBar = Bar()

    assert mod._fit_progress_bar_format(full, compact, minimal) == full


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


def test_malformed_history_is_safely_normalized(addon_module):
    mod = addon_module
    profile = {
        mod.HISTORY_PROGRESS_KEY: [
            "invalid",
            {"day": "bad"},
            {
                "day": "2",
                "cards": "bad",
                "avg_seconds": float("nan"),
                "again": 120,
                "retention": -5,
                "super_mature_retention": float("inf"),
            },
        ]
    }

    assert mod.history.read_history_records(profile) == [
        {
            "day": 2,
            "cards": 0,
            "avg_seconds": 0.0,
            "again": 100.0,
            "retention": 0.0,
            "super_mature_retention": 0.0,
        }
    ]


def test_history_replaces_same_day_and_enforces_retention(addon_module):
    mod = addon_module
    mod._apply_config({"history_days": 2})
    mod.mw.col.sched.day_cutoff = 4 * 86400
    profile = {
        mod.HISTORY_PROGRESS_KEY: [
            {"day": 3, "cards": 1},
            {"day": 2, "cards": 2},
            {"day": 1, "cards": 3},
        ]
    }

    mod.history.update_daily_history(
        profile,
        3,
        [1],
        lambda *_args: (9, 1, 1, 8, 0, 0, 18),
    )

    records = profile[mod.HISTORY_PROGRESS_KEY]
    assert [entry["day"] for entry in records] == [3, 2]
    assert records[0]["cards"] == 9


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


def test_segmented_progress_bar_rounding_fills_track_exactly():
    from addon.ui import progress_bar as progress_ui

    palette = QPalette()
    bar = progress_ui.SegmentedProgressBar(
        {"new": progress_ui.QColor("#111111"), "learning": progress_ui.QColor("#222222"), "review": progress_ui.QColor("#333333")}
    )
    bar.setSegmentData(1, 1, 1, 0.0)
    painter = QPainter()
    bar._draw_segments_horizontal(painter, QRect(0, 0, 10, 4), palette)

    segment_rects = [rect for rect, _brush in painter.filled[1:]]
    assert sum(rect.width() for rect in segment_rects) == 10


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

    assert "Click for full Deck Breakdown." in progress_ui.progressBar.toolTip()
    assert "Cards completed:" in progress_ui.progressBar.toolTip()

    event = QHelpEvent(pos=SimpleNamespace(x=lambda: 0))
    assert progress_ui.progress_tooltip_filter.eventFilter(progress_ui.progressBar, event) is True
    assert "Cards completed:" in QToolTip.last_text
    assert "Click for full Deck Breakdown." in QToolTip.last_text

    mod.setScrollingPB()
    assert "Click for full Deck Breakdown." in progress_ui.progressBar.toolTip()
    assert "Anki is updating the collection" in progress_ui.progressBar.toolTip()


def test_progress_bar_tooltips_can_be_disabled(addon_module):
    from addon.ui import progress_bar as progress_ui
    from tests.stubs import QHelpEvent

    mod = addon_module
    mod._apply_config({"tooltip_enabled": False})
    mod.initPB()
    progress_ui.update_progress_tooltips("Detailed metrics", "Completed", "Remaining", 0.5)

    assert progress_ui.progressBar.toolTip() == ""
    assert progress_ui.progress_tooltip_filter.eventFilter(progress_ui.progressBar, QHelpEvent()) is False


def _prepare_state_change_counts(mod) -> None:
    mod.mw.col.db = SequenceDB(first_rows=[None, None])
    mod.mw.col.sched._deck_tree = DeckNode(0, [DeckNode(1)])
    mod.mw.col.sched.day_cutoff = 1000
    mod.mw.col.decks.current = lambda: {"id": 1}


def test_display_location_default_hides_on_deck_browser(addon_module):
    mod = addon_module
    _prepare_state_change_counts(mod)

    mod._apply_config({})
    mod.afterStateChangeCallBack("deckBrowser", "review")

    assert mod.settings.display_location == "review"
    assert mod.progressBar is None
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


def test_display_location_review_only_hides_on_overview(addon_module):
    mod = addon_module
    _prepare_state_change_counts(mod)

    mod._apply_config({"display_location": "review"})
    mod.initPB()
    assert mod.progressBar is not None

    mod.afterStateChangeCallBack("overview", "deckBrowser")

    assert mod.progressBar is None


def test_display_location_review_only_shows_on_review(addon_module):
    mod = addon_module
    _prepare_state_change_counts(mod)

    mod._apply_config({"display_location": "review"})
    mod.afterStateChangeCallBack("deckBrowser", "review")
    assert mod.progressBar is None

    mod.afterStateChangeCallBack("review", "deckBrowser")

    assert mod.progressBar is not None
    assert mod.currDID == 1


def test_display_location_review_and_home_shows_on_overview(addon_module):
    mod = addon_module
    _prepare_state_change_counts(mod)

    mod._apply_config({"display_location": "review_and_home"})
    mod.afterStateChangeCallBack("overview", "deckBrowser")

    assert mod.progressBar is not None
    assert mod.currDID == 1


def test_display_location_apply_review_only_removes_existing_overview_bar(addon_module):
    mod = addon_module
    _prepare_state_change_counts(mod)

    mod._apply_config({"display_location": "review_and_home"})
    mod.afterStateChangeCallBack("overview", "deckBrowser")
    assert mod.progressBar is not None

    mod.mw.col.db = SequenceDB(first_rows=[(0, 0, 0, 0, 0, 0)])
    mod.addon_config.apply_config(mod.mw, {"display_location": "review"})
    mod._apply_settings(show_messages=False)

    assert mod.progressBar is None


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

    assert dialog._minimum_width == 680
    assert dialog._minimum_height == 560
    assert (dialog._width, dialog._height) == (680, 620)
    assert dialog._compact_layout_active is False
    assert dialog._header.objectName() == "settingsHeader"
    assert dialog._display_card.objectName() == "settingsCard"
    assert dialog._appearance_card.objectName() == "settingsCard"
    assert dialog._footer.objectName() == "settingsFooter"
    assert dialog._save_btn.objectName() == "primaryButton"
    assert dialog._donate_btn._width == 98
    assert dialog.mode_combo._items == [("Simple", "simple"), ("Advanced", "stats")]
    for control in (
        dialog.display_location_combo,
        dialog.mode_combo,
        dialog.dock_area_combo,
        dialog.show_smtr_cb,
        dialog.theme_combo,
        dialog.shortcut_field,
    ):
        assert control._width == 200
    assert dialog.display_location_combo.currentData() == "review"
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
    assert "assets/buy_me_a_coffee.png" in dialog._donate_btn.styleSheet()

    dialog._donate_btn.clicked()

    assert QDesktopServices.last_url.toString() == "https://www.buymeacoffee.com/caleblee78f"


def test_package_builder_includes_donate_asset():
    from scripts import package_addon

    packaged_paths = {path.relative_to(package_addon.ADDON_DIR).as_posix() for path in package_addon._iter_package_files()}

    assert "assets/buy_me_a_coffee.png" in packaged_paths
    assert "ui/theme.py" in packaged_paths


def test_package_builder_manifest_uses_canonical_addon_id(tmp_path):
    from scripts import package_addon

    output = package_addon.build_package(tmp_path / "progress_bar_time_left.ankiaddon", mod_time=123)

    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))

    assert manifest["package"] == "1511983907"
    assert manifest["min_point_version"] == 49
    assert manifest["max_point_version"] == 260500
    assert manifest["human_version"] == "1.1.1"


def test_minimum_advertised_anki_version_uses_modern_gui_hooks(addon_module):
    mod = addon_module

    assert "addHook(" not in Path(mod.__file__).read_text(encoding="utf-8")
    assert mod._on_state_did_change in mod.gui_hooks.state_did_change
    assert mod._on_reviewer_did_show_question in mod.gui_hooks.reviewer_did_show_question


def test_menu_bar_exposes_progress_bar_settings_under_caleb_addons(addon_module):
    mod = addon_module

    tools_menu = mod.mw.form.menuTools
    menu_bar = mod.mw.form.menubar

    assert tools_menu.actions == []
    assert tools_menu.submenus == []
    assert [action.text for action in menu_bar.actions] == ["Caleb M. Add-ons Settings"]
    assert len(menu_bar.submenus) == 1
    submenu = menu_bar.submenus[0]
    assert submenu.title() == "Caleb M. Add-ons Settings"
    assert submenu.objectName() == "caleb_m_addons_menu"
    assert [action.text for action in submenu.actions] == ["Progress Bar settings"]

    mod._install_settings_menu_action()

    assert tools_menu.actions == []
    assert len(menu_bar.submenus) == 1
    assert [action.text for action in submenu.actions] == ["Progress Bar settings"]


def test_progress_bar_settings_reuses_existing_caleb_addons_menu(addon_module):
    mod = addon_module
    first_menu_bar = mod.mw.form.menubar
    first_submenu = first_menu_bar.submenus[0]

    delattr(mod.mw, "_progress_bar_settings_action")
    delattr(mod.mw, "_caleb_m_addons_menu")

    mod._install_settings_menu_action()

    assert len(first_menu_bar.submenus) == 1
    assert first_menu_bar.submenus[0] is first_submenu
    assert [action.text for action in first_submenu.actions] == ["Progress Bar settings"]


def test_legacy_meta_shortcut_is_normalized_on_macos(mw, monkeypatch):
    from addon import config as addon_config

    monkeypatch.setattr(addon_config.sys, "platform", "darwin")
    addon_config.apply_config(mw, {"toggle_shortcut": "Meta+G"})

    assert addon_config.settings.toggle_shortcut == "Ctrl+G"
    assert addon_config.settings.raw_config["toggle_shortcut"] == "Ctrl+G"
    assert addon_config.validation_errors == []


def test_legacy_meta_shortcut_does_not_show_startup_tooltip(monkeypatch):
    import importlib
    import sys

    from tests.stubs import install_stubs

    install_stubs({"toggle_shortcut": "Meta+G"})
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

    assert mod.settings.toggle_shortcut == "Ctrl+G"
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
    from tests.stubs import QHeaderView, Qt

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
    assert mod._BREAKDOWN_DIALOG_MIN_WIDTH <= dialog._width <= mod._BREAKDOWN_DIALOG_MAX_WIDTH
    assert 250 <= dialog._tree._column_widths[0] <= 420
    assert 190 <= dialog._tree._column_widths[1] <= 250
    assert 190 <= dialog._tree._column_widths[2] <= 240
    assert 100 <= dialog._tree._column_widths[3] <= 130
    assert dialog._tree.header()._section_resize == {
        0: QHeaderView.ResizeMode.Stretch,
        1: QHeaderView.ResizeMode.Interactive,
        2: QHeaderView.ResizeMode.Interactive,
        3: QHeaderView.ResizeMode.Interactive,
    }
    assert dialog._toolbar.objectName() == "breakdownToolbar"
    assert dialog._tree._horizontal_scrollbar_policy == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert dialog._tree._vertical_scrollbar_policy == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert sum(dialog._tree._column_widths.values()) + mod._BREAKDOWN_DIALOG_FRAME_WIDTH == dialog._width
    assert dialog._height == mod._BREAKDOWN_DIALOG_DEFAULT_HEIGHT


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


def test_deck_breakdown_reused_dialog_rethemes_after_settings_apply(addon_module):
    mod = addon_module
    mod._apply_config({"theme": "dark"})
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

    assert "#0b1220" in dialog.styleSheet()
    assert dialog._summary_card._palette["summary_bg"] == "#0f172a"
    assert dialog._count_delegate._palette["card_bg"] == "#111827"

    settings_dialog = mod.ProgressBarConfigDialog(mod.mw)
    settings_dialog.theme_combo.setCurrentIndex(settings_dialog.theme_combo.findData("light"))
    settings_dialog._apply_without_closing()

    assert mod.mw.addonManager.config["theme"] == "light"
    assert mod._deck_breakdown_dialog is dialog
    assert "#f7f9fc" in dialog.styleSheet()
    assert "#0b1220" not in dialog.styleSheet()
    assert "#ffffff" in dialog._tree.styleSheet()
    assert dialog._summary_card._palette["summary_bg"] == "#ffffff"
    assert dialog._count_delegate._palette["card_bg"] == "#ffffff"
    assert dialog._tree._update_calls > 0


def test_deck_breakdown_delegate_repaints_parent_view_without_delegate_update(addon_module):
    mod = addon_module
    dialog = mod.DeckBreakdownDialog(mod.mw)
    delegate = dialog._count_delegate
    delegate.update = None

    before = getattr(dialog._tree, "_update_calls", 0)
    delegate.apply_theme(mod._ui_palette("dark"))

    assert dialog._tree._update_calls == before + 1
    assert delegate._palette["chip_new_bg"] == mod._ui_palette("dark")["chip_new_bg"]


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


def test_deck_breakdown_parent_rows_are_stronger_and_children_are_quieter(addon_module):
    mod = addon_module
    mod._apply_config({"theme": "light"})
    dialog = mod.DeckBreakdownDialog(mod.mw)
    dialog.update_rows(
        [
            {
                "name": "Parent",
                "actionable": (1, 0, 0),
                "buried": (0, 0, 0),
                "eta": "09:00 AM",
                "children": [
                    {
                        "name": "Child",
                        "actionable": (1, 0, 0),
                        "buried": (0, 0, 0),
                        "eta": "09:15 AM",
                        "children": [],
                    }
                ],
            }
        ]
    )

    parent = dialog._tree._items[0]
    child = parent.children[0]
    palette = mod._ui_palette("light")
    assert parent._fonts[0].bold() is True
    assert parent.data(0, mod._BREAKDOWN_CHILD_ROLE) is False
    assert child.data(0, mod._BREAKDOWN_CHILD_ROLE) is True
    assert child._foregrounds[0].color.name() == palette["secondary_text"]


def test_deck_breakdown_summary_chips_use_distinct_semantic_tints(addon_module):
    mod = addon_module
    mod._apply_config({"theme": "light"})
    dialog = mod.DeckBreakdownDialog(mod.mw)
    dialog.update_rows(
        [{"name": "Deck", "actionable": (1, 2, 3), "buried": (0, 0, 0), "eta": "09:00 AM", "children": []}]
    )

    palette = mod._ui_palette("light")
    assert palette["chip_new_bg"] in dialog._summary_card._chip_labels["new"].styleSheet()
    assert palette["chip_learning_bg"] in dialog._summary_card._chip_labels["learning"].styleSheet()
    assert palette["chip_review_bg"] in dialog._summary_card._chip_labels["review"].styleSheet()


def test_deck_breakdown_delegate_and_rows_retheme_in_place(addon_module):
    mod = addon_module
    mod._apply_config({"theme": "dark"})
    dialog = mod.DeckBreakdownDialog(mod.mw)
    dialog._hide_empty_cb.setChecked(False)
    dialog.update_rows(
        [
            {"name": "Active", "actionable": (2, 0, 0), "buried": (0, 0, 0), "eta": "09:00 AM", "children": []},
            {"name": "Empty", "actionable": (0, 0, 0), "buried": (0, 0, 0), "eta": "N/A", "children": []},
        ]
    )

    assert dialog._count_delegate._palette["chip_new_bg"] == mod._ui_palette("dark")["chip_new_bg"]

    mod._deck_breakdown_dialog = dialog
    mod._apply_config({"theme": "light"})

    palette = mod._ui_palette("light")
    active, empty = dialog._tree._items
    assert dialog._count_delegate._palette["chip_new_bg"] == palette["chip_new_bg"]
    assert dialog._summary_card._chip_labels["new"].styleSheet().count(palette["chip_new_bg"]) == 1
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


def test_same_day_progress_restoration_tolerates_and_repairs_malformed_data(addon_module):
    mod = addon_module
    mod._prepare_counts_for_new_profile()
    mod.mw.col.sched.day_cutoff = 2 * 86400
    mod.mw.pm.profile = {
        mod.PERSISTED_PROGRESS_KEY: {
            "day": "2",
            "data": {
                "1": {"done": "2.5", "total": "1", "raw_done": "2", "raw_total": "1"},
                "bad-deck": {"done": 5},
                "3": {"done": "not-a-number"},
                "4": {"done": float("nan"), "total": 4},
            },
        }
    }

    mod._ensure_persisted_progress_loaded()

    assert mod.doneCount == {1: 2.5}
    assert mod.totalCount == {1: 2.5}
    assert mod.rawDoneCount == {1: 2}
    assert mod.rawTotalCount == {1: 2}


def test_day_rollover_discards_previous_day_snapshot_and_counts(addon_module):
    mod = addon_module
    mod._prepare_counts_for_new_profile()
    mod.mw.col.sched.day_cutoff = 2 * 86400
    mod.mw.pm.profile = {
        mod.PERSISTED_PROGRESS_KEY: {
            "day": 2,
            "data": {"1": {"done": 1, "total": 5, "raw_done": 1, "raw_total": 5}},
        }
    }
    mod._ensure_persisted_progress_loaded()
    assert mod.totalCount == {1: 5.0}

    mod.mw.col.sched.day_cutoff = 3 * 86400
    mod._ensure_persisted_progress_loaded()

    assert mod.totalCount == {}
    assert mod.PERSISTED_PROGRESS_KEY not in mod.mw.pm.profile


def test_profile_close_restores_before_writing_so_snapshot_is_not_erased(addon_module):
    mod = addon_module
    mod._prepare_counts_for_new_profile()
    mod.mw.col.sched.day_cutoff = 2 * 86400
    mod.mw.col.db = SequenceDB(first_rows=[None])
    mod.mw.pm.profile = {
        mod.PERSISTED_PROGRESS_KEY: {
            "day": 2,
            "data": {"1": {"done": 1, "total": 5, "raw_done": 1, "raw_total": 5}},
        }
    }

    mod._on_profile_will_close()

    assert mod.mw.pm.profile[mod.PERSISTED_PROGRESS_KEY]["data"]["1"]["raw_total"] == 5
    assert mod.totalCount == {}


def test_profile_close_disposes_dialogs_and_progress_dock(addon_module):
    mod = addon_module
    mod._apply_config({})
    mod.mw.col.sched.day_cutoff = 86400
    mod.mw.col.db = SequenceDB(first_rows=[None])
    mod.initPB()
    deck_dialog = mod.DeckBreakdownDialog(mod.mw)
    history_dialog = mod.SessionHistoryDialog(mod.mw)
    mod._deck_breakdown_dialog = deck_dialog
    mod._session_history_dialog = history_dialog

    mod._on_profile_will_close()

    assert mod.progressBar is None
    assert mod.mw.docks == []
    assert deck_dialog._closed is True
    assert history_dialog._closed is True
    assert mod._deck_breakdown_dialog is None
    assert mod._session_history_dialog is None
    assert mod.currDID is None


def test_deleted_dialog_references_are_dropped_during_retheme(addon_module):
    mod = addon_module

    class DeletedDialog:
        def apply_theme(self):
            raise RuntimeError("wrapped C/C++ object has been deleted")

    mod._deck_breakdown_dialog = DeletedDialog()
    mod._session_history_dialog = DeletedDialog()

    mod._refresh_open_theme_surfaces()

    assert mod._deck_breakdown_dialog is None
    assert mod._session_history_dialog is None


def test_empty_queues_render_as_complete_without_division_errors(addon_module):
    mod = addon_module
    mod._apply_config({})
    mod.mw.col.sched.day_cutoff = 86400
    mod.mw.col.sched._deck_tree = DeckNode(0, [DeckNode(1)])
    mod.mw.col.db = SequenceDB(first_rows=[None, None, None, None])
    mod.initPB()

    mod.updateCountsForAllDecks(True)
    mod.updatePB()

    assert mod.progressBar._range == (0, 1)
    assert mod.progressBar._value == 1


def test_auto_theme_change_rethemes_open_surfaces(addon_module):
    from aqt.theme import theme_manager

    mod = addon_module
    mod._apply_config({"theme": "auto"})
    dialog = mod.DeckBreakdownDialog(mod.mw)
    mod._deck_breakdown_dialog = dialog
    theme_manager.night_mode = True

    mod._on_theme_did_change()

    assert dialog._palette["window_bg"] == mod._ui_palette("dark")["window_bg"]
