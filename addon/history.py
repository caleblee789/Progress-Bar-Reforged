from __future__ import annotations

import csv
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from aqt import mw
from aqt.qt import (
    QAbstractItemView,
    QColor,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    Qt,
)
try:
    from aqt.qt import QToolButton
except Exception:  # pragma: no cover - test stub fallback
    class QToolButton(QPushButton):  # type: ignore[misc,override]
        def __init__(self, parent=None) -> None:
            super().__init__("")

try:
    from aqt.qt import QPainter, QPen, QSizePolicy  # type: ignore
except Exception:  # pragma: no cover - fallback for test stubs without Qt painting
    class QPainter:  # type: ignore
        RenderHint = type("RenderHint", (), {"Antialiasing": 0})

        def __init__(self, *args, **kwargs) -> None:
            pass

        def setRenderHint(self, *args, **kwargs) -> None:
            pass

        def fillRect(self, *args, **kwargs) -> None:
            pass

        def setPen(self, *args, **kwargs) -> None:
            pass

        def drawText(self, *args, **kwargs) -> None:
            pass

        def drawRect(self, *args, **kwargs) -> None:
            pass

        def drawLine(self, *args, **kwargs) -> None:
            pass

        def drawPoint(self, *args, **kwargs) -> None:
            pass

    class QPen:  # type: ignore
        def __init__(self, *args, **kwargs) -> None:
            pass

        def setWidth(self, *args, **kwargs) -> None:
            pass

    class QSizePolicy:  # type: ignore
        class Policy:
            Expanding = 0
            MinimumExpanding = 0

if not hasattr(Qt, "AlignmentFlag"):  # pragma: no cover - stub compatibility
    class _AlignmentFlag:
        AlignCenter = 0
        AlignLeft = 0
        AlignRight = 0
        AlignBottom = 0

    Qt.AlignmentFlag = _AlignmentFlag  # type: ignore[attr-defined]

from . import config

HISTORY_PROGRESS_KEY = "progress_bar_history"


def _qt_enum(container: Any, scoped_name: str, value_name: str, default: Any = None) -> Any:
    scoped = getattr(container, scoped_name, None)
    if scoped is not None and hasattr(scoped, value_name):
        return getattr(scoped, value_name)
    return getattr(container, value_name, default)


def _message_box_button(value_name: str) -> Any:
    return _qt_enum(QMessageBox, "StandardButton", value_name)


def _focus_policy(value_name: str) -> Any:
    return _qt_enum(Qt, "FocusPolicy", value_name)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_history_records(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_history = profile.get(HISTORY_PROGRESS_KEY, [])
    if not isinstance(raw_history, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for entry in raw_history:
        if not isinstance(entry, dict):
            continue
        day = entry.get("day")
        try:
            day_int = int(day)
        except (TypeError, ValueError):
            continue
        normalized.append(
            {
                "day": day_int,
                "cards": _safe_int(entry.get("cards", 0) or 0),
                "avg_seconds": _safe_float(entry.get("avg_seconds", 0.0) or 0.0),
                "again": _safe_float(entry.get("again", 0.0) or 0.0),
                "retention": _safe_float(entry.get("retention", 0.0) or 0.0),
                "super_mature_retention": _safe_float(entry.get("super_mature_retention", 0.0) or 0.0),
                "warning_events": _safe_int(entry.get("warning_events", 0) or 0),
            }
        )
    return normalized


def format_history_day(day_stamp: int) -> str:
    try:
        return datetime.fromtimestamp(day_stamp * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return str(day_stamp)


def calculate_today_history_entry(
    day_stamp: int,
    day_cutoff: int,
    deck_ids_for_query: List[int],
    stats_between: Callable[[int, int, List[int]], Optional[tuple]],
) -> Optional[Dict[str, Any]]:
    day_start = (day_cutoff - 86400) * 1000
    day_end = day_cutoff * 1000

    stats_today = stats_between(day_start, day_end, deck_ids_for_query)
    if not stats_today:
        return None

    cards, failed, flunked, passed, passed_supermature, flunked_supermature, thetime = (
        stats_today
    )
    cards = cards or 0
    failed = failed or 0
    flunked = flunked or 0
    passed = passed or 0
    passed_supermature = passed_supermature or 0
    flunked_supermature = flunked_supermature or 0
    thetime = thetime or 0

    again_rate = (failed / cards * 100) if cards else 0.0
    retention = (passed / float(passed + flunked) * 100) if (passed + flunked) else 0.0
    sm_retention = (
        (passed_supermature / float(passed_supermature + flunked_supermature) * 100)
        if (passed_supermature + flunked_supermature)
        else 0.0
    )
    avg_seconds = (thetime / cards) if cards else 0.0

    warning_events = int((1 if again_rate >= 15.0 else 0) + (1 if retention < 80.0 else 0))
    return {
        "day": day_stamp,
        "cards": int(cards),
        "avg_seconds": float(avg_seconds),
        "again": float(again_rate),
        "retention": float(retention),
        "super_mature_retention": float(sm_retention),
        "warning_events": warning_events,
    }


def update_daily_history(
    profile: Dict[str, Any],
    day_stamp: int,
    deck_ids_for_query: List[int],
    stats_between: Callable[[int, int, List[int]], Optional[tuple]],
) -> None:
    if day_stamp <= 0:
        return

    entry = calculate_today_history_entry(day_stamp, mw.col.sched.day_cutoff if mw.col else 0, deck_ids_for_query, stats_between)
    if entry is None:
        return

    history = read_history_records(profile)
    history = [item for item in history if item.get("day") != day_stamp]
    history.append(entry)
    history.sort(key=lambda item: item.get("day", 0), reverse=True)
    history_days = getattr(config.settings, "history_days", 0)
    if history_days > 0:
        history = history[: history_days]

    profile[HISTORY_PROGRESS_KEY] = history


class SessionHistoryDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Progress Bar Session History")
        self.setMinimumWidth(500)
        self._history_data: List[Dict[str, Any]] = []
        self._palette = self._resolve_palette()

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        description = QLabel(
            "Review pace trends at a glance. Data is captured once per day and limited by your history_days setting."
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"color: {self._palette['secondary_text']};")
        layout.addWidget(description)

        controls = QHBoxLayout()
        controls.addStretch()
        range_label = QLabel("Show:")
        range_label.setStyleSheet(f"color: {self._palette['muted_text']};")
        controls.addWidget(range_label)
        self.range_selector = QComboBox()
        self.range_selector.addItem("Last 7 days", 7)
        self.range_selector.addItem("Last 30 days", 30)
        self.range_selector.addItem("All history", 0)
        self.range_selector.setCurrentIndex(1)
        try:
            self.range_selector.currentIndexChanged.connect(self._on_range_changed)  # type: ignore[attr-defined]
        except Exception:
            # Test stubs may not expose signals; fall back to a no-op.
            pass
        controls.addWidget(self.range_selector)
        self._retention_help = QToolButton()
        if hasattr(self._retention_help, "setText"):
            self._retention_help.setText("?")
        if hasattr(self._retention_help, "setAccessibleName"):
            self._retention_help.setAccessibleName("True retention help")
        if hasattr(self._retention_help, "setAccessibleDescription"):
            self._retention_help.setAccessibleDescription(
                "Explains how the true retention metric is calculated."
            )
        self._retention_help.setToolTip("True retention = passed mature reviews / (passed + failed mature reviews).")
        controls.addWidget(self._retention_help)
        layout.addLayout(controls)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"color: {self._palette['secondary_text']}; font-weight: 600;")
        layout.addWidget(self.summary_label)

        charts_layout = QVBoxLayout()
        charts_layout.setSpacing(8)

        self.cards_chart = TrendChartWidget(
            "Cards per day",
            palette=self._palette,
            accent=self._palette.get("tab_selected_bottom", "#5b8def"),
        )
        self.again_chart = TrendChartWidget(
            "Again rate (%)",
            palette=self._palette,
            accent=self._palette.get("focus_border", "#ef4444"),
        )
        self.retention_chart = TrendChartWidget(
            "True retention (%)",
            palette=self._palette,
            accent=self._palette.get("tab_unselected_text", "#16a34a"),
        )
        self.warning_chart = TrendChartWidget(
            "Warning frequency",
            palette=self._palette,
            accent=self._palette.get("focus_border", "#ef4444"),
        )

        charts_layout.addWidget(self.cards_chart)
        charts_layout.addWidget(self.again_chart)
        charts_layout.addWidget(self.retention_chart)
        charts_layout.addWidget(self.warning_chart)
        layout.addLayout(charts_layout)

        self.chart_summary_label = QLabel("")
        self.chart_summary_label.setWordWrap(True)
        self.chart_summary_label.setStyleSheet(f"color: {self._palette['secondary_text']};")
        if hasattr(self.chart_summary_label, "setAccessibleName"):
            self.chart_summary_label.setAccessibleName("Session history chart summary")
        if hasattr(self.chart_summary_label, "setAccessibleDescription"):
            self.chart_summary_label.setAccessibleDescription(
                "Keyboard-readable summary of the visible session history charts."
            )
        focus_policy = _focus_policy("StrongFocus")
        if focus_policy is not None and hasattr(self.chart_summary_label, "setFocusPolicy"):
            self.chart_summary_label.setFocusPolicy(focus_policy)
        layout.addWidget(self.chart_summary_label)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Day", "Cards", "Avg s/card", "Again %", "True Retention %", "Super-mature %", "Warnings"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self._export_csv)
        btn_row.addWidget(export_btn)

        export_clear_btn = QPushButton("Export then Clear")
        export_clear_btn.clicked.connect(self._export_then_clear)
        btn_row.addWidget(export_clear_btn)

        clear_btn = QPushButton("Clear History")
        clear_btn.clicked.connect(self._clear_history)
        btn_row.addWidget(clear_btn)

        layout.addLayout(btn_row)
        self.setLayout(layout)

        self.setStyleSheet(
            f"""
            QDialog {{
                background: {self._palette['window_bg']};
                color: {self._palette['primary_text']};
            }}
            QTableWidget {{
                background: {self._palette['card_bg']};
                color: {self._palette['primary_text']};
                border: 1px solid {self._palette['card_border']};
            }}
            QHeaderView::section {{
                background: {self._palette['tab_selected_bg']};
                color: {self._palette['tab_selected_text']};
                border: 1px solid {self._palette['tab_border']};
            }}
            QPushButton {{
                padding: 6px 12px;
                background: {self._palette['tab_selected_bg']};
                color: {self._palette['primary_text']};
                border: 1px solid {self._palette['tab_border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {self._palette['tab_hover_bg']};
            }}
            QComboBox {{
                padding: 4px 8px;
                background: {self._palette['card_bg']};
                border: 1px solid {self._palette['field_border']};
                color: {self._palette['primary_text']};
                border-radius: 4px;
            }}
            """
        )

        self._reload()

    def _reload(self) -> None:
        self._history_data = self._load_history()
        self._populate_table()
        self._update_charts()

    def _load_history(self) -> List[Dict[str, Any]]:
        if mw.pm is None:
            return []
        profile = getattr(mw.pm, "profile", None)
        if not isinstance(profile, dict):
            return []
        history = read_history_records(profile)
        history.sort(key=lambda item: item.get("day", 0), reverse=True)
        return history

    def _selected_range_days(self) -> int:
        return int(self.range_selector.currentData() or 0)

    def _filtered_history(self) -> List[Dict[str, Any]]:
        days = self._selected_range_days()
        if days <= 0:
            return list(self._history_data)
        return list(self._history_data[:days])

    def _populate_table(self) -> None:
        filtered = self._filtered_history()
        self.table.setRowCount(len(filtered))
        for row_idx, entry in enumerate(filtered):
            day_display = format_history_day(int(entry.get("day", 0)))
            cards_display = str(int(entry.get("cards", 0)))
            avg_seconds_display = f"{float(entry.get('avg_seconds', 0.0)):.2f}"
            again_display = f"{float(entry.get('again', 0.0)):.2f}"
            retention_display = f"{float(entry.get('retention', 0.0)):.2f}"
            sm_retention_display = f"{float(entry.get('super_mature_retention', 0.0)):.2f}"
            warning_display = str(int(entry.get("warning_events", 0)))

            values = [
                day_display,
                cards_display,
                avg_seconds_display,
                again_display,
                retention_display,
                sm_retention_display,
                warning_display,
            ]
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                self.table.setItem(row_idx, col_idx, item)

        self.table.resizeColumnsToContents()
        self._update_summary_row(filtered)

    def _update_summary_row(self, filtered: List[Dict[str, Any]]) -> None:
        if not hasattr(self.summary_label, "setText"):
            return
        if not filtered:
            self.summary_label.setText("Summary: no history data yet.")
            return

        def _summary(days: int) -> str:
            subset = filtered if days <= 0 else filtered[:days]
            if not subset:
                return f"{days}d: n/a"
            avg_cards = sum(float(x.get("cards", 0)) for x in subset) / len(subset)
            avg_again = sum(float(x.get("again", 0.0)) for x in subset) / len(subset)
            avg_ret = sum(float(x.get("retention", 0.0)) for x in subset) / len(subset)
            trend = "flat"
            if len(subset) >= 2:
                first = float(subset[-1].get("cards", 0))
                last = float(subset[0].get("cards", 0))
                if last > first:
                    trend = "up"
                elif last < first:
                    trend = "down"
            label = "All" if days <= 0 else f"{days}d"
            return f"{label}: cards/day {avg_cards:.1f}, Again {avg_again:.1f}%, true retention {avg_ret:.1f}% ({trend})"

        self.summary_label.setText("Summary — " + " | ".join([_summary(7), _summary(30), _summary(0)]))

    def _update_charts(self) -> None:
        filtered = list(reversed(self._filtered_history()))  # oldest to newest for plotting
        cards_points: List[Tuple[int, float]] = []
        again_points: List[Tuple[int, float]] = []
        retention_points: List[Tuple[int, float]] = []
        warning_points: List[Tuple[int, float]] = []

        for entry in filtered:
            day = int(entry.get("day", 0))
            cards_points.append((day, float(entry.get("cards", 0))))
            again_points.append((day, float(entry.get("again", 0.0))))
            retention_points.append((day, float(entry.get("retention", 0.0))))
            warning_points.append((day, float(entry.get("warning_events", 0))))

        self.cards_chart.set_points(cards_points)
        self.again_chart.set_points(again_points)
        self.retention_chart.set_points(retention_points)
        self.warning_chart.set_points(warning_points)
        self._update_chart_summary(filtered)

    def _update_chart_summary(self, filtered: List[Dict[str, Any]]) -> None:
        if not hasattr(self, "chart_summary_label"):
            return
        if not filtered:
            summary = "Chart summary: no visible history data."
        else:
            days = len(filtered)
            total_cards = sum(float(entry.get("cards", 0)) for entry in filtered)
            avg_cards = total_cards / max(days, 1)
            latest = filtered[-1]
            latest_day = format_history_day(int(latest.get("day", 0)))
            latest_cards = int(latest.get("cards", 0))
            latest_again = float(latest.get("again", 0.0))
            latest_retention = float(latest.get("retention", 0.0))
            warnings = int(sum(int(entry.get("warning_events", 0)) for entry in filtered))
            summary = (
                f"Chart summary: {days} day{'s' if days != 1 else ''} visible; "
                f"average {avg_cards:.1f} cards/day; latest {latest_day}: "
                f"{latest_cards} cards, Again {latest_again:.1f}%, true retention {latest_retention:.1f}%; "
                f"{warnings} warning event{'s' if warnings != 1 else ''}."
            )
        self.chart_summary_label.setText(summary)
        if hasattr(self.chart_summary_label, "setToolTip"):
            self.chart_summary_label.setToolTip(summary)

    def _on_range_changed(self) -> None:
        self._populate_table()
        self._update_charts()

    def _export_csv(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Session History",
            "",
            "CSV Files (*.csv);;All Files (*.*)",
        )
        if not path:
            return False

        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["day", "cards", "avg_seconds", "again_percent", "retention_percent", "super_mature_retention", "warning_events"])
                for entry in self._filtered_history():
                    writer.writerow(
                        [
                            format_history_day(int(entry.get("day", 0))),
                            int(entry.get("cards", 0)),
                            f"{float(entry.get('avg_seconds', 0.0)):.2f}",
                            f"{float(entry.get('again', 0.0)):.2f}",
                            f"{float(entry.get('retention', 0.0)):.2f}",
                            f"{float(entry.get('super_mature_retention', 0.0)):.2f}",
                            int(entry.get("warning_events", 0)),
                        ]
                    )
            QMessageBox.information(self, "Export complete", f"History exported to:\n{path}")
            return True
        except Exception as err:
            QMessageBox.warning(self, "Export failed", f"Could not export history:\n{err}")
            return False

    def _clear_history(self) -> None:
        if mw.pm is None:
            return
        confirm = QMessageBox.question(
            self,
            "Clear history",
            "Remove all stored progress history?",
            _message_box_button("Yes") | _message_box_button("No"),
            _message_box_button("No"),
        )
        if confirm != _message_box_button("Yes"):
            return

        profile = getattr(mw.pm, "profile", None)
        if isinstance(profile, dict):
            profile[HISTORY_PROGRESS_KEY] = []
            mw.pm.save()
        self._reload()

    def _export_then_clear(self) -> None:
        if self._export_csv():
            self._clear_history()

    def _resolve_palette(self) -> Dict[str, str]:
        try:
            from .reviewer_progress_bar import _ui_palette

            return _ui_palette()
        except Exception:
            return {
                "window_bg": "#ffffff",
                "primary_text": "#111827",
                "secondary_text": "#1f2937",
                "muted_text": "#4b5563",
                "tab_border": "#e5e7eb",
                "tab_selected_bg": "#f3f4f6",
                "tab_selected_text": "#111827",
                "tab_hover_bg": "#e5e7eb",
                "tab_unselected_text": "#4b5563",
                "tab_selected_bottom": "#2563eb",
                "card_bg": "#ffffff",
                "card_border": "#e5e7eb",
                "field_border": "#e5e7eb",
                "tab_selected_border": "#e5e7eb",
            }


class TrendChartWidget(QWidget):
    def __init__(self, title: str, palette: Dict[str, str], accent: str, parent: Optional[QWidget] = None) -> None:
        super().__init__()
        self._title = title
        self._palette = palette
        self._accent = QColor(accent)
        self._points: List[Tuple[int, float]] = []

        if hasattr(self, "setMinimumHeight"):
            self.setMinimumHeight(150)
        if hasattr(self, "setSizePolicy"):
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        if hasattr(self, "setAutoFillBackground"):
            self.setAutoFillBackground(True)
        if hasattr(self, "setAccessibleName"):
            self.setAccessibleName(title)
        focus_policy = _focus_policy("StrongFocus")
        if focus_policy is not None and hasattr(self, "setFocusPolicy"):
            self.setFocusPolicy(focus_policy)
        self._sync_accessible_summary()

    def set_points(self, points: Sequence[Tuple[int, float]]) -> None:
        self._points = list(points)
        self._sync_accessible_summary()
        self.update()

    def _sync_accessible_summary(self) -> None:
        if not self._points:
            summary = f"{self._title}: no data yet."
        else:
            values = [point[1] for point in self._points]
            summary = (
                f"{self._title}: {len(values)} point{'s' if len(values) != 1 else ''}, "
                f"from {format_history_day(int(self._points[0][0]))} to {format_history_day(int(self._points[-1][0]))}, "
                f"minimum {min(values):.1f}, maximum {max(values):.1f}, latest {values[-1]:.1f}."
            )
        if hasattr(self, "setAccessibleDescription"):
            self.setAccessibleDescription(summary)
        if hasattr(self, "setToolTip"):
            self.setToolTip(summary)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        painter.fillRect(rect, QColor(self._palette["card_bg"]))

        margin = 14
        title_height = 18
        area = rect.adjusted(margin, margin + title_height, -margin, -margin * 2)

        title_pen = QPen(QColor(self._palette["primary_text"]))
        title_pen.setWidth(1)
        painter.setPen(title_pen)
        painter.drawText(rect.adjusted(margin, margin, -margin, 0), 0, self._title)

        if not self._points:
            painter.setPen(QPen(QColor(self._palette["muted_text"])))
            painter.drawText(area, int(Qt.AlignmentFlag.AlignCenter), "No data yet")
            return

        values = [pt[1] for pt in self._points]
        v_min = min(values)
        v_max = max(values)
        if abs(v_max - v_min) < 1e-6:
            v_min -= 1
            v_max += 1

        x_count = max(len(self._points) - 1, 1)
        left = area.left()
        right = area.right()
        top = area.top()
        bottom = area.bottom()

        baseline_pen = QPen(QColor(self._palette["tab_border"]))
        baseline_pen.setWidth(1)
        painter.setPen(baseline_pen)
        painter.drawRect(area)

        line_pen = QPen(self._accent)
        line_pen.setWidth(2)
        painter.setPen(line_pen)

        points = []
        for idx, (_, value) in enumerate(self._points):
            ratio_x = idx / float(x_count)
            ratio_y = (value - v_min) / float(v_max - v_min) if v_max != v_min else 0.5
            x = left + ratio_x * (right - left)
            y = bottom - ratio_y * (bottom - top)
            points.append((x, y))

        for start, end in zip(points, points[1:]):
            painter.drawLine(int(start[0]), int(start[1]), int(end[0]), int(end[1]))

        point_pen = QPen(self._accent)
        point_pen.setWidth(5)
        painter.setPen(point_pen)
        for x, y in points:
            painter.drawPoint(int(x), int(y))

        label_pen = QPen(QColor(self._palette["muted_text"]))
        painter.setPen(label_pen)
        start_day = format_history_day(int(self._points[0][0]))
        end_day = format_history_day(int(self._points[-1][0]))
        painter.drawText(rect.adjusted(margin, 0, -margin, -margin), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom), start_day)
        painter.drawText(rect.adjusted(margin, 0, -margin, -margin), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom), end_day)


__all__ = [
    "HISTORY_PROGRESS_KEY",
    "SessionHistoryDialog",
    "calculate_today_history_entry",
    "format_history_day",
    "read_history_records",
    "update_daily_history",
]
