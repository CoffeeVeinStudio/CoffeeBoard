from __future__ import annotations

import math
from typing import Any, Optional

from CoffeeBoard.core.image_item import (
    _Handle, _RotationHandle, _SelectionBorder, HandlePos, _ROFF, _get_view_scale
)

try:
    from PySide2.QtCore import Qt, QPointF, QRectF
    from PySide2.QtGui import QColor, QPen, QPainter, QBrush, QPolygonF
    from PySide2.QtWidgets import QGraphicsItem, QGraphicsEllipseItem
except ImportError:
    from PySide6.QtCore import Qt, QPointF, QRectF
    from PySide6.QtGui import QColor, QPen, QPainter, QBrush, QPolygonF
    from PySide6.QtWidgets import QGraphicsItem, QGraphicsEllipseItem


class _EndpointHandle(QGraphicsEllipseItem):
    """A draggable circular handle placed at one endpoint of a line/arrow ShapeItem."""

    def __init__(self, parent_line: 'ShapeItem', endpoint_idx: int) -> None:
        super().__init__(-7, -7, 14, 14, parent_line)
        self.parent_line = parent_line
        self.endpoint_idx = endpoint_idx  # 0 = origin (p1), 1 = far end (p2)
        self.setBrush(QBrush(QColor(0, 200, 180, 220)))
        self.setPen(QPen(QColor(255, 255, 255), 1.5))
        self.setZValue(1001)
        self.setVisible(False)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CrossCursor)
        self.dragging = False
        self._drag_start_pos = None
        self._drag_start_dx = None
        self._drag_start_dy = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self._drag_start_pos = self.parent_line.pos()
            self._drag_start_dx = self.parent_line._dx
            self._drag_start_dy = self.parent_line._dy
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.dragging:
            self._apply_drag(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self.dragging and event.button() == Qt.LeftButton:
            self.dragging = False
            old_pos = self._drag_start_pos
            old_dx = self._drag_start_dx
            old_dy = self._drag_start_dy
            new_pos = self.parent_line.pos()
            new_dx = self.parent_line._dx
            new_dy = self.parent_line._dy

            if old_pos != new_pos or old_dx != new_dx or old_dy != new_dy:
                views = self.scene().views() if self.scene() else []
                if views and hasattr(views[0], 'undo_stack'):
                    from CoffeeBoard.core.undo_commands import EditLineEndpointCommand
                    views[0].undo_stack.push(
                        EditLineEndpointCommand(
                            self.parent_line,
                            old_pos, old_dx, old_dy,
                            new_pos, new_dx, new_dy,
                        )
                    )
        event.accept()

    def _apply_drag(self, scene_pos: QPointF) -> None:
        item = self.parent_line
        if self.endpoint_idx == 1:
            # Far end moves; origin stays fixed — just update dx/dy in local coords
            local = item.mapFromScene(scene_pos)
            item._dx = local.x()
            item._dy = local.y()
            item.prepareGeometryChange()
            item.update_handles()
            item.update()
        else:
            # Origin (p1) moves; keep p2 fixed in scene
            p2_scene = item.mapToScene(QPointF(item._dx, item._dy))
            item.setPos(scene_pos)
            new_local_p2 = item.mapFromScene(p2_scene)
            item._dx = new_local_p2.x()
            item._dy = new_local_p2.y()
            item.prepareGeometryChange()
            item.update_handles()
            item.update()

    def hoverEnterEvent(self, event) -> None:
        self.setCursor(Qt.CrossCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)


class ShapeItem(QGraphicsItem):
    """A drawable shape item supporting rect, ellipse, line, and arrow types."""

    _nat_w: float
    _nat_h: float
    current_scale: float
    shape_type: str
    stroke_color: QColor
    fill_color: Optional[QColor]
    stroke_width: float

    def __init__(
        self,
        shape_type: str = 'rect',
        nat_w: float = 100.0,
        nat_h: float = 80.0,
        dx: float = 100.0,
        dy: float = 0.0,
        stroke_color: QColor = None,
        fill_color: QColor = None,
        stroke_width: float = 2.0,
    ) -> None:
        super().__init__()

        self.shape_type = shape_type
        self.current_scale = 1.0
        self.stroke_color = stroke_color if stroke_color is not None else QColor(0, 200, 180, 220)
        self.fill_color = fill_color
        self.stroke_width = stroke_width
        self._drag_start_pos = None

        if shape_type in ('line', 'arrow'):
            self._dx = float(dx)
            self._dy = float(dy)
            self._nat_w = max(1.0, abs(dx))
            self._nat_h = max(1.0, abs(dy))
            self._init_handles()
            self.setTransformOriginPoint(self._dx / 2, self._dy / 2)
        else:
            self._dx = 0.0
            self._dy = 0.0
            self._nat_w = max(4.0, nat_w)
            self._nat_h = max(4.0, nat_h)
            self._init_handles()
            self.setTransformOriginPoint(self._nat_w / 2, self._nat_h / 2)

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

    # --- Duck-type interface (shared with ImageDisplay / TextItem) ---

    def base_width(self) -> float:
        return self._nat_w

    def base_height(self) -> float:
        return self._nat_h

    def resize_item(self, scale: float) -> None:
        if self.shape_type in ('line', 'arrow'):
            return  # endpoints define geometry; scaling not applicable
        self.current_scale = scale
        self.setTransformOriginPoint(self._nat_w * scale / 2, self._nat_h * scale / 2)
        self.update_handles()
        self.prepareGeometryChange()
        self.update()

    def update_natural_size(self, w: float, h: float) -> None:
        """Update natural dimensions in-place (used for live draw preview of rect/ellipse)."""
        self._nat_w = max(1.0, w)
        self._nat_h = max(1.0, h)
        self.setTransformOriginPoint(self._nat_w * self.current_scale / 2,
                                     self._nat_h * self.current_scale / 2)
        self.prepareGeometryChange()
        self.update()

    def update_line_vector(self, dx: float, dy: float) -> None:
        """Update line/arrow endpoint vector in-place (used for live draw preview)."""
        self._dx = dx
        self._dy = dy
        self.prepareGeometryChange()
        self.update()

    def set_preview_mode(self) -> None:
        """Configure as a non-interactive draw preview (semi-transparent, not selectable)."""
        self.setOpacity(0.5)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setZValue(9999)

    # --- Property setters (called from ShapeSettingsPanel) ---

    def set_stroke_color(self, color: QColor) -> None:
        self.stroke_color = color
        self.update()

    def set_stroke_width(self, width: float) -> None:
        self.stroke_width = width
        self.prepareGeometryChange()
        self.update()

    def set_fill_color(self, color: Optional[QColor]) -> None:
        self.fill_color = color
        self.update()

    # --- QGraphicsItem interface ---

    def boundingRect(self) -> QRectF:
        if self.shape_type in ('line', 'arrow'):
            margin = max(self.stroke_width, 12.0) + 2.0
            x1, y1 = 0.0, 0.0
            x2, y2 = self._dx, self._dy
            return QRectF(
                min(x1, x2) - margin,
                min(y1, y2) - margin,
                abs(x2 - x1) + margin * 2,
                abs(y2 - y1) + margin * 2,
            )
        half_sw = self.stroke_width / 2.0 + 1.0
        w = self._nat_w * self.current_scale
        h = self._nat_h * self.current_scale
        return QRectF(-half_sw, -half_sw, w + half_sw * 2, h + half_sw * 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        pen = QPen(self.stroke_color, self.stroke_width)
        pen.setCosmetic(False)
        painter.setPen(pen)

        if self.fill_color is not None:
            painter.setBrush(QBrush(self.fill_color))
        else:
            painter.setBrush(QBrush(Qt.NoBrush))

        if self.shape_type in ('line', 'arrow'):
            if self.shape_type == 'arrow':
                # Stop the line at the arrowhead base so it doesn't poke through the tip
                dx, dy = self._dx, self._dy
                length = math.hypot(dx, dy)
                if length >= 1.0:
                    head_len = max(12.0, self.stroke_width * 4) * self.current_scale
                    if length > head_len:
                        ux, uy = dx / length, dy / length
                        line_end = QPointF(dx - ux * head_len, dy - uy * head_len)
                    else:
                        line_end = QPointF(0, 0)
                    painter.drawLine(QPointF(0, 0), line_end)
                self._draw_arrowhead(painter, QPointF(0, 0), QPointF(self._dx, self._dy))
            else:
                painter.drawLine(QPointF(0, 0), QPointF(self._dx, self._dy))
        else:
            w = self._nat_w * self.current_scale
            h = self._nat_h * self.current_scale
            if self.shape_type == 'rect':
                painter.drawRect(QRectF(0, 0, w, h))
            elif self.shape_type == 'ellipse':
                painter.drawEllipse(QRectF(0, 0, w, h))

    def _draw_arrowhead(self, painter: QPainter, start: QPointF, end: QPointF) -> None:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1.0:
            return

        head_len = max(12.0, self.stroke_width * 4) * self.current_scale
        head_width = head_len * 0.45

        # Unit vector along the line direction (toward end)
        ux = dx / length
        uy = dy / length

        # Perpendicular unit vector
        px = -uy
        py = ux

        # Arrowhead tip is at end; base is behind
        base = QPointF(end.x() - ux * head_len, end.y() - uy * head_len)
        left = QPointF(base.x() + px * head_width, base.y() + py * head_width)
        right = QPointF(base.x() - px * head_width, base.y() - py * head_width)

        triangle = QPolygonF([end, left, right])
        painter.setBrush(QBrush(self.stroke_color))
        painter.setPen(QPen(Qt.NoPen))
        painter.drawPolygon(triangle)

    # --- Handle management ---

    def _init_handles(self) -> None:
        self._selection_border = _SelectionBorder(self)
        if self.shape_type in ('line', 'arrow'):
            self._handles = []
            self._rotation_handles = []
            self._endpoint_handles = [_EndpointHandle(self, 0), _EndpointHandle(self, 1)]
        else:
            self._endpoint_handles = []
            self._handles = [_Handle(self, hp) for hp in HandlePos]
            self._rotation_handles = [_RotationHandle(self, c)
                                       for c in (HandlePos.TL, HandlePos.TR,
                                                 HandlePos.BL, HandlePos.BR)]

    def update_handles(self) -> None:
        if self.shape_type in ('line', 'arrow'):
            for eh in self._endpoint_handles:
                if eh.endpoint_idx == 0:
                    eh.setPos(QPointF(0, 0))
                else:
                    eh.setPos(QPointF(self._dx, self._dy))
            return

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
        if self.shape_type in ('line', 'arrow'):
            for eh in self._endpoint_handles:
                eh.setVisible(True)
            self.update_handles()
            return
        self._selection_border.setVisible(True)
        for h in self._handles:
            h.setVisible(True)
        for rh in self._rotation_handles:
            rh.setVisible(True)
        self.update_handles()

    def hide_handles(self) -> None:
        if self.shape_type in ('line', 'arrow'):
            for eh in self._endpoint_handles:
                eh.setVisible(False)
            return
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

    # --- Mouse events ---

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
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
        views = self.scene().views() if self.scene() else []
        if views and hasattr(views[0], 'open_shape_settings_panel'):
            views[0].open_shape_settings_panel(self)
        event.accept()

    def hoverEnterEvent(self, event) -> None:
        self.setCursor(Qt.PointingHandCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)
