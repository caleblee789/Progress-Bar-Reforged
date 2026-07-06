from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ThemeTokens:
    name: str
    window_bg: str
    primary_text: str
    secondary_text: str
    muted_text: str
    helper_text: str
    section_header_text: str
    tab_border: str
    tab_selected_bg: str
    tab_selected_text: str
    card_bg: str
    card_border: str
    advanced_bg: str
    field_bg: str
    field_border: str
    focus_border: str
    focus_shadow: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    danger_bg: str
    danger_hover_bg: str
    danger_pressed_bg: str
    danger_border: str
    danger_text: str
    button_bg: str
    button_hover_bg: str
    button_pressed_bg: str
    button_border: str
    button_text: str
    disabled_text: str
    disabled_bg: str
    checkbox_text: str
    checkbox_indicator_bg: str
    summary_bg: str
    summary_border: str
    summary_title_text: str
    summary_text: str
    chip_border: str
    chip_muted_bg: str
    chip_muted_text: str
    chip_new_bg: str
    chip_new_border: str
    chip_new_text: str
    chip_learning_bg: str
    chip_learning_border: str
    chip_learning_text: str
    chip_review_bg: str
    chip_review_border: str
    chip_review_text: str
    segment_track: str
    segment_empty: str
    segment_new: str
    segment_learning: str
    segment_review: str
    table_alt_bg: str
    table_selection_bg: str
    table_selection_text: str
    table_hover_bg: str
    muted_row_text: str
    eta_muted_text: str
    row_divider: str
    scrollbar_bg: str
    scrollbar_handle: str
    scrollbar_handle_hover: str
    tooltip_bg: str
    tooltip_border: str
    tooltip_text: str
    chart_cards: str
    chart_again: str
    chart_retention: str

    def as_palette(self) -> Dict[str, str]:
        return {
            key: value
            for key, value in self.__dict__.items()
            if key != "name"
        }


DARK = ThemeTokens(
    name="dark",
    window_bg="#0b1220",
    primary_text="#e5e7eb",
    secondary_text="#cbd5e1",
    muted_text="#9ca3af",
    helper_text="#a5b2c5",
    section_header_text="#e5e7eb",
    tab_border="#5b6b82",
    tab_selected_bg="#111827",
    tab_selected_text="#e5e7eb",
    card_bg="#111827",
    card_border="#5b6b82",
    advanced_bg="#0f172a",
    field_bg="#0f172a",
    field_border="#5b6b82",
    focus_border="#60a5fa",
    focus_shadow="0 0 0 2px rgba(96, 165, 250, 0.28)",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    accent_pressed="#1e40af",
    accent_text="#ffffff",
    danger_bg="#32171b",
    danger_hover_bg="#451b21",
    danger_pressed_bg="#541d25",
    danger_border="#fca5a5",
    danger_text="#fca5a5",
    button_bg="#111827",
    button_hover_bg="#1f2937",
    button_pressed_bg="#0f172a",
    button_border="#5b6b82",
    button_text="#e5e7eb",
    disabled_text="#94a3b8",
    disabled_bg="#182234",
    checkbox_text="#e5e7eb",
    checkbox_indicator_bg="#0f172a",
    summary_bg="#0f172a",
    summary_border="#5b6b82",
    summary_title_text="#f8fafc",
    summary_text="#cbd5e1",
    chip_border="#718096",
    chip_muted_bg="rgba(100, 116, 139, 0.12)",
    chip_muted_text="#94a3b8",
    chip_new_bg="#123342",
    chip_new_border="#378ba5",
    chip_new_text="#67d7ee",
    chip_learning_bg="#382b12",
    chip_learning_border="#a77d31",
    chip_learning_text="#f4bd55",
    chip_review_bg="#15351f",
    chip_review_border="#41965a",
    chip_review_text="#6fd28c",
    segment_track="#263449",
    segment_empty="#718096",
    segment_new="#378ba5",
    segment_learning="#aa7926",
    segment_review="#41965a",
    table_alt_bg="rgba(255, 255, 255, 0.03)",
    table_selection_bg="rgba(96, 165, 250, 0.20)",
    table_selection_text="#f8fafc",
    table_hover_bg="rgba(96, 165, 250, 0.10)",
    muted_row_text="#94a3b8",
    eta_muted_text="#94a3b8",
    row_divider="#5b6b82",
    scrollbar_bg="#0f172a",
    scrollbar_handle="#5b6b82",
    scrollbar_handle_hover="#718096",
    tooltip_bg="#1e293b",
    tooltip_border="#718096",
    tooltip_text="#f8fafc",
    chart_cards="#60a5fa",
    chart_again="#f87171",
    chart_retention="#4ade80",
)


LIGHT = ThemeTokens(
    name="light",
    window_bg="#f7f9fc",
    primary_text="#1f2937",
    secondary_text="#3f4a59",
    muted_text="#667085",
    helper_text="#5f6c7b",
    section_header_text="#1f2937",
    tab_border="#7c8ba1",
    tab_selected_bg="#f5f7fb",
    tab_selected_text="#1f2937",
    card_bg="#ffffff",
    card_border="#7c8ba1",
    advanced_bg="#f7f9fb",
    field_bg="#ffffff",
    field_border="#7c8ba1",
    focus_border="#5b8def",
    focus_shadow="0 0 0 2px rgba(91, 141, 239, 0.18)",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    accent_pressed="#1e40af",
    accent_text="#ffffff",
    danger_bg="#fff1f2",
    danger_hover_bg="#ffe4e6",
    danger_pressed_bg="#fecdd3",
    danger_border="#b42318",
    danger_text="#b42318",
    button_bg="#f5f7fb",
    button_hover_bg="#eef2ff",
    button_pressed_bg="#e7edf8",
    button_border="#7c8ba1",
    button_text="#1f2937",
    disabled_text="#596579",
    disabled_bg="#eef2f7",
    checkbox_text="#2d2f36",
    checkbox_indicator_bg="#ffffff",
    summary_bg="#ffffff",
    summary_border="#7c8ba1",
    summary_title_text="#111827",
    summary_text="#475467",
    chip_border="#748399",
    chip_muted_bg="#f1f3f5",
    chip_muted_text="#5f6c7b",
    chip_new_bg="#ecfeff",
    chip_new_border="#3b91a5",
    chip_new_text="#0e7490",
    chip_learning_bg="#fffbeb",
    chip_learning_border="#b98229",
    chip_learning_text="#a16207",
    chip_review_bg="#f0fdf4",
    chip_review_border="#3c985b",
    chip_review_text="#15803d",
    segment_track="#e7edf3",
    segment_empty="#748399",
    segment_new="#378ba5",
    segment_learning="#aa7926",
    segment_review="#41965a",
    table_alt_bg="#f5f8fc",
    table_selection_bg="#dbeafe",
    table_selection_text="#111827",
    table_hover_bg="#eff6ff",
    muted_row_text="#667085",
    eta_muted_text="#667085",
    row_divider="#7c8ba1",
    scrollbar_bg="#eef2f7",
    scrollbar_handle="#7c8ba1",
    scrollbar_handle_hover="#667085",
    tooltip_bg="#1f2937",
    tooltip_border="#9ca3af",
    tooltip_text="#f9fafb",
    chart_cards="#2563eb",
    chart_again="#dc2626",
    chart_retention="#15803d",
)


def resolve_theme_tokens(theme: Optional[str] = None) -> ThemeTokens:
    addon_config = _addon_config()
    mode = addon_config.resolve_theme_mode(theme or _current_theme_choice())
    return DARK if mode == "dark" else LIGHT


def ui_palette(theme: Optional[str] = None) -> Dict[str, str]:
    return resolve_theme_tokens(theme).as_palette()


def _current_theme_choice() -> str:
    addon_config = _addon_config()
    current_settings = getattr(addon_config, "settings", None)
    if current_settings is not None:
        return getattr(current_settings, "theme", "auto")
    return "auto"


def _addon_config():
    from .. import config as addon_config

    return addon_config


def base_dialog_qss(tokens: ThemeTokens) -> str:
    return f"""
        QDialog {{
            background: {tokens.window_bg};
            color: {tokens.primary_text};
        }}
        QLabel {{
            color: {tokens.primary_text};
        }}
        QToolTip {{
            background: {tokens.tooltip_bg};
            color: {tokens.tooltip_text};
            border: 1px solid {tokens.tooltip_border};
            border-radius: 4px;
            padding: 4px 6px;
        }}
        QCheckBox {{
            color: {tokens.checkbox_text};
            spacing: 6px;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1px solid {tokens.button_border};
            background: {tokens.checkbox_indicator_bg};
        }}
        QCheckBox::indicator:checked {{
            background: {tokens.accent};
            border-color: {tokens.accent};
        }}
        QCheckBox::indicator:checked:hover {{
            background: {tokens.accent_hover};
            border-color: {tokens.accent_hover};
        }}
        QPushButton, QToolButton {{
            padding: 6px 10px;
            border: 1px solid {tokens.button_border};
            border-radius: 5px;
            background: {tokens.button_bg};
            color: {tokens.button_text};
            min-height: 20px;
        }}
        QPushButton:hover, QToolButton:hover {{
            background: {tokens.button_hover_bg};
            border-color: {tokens.focus_border};
        }}
        QPushButton:pressed, QToolButton:pressed {{
            background: {tokens.button_pressed_bg};
        }}
        QPushButton:disabled, QToolButton:disabled {{
            background: {tokens.disabled_bg};
            color: {tokens.disabled_text};
            border-color: {tokens.button_border};
        }}
        QPushButton:focus, QToolButton:focus {{
            border-color: {tokens.focus_border};
        }}
    """


def field_qss(tokens: ThemeTokens, selector: str = "QComboBox") -> str:
    return f"""
        {selector} {{
            padding: 6px 8px;
            border: 1px solid {tokens.field_border};
            border-radius: 5px;
            background: {tokens.field_bg};
            color: {tokens.primary_text};
            min-height: 20px;
        }}
        {selector}:hover, {selector}:focus {{
            background: {tokens.field_bg};
            border-color: {tokens.focus_border};
            color: {tokens.primary_text};
        }}
    """


def combo_qss(tokens: ThemeTokens) -> str:
    return field_qss(tokens, "QComboBox") + f"""
        QComboBox QAbstractItemView {{
            background: {tokens.card_bg};
            color: {tokens.primary_text};
            border: 1px solid {tokens.field_border};
            selection-background-color: {tokens.table_selection_bg};
            selection-color: {tokens.table_selection_text};
            outline: 0;
        }}
    """


def shortcut_qss(tokens: ThemeTokens) -> str:
    return field_qss(tokens, "QKeySequenceEdit#shortcutRecorder") + f"""
        QKeySequenceEdit#shortcutRecorder,
        QKeySequenceEdit#shortcutRecorder:hover,
        QKeySequenceEdit#shortcutRecorder:focus,
        QKeySequenceEdit#shortcutRecorder:active,
        QKeySequenceEdit#shortcutRecorder:enabled {{
            background-color: {tokens.field_bg};
            background: {tokens.field_bg};
            color: {tokens.primary_text};
            selection-background-color: {tokens.table_selection_bg};
            selection-color: {tokens.table_selection_text};
        }}
        QKeySequenceEdit#shortcutRecorder QLineEdit {{
            background-color: {tokens.field_bg};
            background: {tokens.field_bg};
            color: {tokens.primary_text};
            border: 1px solid {tokens.field_border};
            border-radius: 5px;
            padding: 5px 7px;
            selection-background-color: {tokens.table_selection_bg};
            selection-color: {tokens.table_selection_text};
        }}
        QKeySequenceEdit#shortcutRecorder:hover QLineEdit,
        QKeySequenceEdit#shortcutRecorder:focus QLineEdit,
        QKeySequenceEdit#shortcutRecorder:active QLineEdit {{
            background-color: {tokens.field_bg};
            background: {tokens.field_bg};
            border-color: {tokens.focus_border};
            color: {tokens.primary_text};
        }}
        QKeySequenceEdit#shortcutRecorder QToolButton,
        QKeySequenceEdit#shortcutRecorder QAbstractButton {{
            background: transparent;
            color: {tokens.muted_text};
            border: none;
            border-radius: 4px;
            padding: 0 4px;
            min-height: 16px;
        }}
        QKeySequenceEdit#shortcutRecorder QToolButton:hover,
        QKeySequenceEdit#shortcutRecorder QAbstractButton:hover {{
            background: {tokens.button_hover_bg};
            color: {tokens.primary_text};
        }}
    """


def scrollbar_qss(tokens: ThemeTokens) -> str:
    return f"""
        QScrollBar:vertical {{
            background: {tokens.scrollbar_bg};
            width: 12px;
            margin: 0px;
            border-radius: 6px;
        }}
        QScrollBar::handle:vertical {{
            background: {tokens.scrollbar_handle};
            border-radius: 6px;
            min-height: 32px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {tokens.scrollbar_handle_hover};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
            background: transparent;
            border: none;
        }}
        QScrollBar:horizontal {{
            background: {tokens.scrollbar_bg};
            height: 12px;
            margin: 0px;
            border-radius: 6px;
        }}
        QScrollBar::handle:horizontal {{
            background: {tokens.scrollbar_handle};
            border-radius: 6px;
            min-width: 32px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {tokens.scrollbar_handle_hover};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
            background: transparent;
            border: none;
        }}
    """


def deck_breakdown_qss(tokens: ThemeTokens) -> str:
    return base_dialog_qss(tokens) + combo_qss(tokens) + scrollbar_qss(tokens) + f"""
        QFrame#dashboardSummaryCard {{
            background: {tokens.summary_bg};
            border: 1px solid {tokens.summary_border};
            border-radius: 8px;
        }}
        QFrame#breakdownToolbar {{
            background: {tokens.advanced_bg};
            border: 1px solid {tokens.card_border};
            border-radius: 7px;
        }}
        QLabel#dashboardTitle {{
            color: {tokens.summary_title_text};
            font-size: 15px;
            font-weight: 700;
        }}
        QLabel#dashboardMain {{
            color: {tokens.summary_text};
            font-size: 12px;
        }}
        QTreeWidget {{
            background: {tokens.card_bg};
            alternate-background-color: {tokens.table_alt_bg};
            color: {tokens.primary_text};
            border: 1px solid {tokens.card_border};
            border-radius: 6px;
        }}
        QTreeWidget QAbstractScrollArea::corner {{
            background: {tokens.card_bg};
            border: none;
        }}
        QTreeWidget::item {{
            border: none;
            padding: 5px 6px;
        }}
        QTreeWidget::item:hover {{
            background: {tokens.table_hover_bg};
        }}
        QTreeWidget::item:selected {{
            background: {tokens.table_selection_bg};
            color: {tokens.table_selection_text};
        }}
        QTreeWidget::item:selected:!active {{
            background: {tokens.table_selection_bg};
            color: {tokens.table_selection_text};
        }}
        QHeaderView {{
            background: {tokens.tab_selected_bg};
            color: {tokens.tab_selected_text};
        }}
        QHeaderView::section {{
            background: {tokens.tab_selected_bg};
            color: {tokens.tab_selected_text};
            border: 1px solid {tokens.tab_border};
            padding: 5px 8px;
            font-weight: 700;
        }}
    """


def history_dialog_qss(tokens: ThemeTokens) -> str:
    return base_dialog_qss(tokens) + combo_qss(tokens) + scrollbar_qss(tokens) + f"""
        QLabel#historyDescription {{
            color: {tokens.secondary_text};
        }}
        QLabel#historyRangeLabel {{
            color: {tokens.muted_text};
        }}
        QTableWidget {{
            background: {tokens.card_bg};
            alternate-background-color: {tokens.table_alt_bg};
            color: {tokens.primary_text};
            border: 1px solid {tokens.card_border};
            border-radius: 6px;
            gridline-color: {tokens.row_divider};
            selection-background-color: {tokens.table_selection_bg};
            selection-color: {tokens.table_selection_text};
        }}
        QTableWidget::item {{
            padding: 5px 7px;
        }}
        QTableWidget::item:hover {{
            background: {tokens.table_hover_bg};
        }}
        QTableWidget::item:selected,
        QTableWidget::item:selected:!active {{
            background: {tokens.table_selection_bg};
            color: {tokens.table_selection_text};
        }}
        QHeaderView {{
            background: {tokens.tab_selected_bg};
            color: {tokens.tab_selected_text};
        }}
        QHeaderView::section {{
            background: {tokens.tab_selected_bg};
            color: {tokens.tab_selected_text};
            border: 1px solid {tokens.tab_border};
            padding: 5px 8px;
            font-weight: 700;
        }}
        QTableCornerButton::section {{
            background: {tokens.tab_selected_bg};
            border: 1px solid {tokens.tab_border};
        }}
        QPushButton#destructiveButton {{
            background: {tokens.danger_bg};
            color: {tokens.danger_text};
            border-color: {tokens.danger_border};
            font-weight: 600;
        }}
        QPushButton#destructiveButton:hover {{
            background: {tokens.danger_hover_bg};
            border-color: {tokens.danger_text};
        }}
        QPushButton#destructiveButton:pressed {{
            background: {tokens.danger_pressed_bg};
            border-color: {tokens.danger_text};
        }}
    """


def settings_dialog_qss(tokens: ThemeTokens) -> str:
    return base_dialog_qss(tokens) + combo_qss(tokens) + shortcut_qss(tokens) + scrollbar_qss(tokens) + f"""
        QFrame#settingsHeader {{
            background: {tokens.table_selection_bg};
            border: 1px solid {tokens.card_border};
            border-radius: 8px;
        }}
        QFrame#settingsCard {{
            background: {tokens.card_bg};
            border: 1px solid {tokens.card_border};
            border-radius: 8px;
        }}
        QLabel#settingsSectionTitle {{
            color: {tokens.section_header_text};
            font-size: 12px;
            font-weight: 700;
            padding: 0 12px 5px 12px;
        }}
        QFrame#settingsFooter {{
            border: none;
            border-top: 1px solid {tokens.card_border};
            background: transparent;
        }}
        QLabel#dirtyBadge {{
            color: {tokens.muted_text};
            font-weight: 600;
        }}
        QToolButton#buyMeACoffeeButton {{
            border: none;
            background: transparent;
            padding: 0px;
        }}
        QToolButton#buyMeACoffeeButton:hover {{
            border: none;
            background: transparent;
        }}
        QPushButton#primaryButton {{
            background: {tokens.accent};
            color: {tokens.accent_text};
            border-color: {tokens.accent};
            font-weight: 600;
        }}
        QPushButton#primaryButton:hover {{
            background: {tokens.accent_hover};
            border-color: {tokens.accent_hover};
        }}
        QPushButton#primaryButton:pressed {{
            background: {tokens.accent_pressed};
            border-color: {tokens.accent_pressed};
        }}
        QPushButton#primaryButton:disabled {{
            background: {tokens.disabled_bg};
            color: {tokens.disabled_text};
            border-color: {tokens.button_border};
        }}
        QToolButton#shortcutResetButton {{
            padding: 6px 10px;
            border: 1px solid {tokens.button_border};
            border-radius: 5px;
            background: {tokens.button_bg};
            color: {tokens.button_text};
            min-height: 20px;
        }}
        QToolButton#shortcutResetButton:hover {{
            background: {tokens.button_hover_bg};
            border-color: {tokens.focus_border};
        }}
    """
