from __future__ import annotations

from typing import Any, Dict, Optional

from aqt import mw
from aqt.qt import (
    QColor,
    QDockWidget,
    QEvent,
    QHelpEvent,
    QHBoxLayout,
    QLabel,
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
    QVBoxLayout,
    QWidget,
)
try:
    from aqt.qt import QToolButton
except Exception:  # pragma: no cover - test stub fallback
    class QToolButton(QWidget):  # type: ignore[misc,override]
        def __init__(self, parent=None) -> None:
            try:
                super().__init__(parent)
            except TypeError:
                super().__init__()

        def setText(self, *_args, **_kwargs) -> None:
            return None

        def setAutoRaise(self, *_args, **_kwargs) -> None:
            return None

        def clicked(self):  # type: ignore[override]
            return self

        def connect(self, *_args, **_kwargs) -> None:
            return None
from aqt.utils import tooltip

from .. import config

nmStyleApplied = 0
nmUnavailable = 0
progressBar: Optional[QProgressBar] = None
progressLegend: Optional["ProgressLegendWidget"] = None
progressContainer: Optional[QWidget] = None
toggle_shortcut: Optional[QShortcut] = None
progress_tooltip_filter: Optional[QObject] = None
interaction_filter: Optional[QObject] = None
_click_handler = None
_progress_segment_tooltips: Dict[str, str] = {}
_progress_fraction: float = 0.0
_default_tooltip_text: str = ""
_info_button: Optional[QToolButton] = None


def _qt_enum(container: Any, scoped_name: str, value_name: str, default: Any = None) -> Any:
    scoped = getattr(container, scoped_name, None)
    if scoped is not None and hasattr(scoped, value_name):
        return getattr(scoped, value_name)
    return getattr(container, value_name, default)


def _qt_event_type(value_name: str) -> Any:
    return _qt_enum(QEvent, "Type", value_name)


def _qt_cursor(value_name: str) -> Any:
    return _qt_enum(Qt, "CursorShape", value_name)


def _qt_mouse_button(value_name: str) -> Any:
    return _qt_enum(Qt, "MouseButton", value_name)


def _qt_alignment(value_name: str) -> Any:
    return _qt_enum(Qt, "AlignmentFlag", value_name, 0)


def _qt_shortcut_context(value_name: str) -> Any:
    return _qt_enum(Qt, "ShortcutContext", value_name)


def _qt_focus_policy(value_name: str) -> Any:
    return _qt_enum(Qt, "FocusPolicy", value_name)


def _qt_key(value_name: str) -> Any:
    return _qt_enum(Qt, "Key", value_name)


def _set_pointing_cursor(widget: Optional[QWidget]) -> None:
    if widget is None or not hasattr(widget, "setCursor"):
        return
    cursor = _qt_cursor("PointingHandCursor")
    if cursor is not None:
        widget.setCursor(cursor)


def _clear_cursor(widget: Optional[QWidget]) -> None:
    if widget is None:
        return
    if hasattr(widget, "unsetCursor"):
        widget.unsetCursor()


def _apply_size_constraints(widget: Optional[QWidget]) -> None:
    if widget is None or config.settings is None:
        return

    max_width = (config.settings.max_width or "").strip().lower()
    if not max_width.endswith("px"):
        return

    try:
        limit = int(float(max_width[:-2]))
    except ValueError:
        return

    if limit <= 0:
        return

    if config.settings.orientation == Qt.Orientation.Horizontal:
        if hasattr(widget, "setMaximumWidth"):
            widget.setMaximumWidth(limit)
    elif hasattr(widget, "setMaximumHeight"):
        widget.setMaximumHeight(limit)


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

    _default_tooltip_text = default_text
    _progress_segment_tooltips = {
        "completed": completed_text or default_text,
        "remaining": remaining_text or default_text,
    }
    if fraction is not None:
        _progress_fraction = max(0.0, min(1.0, fraction))

    if progressBar is not None:
        progressBar.setToolTip(default_text)


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
        if obj is progressBar and event.type() == _qt_event_type("ToolTip"):
            return _on_progress_bar_tooltip(event)
        return False


class _ProgressBarInteractionFilter(QObject):
    def eventFilter(self, obj, event) -> bool:
        if obj is not progressBar:
            return False

        global _click_handler
        if _click_handler is None:
            return False

        if event.type() == _qt_event_type("MouseButtonRelease") and event.button() in (
            _qt_mouse_button("LeftButton"),
            _qt_mouse_button("RightButton"),
        ):
            _click_handler()
            return True
        if event.type() == _qt_event_type("ContextMenu"):
            _click_handler()
            return True
        if event.type() == _qt_event_type("KeyPress"):
            key = event.key()
            if key in (_qt_key("Key_Return"), _qt_key("Key_Enter"), _qt_key("Key_Space")):
                _click_handler()
                return True
            return False
        if event.type() == _qt_event_type("Enter"):
            _set_pointing_cursor(progressBar)
            return False
        if event.type() == _qt_event_type("Leave"):
            _clear_cursor(progressBar)
            return False
        return False


def _show_info_popover() -> None:
    if progressBar is None:
        return
    info_text = (
        "Progress Bar Time Left\n"
        "• Fill shows completed cards for today's active queues.\n"
        "• Hover for queue + warning details.\n"
        "• Click to open the deck breakdown."
    )
    try:
        QToolTip.showText(progressBar.mapToGlobal(progressBar.rect().bottomRight()), info_text, progressBar)
    except Exception:
        tooltip(info_text, parent=mw, period=5000)


class SegmentedProgressBar(QProgressBar):
    """Lightweight progress bar that paints queue segments when enabled."""

    def __init__(self, segment_colors: Dict[str, QColor], parent: Optional[QWidget] = None) -> None:
        try:
            super().__init__(parent)
        except TypeError:
            super().__init__()
        self._segment_colors = segment_colors
        self._segment_counts = (0, 0, 0)
        self._progress_fraction: float = 0.0
        self._show_inline_labels: bool = False
        self._focus_mode: bool = False

    def setSegmentData(
        self,
        new_total: int,
        lrn_total: int,
        rev_total: int,
        progress_fraction: float,
        *,
        show_inline_labels: bool = False,
        focus_mode: bool = False,
    ) -> None:
        self._segment_counts = (max(0, new_total), max(0, lrn_total), max(0, rev_total))
        self._progress_fraction = max(0.0, min(1.0, progress_fraction))
        self._show_inline_labels = show_inline_labels
        self._focus_mode = focus_mode
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

        drawn_width = 0
        remaining_segments = [(name, count) for name, count in segment_order if count > 0]
        for index, (name, count) in enumerate(remaining_segments):
            if index == len(remaining_segments) - 1:
                segment_width = max(0, remaining_width - drawn_width)
            else:
                proportion = count / total_remaining
                segment_width = int(round(remaining_width * proportion))
                segment_width = max(0, min(segment_width, remaining_width - drawn_width))
            if segment_width <= 0:
                continue

            seg_rect = QRect(running_x, rect.top(), segment_width, rect.height())
            running_x += segment_width
            drawn_width += segment_width

            painter.fillRect(seg_rect, self._segment_colors.get(name, palette.color(palette.ColorRole.Highlight)))
            if self._show_inline_labels:
                self._draw_inline_label(painter, seg_rect, name[0].upper())

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
        drawn_height = 0
        remaining_segments = [(name, count) for name, count in segment_order if count > 0]
        for index, (name, count) in enumerate(remaining_segments):
            if index == len(remaining_segments) - 1:
                segment_height = max(0, remaining_height - drawn_height)
            else:
                proportion = count / total_remaining
                segment_height = int(round(remaining_height * proportion))
                segment_height = max(0, min(segment_height, remaining_height - drawn_height))
            if segment_height <= 0:
                continue

            seg_rect = QRect(rect.left(), running_y, rect.width(), segment_height)
            running_y += segment_height
            drawn_height += segment_height

            painter.fillRect(seg_rect, self._segment_colors.get(name, palette.color(palette.ColorRole.Highlight)))
            if self._show_inline_labels:
                self._draw_inline_label(painter, seg_rect, name[0].upper())


    def _draw_inline_label(self, painter: QPainter, rect: QRect, text: str) -> None:
        if not hasattr(painter, "drawText"):
            return
        if rect.width() < 34 or rect.height() < 10:
            return
        if self._focus_mode:
            return
        painter.drawText(rect, int(_qt_alignment("AlignCenter")), text)

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


class ProgressLegendWidget(QWidget):
    """Small legend widget showing queue colors and counts."""

    def __init__(self, segment_colors: Dict[str, QColor], parent: Optional[QWidget] = None) -> None:
        try:
            super().__init__(parent)
        except TypeError:
            super().__init__()
        self._segment_colors = segment_colors
        self._labels: Dict[str, QLabel] = {}
        self._swatches: Dict[str, QWidget] = {}

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        for key, label in [("new", "New"), ("learning", "Learning"), ("review", "Review")]:
            item = QWidget()
            item_layout = QHBoxLayout()
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(4)

            swatch = QWidget()
            if hasattr(swatch, "setFixedSize"):
                swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(
                f"background-color: {self._segment_colors.get(key, QColor()).name()};"
                "border-radius: 2px;"
            )

            text = QLabel(f"{label}: 0")
            text.setToolTip(f"{label} cards remaining")

            item_layout.addWidget(swatch)
            item_layout.addWidget(text)
            item.setLayout(item_layout)

            layout.addWidget(item)
            self._labels[key] = text
            self._swatches[key] = swatch

        layout.addStretch()
        self.setLayout(layout)
        if config.settings is not None:
            self.setStyleSheet(f"color: {config.settings.active_theme.text};")

    def set_counts(self, new_total: int, lrn_total: int, rev_total: int) -> None:
        self._labels["new"].setText(f"New: {max(0, new_total)}")
        self._labels["learning"].setText(f"Learning: {max(0, lrn_total)}")
        self._labels["review"].setText(f"Review: {max(0, rev_total)}")


def _apply_progress_style(
    bar: QProgressBar,
    palette,
    stylesheet: str,
    qstyle: Optional[QStyle],
    *,
    apply_constraints: bool = True,
) -> None:
    if qstyle is not None:
        bar.setStyle(qstyle)
    if hasattr(bar, "setStyleSheet"):
        bar.setStyleSheet(stylesheet)
    bar.setPalette(palette)
    if apply_constraints:
        _apply_size_constraints(bar)


def apply_bar_style(is_warning: bool) -> None:
    if progressBar is None or config.settings is None:
        return

    palette_to_apply = config.settings.warning_palette if is_warning else config.settings.palette
    stylesheet = config.settings.warning_stylesheet if is_warning else config.settings.default_stylesheet
    _apply_progress_style(
        progressBar,
        palette_to_apply,
        stylesheet,
        config.settings.progress_bar_qstyle,
        apply_constraints=True,
    )


def apply_bar_style_to(
    bar: QProgressBar,
    palette,
    stylesheet: str,
    qstyle: Optional[QStyle],
) -> None:
    _apply_progress_style(bar, palette, stylesheet, qstyle, apply_constraints=False)


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
    global progressLegend
    global progressContainer
    global _info_button
    if config.settings is None:
        return
    if config.settings.stacked_segments:
        progressBar = SegmentedProgressBar(config.settings.segment_colors)
    else:
        progressBar = QProgressBar()
    if hasattr(progressBar, "setAccessibleName"):
        progressBar.setAccessibleName("Daily review progress")
    if hasattr(progressBar, "setAccessibleDescription"):
        progressBar.setAccessibleDescription(
            "Shows completed review progress and supports opening deck breakdown with click or Enter."
        )
    focus_policy = _qt_focus_policy("StrongFocus")
    if focus_policy is not None and hasattr(progressBar, "setFocusPolicy"):
        progressBar.setFocusPolicy(focus_policy)
    progressBar.setTextVisible(config.settings.show_percent or config.settings.show_number)
    progressBar.setInvertedAppearance(config.settings.invert_progress)
    progressBar.setOrientation(config.settings.orientation)
    apply_bar_style(False)

    if progress_tooltip_filter is None:
        progress_tooltip_filter = _ProgressBarTooltipFilter()
    progressBar.installEventFilter(progress_tooltip_filter)

    if interaction_filter is None:
        interaction_filter = _ProgressBarInteractionFilter()
    progressBar.installEventFilter(interaction_filter)

    progressLegend = ProgressLegendWidget(config.settings.segment_colors)
    if hasattr(progressLegend, "setVisible"):
        progressLegend.setVisible(config.settings.show_progress_legend and not config.settings.focus_mode)

    bar_with_info = QWidget()
    bar_layout = QHBoxLayout()
    bar_layout.setContentsMargins(0, 0, 0, 0)
    bar_layout.setSpacing(6)
    bar_layout.addWidget(progressBar)
    _info_button = QToolButton()
    _info_button.setText("ⓘ")
    _info_button.setAutoRaise(True)
    if hasattr(_info_button, "setAccessibleName"):
        _info_button.setAccessibleName("Progress bar help")
    if hasattr(_info_button, "setAccessibleDescription"):
        _info_button.setAccessibleDescription("Shows a short explanation for the progress bar.")
    if hasattr(_info_button, "setMinimumSize"):
        _info_button.setMinimumSize(20, 20)
    if focus_policy is not None and hasattr(_info_button, "setFocusPolicy"):
        _info_button.setFocusPolicy(focus_policy)
    _set_pointing_cursor(_info_button)
    _info_button.setToolTip("What am I seeing?")
    if hasattr(_info_button, "setStyleSheet"):
        _info_button.setStyleSheet(
            "QToolButton {"
            f" color: {config.settings.active_theme.text};"
            " background: transparent;"
            " border: none;"
            " font-weight: 700;"
            " padding: 0 2px;"
            "}"
        )
    try:
        _info_button.clicked.connect(_show_info_popover)
    except Exception:
        pass
    if hasattr(_info_button, "setVisible"):
        _info_button.setVisible(not config.settings.focus_mode)
    bar_layout.addWidget(_info_button)
    bar_with_info.setLayout(bar_layout)

    progressContainer = QWidget()
    legend_position = config.settings.legend_position
    if legend_position in ("left", "right"):
        layout = QHBoxLayout()
    else:
        layout = QVBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    if legend_position in ("above", "left"):
        layout.addWidget(progressLegend)
        layout.addWidget(bar_with_info)
    else:
        layout.addWidget(bar_with_info)
        layout.addWidget(progressLegend)
    progressContainer.setLayout(layout)

    dock = _dock(progressContainer)
    if hasattr(mw, "docks") and dock not in getattr(mw, "docks", []):
        try:
            mw.docks.append(dock)
        except Exception:
            pass
    if hasattr(mw, "docks") and not getattr(mw, "docks", []):
        fallback_dock = QDockWidget()
        fallback_dock.setObjectName("pbDock")
        mw.addDockWidget(config.settings.dock_area, fallback_dock)


def _dock(widget: QWidget) -> QDockWidget:
    """Dock for the progress bar. Giving it a blank title bar,
        making sure to set focus back to the reviewer."""
    dock = QDockWidget()
    tWidget = QWidget()
    dock.setObjectName("pbDock")
    dock.setWidget(widget)
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
    global progressLegend
    global progressContainer
    global _info_button
    if progressBar is None:
        return

    container = progressContainer or progressBar.parentWidget()
    dock = container.parentWidget() if container is not None else None
    if isinstance(dock, QDockWidget):
        mw.removeDockWidget(dock)
    if container is not None and hasattr(container, "deleteLater"):
        container.deleteLater()
    if hasattr(progressBar, "deleteLater"):
        progressBar.deleteLater()
    progressBar = None
    progressLegend = None
    progressContainer = None
    _info_button = None


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


def update_progress_legend(new_total: int, lrn_total: int, rev_total: int) -> None:
    if config.settings is None or progressLegend is None:
        return
    if hasattr(progressLegend, "setVisible"):
        progressLegend.setVisible(config.settings.show_progress_legend and not config.settings.focus_mode)
    if config.settings.show_progress_legend and not config.settings.focus_mode:
        progressLegend.set_counts(new_total, lrn_total, rev_total)


def update_toggle_shortcut(on_toggle) -> None:
    global toggle_shortcut
    if config.settings is None:
        return
    shortcut = QKeySequence(config.settings.toggle_shortcut or 'Ctrl+G')
    if toggle_shortcut is None:
        toggle_shortcut = QShortcut(shortcut, mw)
        context = _qt_shortcut_context("ApplicationShortcut")
        if context is not None:
            toggle_shortcut.setContext(context)
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
    "update_progress_legend",
    "update_progress_tooltips",
    "update_toggle_shortcut",
]
