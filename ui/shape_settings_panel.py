from __future__ import annotations

from typing import Optional, TYPE_CHECKING

try:
    from PySide2.QtCore import Qt, QPoint, QEvent
    from PySide2.QtGui import QColor
    from PySide2.QtWidgets import (
        QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QWidget, QDoubleSpinBox, QCheckBox,
        QColorDialog,
    )
except ImportError:
    from PySide6.QtCore import Qt, QPoint, QEvent
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (
        QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QWidget, QDoubleSpinBox, QCheckBox,
        QColorDialog,
    )

if TYPE_CHECKING:
    from CoffeeBoard.core.shape_item import ShapeItem


class ShapeSettingsPanel(QFrame):
    """Floating per-shape settings panel.

    Opens via right-click → "Shape Properties" or double-click. Provides
    stroke color, stroke width, and fill color controls.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(240)
        self.setMinimumHeight(140)
        self._item: Optional['ShapeItem'] = None
        self._updating = False
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

        title_label = QLabel("Shape Properties")
        title_label.setObjectName("titleLabel")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        close_btn = QPushButton("×")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self.hide_panel)
        title_layout.addWidget(close_btn)

        outer.addWidget(title_bar)

        # --- Controls ---
        controls = QWidget()
        grid = QGridLayout(controls)
        grid.setContentsMargins(10, 6, 10, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        # Row 0: Stroke color
        grid.addWidget(QLabel("Stroke:"), 0, 0)
        self._stroke_btn = QPushButton()
        self._stroke_btn.setObjectName("colorBtn")
        self._stroke_btn.setFixedHeight(24)
        self._stroke_btn.setToolTip("Click to pick stroke color")
        grid.addWidget(self._stroke_btn, 0, 1)

        # Row 1: Stroke width
        grid.addWidget(QLabel("Width:"), 1, 0)
        self._width_spin = QDoubleSpinBox()
        self._width_spin.setRange(0.5, 30.0)
        self._width_spin.setSingleStep(0.5)
        self._width_spin.setDecimals(1)
        self._width_spin.setSuffix(" px")
        self._width_spin.setFixedHeight(24)
        grid.addWidget(self._width_spin, 1, 1)

        # Row 2: Fill color
        grid.addWidget(QLabel("Fill:"), 2, 0)
        fill_row = QWidget()
        fill_layout = QHBoxLayout(fill_row)
        fill_layout.setContentsMargins(0, 0, 0, 0)
        fill_layout.setSpacing(6)
        self._fill_btn = QPushButton()
        self._fill_btn.setObjectName("colorBtn")
        self._fill_btn.setFixedHeight(24)
        self._fill_btn.setToolTip("Click to pick fill color")
        self._no_fill_cb = QCheckBox("None")
        self._no_fill_cb.setObjectName("noFillCb")
        fill_layout.addWidget(self._fill_btn)
        fill_layout.addWidget(self._no_fill_cb)
        grid.addWidget(fill_row, 2, 1)

        outer.addWidget(controls)

        # Connect signals
        self._stroke_btn.clicked.connect(self._on_stroke_clicked)
        self._width_spin.valueChanged.connect(self._on_width_changed)
        self._fill_btn.clicked.connect(self._on_fill_clicked)
        self._no_fill_cb.toggled.connect(self._on_no_fill_toggled)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            ShapeSettingsPanel {
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
            QPushButton#closeBtn:hover { color: rgba(255, 255, 255, 255); }
            QLabel {
                color: rgba(210, 210, 210, 255);
                font-size: 11px;
            }
            QDoubleSpinBox {
                background: rgba(40, 40, 40, 220);
                color: rgba(210, 210, 210, 255);
                border: 1px solid rgba(70, 70, 70, 180);
                border-radius: 3px;
                padding: 1px 4px;
                font-size: 11px;
            }
            QPushButton#colorBtn {
                border: 1px solid rgba(70, 70, 70, 180);
                border-radius: 3px;
                font-size: 10px;
            }
            QPushButton#colorBtn:hover { border: 1px solid rgba(0, 200, 180, 200); }
            QCheckBox#noFillCb {
                color: rgba(210, 210, 210, 255);
                font-size: 11px;
            }
        """)

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

    # --- Public API ---

    def show_for_item(self, item: 'ShapeItem', anchor_viewport_pos: QPoint) -> None:
        self._item = item
        self._populate(item)
        self.adjustSize()
        self._clamp_and_place(anchor_viewport_pos)
        self.show()
        self.raise_()

    def hide_panel(self) -> None:
        self._item = None
        self.hide()

    def _clamp_and_place(self, anchor: QPoint) -> None:
        if self.parent() is None:
            self.move(anchor)
            return
        parent_w = self.parent().width()
        parent_h = self.parent().height()
        panel_w = self.width()
        panel_h = self.height()
        margin = 6

        x = anchor.x() + margin
        if x + panel_w > parent_w - margin:
            x = anchor.x() - panel_w - margin

        y = anchor.y()
        x = max(margin, min(x, parent_w - panel_w - margin))
        y = max(margin, min(y, parent_h - panel_h - margin))
        self.move(x, y)

    def _populate(self, item: 'ShapeItem') -> None:
        self._updating = True
        try:
            self._update_stroke_swatch(item.stroke_color)
            self._width_spin.setValue(item.stroke_width)
            has_fill = item.fill_color is not None
            self._no_fill_cb.setChecked(not has_fill)
            self._fill_btn.setEnabled(has_fill)
            self._update_fill_swatch(item.fill_color if has_fill else QColor(80, 80, 80))
        finally:
            self._updating = False

    def _update_stroke_swatch(self, color: QColor) -> None:
        r, g, b = color.red(), color.green(), color.blue()
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        text_color = "#000" if lum > 128 else "#fff"
        self._stroke_btn.setStyleSheet(
            f"QPushButton#colorBtn {{ background: rgb({r},{g},{b}); color: {text_color}; "
            f"border: 1px solid rgba(70,70,70,180); border-radius: 3px; }}"
            f"QPushButton#colorBtn:hover {{ border: 1px solid rgba(0,200,180,200); }}"
        )
        self._stroke_btn.setText(color.name().upper())

    def _update_fill_swatch(self, color: QColor) -> None:
        r, g, b = color.red(), color.green(), color.blue()
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        text_color = "#000" if lum > 128 else "#fff"
        self._fill_btn.setStyleSheet(
            f"QPushButton#colorBtn {{ background: rgb({r},{g},{b}); color: {text_color}; "
            f"border: 1px solid rgba(70,70,70,180); border-radius: 3px; }}"
            f"QPushButton#colorBtn:hover {{ border: 1px solid rgba(0,200,180,200); }}"
        )
        self._fill_btn.setText(color.name().upper() if self._item and self._item.fill_color else "")

    # --- Signal handlers ---

    def _on_stroke_clicked(self) -> None:
        if self._item is None:
            return
        color = QColorDialog.getColor(
            self._item.stroke_color, self, "Stroke Color",
            QColorDialog.DontUseNativeDialog | QColorDialog.ShowAlphaChannel
        )
        if color.isValid():
            self._item.set_stroke_color(color)
            self._update_stroke_swatch(color)

    def _on_width_changed(self, value: float) -> None:
        if self._updating or self._item is None:
            return
        self._item.set_stroke_width(value)

    def _on_fill_clicked(self) -> None:
        if self._item is None:
            return
        initial = self._item.fill_color or QColor(255, 255, 255, 128)
        color = QColorDialog.getColor(
            initial, self, "Fill Color",
            QColorDialog.DontUseNativeDialog | QColorDialog.ShowAlphaChannel
        )
        if color.isValid():
            self._item.set_fill_color(color)
            self._update_fill_swatch(color)

    def _on_no_fill_toggled(self, checked: bool) -> None:
        if self._updating or self._item is None:
            return
        if checked:
            self._item.set_fill_color(None)
            self._fill_btn.setEnabled(False)
        else:
            # Restore a default semi-transparent white if coming from no-fill
            color = QColor(255, 255, 255, 80)
            self._item.set_fill_color(color)
            self._fill_btn.setEnabled(True)
            self._update_fill_swatch(color)
