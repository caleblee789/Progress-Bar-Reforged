from __future__ import annotations

import sys
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from aqt.qt import QColor, QPalette, QStyle, QStyleFactory, Qt

from .nightmode import isnightmode

PACKAGE_ID = "1511983907"
CONFIG_KEY = PACKAGE_ID
LEGACY_WARNING_KEYS = {
    "warnings_enabled",
    "pace_warnings_enabled",
    "time_warning_minutes",
    "again_warning_percent",
    "retention_warning_percent",
    "warning_colors",
}
LEGACY_SETTING_KEYS = set(LEGACY_WARNING_KEYS)


def config_key() -> str:
    """Return the Anki add-on package key used for config persistence."""

    return CONFIG_KEY


def read_config(mw) -> Dict[str, Any]:
    config_data = mw.addonManager.getConfig(config_key())
    return dict(config_data) if isinstance(config_data, dict) else {}


def write_config(mw, new_config: Dict[str, Any]) -> None:
    mw.addonManager.writeConfig(config_key(), dict(new_config))


def resolve_theme_mode(theme: str) -> str:
    theme_choice = str(theme or "auto").strip().lower()
    if theme_choice == "dark":
        return "dark"
    if theme_choice == "light":
        return "light"
    return "dark" if isnightmode() else "light"


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
        number = float(value)
        return number if math.isfinite(number) else default
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
    # Only permit non-negative CSS dimensions. Older configs may contain
    # strings, but arbitrary text must never be interpolated into a stylesheet.
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(px|pt|em|rem|%)?", value_str, re.IGNORECASE)
    if match is None:
        return ""
    number, unit = match.groups()
    return f"{number}{unit or 'px'}"


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
    opacity: int


@dataclass
class WarningColors:
    text: QColor
    background: QColor
    foreground: QColor


@dataclass
class Settings:
    progress_bar_enabled: bool
    display_location: str
    mode: str
    theme: str
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
    show_debug: bool
    daily_target_cards: int
    target_review_minutes: int
    pace_warnings_enabled: bool
    toggle_shortcut: str
    scrolling_bar_when_editing: bool
    invert_progress: bool
    orientation: Qt.Orientation
    dock_area: Qt.DockWidgetArea
    max_width: str
    min_height: str
    bar_height: str
    padding: str
    restrict_size: str
    progress_bar_style: str
    progress_bar_qstyle: Optional[QStyle]
    stacked_segments: bool
    font_size: str
    opacity: int
    animation_enabled: bool
    animation_duration_ms: int
    tooltip_enabled: bool
    tooltip_delay_ms: int
    theme_preset: str
    text_format: str
    compact_mode: bool
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
    border_radius = _coerce_int(overrides.get("border_radius"), defaults.get("border_radius", 0))
    if border_radius < 0:
        errors.append(f"{path}.border_radius must be >= 0; using {defaults.get('border_radius', 0)}.")
        border_radius = defaults.get("border_radius", 0)
    opacity = _coerce_int(overrides.get("opacity"), defaults.get("opacity", 100))
    if opacity < 0 or opacity > 100:
        errors.append(f"{path}.opacity must be 0-100; using {defaults.get('opacity', 100)}.")
        opacity = defaults.get("opacity", 100)
    return ThemeSettings(text=text, background=background, foreground=foreground, border_radius=border_radius, opacity=opacity)


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
    config_data = read_config(mw)

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
            conversion_failed = not math.isfinite(value)
            if conversion_failed:
                value = default
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
    display_location = str(config_data.get("display_location", "review")).strip().lower()
    if display_location not in {"review", "review_and_home"}:
        errors.append(f"display_location {display_location!r} invalid; using review.")
        display_location = "review"
    normalized["display_location"] = display_location

    mode = str(config_data.get("mode", "stats")).strip().lower()
    if mode not in {"simple", "time_left", "stats"}:
        errors.append(f"mode {mode!r} invalid; using stats.")
        mode = "stats"
    normalized["mode"] = mode

    theme = str(config_data.get("theme", "auto")).strip().lower()
    if theme not in {"auto", "light", "dark"}:
        errors.append(f"theme {theme!r} invalid; using auto.")
        theme = "auto"
    normalized["theme"] = theme

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
    warnings_enabled = False
    pace_warnings_enabled = False

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

    min_height = _normalize_dimension(config_data.get("min_height", ""))
    normalized["min_height"] = min_height

    bar_height = _normalize_dimension(config_data.get("bar_height", ""))
    normalized["bar_height"] = bar_height

    padding = _normalize_dimension(config_data.get("padding", ""))
    normalized["padding"] = padding

    font_size = _normalize_dimension(config_data.get("font_size", ""))
    normalized["font_size"] = font_size

    opacity = _int("opacity", 100, minimum=0, maximum=100)
    animation_enabled = _bool("animation_enabled", True)
    animation_duration_ms = _int("animation_duration_ms", 300, minimum=0, maximum=2000)
    tooltip_enabled = _bool("tooltip_enabled", True)
    tooltip_delay_ms = _int("tooltip_delay_ms", 500, minimum=0, maximum=5000)

    theme_preset_raw = str(config_data.get("theme_preset", "default")).lower()
    valid_presets = {"default", "minimal", "colorful", "dark", "light", "high_contrast"}
    if theme_preset_raw not in valid_presets:
        errors.append(f"theme_preset {theme_preset_raw!r} invalid; using default.")
        theme_preset_raw = "default"
    normalized["theme_preset"] = theme_preset_raw

    text_format_raw = str(config_data.get("text_format", "auto")).lower()
    valid_formats = {"auto", "compact", "verbose", "minimal"}
    if text_format_raw not in valid_formats:
        errors.append(f"text_format {text_format_raw!r} invalid; using auto.")
        text_format_raw = "auto"
    normalized["text_format"] = text_format_raw

    compact_mode = _bool("compact_mode", False)

    progress_bar_style = str(config_data.get("progress_bar_style", ""))
    normalized["progress_bar_style"] = progress_bar_style
    progress_bar_qstyle: Optional[QStyle] = None
    if progress_bar_style:
        progress_bar_qstyle = QStyleFactory.create(progress_bar_style)
        if progress_bar_qstyle is None:
            errors.append(f"progress_bar_style {progress_bar_style!r} not available; using default theme style.")
            progress_bar_style = ""
            normalized["progress_bar_style"] = ""

    # Qt maps Ctrl to the Command key on macOS.  Meta maps to the physical
    # Control key there, so keep the portable form as the public default.
    default_shortcut = "Ctrl+G"
    toggle_shortcut = str(config_data.get("toggle_shortcut", default_shortcut)).strip() or default_shortcut
    if sys.platform == "darwin" and toggle_shortcut.lower() == "meta+g":
        toggle_shortcut = "Ctrl+G"
    normalized["toggle_shortcut"] = toggle_shortcut

    lrn_steps = _int("lrn_steps", 2, minimum=1)
    no_days = _int("no_days", 7, minimum=1)
    use_system_timezone = _bool("use_system_timezone", True)
    tz = _int("tz", 0, minimum=-12, maximum=14)

    show_percent = _bool("show_percent", True)
    show_retention = _bool("show_retention", True)
    show_super_mature_retention = _bool("show_super_mature_retention", False)
    show_again = _bool("show_again", True)
    show_number = _bool("show_number", True)
    show_yesterday = _bool("show_yesterday", True)
    show_debug = _bool("show_debug", False)

    daily_target_cards = _int("daily_target_cards", 0, minimum=0)
    target_review_minutes = _int("target_review_minutes", 0, minimum=0)

    time_warning_minutes = 0
    again_warning_percent = 0.0
    retention_warning_percent = 0.0

    history_days = _int("history_days", 30, minimum=0)

    if mode == "simple":
        show_percent = True
        show_number = True
        show_again = False
        show_retention = False
        show_super_mature_retention = False
        show_yesterday = False
        show_debug = False
    elif mode == "time_left":
        show_percent = True
        show_number = True
        show_again = False
        show_retention = False
        show_super_mature_retention = False
        show_yesterday = False
        show_debug = False
    else:
        show_percent = True
        show_number = True
        show_again = True
        show_retention = True
        show_super_mature_retention = bool(show_super_mature_retention)
        show_yesterday = True

    normalized.update(
        {
            "show_percent": show_percent,
            "show_number": show_number,
            "show_again": show_again,
            "show_retention": show_retention,
            "show_super_mature_retention": show_super_mature_retention,
            "show_yesterday": show_yesterday,
            "show_debug": show_debug,
        }
    )
    for legacy_key in LEGACY_SETTING_KEYS:
        normalized.pop(legacy_key, None)

    default_day = {
        "text": "#111827",
        "background": "#e7edf3",
        "foreground": "#0e7490",
        "border_radius": 0,
        "opacity": 100,
    }
    default_night = {
        "text": "aliceblue",
        "background": "rgba(39, 40, 40, 1)",
        "foreground": "#3399cc",
        "border_radius": 0,
        "opacity": 100,
    }

    appearance = config_data.get("appearance", {})
    if not isinstance(appearance, dict):
        errors.append("appearance must be an object; using defaults.")
        appearance = {}
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

    theme_is_night = resolve_theme_mode(theme) == "dark"
    active_theme = night_theme if theme_is_night else day_theme

    segment_color_config = config_data.get("segment_colors", {})
    if not isinstance(segment_color_config, dict):
        errors.append("segment_colors must be an object; using defaults.")
        segment_color_config = {}
    # These defaults retain at least 3:1 contrast against both built-in tracks.
    # Explicit user colors remain authoritative.
    default_segment_colors = {"new": "#378ba5", "learning": "#aa7926", "review": "#41965a"}
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

    warning_colors = WarningColors(
        text=_to_qcolor(active_theme.text),
        background=_to_qcolor(active_theme.background),
        foreground=_to_qcolor(active_theme.foreground),
    )

    palette = _build_palette(active_theme)
    warning_palette = QPalette(palette)

    normalized["appearance"] = {
        "day": {
            "text": day_theme.text,
            "background": day_theme.background,
            "foreground": day_theme.foreground,
            "border_radius": day_theme.border_radius,
            "opacity": day_theme.opacity,
        },
        "night": {
            "text": night_theme.text,
            "background": night_theme.background,
            "foreground": night_theme.foreground,
            "border_radius": night_theme.border_radius,
            "opacity": night_theme.opacity,
        },
    }

    restrict_size = ""
    size_parts = []
    if max_width:
        size_parts.append(f"max-width: {max_width};" if orientation == Qt.Orientation.Horizontal else f"max-height: {max_width};")
    if min_height:
        size_parts.append(f"min-height: {min_height};" if orientation == Qt.Orientation.Horizontal else f"min-width: {min_height};")
    if bar_height:
        size_parts.append(f"height: {bar_height};" if orientation == Qt.Orientation.Horizontal else f"width: {bar_height};")
    if padding:
        size_parts.append(f"padding: {padding};")
    if font_size:
        size_parts.append(f"font-size: {font_size};")
    size_parts.append("font-weight: 600;")
    size_parts.append("min-height: 22px;" if orientation == Qt.Orientation.Horizontal else "min-width: 22px;")
    restrict_size = " ".join(size_parts)

    default_stylesheet = (
        '''
                QProgressBar
                {
                    text-align:center;
                    color:%s;
                    background-color: %s;
                    border-radius: %dpx;
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
            restrict_size,
            active_theme.foreground,
            active_theme.border_radius,
        )
    )
    warning_stylesheet = default_stylesheet

    settings = Settings(
        progress_bar_enabled=progress_bar_enabled,
        display_location=display_location,
        mode=mode,
        theme=theme,
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
        show_debug=show_debug,
        toggle_shortcut=toggle_shortcut,
        scrolling_bar_when_editing=scrolling_bar_when_editing,
        invert_progress=invert_progress,
        orientation=orientation,
        dock_area=dock_area,
        max_width=max_width,
        min_height=min_height,
        bar_height=bar_height,
        padding=padding,
        restrict_size=restrict_size,
        progress_bar_style=progress_bar_style,
        progress_bar_qstyle=progress_bar_qstyle,
        stacked_segments=stacked_segments,
        font_size=font_size,
        opacity=opacity,
        animation_enabled=animation_enabled,
        animation_duration_ms=animation_duration_ms,
        tooltip_enabled=tooltip_enabled,
        tooltip_delay_ms=tooltip_delay_ms,
        theme_preset=theme_preset_raw,
        text_format=text_format_raw,
        compact_mode=compact_mode,
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

    config_to_write = dict(new_config)
    for legacy_key in LEGACY_SETTING_KEYS:
        config_to_write.pop(legacy_key, None)
    write_config(mw, config_to_write)
    new_settings = reload_settings(mw, notify=notify)
    if config_to_write != new_settings.raw_config:
        write_config(mw, new_settings.raw_config)
    return new_settings


# Alias preserved for test fixtures and legacy imports.
def _apply_config(new_config: Dict[str, Any], mw=None):  # type: ignore[override]
    return apply_config(mw, new_config) if mw is not None else apply_config(__import__("aqt").mw, new_config)
