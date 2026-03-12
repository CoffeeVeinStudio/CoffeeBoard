from __future__ import annotations

from typing import Any

from CoffeeBoard.core.image_item import (
    _Handle, _RotationHandle, _SelectionBorder, HandlePos, _ROFF, _get_view_scale
)

try:
    from PySide2.QtCore import Qt, QPointF, QRectF
    from PySide2.QtGui import QColor, QFont, QTransform, QTextCursor
    from PySide2.QtWidgets import QGraphicsItem, QGraphicsTextItem
except ImportError:
    from PySide6.QtCore import Qt, QPointF, QRectF
    from PySide6.QtGui import QColor, QFont, QTransform, QTextCursor
    from PySide6.QtWidgets import QGraphicsItem, QGraphicsTextItem


class _InnerText(QGraphicsTextItem):
    """Child text item; calls back to parent on focus loss."""
    def __init__(self, parent_text: 'TextItem') -> None:
        super().__init__(parent_text)
        self._parent = parent_text

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._parent._exit_edit_mode()


class TextItem(QGraphicsItem):
    _nat_w: float
    _nat_h: float
    current_scale: float
    text_content: str
    font_family: str
    font_size_pt: float
    text_color: QColor
    bold: bool
    italic: bool

    def __init__(self, text: str = "New Text", font_family: str = "Arial",
                 font_size_pt: float = 24.0, color: QColor = None) -> None:
        super().__init__()

        if color is None:
            color = QColor(Qt.white)

        self.text_content = text
        self.font_family = font_family
        self.font_size_pt = font_size_pt
        self.text_color = color
        self.bold = False
        self.italic = False
        self.current_scale = 1.0
        self._in_edit_mode = False

        self._inner = _InnerText(self)
        self._inner.setDefaultTextColor(color)
        self._inner.setPlainText(text)
        self._inner.setTextInteractionFlags(Qt.NoTextInteraction)
        self._rebuild_font()

        self._init_handles()
        self.setTransformOriginPoint(self._nat_w / 2, self._nat_h / 2)

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self._drag_start_pos = None

    def _rebuild_font(self) -> None:
        font = QFont(self.font_family)
        font.setPointSizeF(self.font_size_pt)
        font.setBold(self.bold)
        font.setItalic(self.italic)
        self._inner.setFont(font)
        r = self._inner.boundingRect()
        self._nat_w = r.width()
        self._nat_h = r.height()
        self.prepareGeometryChange()

    def _init_handles(self) -> None:
        self._selection_border = _SelectionBorder(self)
        self._handles = [_Handle(self, hp) for hp in HandlePos]
        self._rotation_handles = [_RotationHandle(self, c)
                                   for c in (HandlePos.TL, HandlePos.TR,
                                             HandlePos.BL, HandlePos.BR)]

    # --- Duck-type interface (shared with ImageDisplay) ---

    def base_width(self) -> float:
        return self._nat_w

    def base_height(self) -> float:
        return self._nat_h

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._nat_w * self.current_scale,
                      self._nat_h * self.current_scale)

    def paint(self, painter, option, widget=None) -> None:
        pass  # _inner handles rendering

    def resize_item(self, scale: float) -> None:
        self.current_scale = scale
        self._inner.setTransform(QTransform().scale(scale, scale))
        self.setTransformOriginPoint(self._nat_w * scale / 2,
                                     self._nat_h * scale / 2)
        self.update_handles()

    # --- Handle management ---

    def update_handles(self) -> None:
        w = self.base_width() * self.current_scale
        h = self.base_height() * self.current_scale

        vs = _get_view_scale(self)
        hs = max(5.0, 12.0 / vs)
        rs = max(5.0, 12.0 / vs)
        roff = max(_ROFF, 18.0 / vs)

        self._selection_border.setRect(0, 0, w, h)

        positions = {
            HandlePos.TL: QPointF(0, 0),
            HandlePos.TM: QPointF(w / 2, 0),
            HandlePos.TR: QPointF(w, 0),
            HandlePos.LM: QPointF(0, h / 2),
            HandlePos.RM: QPointF(w, h / 2),
            HandlePos.BL: QPointF(0, h),
            HandlePos.BM: QPointF(w / 2, h),
            HandlePos.BR: QPointF(w, h),
        }
        for handle in self._handles:
            handle.setRect(-hs, -hs, hs * 2, hs * 2)
            handle.setPos(positions[handle.handle_pos])

        rotation_positions = {
            HandlePos.TL: QPointF(-roff, -roff),
            HandlePos.TR: QPointF(w + roff, -roff),
            HandlePos.BL: QPointF(-roff, h + roff),
            HandlePos.BR: QPointF(w + roff, h + roff),
        }
        for rh in self._rotation_handles:
            rh.setRect(-rs, -rs, rs * 2, rs * 2)
            rh.setPos(rotation_positions[rh.corner])

    def show_handles(self) -> None:
        self._selection_border.setVisible(True)
        for h in self._handles:
            h.setVisible(True)
        for rh in self._rotation_handles:
            rh.setVisible(True)
        self.update_handles()

    def hide_handles(self) -> None:
        self._selection_border.setVisible(False)
        for h in self._handles:
            h.setVisible(False)
        for rh in self._rotation_handles:
            rh.setVisible(False)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.ItemSelectedChange:
            if value:
                self.show_handles()
            else:
                self.hide_handles()
        return super().itemChange(change, value)

    # --- Edit mode ---

    def enter_edit_mode(self) -> None:
        self._in_edit_mode = True
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self._inner.setTextInteractionFlags(Qt.TextEditorInteraction)
        self._inner.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self._inner.setFocus(Qt.MouseFocusReason)
        cursor = self._inner.textCursor()
        cursor.select(QTextCursor.Document)
        self._inner.setTextCursor(cursor)
        # Auto-show the text settings panel
        views = self.scene().views() if self.scene() else []
        if views and hasattr(views[0], 'open_text_settings_panel'):
            views[0].open_text_settings_panel(self)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self._in_edit_mode:
            self._drag_start_pos = self.pos()
        else:
            self._drag_start_pos = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and self._drag_start_pos is not None:
            if self.pos() != self._drag_start_pos:
                views = self.scene().views() if self.scene() else []
                if views and hasattr(views[0], 'undo_stack'):
                    from CoffeeBoard.core.undo_commands import MoveCommand
                    views[0].undo_stack.push(MoveCommand(self, self._drag_start_pos, self.pos()))
            self._drag_start_pos = None

    def mouseDoubleClickEvent(self, event) -> None:
        self.enter_edit_mode()
        event.accept()

    def _exit_edit_mode(self) -> None:
        self._in_edit_mode = False
        self._inner.setTextInteractionFlags(Qt.NoTextInteraction)
        self._inner.setFlag(QGraphicsItem.ItemIsFocusable, False)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        # Clear text highlight
        cursor = self._inner.textCursor()
        cursor.clearSelection()
        self._inner.setTextCursor(cursor)
        r = self._inner.boundingRect()
        self._nat_w = r.width()
        self._nat_h = r.height()
        self.resize_item(self.current_scale)
        self.text_content = self._inner.toPlainText()

    # --- Property setters (called from TextSettingsPanel) ---

    def set_font_family(self, family: str) -> None:
        self.font_family = family
        self._rebuild_font()
        self.resize_item(self.current_scale)

    def set_font_size_pt(self, size: float) -> None:
        self.font_size_pt = size
        self._rebuild_font()
        self.resize_item(self.current_scale)

    def set_bold(self, bold: bool) -> None:
        self.bold = bold
        self._rebuild_font()
        self.resize_item(self.current_scale)

    def set_italic(self, italic: bool) -> None:
        self.italic = italic
        self._rebuild_font()
        self.resize_item(self.current_scale)

    def set_color(self, color: QColor) -> None:
        self.text_color = color
        self._inner.setDefaultTextColor(color)

    # --- Hover ---

    def hoverEnterEvent(self, event) -> None:
        self.setCursor(Qt.PointingHandCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)
