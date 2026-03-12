from __future__ import annotations

import os
from typing import Optional, TYPE_CHECKING

try:
    from PySide2.QtCore import Qt, QPoint, QEvent
    from PySide2.QtWidgets import (
        QFrame, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QWidget, QListWidget, QListWidgetItem,
    )
except ImportError:
    from PySide6.QtCore import Qt, QPoint, QEvent
    from PySide6.QtWidgets import (
        QFrame, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QWidget, QListWidget, QListWidgetItem,
    )

if TYPE_CHECKING:
    from CoffeeBoard.core.canvas import CoffeeBoard


class ItemListPanel(QFrame):
    """Floating panel showing all board items sorted by z-order (front to back).

    Supports click-to-select and drag-to-reorder. Modelled after ImageSettingsPanel.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(200)
        self.setMinimumHeight(120)
        self._syncing: bool = False
        self._drag_offset = None
        self._build_ui()
        self._apply_style()
        from CoffeeBoard.ui._resize_corner import _ResizeCorner
        self._rc_nw = _ResizeCorner(self, 'nw')
        self._rc_ne = _ResizeCorner(self, 'ne')
        self._rc_sw = _ResizeCorner(self, 'sw')
        self._rc_se = _ResizeCorner(self, 'se')
        self._place_resize_corners()
        self.hide()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- Title bar ---
        title_bar = QWidget()
        title_bar.setObjectName("titleBar")
        title_bar.setFixedHeight(28)
        title_bar.setCursor(Qt.SizeAllCursor)
        title_bar.installEventFilter(self)
        self._title_bar = title_bar
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(8, 4, 4, 4)
        title_layout.setSpacing(4)

        title_label = QLabel("Item List")
        title_label.setObjectName("titleLabel")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        close_btn = QPushButton("×")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self.hide_panel)
        title_layout.addWidget(close_btn)

        outer.addWidget(title_bar)

        # --- List widget ---
        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.InternalMove)
        self._list.setSelectionMode(QListWidget.ExtendedSelection)
        self._list.setObjectName("itemList")
        outer.addWidget(self._list)

        self._list.itemClicked.connect(self._on_row_clicked)
        self._list.model().rowsMoved.connect(self._on_rows_reordered)
        self._editing = False
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.itemChanged.connect(self._on_item_label_changed)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            ItemListPanel {
                background-color: rgba(20, 20, 20, 220);
                border: 1px solid rgba(0, 180, 160, 160);
                border-radius: 4px;
            }
            QWidget#titleBar {
                background-color: rgba(0, 140, 120, 180);
                border-top-left-radius: 3px;
                border-top-right-radius: 3px;
            }
            QLabel#titleLabel {
                color: rgba(240, 240, 240, 255);
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#closeBtn {
                background: transparent;
                color: rgba(220, 220, 220, 200);
                border: none;
                font-size: 14px;
                padding: 0;
            }
            QPushButton#closeBtn:hover {
                color: rgba(255, 255, 255, 255);
            }
            QListWidget#itemList {
                background-color: rgba(30, 30, 30, 200);
                color: rgba(210, 210, 210, 255);
                border: none;
                font-size: 11px;
            }
            QListWidget#itemList::item {
                padding: 3px 6px;
            }
            QListWidget#itemList::item:selected {
                background-color: rgba(0, 160, 140, 100);
            }
            QListWidget#itemList::item:hover {
                background-color: rgba(0, 120, 100, 60);
            }
        """)

    # --- Public API ---

    def refresh(self) -> None:
        """Rebuild the list from canvas item lists, sorted by z-value (highest first)."""
        canvas = self.parent()
        if canvas is None or not hasattr(canvas, 'image_items'):
            return

        all_items = canvas.image_items + canvas.text_items + getattr(canvas, 'shape_items', [])
        sorted_items = sorted(all_items, key=lambda x: x.zValue(), reverse=True)

        self._list.model().rowsMoved.disconnect(self._on_rows_reordered)
        self._list.itemChanged.disconnect(self._on_item_label_changed)
        self._list.clear()
        for item in sorted_items:
            from CoffeeBoard.core.image_item import ImageDisplay
            row = QListWidgetItem(self._item_label(item))
            row.setData(Qt.UserRole, item)
            if isinstance(item, ImageDisplay):
                row.setFlags(row.flags() | Qt.ItemIsEditable)
            self._list.addItem(row)
        self._list.model().rowsMoved.connect(self._on_rows_reordered)
        self._list.itemChanged.connect(self._on_item_label_changed)

        self._sync_selection_from_scene()

    def show_panel(self) -> None:
        canvas = self.parent()
        self.adjustSize()
        if canvas is not None:
            x = canvas.width() - self.width() - 10
            self.move(x, 10)
        self.show()
        self.raise_()

    def hide_panel(self) -> None:
        self.hide()

    # --- Sync ---

    def _sync_selection_from_scene(self) -> None:
        """Highlight list rows that correspond to selected canvas items."""
        if self._syncing:
            return
        canvas = self.parent()
        if canvas is None or not hasattr(canvas, 'scene'):
            return

        self._syncing = True
        try:
            selected = set(canvas.scene.selectedItems())
            for row_idx in range(self._list.count()):
                row = self._list.item(row_idx)
                item = row.data(Qt.UserRole)
                row.setSelected(item in selected)
        finally:
            self._syncing = False

    def _on_row_clicked(self, list_item: QListWidgetItem) -> None:
        """Select the corresponding canvas item when a row is clicked."""
        if self._syncing:
            return
        canvas = self.parent()
        if canvas is None or not hasattr(canvas, 'scene'):
            return

        self._syncing = True
        try:
            canvas.scene.clearSelection()
            item = list_item.data(Qt.UserRole)
            if item is not None:
                item.setSelected(True)
        finally:
            self._syncing = False

    def _on_rows_reordered(self, *args) -> None:
        """Apply new z-order after an internal drag-drop reorder and push to undo stack."""
        canvas = self.parent()
        if canvas is None or not hasattr(canvas, 'image_items'):
            return

        all_items = canvas.image_items + canvas.text_items + getattr(canvas, 'shape_items', [])
        before = [(item, item.zValue()) for item in all_items]

        n = self._list.count()
        for row_idx in range(n):
            item = self._list.item(row_idx).data(Qt.UserRole)
            item.setZValue(n - 1 - row_idx)   # row 0 → highest z

        after = [(item, item.zValue()) for item in all_items]

        from CoffeeBoard.core.undo_commands import ZOrderCommand
        # Push without triggering redo() re-apply (values already set).
        # We temporarily bypass redo by pushing a command whose redo() is idempotent.
        canvas.undo_stack.push(ZOrderCommand(before, after))

    # --- Helpers ---

    def _item_label(self, item) -> str:
        from CoffeeBoard.core.image_item import ImageDisplay
        from CoffeeBoard.core.text_item import TextItem
        from CoffeeBoard.core.shape_item import ShapeItem
        if isinstance(item, ImageDisplay):
            dn = getattr(item, 'display_name', None)
            if dn:
                return dn
            path = getattr(item, 'path', '')
            if path == 'clipboard_image':
                return 'Clipboard'
            return os.path.basename(path) if path else 'Image'
        if isinstance(item, TextItem):
            text = getattr(item, 'text_content', '').strip()
            if not text:
                return 'T: (empty)'
            return 'T: ' + (text[:24] if len(text) <= 24 else text[:24])
        if isinstance(item, ShapeItem):
            return {
                'rect': '\u25ad Rect',
                'ellipse': '\u25ef Ellipse',
                'line': '\u2571 Line',
                'arrow': '\u2192 Arrow',
            }.get(item.shape_type, 'Shape')
        return str(item)

    def _on_item_double_clicked(self, list_item: QListWidgetItem) -> None:
        from CoffeeBoard.core.image_item import ImageDisplay
        item = list_item.data(Qt.UserRole)
        if isinstance(item, ImageDisplay):
            self._editing = True
            self._list.editItem(list_item)

    def _on_item_label_changed(self, list_item: QListWidgetItem) -> None:
        if not self._editing:
            return
        self._editing = False
        from CoffeeBoard.core.image_item import ImageDisplay
        item = list_item.data(Qt.UserRole)
        if not isinstance(item, ImageDisplay):
            return
        text = list_item.text().strip()
        item.display_name = text if text else None
        self.refresh()

    def _place_resize_corners(self) -> None:
        w, h = self.width(), self.height()
        self._rc_nw.move(0, 0)
        self._rc_ne.move(w - 12, 0)
        self._rc_sw.move(0, h - 12)
        self._rc_se.move(w - 12, h - 12)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_resize_corners()

    # --- Draggable title bar ---

    def eventFilter(self, obj, event) -> bool:
        if obj is self._title_bar:
            t = event.type()
            if t == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                gpos = (event.globalPosition().toPoint()
                        if hasattr(event, 'globalPosition') else event.globalPos())
                self._drag_offset = gpos - self.mapToGlobal(QPoint(0, 0))
                return True
            elif t == QEvent.MouseMove and (event.buttons() & Qt.LeftButton):
                if self._drag_offset is not None:
                    gpos = (event.globalPosition().toPoint()
                            if hasattr(event, 'globalPosition') else event.globalPos())
                    new_global = gpos - self._drag_offset
                    if self.parent():
                        new_pos = self.parent().mapFromGlobal(new_global)
                        margin = 6
                        p = self.parent()
                        x = max(margin, min(new_pos.x(), p.width() - self.width() - margin))
                        y = max(margin, min(new_pos.y(), p.height() - self.height() - margin))
                        self.move(x, y)
                    else:
                        self.move(new_global)
                return True
            elif t == QEvent.MouseButtonRelease:
                self._drag_offset = None
        return super().eventFilter(obj, event)
