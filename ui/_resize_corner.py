from __future__ import annotations

try:
    from PySide2.QtCore import Qt, QPoint
    from PySide2.QtGui import QPainter, QColor, QPen
    from PySide2.QtWidgets import QWidget
except ImportError:
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtGui import QPainter, QColor, QPen
    from PySide6.QtWidgets import QWidget


_CURSORS = {
    'se': Qt.SizeFDiagCursor,
    'nw': Qt.SizeFDiagCursor,
    'sw': Qt.SizeBDiagCursor,
    'ne': Qt.SizeBDiagCursor,
}


class _ResizeCorner(QWidget):
    """12×12 px drag handle at one of the four panel corners.

    corner: 'nw' | 'ne' | 'sw' | 'se'
    NW/NE/SW corners also move the panel position while resizing.
    """

    def __init__(self, panel: QWidget, corner: str = 'se') -> None:
        super().__init__(panel)
        self._panel = panel
        self._corner = corner
        self._drag_start_global: QPoint | None = None
        self._start_size: tuple[int, int] = (0, 0)
        self._start_pos: QPoint = QPoint(0, 0)
        self.setFixedSize(12, 12)
        self.setCursor(_CURSORS.get(corner, Qt.SizeFDiagCursor))
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start_global = (
                event.globalPosition().toPoint()
                if hasattr(event, 'globalPosition') else event.globalPos()
            )
            self._start_size = (self._panel.width(), self._panel.height())
            self._start_pos = QPoint(self._panel.x(), self._panel.y())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start_global is None:
            return
        gpos = (
            event.globalPosition().toPoint()
            if hasattr(event, 'globalPosition') else event.globalPos()
        )
        dx = gpos.x() - self._drag_start_global.x()
        dy = gpos.y() - self._drag_start_global.y()
        min_w = self._panel.minimumWidth()
        min_h = self._panel.minimumHeight()
        sw, sh = self._start_size
        sx, sy = self._start_pos.x(), self._start_pos.y()

        if self._corner == 'se':
            new_w = max(min_w, sw + dx)
            new_h = max(min_h, sh + dy)
            self._panel.resize(int(new_w), int(new_h))

        elif self._corner == 'sw':
            new_w = max(min_w, sw - dx)
            new_h = max(min_h, sh + dy)
            actual_dx = sw - new_w          # how much left edge actually moved
            self._panel.move(sx + actual_dx, sy)
            self._panel.resize(int(new_w), int(new_h))

        elif self._corner == 'ne':
            new_w = max(min_w, sw + dx)
            new_h = max(min_h, sh - dy)
            actual_dy = sh - new_h          # how much top edge actually moved
            self._panel.move(sx, sy + actual_dy)
            self._panel.resize(int(new_w), int(new_h))

        elif self._corner == 'nw':
            new_w = max(min_w, sw - dx)
            new_h = max(min_h, sh - dy)
            actual_dx = sw - new_w
            actual_dy = sh - new_h
            self._panel.move(sx + actual_dx, sy + actual_dy)
            self._panel.resize(int(new_w), int(new_h))

        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start_global = None

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(0, 180, 160, 160), 1.5)
        p.setPen(pen)
        # Three diagonal dots pointing toward the respective corner
        if self._corner == 'se':
            for i in range(3):
                p.drawPoint(11 - i * 3, 11)
                p.drawPoint(11, 11 - i * 3)
        elif self._corner == 'sw':
            for i in range(3):
                p.drawPoint(i * 3, 11)
                p.drawPoint(0, 11 - i * 3)
        elif self._corner == 'ne':
            for i in range(3):
                p.drawPoint(11 - i * 3, 0)
                p.drawPoint(11, i * 3)
        elif self._corner == 'nw':
            for i in range(3):
                p.drawPoint(i * 3, 0)
                p.drawPoint(0, i * 3)
        p.end()
