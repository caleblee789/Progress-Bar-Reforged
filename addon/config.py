from __future__ import annotations

from dataclasses import dataclass
import sys
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from aqt.qt import QColor, QPalette, QStyle, QStyleFactory, Qt

from .nightmode import isnightmode

# Preserve the original configuration namespace for compatibility with existing installs.
CONFIG_KEY = "addon.reviewer_progress_bar"


def _coerce_bool(value: Any, default: bool) -> bool:
    """Convert config values that may be stored as strings or ints into booleans."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_dimension(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        if value <= 0:
            return ""
        return f"{int(value)}px"
    value_str = str(value).strip()
    if not value_str:
        return ""
    # Allow units supplied by the user, defaulting to px for digits
    if value_str[-2:].lower() in {"px", "pt", "em"} or value_str.endswith("%"):
        return value_str
    if value_str.isdigit():
        return f"{value_str}px"
    return value_str


def _to_qcolor(color_value: str) -> QColor:
    """Return a QColor from common CSS-like strings.

    Supports names (e.g. 'black'), hex, and rgba(r,g,b,a). If rgba alpha is
    provided as 0-1, it will be converted to 0-255 as Qt expects.
    """
    try:
        s = str(color_value).strip()
        lower = s.lower()
        if lower.startswith("rgba(") and s.endswith(")"):
            inner = s[s.find("(") + 1 : -1]
            parts = [p.strip() for p in inner.split(",")]
            if len(parts) == 4:
                r = int(float(parts[0]))
                g = int(float(parts[1]))
                b = int(float(parts[2]))
                a_raw = parts[3]
                a_f = float(a_raw)
                # Treat 0-1 as fractional alpha; otherwise assume 0-255
                a = int(round(a_f * 255)) if 0 <= a_f <= 1 else int(round(a_f))
                a = max(0, min(a, 255))
                return QColor(r, g, b, a)
        return QColor(s)
    except Exception:
        # Fall back to whatever Qt can parse
        return QColor(color_value)


@dataclass
class ThemeSettings:
    text: str
    background: str
    foreground: str
    border_radius: int


@dataclass
class WarningColors:
    text: QColor
    background: QColor
    foreground: QColor


@dataclass
class Settings:
    progress_bar_enabled: bool
    include_new: bool
    include_rev: bool
    include_lrn: bool
    include_new_after_revs: bool
    counting_basis: str
    count_scope: str
    force_forward: bool
    lrn_steps: int
    no_days: int
    use_system_timezone: bool
    tz: int
    show_percent: bool
    show_retention: bool
    show_super_mature_retention: bool
    show_again: bool
    show_number: bool
    show_yesterday: bool
    text_hierarchy_style: str
    label_style: str
    compact_separators: bool
    vertical_text_line_break: bool
    show_debug: bool
    show_progress_legend: bool
    legend_position: str
    daily_target_cards: int
    target_review_minutes: int
    pace_warnings_enabled: bool
    pacing_strategy: str
    show_eta_confidence: bool
    warning_hysteresis_percent: float
    warning_cooldown_seconds: int
    display_preset: str
    onboarding_completed: bool
    quick_setup_enabled: bool
    focus_mode: bool
    reduced_motion: bool
    animated_updates: bool
    show_segment_inline_labels: bool
    show_warning_badge: bool
    completion_celebration: bool
    responsive_breakpoints: bool
    warning_transition_animations: bool
    pinned_deck_views: List[str]
    auto_adjust_contrast: bool
    deck_profiles: Dict[str, Dict[str, float]]
    toggle_shortcut: str
    scrolling_bar_when_editing: bool
    invert_progress: bool
    orientation: Qt.Orientation
    dock_area: Qt.DockWidgetArea
    max_width: str
    restrict_size: str
    progress_bar_style: str
    progress_bar_qstyle: Optional[QStyle]
    stacked_segments: bool
    segment_colors: Dict[str, QColor]
    warnings_enabled: bool
    time_warning_minutes: int
    again_warning_percent: float
    retention_warning_percent: float
    warning_colors: WarningColors
    day_theme: ThemeSettings
    night_theme: ThemeSettings
    active_theme: ThemeSettings
    palette: QPalette
    warning_palette: QPalette
    default_stylesheet: str
    warning_stylesheet: str
    history_days: int
    raw_config: Dict[str, Any]


# Global settings state populated via reload_settings().
settings: Settings
settings = None  # type: ignore[assignment]
validation_errors: List[str] = []


def _validate_theme(
    overrides: Dict[str, Any],
    defaults: Dict[str, Any],
    path: str,
    errors: List[str],
) -> ThemeSettings:
    text = _validate_color_string(overrides.get("text"), defaults["text"], f"{path}.text", errors)
    background = _validate_color_string(overrides.get("background"), defaults["background"], f"{path}.background", errors)
    foreground = _validate_color_string(overrides.get("foreground"), defaults["foreground"], f"{path}.foreground", errors)
    border_radius = _coerce_int(overrides.get("border_radius"), defaults["border_radius"])
    if border_radius < 0:
        errors.append(f"{path}.border_radius must be >= 0; using {defaults['border_radius']}.")
        border_radius = defaults["border_radius"]
    return ThemeSettings(text=text, background=background, foreground=foreground, border_radius=border_radius)


def _color_or_default(
    value: Any,
    default: str,
    key: str,
    errors: List[str],
) -> QColor:
    if value in (None, ""):
        return _to_qcolor(default)

    color = _to_qcolor(value)
    if not color.isValid():
        errors.append(f"{key} had an invalid color; using {default}.")
        color = _to_qcolor(default)
    return color


def _validate_color_string(value: Any, default: str, key: str, errors: List[str]) -> str:
    candidate = str(value if value is not None else default)
    if not _to_qcolor(candidate).isValid():
        errors.append(f"{key} had an invalid color; using {default}.")
        return default
    return candidate


def _relative_luminance(color: QColor) -> float:
    def ch(v: int) -> float:
        x = v / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    try:
        r, g, b = color.red(), color.green(), color.blue()
    except Exception:
        try:
            name = color.name()
            if isinstance(name, str) and name.startswith("#") and len(name) >= 7:
                r = int(name[1:3], 16)
                g = int(name[3:5], 16)
                b = int(name[5:7], 16)
            else:
                return 1.0
        except Exception:
            return 1.0

    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast_ratio(foreground: QColor, background: QColor) -> float:
    l1 = _relative_luminance(foreground)
    l2 = _relative_luminance(background)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _ensure_contrast(text: QColor, background: QColor, minimum: float = 4.5) -> Tuple[QColor, float]:
    ratio = _contrast_ratio(text, background)
    if ratio >= minimum:
        return text, ratio

    if _relative_luminance(background) < 0.5:
        adjusted = QColor("#ffffff")
    else:
        adjusted = QColor("#111111")
    return adjusted, _contrast_ratio(adjusted, background)


def _resolve_qstyle(style_name: str) -> Optional[QStyle]:
    """Resolve a QStyle by name while tolerating platform-specific casing differences."""

    candidate = (style_name or "").strip()
    if not candidate:
        return None

    # Fast path for an exact style name.
    style = QStyleFactory.create(candidate)
    if style is not None:
        return style

    # Cross-platform fallback: style keys differ by platform and casing.
    try:
        keys = list(QStyleFactory.keys())
    except Exception:
        keys = []

    lowered = candidate.lower()
    for key in keys:
        if str(key).lower() == lowered:
            style = QStyleFactory.create(str(key))
            if style is not None:
                return style

    return None


def _build_palette(theme: ThemeSettings) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Base, _to_qcolor(theme.background))
    palette.setColor(QPalette.ColorRole.Highlight, _to_qcolor(theme.foreground))
    palette.setColor(QPalette.ColorRole.Button, _to_qcolor(theme.background))
    palette.setColor(QPalette.ColorRole.WindowText, _to_qcolor(theme.text))
    palette.setColor(QPalette.ColorRole.Window, _to_qcolor(theme.background))
    return palette


def load_settings(mw) -> Tuple[Settings, List[str]]:
    """Load, validate, and normalize add-on settings."""
    config_data = mw.addonManager.getConfig(CONFIG_KEY)
    if not isinstance(config_data, dict):
        config_data = {}

    errors: List[str] = []
    normalized: Dict[str, Any] = dict(config_data)

    def _bool(key: str, default: bool) -> bool:
        value_raw = config_data.get(key)
        value = _coerce_bool(value_raw, default)
        if isinstance(value_raw, str):
            lowered = value_raw.strip().lower()
            if lowered not in {"true", "1", "yes", "on", "false", "0", "no", "off"}:
                errors.append(f"{key} had an unrecognized boolean value; using {value}.")
        elif value_raw is not None and not isinstance(value_raw, (bool, int, float)):
            errors.append(f"{key} was invalid; using {default}.")
        normalized[key] = value
        return value

    def _int(key: str, default: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
        value_raw = config_data.get(key)
        try:
            if value_raw is None:
                raise ValueError
            value = int(value_raw)
            conversion_failed = False
        except (TypeError, ValueError):
            value = default
            conversion_failed = value_raw is not None
        if minimum is not None and value < minimum:
            errors.append(f"{key} below {minimum}; using {minimum}.")
            value = minimum
        if maximum is not None and value > maximum:
            errors.append(f"{key} above {maximum}; using {maximum}.")
            value = maximum
        normalized[key] = value
        if conversion_failed:
            errors.append(f"{key} was invalid; using {value}.")
        return value

    def _float(key: str, default: float, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
        value_raw = config_data.get(key)
        try:
            if value_raw is None:
                raise ValueError
            value = float(value_raw)
            conversion_failed = False
        except (TypeError, ValueError):
            value = default
            conversion_failed = value_raw is not None
        if minimum is not None and value < minimum:
            errors.append(f"{key} below {minimum}; clamping to {minimum}.")
            value = minimum
        if maximum is not None and value > maximum:
            errors.append(f"{key} above {maximum}; clamping to {maximum}.")
            value = maximum
        normalized[key] = value
        if conversion_failed:
            errors.append(f"{key} was invalid; using {value}.")
        return value

    progress_bar_enabled = _bool("progress_bar_enabled", True)
    include_new = _bool("include_new", True)
    include_rev = _bool("include_rev", True)
    include_lrn = _bool("include_lrn", True)
    include_new_after_revs = _bool("include_new_after_revs", False)
    force_forward = _bool("force_forward", False)
    counting_basis_raw = str(config_data.get("counting_basis", "answered")).lower()
    if counting_basis_raw not in {"answered", "seen"}:
        errors.append(f"counting_basis {counting_basis_raw!r} invalid; using answered.")
        counting_basis_raw = "answered"
    normalized["counting_basis"] = counting_basis_raw

    count_scope_raw = str(config_data.get("count_scope", "per_deck")).lower()
    if count_scope_raw not in {"per_deck", "global"}:
        errors.append(f"count_scope {count_scope_raw!r} invalid; using per_deck.")
        count_scope_raw = "per_deck"
    normalized["count_scope"] = count_scope_raw

    scrolling_bar_when_editing = _bool("scrolling_bar_when_editing", True)
    invert_progress = _bool("invert_progress", False)
    stacked_segments = _bool("stacked_segments", False)
    warnings_enabled = _bool("warnings_enabled", False)
    pace_warnings_enabled = _bool("pace_warnings_enabled", True)
    show_eta_confidence = _bool("show_eta_confidence", True)
    auto_adjust_contrast = _bool("auto_adjust_contrast", True)
    onboarding_completed = _bool("onboarding_completed", False)
    quick_setup_enabled = _bool("quick_setup_enabled", True)
    focus_mode = _bool("focus_mode", False)
    reduced_motion = _bool("reduced_motion", False)
    animated_updates = _bool("animated_updates", True)
    show_segment_inline_labels = _bool("show_segment_inline_labels", False)
    show_warning_badge = _bool("show_warning_badge", True)
    completion_celebration = _bool("completion_celebration", True)
    responsive_breakpoints = _bool("responsive_breakpoints", True)
    warning_transition_animations = _bool("warning_transition_animations", True)

    pinned_views_raw = config_data.get("pinned_deck_views", [])
    pinned_deck_views: List[str] = []
    if isinstance(pinned_views_raw, list):
        pinned_deck_views = [str(item) for item in pinned_views_raw if str(item).strip()]
    elif pinned_views_raw not in (None, ""):
        errors.append("pinned_deck_views must be a list; using [].")
    normalized["pinned_deck_views"] = pinned_deck_views

    pacing_strategy = str(config_data.get("pacing_strategy", "ewma")).lower()
    if pacing_strategy not in {"average", "ewma", "trimmed", "median", "segmented"}:
        errors.append(f"pacing_strategy {pacing_strategy!r} invalid; using ewma.")
        pacing_strategy = "ewma"
    normalized["pacing_strategy"] = pacing_strategy

    display_preset = str(config_data.get("display_preset", "compact")).lower()
    if display_preset not in {"minimal", "compact", "expanded"}:
        errors.append(f"display_preset {display_preset!r} invalid; using compact.")
        display_preset = "compact"
    normalized["display_preset"] = display_preset

    warning_hysteresis_percent = _float("warning_hysteresis_percent", 2.0, minimum=0.0, maximum=20.0)
    warning_cooldown_seconds = _int("warning_cooldown_seconds", 15, minimum=0, maximum=600)

    deck_profiles_raw = config_data.get("deck_profiles", {})
    deck_profiles: Dict[str, Dict[str, float]] = {}
    if isinstance(deck_profiles_raw, dict):
        for key, profile in deck_profiles_raw.items():
            if not isinstance(profile, dict):
                continue
            did = str(key)
            deck_profiles[did] = {
                "new_weight": _coerce_float(profile.get("new_weight"), 1.0),
                "lrn_weight": _coerce_float(profile.get("lrn_weight"), 1.0),
                "rev_weight": _coerce_float(profile.get("rev_weight"), 1.0),
                "expected_seconds": _coerce_float(profile.get("expected_seconds"), 0.0),
            }
    else:
        errors.append("deck_profiles must be an object; using defaults.")
    normalized["deck_profiles"] = deck_profiles

    orientation_map = {
        "horizontal": Qt.Orientation.Horizontal,
        "vertical": Qt.Orientation.Vertical,
    }
    orientation_raw = str(config_data.get("orientation", "horizontal")).lower()
    orientation = orientation_map.get(orientation_raw)
    if orientation is None:
        errors.append(f"orientation {orientation_raw!r} invalid; using horizontal.")
        orientation = Qt.Orientation.Horizontal
        normalized["orientation"] = "horizontal"
    else:
        normalized["orientation"] = orientation_raw

    dock_area_map = {
        "top": Qt.DockWidgetArea.TopDockWidgetArea,
        "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
        "right": Qt.DockWidgetArea.RightDockWidgetArea,
        "left": Qt.DockWidgetArea.LeftDockWidgetArea,
    }
    dock_area_raw = str(config_data.get("dock_area", "top")).lower()
    dock_area = dock_area_map.get(dock_area_raw)
    if dock_area is None:
        errors.append(f"dock_area {dock_area_raw!r} invalid; using top.")
        dock_area = Qt.DockWidgetArea.TopDockWidgetArea
        normalized["dock_area"] = "top"
    else:
        normalized["dock_area"] = dock_area_raw

    max_width = _normalize_dimension(config_data.get("max_width", ""))
    normalized["max_width"] = max_width

    progress_bar_style = str(config_data.get("progress_bar_style", "")).strip()
    normalized["progress_bar_style"] = progress_bar_style
    progress_bar_qstyle: Optional[QStyle] = None
    if progress_bar_style:
        progress_bar_qstyle = _resolve_qstyle(progress_bar_style)
        if progress_bar_qstyle is None:
            errors.append(f"progress_bar_style {progress_bar_style!r} not available; using default theme style.")
            progress_bar_style = ""
            normalized["progress_bar_style"] = ""

    default_shortcut = "Meta+G" if sys.platform == "darwin" else "Ctrl+G"
    toggle_shortcut = str(config_data.get("toggle_shortcut", default_shortcut)).strip() or default_shortcut
    if sys.platform == "darwin" and toggle_shortcut.lower() == "ctrl+g":
        errors.append("toggle_shortcut Ctrl+G is legacy on macOS; using Meta+G.")
        toggle_shortcut = "Meta+G"
    normalized["toggle_shortcut"] = toggle_shortcut

    lrn_steps = _int("lrn_steps", 2, minimum=1)
    no_days = _int("no_days", 7, minimum=1)
    use_system_timezone = _bool("use_system_timezone", True)
    tz = _int("tz", 0, minimum=-12, maximum=14)

    show_percent = _bool("show_percent", True)
    show_retention = _bool("show_retention", True)
    show_super_mature_retention = _bool("show_super_mature_retention", True)
    show_again = _bool("show_again", True)
    show_number = _bool("show_number", True)
    show_yesterday = _bool("show_yesterday", True)
    text_hierarchy_style = str(config_data.get("text_hierarchy_style", "compact")).lower()
    if text_hierarchy_style not in {"compact", "two_line"}:
        errors.append(f"text_hierarchy_style {text_hierarchy_style!r} invalid; using compact.")
        text_hierarchy_style = "compact"
    normalized["text_hierarchy_style"] = text_hierarchy_style
    label_style = str(config_data.get("label_style", "detailed")).lower()
    if label_style not in {"compact", "detailed"}:
        errors.append(f"label_style {label_style!r} invalid; using detailed.")
        label_style = "detailed"
    normalized["label_style"] = label_style
    compact_separators = _bool("compact_separators", True)
    vertical_text_line_break = _bool("vertical_text_line_break", True)
    show_debug = _bool("show_debug", False)
    show_progress_legend = _bool("show_progress_legend", False)

    legend_position_raw = str(config_data.get("legend_position", "below")).lower()
    if legend_position_raw not in {"above", "below", "left", "right"}:
        errors.append(f"legend_position {legend_position_raw!r} invalid; using below.")
        legend_position_raw = "below"
    normalized["legend_position"] = legend_position_raw

    daily_target_cards = _int("daily_target_cards", 0, minimum=0)
    target_review_minutes = _int("target_review_minutes", 0, minimum=0)

    time_warning_minutes = _int("time_warning_minutes", 45, minimum=0)
    again_warning_percent = _float("again_warning_percent", 15.0, minimum=0.0, maximum=100.0)
    retention_warning_percent = _float("retention_warning_percent", 80.0, minimum=0.0, maximum=100.0)

    history_days = _int("history_days", 30, minimum=0)

    default_day = {
        "text": "black",
        "background": "rgba(228, 228, 228, 1)",
        "foreground": "#3399cc",
        "border_radius": 0,
    }
    default_night = {
        "text": "aliceblue",
        "background": "rgba(39, 40, 40, 1)",
        "foreground": "#3399cc",
        "border_radius": 0,
    }

    appearance = config_data.get("appearance", {})
    day_overrides = appearance.get("day", {}) if isinstance(appearance, dict) else {}
    night_overrides = appearance.get("night", {}) if isinstance(appearance, dict) else {}
    if not isinstance(day_overrides, dict):
        errors.append("appearance.day must be an object; using defaults.")
        day_overrides = {}
    if not isinstance(night_overrides, dict):
        errors.append("appearance.night must be an object; using defaults.")
        night_overrides = {}

    day_theme = _validate_theme(day_overrides, default_day, "appearance.day", errors)
    night_theme = _validate_theme(night_overrides, default_night, "appearance.night", errors)

    active_theme = night_theme if isnightmode() else day_theme

    hierarchy_font_weight = "bold" if text_hierarchy_style == "two_line" else ("600" if isnightmode() else "normal")
    hierarchy_font_size = "11px" if (text_hierarchy_style == "two_line" and orientation == Qt.Orientation.Vertical) else "12px"

    active_text = _to_qcolor(active_theme.text)
    active_bg = _to_qcolor(active_theme.background)
    contrast_ratio = _contrast_ratio(active_text, active_bg)
    if contrast_ratio < 4.5:
        if auto_adjust_contrast:
            adjusted_text, new_ratio = _ensure_contrast(active_text, active_bg)
            errors.append(f"appearance contrast too low ({contrast_ratio:.2f}); adjusted text color to {adjusted_text.name()} ({new_ratio:.2f}).")
            active_theme = ThemeSettings(
                text=adjusted_text.name(),
                background=active_theme.background,
                foreground=active_theme.foreground,
                border_radius=active_theme.border_radius,
            )
        else:
            errors.append(f"appearance contrast is low ({contrast_ratio:.2f}); text may be hard to read.")

    segment_color_config = config_data.get("segment_colors", {}) if isinstance(config_data.get("segment_colors"), dict) else {}
    if not isinstance(segment_color_config, dict):
        errors.append("segment_colors must be an object; using defaults.")
        segment_color_config = {}
    default_segment_colors = {"new": "#4aa3df", "learning": "#f0c674", "review": "#50c878"}
    segment_colors = {
        "new": _color_or_default(segment_color_config.get("new"), default_segment_colors["new"], "segment_colors.new", errors),
        "learning": _color_or_default(segment_color_config.get("learning"), default_segment_colors["learning"], "segment_colors.learning", errors),
        "review": _color_or_default(segment_color_config.get("review"), default_segment_colors["review"], "segment_colors.review", errors),
    }
    normalized["segment_colors"] = {
        "new": segment_colors["new"].name(),
        "learning": segment_colors["learning"].name(),
        "review": segment_colors["review"].name(),
    }

    warning_color_config = config_data.get("warning_colors", {}) if isinstance(config_data.get("warning_colors"), dict) else {}
    if not isinstance(warning_color_config, dict):
        errors.append("warning_colors must be an object; using defaults.")
        warning_color_config = {}

    default_warning_colors = {
        "text": active_theme.text,
        "background": active_theme.background,
        "foreground": active_theme.foreground,
    }
    warning_colors = WarningColors(
        text=_color_or_default(
            warning_color_config.get("text"), default_warning_colors["text"], "warning_colors.text", errors
        ),
        background=_color_or_default(
            warning_color_config.get("background"), default_warning_colors["background"], "warning_colors.background", errors
        ),
        foreground=_color_or_default(
            warning_color_config.get("foreground"), default_warning_colors["foreground"], "warning_colors.foreground", errors
        ),
    )
    normalized["warning_colors"] = {
        "text": "" if warning_color_config.get("text") in (None, "") else warning_colors.text.name(),
        "background": "" if warning_color_config.get("background") in (None, "") else warning_colors.background.name(),
        "foreground": "" if warning_color_config.get("foreground") in (None, "") else warning_colors.foreground.name(),
    }

    palette = _build_palette(active_theme)
    warning_palette = _build_palette(
        ThemeSettings(
            text=warning_colors.text.name(),
            background=warning_colors.background.name(),
            foreground=warning_colors.foreground.name(),
            border_radius=active_theme.border_radius,
        )
    )

    normalized["appearance"] = {
        "day": {
            "text": day_theme.text,
            "background": day_theme.background,
            "foreground": day_theme.foreground,
            "border_radius": day_theme.border_radius,
        },
        "night": {
            "text": night_theme.text,
            "background": night_theme.background,
            "foreground": night_theme.foreground,
            "border_radius": night_theme.border_radius,
        },
    }

    restrict_size = ""
    if max_width:
        restrict_size = f"max-width: {max_width};" if orientation == Qt.Orientation.Horizontal else f"max-height: {max_width};"
    warning_transition = (
        "transition: color 160ms ease, background-color 160ms ease;"
        if warning_transition_animations and not reduced_motion
        else ""
    )

    default_stylesheet = (
        '''
                QProgressBar
                {
                    text-align:center;
                    color:%s;
                    background-color: %s;
                    border-radius: %dpx;
                    font-size: %s;
                    font-weight: %s;
                    %s
                    %s
                }
                QProgressBar::chunk
                {
                    background-color: %s;
                    margin: 0px;
                    border-radius: %dpx;
                }
                ''' % (
            active_theme.text,
            active_theme.background,
            active_theme.border_radius,
            hierarchy_font_size,
            hierarchy_font_weight,
            warning_transition,
            restrict_size,
            active_theme.foreground,
            active_theme.border_radius,
        )
    )
    warning_stylesheet = (
        '''
                QProgressBar
                {
                    text-align:center;
                    color:%s;
                    background-color: %s;
                    border-radius: %dpx;
                    font-size: %s;
                    font-weight: %s;
                    %s
                    %s
                }
                QProgressBar::chunk
                {
                    background-color: %s;
                    margin: 0px;
                    border-radius: %dpx;
                }
                ''' % (
            warning_colors.text.name(),
            warning_colors.background.name(),
            active_theme.border_radius,
            hierarchy_font_size,
            hierarchy_font_weight,
            warning_transition,
            restrict_size,
            warning_colors.foreground.name(),
            active_theme.border_radius,
        )
    )

    settings = Settings(
        progress_bar_enabled=progress_bar_enabled,
        include_new=include_new,
        include_rev=include_rev,
        include_lrn=include_lrn,
        include_new_after_revs=include_new_after_revs,
        counting_basis=counting_basis_raw,
        count_scope=count_scope_raw,
        force_forward=force_forward,
        lrn_steps=lrn_steps,
        no_days=no_days,
        use_system_timezone=use_system_timezone,
        tz=tz,
        show_percent=show_percent,
        show_retention=show_retention,
        show_super_mature_retention=show_super_mature_retention,
        show_again=show_again,
        show_number=show_number,
        show_yesterday=show_yesterday,
        text_hierarchy_style=text_hierarchy_style,
        label_style=label_style,
        compact_separators=compact_separators,
        vertical_text_line_break=vertical_text_line_break,
        show_debug=show_debug,
        show_progress_legend=show_progress_legend,
        legend_position=legend_position_raw,
        toggle_shortcut=toggle_shortcut,
        scrolling_bar_when_editing=scrolling_bar_when_editing,
        invert_progress=invert_progress,
        orientation=orientation,
        dock_area=dock_area,
        max_width=max_width,
        restrict_size=restrict_size,
        progress_bar_style=progress_bar_style,
        progress_bar_qstyle=progress_bar_qstyle,
        stacked_segments=stacked_segments,
        warnings_enabled=warnings_enabled,
        segment_colors=segment_colors,
        time_warning_minutes=time_warning_minutes,
        again_warning_percent=again_warning_percent,
        retention_warning_percent=retention_warning_percent,
        warning_colors=warning_colors,
        day_theme=day_theme,
        night_theme=night_theme,
        active_theme=active_theme,
        palette=palette,
        warning_palette=warning_palette,
        default_stylesheet=default_stylesheet,
        warning_stylesheet=warning_stylesheet,
        history_days=history_days,
        daily_target_cards=daily_target_cards,
        target_review_minutes=target_review_minutes,
        pace_warnings_enabled=pace_warnings_enabled,
        pacing_strategy=pacing_strategy,
        show_eta_confidence=show_eta_confidence,
        warning_hysteresis_percent=warning_hysteresis_percent,
        warning_cooldown_seconds=warning_cooldown_seconds,
        display_preset=display_preset,
        onboarding_completed=onboarding_completed,
        quick_setup_enabled=quick_setup_enabled,
        focus_mode=focus_mode,
        reduced_motion=reduced_motion,
        animated_updates=animated_updates,
        show_segment_inline_labels=show_segment_inline_labels,
        show_warning_badge=show_warning_badge,
        completion_celebration=completion_celebration,
        responsive_breakpoints=responsive_breakpoints,
        warning_transition_animations=warning_transition_animations,
        pinned_deck_views=pinned_deck_views,
        auto_adjust_contrast=auto_adjust_contrast,
        deck_profiles=deck_profiles,
        raw_config=normalized,
    )

    return settings, errors


def reload_settings(mw, *, notify: Optional[Callable[[List[str]], None]] = None) -> Settings:
    """Load settings and populate globals, optionally notifying about adjustments."""

    global settings
    global validation_errors

    settings, validation_errors = load_settings(mw)
    if notify is not None and validation_errors:
        notify(validation_errors)
    return settings


def apply_config(mw, new_config: Dict[str, Any], *, notify: Optional[Callable[[List[str]], None]] = None) -> Settings:
    """Persist a new configuration payload and refresh the global settings."""

    mw.addonManager.writeConfig(CONFIG_KEY, dict(new_config))
    return reload_settings(mw, notify=notify)


def validate_config_payload(mw, payload: Dict[str, Any]) -> List[str]:
    """Validate a config payload and return user-facing normalization errors."""

    fake_mw = SimpleNamespace(
        addonManager=SimpleNamespace(getConfig=lambda _key: dict(payload or {})),
        col=getattr(mw, "col", None),
    )
    _, errors = load_settings(fake_mw)
    return errors


# Alias preserved for test fixtures and legacy imports.
def _apply_config(new_config: Dict[str, Any], mw=None):  # type: ignore[override]
    return apply_config(mw, new_config) if mw is not None else apply_config(__import__("aqt").mw, new_config)
