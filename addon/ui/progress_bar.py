from __future__ import annotations

from typing import Any, Dict, Optional

from aqt import mw
from aqt.qt import (
    QColor,
    QDockWidget,
    QEvent,
    QHelpEvent,
    QObject,
    QPainter,
    QProgressBar,
    QRect,
    QShortcut,
    QStyle,
    QStyleOptionProgressBar,
    QStylePainter,
    QToolTip,
    Qt,
    QKeySequence,
    QWidget,
)
from aqt.utils import tooltip

from .. import config

nmStyleApplied = 0
nmUnavailable = 0
progressBar: Optional[QProgressBar] = None
toggle_shortcut: Optional[QShortcut] = None
progress_tooltip_filter: Optional[QObject] = None
interaction_filter: Optional[QObject] = None
_click_handler = None
_progress_segment_tooltips: Dict[str, str] = {}
_progress_fraction: float = 0.0
_default_tooltip_text: str = ""
PROGRESS_BAR_TOOLTIP_HINT = "Click for full Deck Breakdown."


try:
    # Remove that annoying separator strip if we have Night Mode, avoiding conflicts with this add-on.
    import Night_Mode  # type: ignore[attr-defined]

    existing_nm_css_menu = getattr(Night_Mode, "nm_css_menu", None)
    if isinstance(existing_nm_css_menu, str):
        Night_Mode.nm_css_menu = existing_nm_css_menu + '''
            QMainWindow::separator
        {
            width: 0px;
            height: 0px;
        }
        '''
    else:
        nmUnavailable = 1
except Exception:
    # Gracefully degrade if Night_Mode isn't installed or exposes an unexpected API.
    nmUnavailable = 1


def _update_progress_tooltips(
    default_text: str,
    completed_text: Optional[str] = None,
    remaining_text: Optional[str] = None,
    fraction: Optional[float] = None,
) -> None:
    """Store tooltip variants for different hover regions of the bar."""
    global _progress_segment_tooltips
    global _progress_fraction
    global _default_tooltip_text

    _default_tooltip_text = PROGRESS_BAR_TOOLTIP_HINT
    _progress_segment_tooltips = {
        "completed": PROGRESS_BAR_TOOLTIP_HINT,
        "remaining": PROGRESS_BAR_TOOLTIP_HINT,
    }
    if fraction is not None:
        _progress_fraction = max(0.0, min(1.0, fraction))

    if progressBar is not None:
        progressBar.setToolTip(_default_tooltip_text)


def _on_progress_bar_tooltip(event: QHelpEvent) -> bool:
    """Show context-aware tooltips based on the hovered portion of the bar."""
    if progressBar is None:
        return False

    try:
        pos = event.position()  # Qt6
    except AttributeError:
        pos = event.pos()  # Qt5 fallback

    bar_width = max(1, progressBar.width())
    hover_ratio = max(0.0, min(1.0, pos.x() / bar_width))
    tooltip_text = _default_tooltip_text
    if _progress_fraction > 0 and hover_ratio <= _progress_fraction:
        tooltip_text = _progress_segment_tooltips.get("completed", _default_tooltip_text)
    elif _progress_fraction < 1 and hover_ratio > _progress_fraction:
        tooltip_text = _progress_segment_tooltips.get("remaining", _default_tooltip_text)

    QToolTip.showText(event.globalPos(), tooltip_text, progressBar)
    return True


class _ProgressBarTooltipFilter(QObject):
    def eventFilter(self, obj, event) -> bool:
        if obj is progressBar and event.type() == QEvent.Type.ToolTip:
            return _on_progress_bar_tooltip(event)
        return False


class _ProgressBarInteractionFilter(QObject):
    def eventFilter(self, obj, event) -> bool:
        if obj is not progressBar:
            return False

        global _click_handler
        if _click_handler is None:
            return False

        if event.type() == QEvent.Type.MouseButtonRelease and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
        ):
            _click_handler()
            return True
        if event.type() == QEvent.Type.ContextMenu:
            _click_handler()
            return True
        if event.type() == QEvent.Type.KeyPress:
            qt_key = getattr(Qt, "Key", Qt)
            activation_keys = {
                getattr(qt_key, "Key_Return", None),
                getattr(qt_key, "Key_Enter", None),
                getattr(qt_key, "Key_Space", None),
            }
            if event.key() in activation_keys:
                _click_handler()
                try:
                    event.accept()
                except Exception:
                    pass
                return True
        return False


class SegmentedProgressBar(QProgressBar):
    """Lightweight progress bar that paints queue segments when enabled."""

    def __init__(self, segment_colors: Dict[str, QColor], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._segment_colors = segment_colors
        self._segment_counts = (0, 0, 0)
        self._progress_fraction: float = 0.0

    def setSegmentData(
        self, new_total: int, lrn_total: int, rev_total: int, progress_fraction: float
    ) -> None:
        self._segment_counts = (max(0, new_total), max(0, lrn_total), max(0, rev_total))
        self._progress_fraction = max(0.0, min(1.0, progress_fraction))
        self.update()

    def _draw_segments_horizontal(self, painter: QPainter, rect: QRect, palette) -> None:
        available_width = rect.width()
        start_x = rect.left()

        filled_width = int(round(available_width * self._progress_fraction))
        if self.invertedAppearance():
            filled_rect = QRect(rect.right() - filled_width + 1, rect.top(), filled_width, rect.height())
        else:
            filled_rect = QRect(start_x, rect.top(), filled_width, rect.height())

        painter.fillRect(rect, palette.color(palette.ColorRole.Base))
        if filled_rect.width() > 0:
            painter.fillRect(filled_rect, palette.color(palette.ColorRole.Highlight))

        remaining_width = available_width - filled_width
        total_remaining = sum(self._segment_counts)
        if remaining_width <= 0 or total_remaining <= 0:
            return

        segment_order = [
            ("new", self._segment_counts[0]),
            ("learning", self._segment_counts[1]),
            ("review", self._segment_counts[2]),
        ]

        running_x = rect.left()
        if not self.invertedAppearance():
            running_x += filled_width
        for name, count in segment_order:
            if count <= 0:
                continue
            proportion = count / total_remaining
            segment_width = int(round(remaining_width * proportion))
            if segment_width <= 0:
                continue

            seg_rect = QRect(running_x, rect.top(), segment_width, rect.height())
            running_x += segment_width

            painter.fillRect(seg_rect, self._segment_colors.get(name, palette.color(palette.ColorRole.Highlight)))

    def _draw_segments_vertical(self, painter: QPainter, rect: QRect, palette) -> None:
        available_height = rect.height()

        filled_height = int(round(available_height * self._progress_fraction))
        if self.invertedAppearance():
            filled_rect = QRect(rect.left(), rect.top(), rect.width(), filled_height)
            remaining_start = rect.top() + filled_height
        else:
            filled_rect = QRect(rect.left(), rect.bottom() - filled_height + 1, rect.width(), filled_height)
            remaining_start = rect.top()

        painter.fillRect(rect, palette.color(palette.ColorRole.Base))
        if filled_rect.height() > 0:
            painter.fillRect(filled_rect, palette.color(palette.ColorRole.Highlight))

        remaining_height = available_height - filled_height
        total_remaining = sum(self._segment_counts)
        if remaining_height <= 0 or total_remaining <= 0:
            return

        segment_order = [
            ("new", self._segment_counts[0]),
            ("learning", self._segment_counts[1]),
            ("review", self._segment_counts[2]),
        ]

        running_y = remaining_start
        for name, count in segment_order:
            if count <= 0:
                continue
            proportion = count / total_remaining
            segment_height = int(round(remaining_height * proportion))
            if segment_height <= 0:
                continue

            seg_rect = QRect(rect.left(), running_y, rect.width(), segment_height)
            running_y += segment_height

            painter.fillRect(seg_rect, self._segment_colors.get(name, palette.color(palette.ColorRole.Highlight)))

    def paintEvent(self, event) -> None:  # type: ignore[override]
        option = QStyleOptionProgressBar()
        self.initStyleOption(option)
        painter = QStylePainter(self)

        rect = option.rect.adjusted(1, 1, -1, -1)
        if self.orientation() == Qt.Orientation.Vertical:
            self._draw_segments_vertical(painter, rect, option.palette)
        else:
            self._draw_segments_horizontal(painter, rect, option.palette)

        option.rect = rect
        painter.drawControl(QStyle.ControlElement.CE_ProgressBarLabel, option)


def apply_bar_style(is_warning: bool) -> None:
    if progressBar is None or config.settings is None:
        return

    palette_to_apply = config.settings.warning_palette if is_warning else config.settings.palette
    if config.settings.progress_bar_qstyle is None:
        stylesheet = config.settings.warning_stylesheet if is_warning else config.settings.default_stylesheet
        progressBar.setStyleSheet(stylesheet)
        progressBar.setPalette(palette_to_apply)
    else:
        progressBar.setStyle(config.settings.progress_bar_qstyle)
        progressBar.setPalette(palette_to_apply)


def nmApplyStyle() -> None:
    """Checks whether Night_Mode is disabled:
        if so, we remove the separator here."""
    global nmStyleApplied
    if not nmUnavailable:
        try:
            nmStyleApplied = Night_Mode.nm_state_on
        except Exception:
            nmStyleApplied = 0
    if not nmStyleApplied:
        mw.setStyleSheet(
            '''
        QMainWindow::separator
    {
        width: 0px;
        height: 0px;
    }
    ''')


def init_progress_bar() -> None:
    """Initialize and set parameters for progress bar, adding it to the dock."""
    global progressBar
    global progress_tooltip_filter
    global interaction_filter
    if config.settings is None:
        return
    if config.settings.stacked_segments:
        progressBar = SegmentedProgressBar(config.settings.segment_colors)
    else:
        progressBar = QProgressBar()
    progressBar.setTextVisible(config.settings.show_percent or config.settings.show_number)
    progressBar.setInvertedAppearance(config.settings.invert_progress)
    progressBar.setOrientation(config.settings.orientation)
    progressBar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    progressBar.setAccessibleName("Progress_Bar_Reforged")
    progressBar.setAccessibleDescription(
        "Shows current review progress. Press Enter or Space to open the deck breakdown."
    )
    apply_bar_style(False)

    if progress_tooltip_filter is None:
        progress_tooltip_filter = _ProgressBarTooltipFilter()
    progressBar.installEventFilter(progress_tooltip_filter)

    if interaction_filter is None:
        interaction_filter = _ProgressBarInteractionFilter()
    progressBar.installEventFilter(interaction_filter)

    dock = _dock(progressBar)
    if hasattr(mw, "docks") and dock not in getattr(mw, "docks", []):
        try:
            mw.docks.append(dock)
        except Exception:
            pass
    if hasattr(mw, "docks") and not getattr(mw, "docks", []):
        fallback_dock = QDockWidget()
        fallback_dock.setObjectName("pbDock")
        mw.addDockWidget(config.settings.dock_area, fallback_dock)


def _dock(pb: QProgressBar) -> QDockWidget:
    """Dock for the progress bar. Giving it a blank title bar,
        making sure to set focus back to the reviewer."""
    dock = QDockWidget()
    tWidget = QWidget()
    dock.setObjectName("pbDock")
    dock.setWidget(pb)
    dock.setTitleBarWidget(tWidget)

    existing_widgets = [widget for widget in mw.findChildren(QDockWidget) if mw.dockWidgetArea(widget) == config.settings.dock_area]

    mw.addDockWidget(config.settings.dock_area, dock)

    if len(existing_widgets) > 0:
        mw.setDockNestingEnabled(True)

        if config.settings.dock_area in (
            Qt.DockWidgetArea.TopDockWidgetArea,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        ):
            stack_method = Qt.Orientation.Vertical
        else:
            stack_method = Qt.Orientation.Horizontal

        mw.splitDockWidget(existing_widgets[0], dock, stack_method)

    if config.settings.active_theme.border_radius > 0 or config.settings.progress_bar_qstyle is not None:
        mw.setPalette(config.settings.palette)
    mw.web.setFocus()
    return dock


def remove_progress_bar() -> None:
    """Tear down any existing progress bar dock."""
    global progressBar
    if progressBar is None:
        return

    dock = progressBar.parentWidget()
    if isinstance(dock, QDockWidget):
        mw.removeDockWidget(dock)
    progressBar.deleteLater()
    progressBar = None


def reinitialize_progress_bar() -> None:
    """Recreate the progress bar with the latest configuration."""
    global progressBar

    remove_progress_bar()

    if not config.settings.progress_bar_enabled:
        return

    init_progress_bar()


def set_scrolling_bar_state() -> None:
    """Make progress bar in waiting style if the state is resetRequired (happened after editing cards.)"""
    if progressBar is None or config.settings is None:
        return
    progressBar.setRange(0, 0)
    if config.settings.show_number:
        progressBar.setFormat("Waiting...")
        waiting_tooltip = (
            "Anki is updating the collection. Progress stats will resume once reviews restart."
        )
    else:
        waiting_tooltip = (
            "Anki is updating the collection. Enable progress text to view detailed statistics."
        )
    _update_progress_tooltips(waiting_tooltip)
    nmApplyStyle()


def update_progress_tooltips(
    default_text: str,
    completed_text: Optional[str] = None,
    remaining_text: Optional[str] = None,
    fraction: Optional[float] = None,
) -> None:
    _update_progress_tooltips(default_text, completed_text, remaining_text, fraction)


def update_toggle_shortcut(on_toggle) -> None:
    global toggle_shortcut
    if config.settings is None:
        return
    shortcut = QKeySequence(config.settings.toggle_shortcut or 'Ctrl+G')
    if toggle_shortcut is None:
        toggle_shortcut = QShortcut(shortcut, mw)
        toggle_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        toggle_shortcut.activated.connect(on_toggle)
    else:
        toggle_shortcut.setKey(shortcut)


def set_click_handler(on_click) -> None:
    """Register a callable to open the deck breakdown dialog when the bar is clicked."""
    global _click_handler
    global interaction_filter
    _click_handler = on_click
    if progressBar is not None:
        if interaction_filter is None:
            interaction_filter = _ProgressBarInteractionFilter()
        progressBar.installEventFilter(interaction_filter)


__all__ = [
    "SegmentedProgressBar",
    "apply_bar_style",
    "init_progress_bar",
    "nmApplyStyle",
    "progressBar",
    "reinitialize_progress_bar",
    "remove_progress_bar",
    "set_scrolling_bar_state",
    "set_click_handler",
    "update_progress_tooltips",
    "update_toggle_shortcut",
]
