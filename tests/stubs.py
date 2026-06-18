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
        self.profile_did_open = HookList()
        self.profile_will_close = HookList()


class QColor:
    def __init__(self, *args: Any) -> None:
        if len(args) == 1 and isinstance(args[0], QColor):
            self.value = args[0].value
        elif args:
            self.value = args[0]
        else:
            self.value = "#000000"

    def name(self) -> str:
        return str(self.value)

    def isValid(self) -> bool:
        return True


class QPalette:
    class ColorRole:
        Base = 0
        Highlight = 1
        Button = 2
        WindowText = 3
        Window = 4

    def __init__(self, other: Optional["QPalette"] = None) -> None:
        self.colors: Dict[int, QColor] = {}
        if isinstance(other, QPalette):
            self.colors = dict(other.colors)

    def setColor(self, role: int, color: QColor) -> None:
        self.colors[role] = color

    def color(self, role: int) -> QColor:
        return self.colors.get(role, QColor("#000000"))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QPalette):
            return False
        return self.colors == other.colors


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
        pass

    def show(self) -> None:
        self._visible = True

    def hide(self) -> None:
        self._visible = False

    def setVisible(self, visible: bool) -> None:
        self._visible = visible

    def isVisible(self) -> bool:
        return getattr(self, "_visible", True)

    def width(self) -> int:
        return getattr(self, "_width", 100)

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

    def deleteLater(self) -> None:
        self._deleted = True


class QAction(QWidget):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__()
        self.text = text
        self.triggered = HookList()


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

    def setClearButtonEnabled(self, enabled: bool) -> None:
        self._clear_enabled = enabled

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

    def setColumnCount(self, count: int) -> None:
        self._columns = count

    def setHorizontalHeaderLabels(self, labels: Sequence[str]) -> None:
        self._headers = list(labels)

    def horizontalHeader(self) -> "QTableWidget":
        return self

    def setStretchLastSection(self, value: bool) -> None:
        self._stretch_last = value

    def setSelectionBehavior(self, behavior: Any) -> None:
        self._selection_behavior = behavior

    def setEditTriggers(self, triggers: Any) -> None:
        self._edit_triggers = triggers

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

    def setStretchLastSection(self, value: bool) -> None:
        self._stretch_last = value

    def setSectionResizeMode(self, section: int, mode: Any) -> None:
        self._section_resize = getattr(self, "_section_resize", {})
        self._section_resize[section] = mode


class QTreeWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._header = QHeaderView()
        self._items: List["QTreeWidgetItem"] = []
        self._current_item: Optional["QTreeWidgetItem"] = None

    def setRootIsDecorated(self, value: bool) -> None:
        self._root_decorated = value

    def setUniformRowHeights(self, value: bool) -> None:
        self._uniform_rows = value

    def setAlternatingRowColors(self, value: bool) -> None:
        self._alternating_rows = value

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


class QTreeWidgetItem:
    def __init__(self, parent: Optional[Any] = None) -> None:
        self._texts: Dict[int, str] = {}
        self._data: Dict[Tuple[int, int], Any] = {}
        self._alignments: Dict[int, Any] = {}
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


class AddonManagerStub:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}

    def getConfig(self, name: str) -> Dict[str, Any]:
        return dict(self.config)

    def writeConfig(self, name: str, config: Dict[str, Any]) -> None:
        self.config = dict(config)

    def addonConfigDefaults(self, name: str) -> Dict[str, Any]:
        return dict(self.config)


class MenuToolsStub:
    def __init__(self) -> None:
        self.actions: List[QAction] = []

    def addAction(self, action: QAction) -> None:
        self.actions.append(action)


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
        self.form = types.SimpleNamespace(menuTools=MenuToolsStub())
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

    def tooltip(message: str, parent: Optional[QWidget] = None, period: int = 0) -> str:
        if parent is not None:
            parent._last_tooltip = (message, period)
        return message

    utils.tooltip = tooltip
    qt = types.ModuleType("aqt.qt")
    qt.__dict__.update(
        {
            "QColor": QColor,
            "QPalette": QPalette,
            "QProgressBar": QProgressBar,
            "QDockWidget": QDockWidget,
            "QWidget": QWidget,
            "Qt": Qt,
            "QStyleFactory": QStyleFactory,
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
    mw = MainWindowStub(config)
    aqt.mw = mw
    aqt.gui_hooks = GuiHooks()
    aqt.utils = utils
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
