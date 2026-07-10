import sys
import types
from typing import Any, Dict, List, Optional, Sequence, Tuple


class HookList(list):
    def append(self, func):  # type: ignore[override]
        super().append(func)
        return func

    def connect(self, func):
        return self.append(func)

    def emit(self, *args, **kwargs):
        self(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        for func in list(self):
            func(*args, **kwargs)


def pyqtSignal(*_args, **_kwargs):
    return HookList()


class GuiHooks:
    def __init__(self) -> None:
        self.main_window_did_init = HookList()
        self.state_did_change = HookList()
        self.reviewer_did_show_question = HookList()
        self.profile_did_open = HookList()
        self.profile_will_close = HookList()


class QColor:
    def __init__(self, *args: Any) -> None:
        if len(args) == 1 and isinstance(args[0], QColor):
            self.value = args[0].value
            self.alpha_f = getattr(args[0], "alpha_f", 1.0)
        elif len(args) >= 3:
            self.value = tuple(int(arg) for arg in args[:3])
            self.alpha_f = 1.0
        elif args:
            self.value = args[0]
            self.alpha_f = 1.0
        else:
            self.value = "#000000"
            self.alpha_f = 1.0

    def name(self) -> str:
        return str(self.value)

    def isValid(self) -> bool:
        return True

    def setAlphaF(self, alpha: float) -> None:
        self.alpha_f = alpha

    def setAlpha(self, alpha: int) -> None:
        self.alpha_f = alpha / 255


class QPalette:
    class ColorGroup:
        Active = 0
        Inactive = 1
        Disabled = 2

    class ColorRole:
        Base = 0
        Highlight = 1
        Button = 2
        WindowText = 3
        Window = 4
        Text = 5
        ButtonText = 6
        HighlightedText = 7

    def __init__(self, other: Optional["QPalette"] = None) -> None:
        self.colors: Dict[Any, QColor] = {}
        if isinstance(other, QPalette):
            self.colors = dict(other.colors)

    def setColor(self, *args: Any) -> None:
        if len(args) == 2:
            role, color = args
            self.colors[role] = color
            return
        group, role, color = args
        self.colors[(group, role)] = color

    def color(self, *args: Any) -> QColor:
        if len(args) == 1:
            role = args[0]
            return self.colors.get(role, self.colors.get((self.ColorGroup.Active, role), QColor("#000000")))
        group, role = args
        return self.colors.get((group, role), self.colors.get(role, QColor("#000000")))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QPalette):
            return False
        return self.colors == other.colors


class QBrush:
    def __init__(self, color: Any) -> None:
        self.color = color


class QRect:
    def __init__(self, left: int, top: int, width: int, height: int) -> None:
        self._left = left
        self._top = top
        self._width = width
        self._height = height

    def left(self) -> int:
        return self._left

    def top(self) -> int:
        return self._top

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def adjusted(self, dx1: int, dy1: int, dx2: int, dy2: int) -> "QRect":
        return QRect(
            self._left + dx1,
            self._top + dy1,
            self._width + dx2 - dx1,
            self._height + dy2 - dy1,
        )


class Qt:
    class DockWidgetArea:
        TopDockWidgetArea = 1
        BottomDockWidgetArea = 2
        LeftDockWidgetArea = 3
        RightDockWidgetArea = 4

    class Orientation:
        Horizontal = 1
        Vertical = 2

    class ShortcutContext:
        ApplicationShortcut = 1

    class ScrollBarPolicy:
        ScrollBarAlwaysOff = 1
        ScrollBarAsNeeded = 2

    class ArrowType:
        RightArrow = 1
        DownArrow = 2

    class ToolButtonStyle:
        ToolButtonTextBesideIcon = 1

    class CursorShape:
        PointingHandCursor = 1

    class WidgetAttribute:
        WA_DeleteOnClose = 1

    class FocusPolicy:
        StrongFocus = 1
        ClickFocus = 2

    class MouseButton:
        LeftButton = 1
        RightButton = 2

    class Key:
        Key_Return = 16777220
        Key_Enter = 16777221
        Key_Space = 32

    class ItemDataRole:
        UserRole = 32

    class AlignmentFlag:
        AlignCenter = 0
        AlignLeft = 0
        AlignRight = 0
        AlignBottom = 0
        AlignVCenter = 0


class QSize:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height


class QFont:
    def __init__(self, other: Optional["QFont"] = None) -> None:
        self._bold = bool(getattr(other, "_bold", False))

    def setBold(self, bold: bool) -> None:
        self._bold = bool(bold)

    def bold(self) -> bool:
        return self._bold


class QUrl:
    def __init__(self, url: str) -> None:
        self.url = url

    def toString(self) -> str:
        return self.url


class QIcon:
    def __init__(self, path: str = "") -> None:
        self.path = getattr(path, "path", path)


class QPixmap:
    def __init__(self, path: str = "") -> None:
        self.path = path

    def isNull(self) -> bool:
        return not bool(self.path)


class QDesktopServices:
    last_url: Optional[QUrl] = None

    @staticmethod
    def openUrl(url: QUrl) -> bool:
        QDesktopServices.last_url = url
        return True


class QWidget:
    def __init__(self, parent: Optional["QWidget"] = None) -> None:
        self._parent: Optional["QWidget"] = None
        self._layout = None
        self._object_name = ""
        self._style_sheet = ""
        self._children: List["QWidget"] = []
        self._visible = True
        self._enabled = True
        if parent is not None:
            self.setParent(parent)

    def setParent(self, parent: "QWidget") -> None:
        self._parent = parent

    def parentWidget(self) -> Optional["QWidget"]:
        return self._parent

    def setLayout(self, layout: Any) -> None:
        self._layout = layout

    def setObjectName(self, name: str) -> None:
        self._object_name = name

    def objectName(self) -> str:
        return self._object_name

    def setStyleSheet(self, style: str) -> None:
        self._style_sheet = style

    def styleSheet(self) -> str:
        return self._style_sheet

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def isEnabled(self) -> bool:
        return getattr(self, "_enabled", True)

    def installEventFilter(self, flt: Any) -> None:
        self._event_filters = getattr(self, "_event_filters", [])
        self._event_filters.append(flt)

    def setFocus(self) -> None:
        self._has_focus = True

    def clearFocus(self) -> None:
        self._has_focus = False

    def hasFocus(self) -> bool:
        return getattr(self, "_has_focus", False)

    def setPalette(self, palette: QPalette) -> None:
        self._palette = palette

    def palette(self) -> Optional[QPalette]:
        return getattr(self, "_palette", None)

    def setAutoFillBackground(self, enabled: bool) -> None:
        self._auto_fill_background = enabled

    def setToolTip(self, text: str) -> None:
        self._tooltip = text

    def toolTip(self) -> str:
        return getattr(self, "_tooltip", "")

    def addChild(self, child: "QWidget") -> None:
        self._children.append(child)
        child.setParent(self)

    def findChildren(self, klass=None) -> List["QWidget"]:
        if klass is None:
            return list(self._children)
        return [c for c in self._children if isinstance(c, klass)]

    def update(self) -> None:
        self._update_calls = getattr(self, "_update_calls", 0) + 1

    def show(self) -> None:
        self._visible = True

    def hide(self) -> None:
        self._visible = False

    def close(self) -> None:
        self._visible = False
        self._closed = True

    def raise_(self) -> None:
        self._raised = True

    def activateWindow(self) -> None:
        self._activated = True

    def setVisible(self, visible: bool) -> None:
        self._visible = visible

    def isVisible(self) -> bool:
        return getattr(self, "_visible", True)

    def width(self) -> int:
        return getattr(self, "_width", 100)

    def height(self) -> int:
        return getattr(self, "_height", 100)

    def resize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def setFixedWidth(self, width: int) -> None:
        self._width = width

    def setFixedSize(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def setMinimumSize(self, width: int, height: int) -> None:
        self._minimum_width = width
        self._minimum_height = height

    def setMinimumWidth(self, width: int) -> None:
        self._minimum_width = width
        self._width = max(getattr(self, "_width", 0), width)

    def setMinimumHeight(self, height: int) -> None:
        self._minimum_height = height

    def setAttribute(self, attr: Any, value: bool = True) -> None:
        self._attribute = (attr, value)

    def setAccessibleName(self, text: str) -> None:
        self._accessible_name = text

    def setAccessibleDescription(self, text: str) -> None:
        self._accessible_description = text

    def setFocusPolicy(self, policy: Any) -> None:
        self._focus_policy = policy

    def setCursor(self, cursor: Any) -> None:
        self._cursor = cursor

    def setMouseTracking(self, enabled: bool) -> None:
        self._mouse_tracking = enabled

    def deleteLater(self) -> None:
        self._deleted = True


class QAction(QWidget):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__()
        self.text = text
        self._shortcut = QKeySequence("")
        self._menu: Optional["QMenu"] = None
        self.triggered = HookList()

    def shortcut(self) -> "QKeySequence":
        return self._shortcut

    def setShortcut(self, sequence: "QKeySequence") -> None:
        self._shortcut = sequence

    def menu(self) -> Optional["QMenu"]:
        return self._menu


class QMenu(QWidget):
    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self.actions: List[QAction] = []
        self.submenus: List["QMenu"] = []

    def title(self) -> str:
        return self._title

    def addAction(self, action_or_text: Any) -> QAction:
        if isinstance(action_or_text, QAction):
            action = action_or_text
        else:
            action = QAction(str(action_or_text), self)
        self.actions.append(action)
        return action

    def addMenu(self, menu_or_title: Any) -> "QMenu":
        if isinstance(menu_or_title, QMenu):
            submenu = menu_or_title
        else:
            submenu = QMenu(str(menu_or_title), self)
        action = QAction(submenu.title(), self)
        action._menu = submenu
        self.actions.append(action)
        self.submenus.append(submenu)
        return submenu


class QDockWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._title_bar_widget: Optional[QWidget] = None

    def setWidget(self, widget: QWidget) -> None:
        self._widget = widget
        self.addChild(widget)

    def widget(self) -> Optional[QWidget]:
        return self._widget

    def setTitleBarWidget(self, widget: QWidget) -> None:
        self._title_bar_widget = widget


class QProgressBar(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__()
        self._format = ""
        self._range: Tuple[int, int] = (0, 0)
        self._value = 0
        self._orientation = Qt.Orientation.Horizontal
        self._inverted = False
        self._text_visible = True
        self._style = None
        self._palette: Optional[QPalette] = None
        self._event_filters: List[Any] = []

    def setTextVisible(self, visible: bool) -> None:
        self._text_visible = visible

    def setInvertedAppearance(self, inverted: bool) -> None:
        self._inverted = inverted

    def invertedAppearance(self) -> bool:
        return self._inverted

    def setOrientation(self, orientation: int) -> None:
        self._orientation = orientation

    def orientation(self) -> int:
        return self._orientation

    def setRange(self, minimum: int, maximum: int) -> None:
        self._range = (minimum, maximum)

    def setValue(self, value: int) -> None:
        self._value = value

    def setFormat(self, fmt: str) -> None:
        self._format = fmt

    def format(self) -> str:
        return self._format

    def setStyle(self, style: Any) -> None:
        self._style = style

    def setPalette(self, palette: QPalette) -> None:
        self._palette = palette

    def palette(self) -> Optional[QPalette]:
        return self._palette

    def installEventFilter(self, flt: Any) -> None:
        self._event_filters.append(flt)


class QStyleFactory:
    @staticmethod
    def create(name: str) -> None:
        return None


class QClipboard:
    def __init__(self) -> None:
        self._text = ""

    def setText(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class QApplication:
    _clipboard = QClipboard()

    @staticmethod
    def clipboard() -> QClipboard:
        return QApplication._clipboard


class QKeySequence:
    def __init__(self, key: str) -> None:
        self.key = key

    class SequenceMatch:
        ExactMatch = 1

    def toString(self) -> str:
        return self.key

    def isEmpty(self) -> bool:
        return not bool(self.key)

    def matches(self, other: "QKeySequence") -> int:
        return self.SequenceMatch.ExactMatch if self.key == other.key else 0


class QKeySequenceEdit(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._sequence = QKeySequence("")
        self.keySequenceChanged = HookList()
        self._native_editor_child = QWidget()
        self._native_editor_child.setObjectName("qt_keysequenceedit_lineedit")
        self.addChild(self._native_editor_child)

    def setClearButtonEnabled(self, enabled: bool) -> None:
        self._clear_enabled = enabled

    def setMaximumSequenceLength(self, length: int) -> None:
        self._maximum_sequence_length = length

    def setKeySequence(self, sequence: QKeySequence) -> None:
        self._sequence = sequence
        self.keySequenceChanged(sequence)

    def keySequence(self) -> QKeySequence:
        return self._sequence


class QShortcut(QWidget):
    def __init__(self, sequence: QKeySequence, parent: QWidget) -> None:
        super().__init__()
        self.sequence = sequence
        self.parent = parent
        self._context = None
        self.activated = HookList()

    def setContext(self, context: Any) -> None:
        self._context = context

    def setKey(self, sequence: QKeySequence) -> None:
        self.sequence = sequence

    def key(self) -> QKeySequence:
        return self.sequence


class QDialog(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__()
        self.parent = parent
        self._window_title = ""
        self._minimum_width = 0

    def setWindowTitle(self, title: str) -> None:
        self._window_title = title

    def setModal(self, modal: bool) -> None:
        self._modal = modal

    def setMinimumWidth(self, width: int) -> None:
        super().setMinimumWidth(width)
        self._minimum_width = width

    def exec(self) -> int:
        return 0

    def accept(self) -> None:
        self._accepted = True

    def reject(self) -> None:
        self._rejected = True


class QLayout:
    def __init__(self) -> None:
        self.items: List[Any] = []
        self._spacing = 0
        self._margins = (0, 0, 0, 0)

    def setSpacing(self, spacing: int) -> None:
        self._spacing = spacing

    def setContentsMargins(self, *margins: int) -> None:
        self._margins = margins

    def addWidget(self, widget: QWidget, *args: Any) -> None:
        self.items.append(widget)

    def addLayout(self, layout: "QLayout", *args: Any) -> None:
        self.items.append(layout)

    def addStretch(self, stretch: int = 0) -> None:
        self.items.append(("stretch", stretch))


class QVBoxLayout(QLayout):
    pass


class QHBoxLayout(QLayout):
    pass


class QLabel(QWidget):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._text = text
        self._word_wrap = False

    def setWordWrap(self, wrap: bool) -> None:
        self._word_wrap = wrap

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text


class QFrame(QWidget):
    class Shape:
        StyledPanel = 0
        HLine = 1
        NoFrame = 2

    class Shadow:
        Sunken = 1

    def setFrameShape(self, shape: Any) -> None:
        self._shape = shape

    def setFrameShadow(self, shadow: Any) -> None:
        self._shadow = shadow


class QTabWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._document_mode = False

    def setDocumentMode(self, mode: bool) -> None:
        self._document_mode = mode


class QAbstractItemView:
    class SelectionBehavior:
        SelectRows = 0

    class EditTrigger:
        NoEditTriggers = 0

    class SelectionMode:
        SingleSelection = 1


class QTableWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._columns = 0
        self._rows = 0
        self._headers: List[str] = []
        self.items: Dict[Tuple[int, int], "QTableWidgetItem"] = {}
        self._vertical_header = QWidget()

    def setColumnCount(self, count: int) -> None:
        self._columns = count

    def setHorizontalHeaderLabels(self, labels: Sequence[str]) -> None:
        self._headers = list(labels)

    def horizontalHeader(self) -> "QTableWidget":
        return self

    def verticalHeader(self) -> QWidget:
        return self._vertical_header

    def setStretchLastSection(self, value: bool) -> None:
        self._stretch_last = value

    def setSelectionBehavior(self, behavior: Any) -> None:
        self._selection_behavior = behavior

    def setEditTriggers(self, triggers: Any) -> None:
        self._edit_triggers = triggers

    def setAlternatingRowColors(self, value: bool) -> None:
        self._alternating_rows = value

    def setRowCount(self, count: int) -> None:
        self._rows = count

    def setItem(self, row: int, column: int, item: "QTableWidgetItem") -> None:
        self.items[(row, column)] = item

    def resizeColumnsToContents(self) -> None:
        pass


class QTableWidgetItem:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class QPushButton(QWidget):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.text = text
        self.clicked = HookList()

    def setText(self, text: str) -> None:
        self.text = text

    def setDefault(self, value: bool) -> None:
        self._default = value


class QToolButton(QPushButton):
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.toggled = HookList()
        self._checked = False

    def setAutoRaise(self, value: bool) -> None:
        self._auto_raise = value

    def setCheckable(self, value: bool) -> None:
        self._checkable = value

    def setChecked(self, value: bool) -> None:
        self._checked = bool(value)
        self.toggled(self._checked)

    def isChecked(self) -> bool:
        return self._checked

    def setArrowType(self, arrow: Any) -> None:
        self._arrow = arrow

    def setToolButtonStyle(self, style: Any) -> None:
        self._tool_button_style = style

    def setIcon(self, icon: QIcon) -> None:
        self._icon = icon

    def setIconSize(self, size: QSize) -> None:
        self._icon_size = size


class QComboBox(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._items: List[Tuple[str, Any]] = []
        self._current_index = 0
        self.currentIndexChanged = HookList()

    def addItem(self, text: str, userData: Any = None) -> None:
        self._items.append((text, userData))

    def findData(self, data: Any) -> int:
        for idx, (_, value) in enumerate(self._items):
            if value == data:
                return idx
        return -1

    def setCurrentIndex(self, index: int) -> None:
        self._current_index = index
        self.currentIndexChanged(index)

    def currentIndex(self) -> int:
        return self._current_index

    def currentData(self) -> Any:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index][1]
        return None


class QHeaderView(QWidget):
    class ResizeMode:
        Stretch = 0
        ResizeToContents = 1
        Interactive = 2

    def setStretchLastSection(self, value: bool) -> None:
        self._stretch_last = value

    def setSectionResizeMode(self, section: int, mode: Any) -> None:
        self._section_resize = getattr(self, "_section_resize", {})
        self._section_resize[section] = mode

    def setMinimumSectionSize(self, size: int) -> None:
        self._minimum_section_size = size


class QStyledItemDelegate(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

    def paint(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def sizeHint(self, *_args: Any, **_kwargs: Any) -> QSize:
        return QSize(170, 30)

    def initStyleOption(self, *_args: Any, **_kwargs: Any) -> None:
        pass


class QTreeWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._header = QHeaderView()
        self._items: List["QTreeWidgetItem"] = []
        self._current_item: Optional["QTreeWidgetItem"] = None
        self._headers: List[str] = []
        self._column_widths: Dict[int, int] = {}

    def setRootIsDecorated(self, value: bool) -> None:
        self._root_decorated = value

    def setUniformRowHeights(self, value: bool) -> None:
        self._uniform_rows = value

    def setAlternatingRowColors(self, value: bool) -> None:
        self._alternating_rows = value

    def setAllColumnsShowFocus(self, value: bool) -> None:
        self._all_columns_show_focus = value

    def setIndentation(self, value: int) -> None:
        self._indentation = value

    def setTextElideMode(self, mode: Any) -> None:
        self._text_elide_mode = mode

    def setHorizontalScrollBarPolicy(self, policy: Any) -> None:
        self._horizontal_scrollbar_policy = policy

    def setVerticalScrollBarPolicy(self, policy: Any) -> None:
        self._vertical_scrollbar_policy = policy

    def setHeaderLabels(self, labels: Sequence[str]) -> None:
        self._headers = list(labels)

    def header(self) -> QHeaderView:
        return self._header

    def clear(self) -> None:
        self._items.clear()
        self._current_item = None

    def currentItem(self) -> Optional["QTreeWidgetItem"]:
        return self._current_item

    def setCurrentItem(self, item: "QTreeWidgetItem") -> None:
        self._current_item = item

    def expandToDepth(self, depth: int) -> None:
        self._expanded_to = depth

    def resizeColumnToContents(self, column: int) -> None:
        self._resized_columns = getattr(self, "_resized_columns", [])
        self._resized_columns.append(column)
        texts = [self._headers[column] if column < len(self._headers) else ""]

        def collect(item: "QTreeWidgetItem") -> None:
            texts.append(item.text(column))
            for child in item.children:
                collect(child)

        for item in self._items:
            collect(item)
        self._column_widths[column] = max(72, max((len(text) for text in texts), default=0) * 8 + 28)

    def setColumnWidth(self, column: int, width: int) -> None:
        self._column_widths[column] = width

    def columnWidth(self, column: int) -> int:
        return self._column_widths.get(column, 100)

    def viewport(self) -> "QTreeWidget":
        return self

    def setItemDelegateForColumn(self, column: int, delegate: Any) -> None:
        self._delegates = getattr(self, "_delegates", {})
        self._delegates[column] = delegate


class QTreeWidgetItem:
    def __init__(self, parent: Optional[Any] = None) -> None:
        self._texts: Dict[int, str] = {}
        self._data: Dict[Tuple[int, int], Any] = {}
        self._alignments: Dict[int, Any] = {}
        self._fonts: Dict[int, QFont] = {}
        self.children: List["QTreeWidgetItem"] = []
        if isinstance(parent, QTreeWidget):
            parent._items.append(self)
        elif isinstance(parent, QTreeWidgetItem):
            parent.children.append(self)

    def setText(self, column: int, text: str) -> None:
        self._texts[column] = text

    def text(self, column: int) -> str:
        return self._texts.get(column, "")

    def setData(self, column: int, role: int, value: Any) -> None:
        self._data[(column, role)] = value

    def data(self, column: int, role: int) -> Any:
        return self._data.get((column, role))

    def setTextAlignment(self, column: int, alignment: Any) -> None:
        self._alignments[column] = alignment

    def font(self, column: int) -> QFont:
        return QFont(self._fonts.get(column))

    def setFont(self, column: int, font: QFont) -> None:
        self._fonts[column] = QFont(font)

    def setToolTip(self, column: int, text: str) -> None:
        self._tooltips = getattr(self, "_tooltips", {})
        self._tooltips[column] = text

    def toolTip(self, column: int) -> str:
        return getattr(self, "_tooltips", {}).get(column, "")

    def setForeground(self, column: int, brush: Any) -> None:
        self._foregrounds = getattr(self, "_foregrounds", {})
        self._foregrounds[column] = brush


class QSpinBox(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._value = 0
        self._range = (0, 0)
        self.valueChanged = HookList()

    def setRange(self, minimum: int, maximum: int) -> None:
        self._range = (minimum, maximum)

    def setValue(self, value: int) -> None:
        self._value = value
        self.valueChanged(value)

    def value(self) -> int:
        return self._value

    def setSuffix(self, suffix: str) -> None:
        self._suffix = suffix

    def setPrefix(self, prefix: str) -> None:
        self._prefix = prefix


class QLineEdit(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._text = ""
        self._placeholder = ""
        self.textChanged = HookList()

    def setPlaceholderText(self, text: str) -> None:
        self._placeholder = text

    def setText(self, text: str) -> None:
        self._text = text
        self.textChanged(text)

    def text(self) -> str:
        return self._text

    def clear(self) -> None:
        self.setText("")


class QDoubleSpinBox(QSpinBox):
    def setRange(self, minimum: float, maximum: float) -> None:
        self._range = (minimum, maximum)

    def setSingleStep(self, step: float) -> None:
        self._step = step


class QCheckBox(QWidget):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.text = text
        self._checked = False
        self.toggled = HookList()

    def setChecked(self, value: bool) -> None:
        self._checked = bool(value)
        self.toggled(self._checked)

    def isChecked(self) -> bool:
        return self._checked

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = enabled


class QAbstractButton(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._text = ""

    def setText(self, text: str) -> None:
        self._text = text


class QDialogButtonBox(QWidget):
    class StandardButton:
        Ok = 1
        Cancel = 2

    def __init__(self, _buttons: int = 0) -> None:
        super().__init__()
        self.accepted = HookList()
        self.rejected = HookList()
        self._buttons = {
            self.StandardButton.Ok: QAbstractButton(),
            self.StandardButton.Cancel: QAbstractButton(),
        }

    def button(self, which: int) -> Optional[QAbstractButton]:
        return self._buttons.get(which)


class QStackedWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._widgets: List[QWidget] = []
        self._current_index = 0

    def addWidget(self, widget: QWidget) -> None:
        self._widgets.append(widget)
        self.addChild(widget)

    def count(self) -> int:
        return len(self._widgets)

    def setCurrentIndex(self, index: int) -> None:
        self._current_index = index


class QListWidgetItem:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class QListWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._items: List[QListWidgetItem] = []
        self._current_item: Optional[QListWidgetItem] = None
        self._hidden_rows: Dict[int, bool] = {}
        self.currentRowChanged = HookList()

    def setSelectionMode(self, mode: Any) -> None:
        self._selection_mode = mode

    def setHorizontalScrollBarPolicy(self, policy: Any) -> None:
        self._scrollbar_policy = policy

    def setSpacing(self, spacing: int) -> None:
        self._spacing = spacing

    def addItem(self, item: QListWidgetItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def item(self, index: int) -> QListWidgetItem:
        return self._items[index]

    def setCurrentItem(self, item: QListWidgetItem) -> None:
        self._current_item = item
        if item in self._items:
            self.currentRowChanged(self._items.index(item))

    def currentItem(self) -> Optional[QListWidgetItem]:
        return self._current_item

    def setRowHidden(self, index: int, hidden: bool) -> None:
        self._hidden_rows[index] = hidden


class QScrollArea(QFrame):
    def setWidgetResizable(self, resizable: bool) -> None:
        self._widget_resizable = resizable

    def setWidget(self, widget: QWidget) -> None:
        self._widget = widget
        self.addChild(widget)


class QColorDialog:
    @staticmethod
    def getColor(initial: QColor, parent: QWidget, title: str) -> QColor:
        return initial


class QFileDialog:
    next_path: str = ""

    @staticmethod
    def getSaveFileName(parent: QWidget, _caption: str, _directory: str, _filter: str):
        return QFileDialog.next_path, None


class QMessageBox:
    class StandardButton:
        Yes = 1
        No = 0

    @staticmethod
    def information(parent: QWidget, title: str, text: str) -> None:
        parent._last_message = ("information", title, text)

    @staticmethod
    def warning(parent: QWidget, title: str, text: str) -> None:
        parent._last_message = ("warning", title, text)

    @staticmethod
    def question(parent: QWidget, title: str, text: str, _buttons: int, default: int):
        parent._last_message = ("question", title, text)
        return default


class QStyleOptionProgressBar:
    def __init__(self) -> None:
        self.rect = QRect(0, 0, 0, 0)
        self.palette = QPalette()


class QStylePainter:
    def __init__(self, widget: QWidget) -> None:
        self.widget = widget

    def drawControl(self, _element: Any, option: QStyleOptionProgressBar) -> None:
        pass


class QStyle:
    class ControlElement:
        CE_ProgressBarLabel = 0


class QObject(QWidget):
    def eventFilter(self, obj: QWidget, event: Any) -> bool:
        return False


class QEvent:
    class Type:
        ToolTip = 0
        MouseButtonRelease = 1
        ContextMenu = 2
        KeyPress = 3
        MouseButtonPress = 4
        FocusIn = 5
        FocusOut = 6

    def __init__(self, type_value: int = 0, *, button: Optional[int] = None, key: Optional[int] = None) -> None:
        self._type = type_value
        self._button = button
        self._key = key
        self._accepted = False

    def type(self) -> int:
        return self._type

    def button(self) -> Optional[int]:
        return self._button

    def key(self) -> Optional[int]:
        return self._key

    def accept(self) -> None:
        self._accepted = True


class QHelpEvent(QEvent):
    def __init__(self, pos: Any = None, global_pos: Any = None) -> None:
        super().__init__(QEvent.Type.ToolTip)
        self._pos = pos or types.SimpleNamespace(x=lambda: 0)
        self._global_pos = global_pos or types.SimpleNamespace()

    def position(self):
        return self._pos

    def pos(self):
        return self._pos

    def globalPos(self):
        return self._global_pos


class QToolTip:
    last_text: Optional[str] = None

    @staticmethod
    def showText(pos: Any, text: str, widget: QWidget) -> None:
        QToolTip.last_text = text


class QPainter:
    def __init__(self, widget: Optional[QWidget] = None) -> None:
        self.widget = widget
        self.filled: List[Tuple[QRect, Any]] = []

    def fillRect(self, rect: QRect, brush: Any) -> None:
        self.filled.append((rect, brush))


class ThemeManagerStub:
    def __init__(self) -> None:
        self.night_mode = False


class AddonManagerStub:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.get_calls: List[str] = []
        self.write_calls: List[Tuple[str, Dict[str, Any]]] = []
        self.missing_package_ids = {"1097423555"}

    def getConfig(self, name: str) -> Dict[str, Any]:
        self.get_calls.append(name)
        return dict(self.config)

    def writeConfig(self, name: str, config: Dict[str, Any]) -> None:
        if name in self.missing_package_ids or name.split(".", 1)[0] == "addon":
            raise FileNotFoundError("[Errno 2] No such file or directory: 'addons21/addon/meta.json'")
        self.write_calls.append((name, dict(config)))
        self.config = dict(config)

    def addonConfigDefaults(self, name: str) -> Dict[str, Any]:
        return dict(self.config)


class MenuToolsStub(QMenu):
    def __init__(self) -> None:
        super().__init__("Tools")


class ProfileManagerStub:
    def __init__(self) -> None:
        self.profile: Dict[str, Any] = {}

    def save(self) -> None:
        self.saved = True


class SchedulerStub:
    def __init__(self) -> None:
        self.day_cutoff = 0
        self._deck_tree = DeckNode(0, [])

    def deck_due_tree(self):
        return self._deck_tree


class CollectionStub:
    def __init__(self) -> None:
        self.db: Any = None
        self.sched = SchedulerStub()
        self.decks = types.SimpleNamespace(current=lambda: {"id": 0})


class MainWindowStub(QWidget):
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__()
        self.addonManager = AddonManagerStub(config)
        self.col = CollectionStub()
        self.pm = ProfileManagerStub()
        self.form = types.SimpleNamespace(menuTools=MenuToolsStub(), menubar=QMenu("Menu Bar"))
        self.web = types.SimpleNamespace(setFocus=lambda: None)
        self.docks: List[QDockWidget] = []
        self.dock_areas: Dict[QDockWidget, int] = {}

    def findChildren(self, klass=None) -> List[QWidget]:  # type: ignore[override]
        if klass is None:
            return list(self.docks)
        return [dock for dock in self.docks if isinstance(dock, klass)]

    def dockWidgetArea(self, dock: QDockWidget) -> int:
        return self.dock_areas.get(dock, Qt.DockWidgetArea.TopDockWidgetArea)

    def addDockWidget(self, area: int, dock: QDockWidget) -> None:
        self.docks.append(dock)
        self.dock_areas[dock] = area

    def setDockNestingEnabled(self, enabled: bool) -> None:
        self.nesting_enabled = enabled

    def splitDockWidget(self, first: QDockWidget, second: QDockWidget, orientation: int) -> None:
        self.last_split = (first, second, orientation)

    def removeDockWidget(self, dock: QDockWidget) -> None:
        if dock in self.docks:
            self.docks.remove(dock)
            self.dock_areas.pop(dock, None)

    def setPalette(self, palette: QPalette) -> None:
        self._palette = palette

    def setStyleSheet(self, style: str) -> None:
        self._style_sheet = style


class DeckNode:
    def __init__(self, deck_id: int, children: Optional[List["DeckNode"]] = None) -> None:
        self.deck_id = deck_id
        self.children: List["DeckNode"] = children or []
        self.review_count = 0
        self.learn_count = 0
        self.new_count = 0


def _ensure_module(name: str, module: types.ModuleType) -> types.ModuleType:
    sys.modules[name] = module
    return module


def install_stubs(config: Optional[Dict[str, Any]] = None) -> MainWindowStub:
    aqt = sys.modules.get("aqt", types.ModuleType("aqt"))
    utils = types.ModuleType("aqt.utils")
    theme = types.ModuleType("aqt.theme")
    theme.theme_manager = ThemeManagerStub()

    def tooltip(message: str, parent: Optional[QWidget] = None, period: int = 0) -> str:
        if parent is not None:
            parent._last_tooltip = (message, period)
        return message

    QDesktopServices.last_url = None
    utils.tooltip = tooltip
    qt = types.ModuleType("aqt.qt")
    qt.__dict__.update(
        {
            "QDesktopServices": QDesktopServices,
            "QIcon": QIcon,
            "QPixmap": QPixmap,
            "QSize": QSize,
            "QFont": QFont,
            "QUrl": QUrl,
            "QColor": QColor,
            "QBrush": QBrush,
            "QPalette": QPalette,
            "QProgressBar": QProgressBar,
            "QDockWidget": QDockWidget,
            "QWidget": QWidget,
            "Qt": Qt,
            "QStyleFactory": QStyleFactory,
            "QApplication": QApplication,
            "QClipboard": QClipboard,
            "QKeySequence": QKeySequence,
            "QKeySequenceEdit": QKeySequenceEdit,
            "QShortcut": QShortcut,
            "QDialog": QDialog,
            "QVBoxLayout": QVBoxLayout,
            "QHBoxLayout": QHBoxLayout,
            "QLabel": QLabel,
            "QTableWidget": QTableWidget,
            "QTableWidgetItem": QTableWidgetItem,
            "QAbstractItemView": QAbstractItemView,
            "QFileDialog": QFileDialog,
            "QMessageBox": QMessageBox,
            "QPushButton": QPushButton,
            "QToolButton": QToolButton,
            "QTabWidget": QTabWidget,
            "QFrame": QFrame,
            "QHeaderView": QHeaderView,
            "QStyledItemDelegate": QStyledItemDelegate,
            "QTreeWidget": QTreeWidget,
            "QTreeWidgetItem": QTreeWidgetItem,
            "QComboBox": QComboBox,
            "QSpinBox": QSpinBox,
            "QDoubleSpinBox": QDoubleSpinBox,
            "QLineEdit": QLineEdit,
            "QCheckBox": QCheckBox,
            "QDialogButtonBox": QDialogButtonBox,
            "QAbstractButton": QAbstractButton,
            "QStackedWidget": QStackedWidget,
            "QListWidget": QListWidget,
            "QListWidgetItem": QListWidgetItem,
            "QScrollArea": QScrollArea,
            "QColorDialog": QColorDialog,
            "QStyleOptionProgressBar": QStyleOptionProgressBar,
            "QStylePainter": QStylePainter,
            "QStyle": QStyle,
            "QRect": QRect,
            "QAction": QAction,
            "QMenu": QMenu,
            "QObject": QObject,
            "QEvent": QEvent,
            "QHelpEvent": QHelpEvent,
            "QToolTip": QToolTip,
            "QPainter": QPainter,
            "pyqtSignal": pyqtSignal,
        }
    )
    qt.__all__ = [name for name in qt.__dict__.keys() if not name.startswith("_")]
    _ensure_module("aqt.qt", qt)
    _ensure_module("aqt.utils", utils)
    _ensure_module("aqt.theme", theme)
    mw = MainWindowStub(config)
    aqt.mw = mw
    aqt.gui_hooks = GuiHooks()
    aqt.utils = utils
    aqt.theme = theme
    _ensure_module("aqt", aqt)

    anki = sys.modules.get("anki", types.ModuleType("anki"))
    anki.version = "2.1.60"

    hooks = types.ModuleType("anki.hooks")

    def addHook(*args, **kwargs):
        return None

    def wrap(fn, *args, **kwargs):
        return fn

    hooks.addHook = addHook
    hooks.wrap = wrap
    _ensure_module("anki.hooks", hooks)
    _ensure_module("anki", anki)
    return mw


def reset_stubs(config: Optional[Dict[str, Any]] = None) -> MainWindowStub:
    mw = install_stubs(config)
    return mw
