from __future__ import annotations

from typing import Optional, TYPE_CHECKING

try:
    from PySide2.QtCore import Qt, QPoint, QEvent
    from PySide2.QtGui import QColor, QFont
    from PySide2.QtWidgets import (
        QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QWidget, QDoubleSpinBox, QFontComboBox,
        QColorDialog,
    )
except ImportError:
    from PySide6.QtCore import Qt, QPoint, QEvent
    from PySide6.QtGui import QColor, QFont
    from PySide6.QtWidgets import (
        QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QWidget, QDoubleSpinBox, QFontComboBox,
        QColorDialog,
    )

if TYPE_CHECKING:
    from CoffeeBoard.core.text_item import TextItem


class TextSettingsPanel(QFrame):
    """Floating per-text-item settings panel.

    Opens via right-click → "Text Properties" on a TextItem. Provides
    font family, size, bold/italic, and color controls.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(260)
        self.setMinimumHeight(160)
        self._item: Optional['TextItem'] = None
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

        title_label = QLabel("Text Properties")
        title_label.setObjectName("titleLabel")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.clicked.connect(self.hide_panel)
        title_layout.addWidget(self._close_btn)

        outer.addWidget(title_bar)

        # --- Controls ---
        controls = QWidget()
        grid = QGridLayout(controls)
        grid.setContentsMargins(10, 6, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        # Row 0: Font family
        grid.addWidget(QLabel("Font:"), 0, 0)
        self._font_combo = QFontComboBox()
        self._font_combo.setFixedHeight(24)
        grid.addWidget(self._font_combo, 0, 1, 1, 2)

        # Row 1: Font size
        grid.addWidget(QLabel("Size:"), 1, 0)
        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(6.0, 400.0)
        self._size_spin.setSingleStep(1.0)
        self._size_spin.setDecimals(1)
        self._size_spin.setSuffix(" pt")
        self._size_spin.setFixedHeight(24)
        grid.addWidget(self._size_spin, 1, 1, 1, 2)

        # Row 2: Bold + Italic
        grid.addWidget(QLabel("Style:"), 2, 0)
        style_row = QWidget()
        style_layout = QHBoxLayout(style_row)
        style_layout.setContentsMargins(0, 0, 0, 0)
        style_layout.setSpacing(6)

        self._bold_btn = QPushButton("B")
        self._bold_btn.setObjectName("styleBtn")
        self._bold_btn.setCheckable(True)
        self._bold_btn.setFixedSize(28, 22)
        font_b = self._bold_btn.font()
        font_b.setBold(True)
        self._bold_btn.setFont(font_b)

        self._italic_btn = QPushButton("I")
        self._italic_btn.setObjectName("styleBtn")
        self._italic_btn.setCheckable(True)
        self._italic_btn.setFixedSize(28, 22)
        font_i = self._italic_btn.font()
        font_i.setItalic(True)
        self._italic_btn.setFont(font_i)

        style_layout.addWidget(self._bold_btn)
        style_layout.addWidget(self._italic_btn)
        style_layout.addStretch()
        grid.addWidget(style_row, 2, 1, 1, 2)

        # Row 3: Color
        grid.addWidget(QLabel("Color:"), 3, 0)
        self._color_btn = QPushButton()
        self._color_btn.setObjectName("colorBtn")
        self._color_btn.setFixedHeight(24)
        self._color_btn.setToolTip("Click to pick text color")
        grid.addWidget(self._color_btn, 3, 1, 1, 2)

        outer.addWidget(controls)

        # Connect signals
        self._font_combo.currentFontChanged.connect(self._on_font_changed)
        self._size_spin.valueChanged.connect(self._on_size_changed)
        self._bold_btn.toggled.connect(self._on_bold_toggled)
        self._italic_btn.toggled.connect(self._on_italic_toggled)
        self._color_btn.clicked.connect(self._on_color_clicked)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            TextSettingsPanel {
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
            QFontComboBox, QDoubleSpinBox {
                background: rgba(40, 40, 40, 220);
                color: rgba(210, 210, 210, 255);
                border: 1px solid rgba(70, 70, 70, 180);
                border-radius: 3px;
                padding: 1px 4px;
                font-size: 11px;
            }
            QPushButton#styleBtn {
                background: rgba(50, 50, 50, 220);
                color: rgba(210, 210, 210, 255);
                border: 1px solid rgba(70, 70, 70, 180);
                border-radius: 3px;
                font-size: 12px;
                padding: 0;
            }
            QPushButton#styleBtn:checked {
                background: rgba(0, 160, 140, 200);
                border: 1px solid rgba(0, 200, 180, 220);
            }
            QPushButton#styleBtn:hover { background: rgba(70, 70, 70, 240); }
            QPushButton#colorBtn {
                border: 1px solid rgba(70, 70, 70, 180);
                border-radius: 3px;
            }
            QPushButton#colorBtn:hover { border: 1px solid rgba(0, 200, 180, 200); }
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

    def show_for_item(self, item: 'TextItem', anchor_viewport_pos: QPoint) -> None:
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

    def _populate(self, item: 'TextItem') -> None:
        self._updating = True
        try:
            self._font_combo.setCurrentFont(QFont(item.font_family))
            self._size_spin.setValue(item.font_size_pt)
            self._bold_btn.setChecked(item.bold)
            self._italic_btn.setChecked(item.italic)
            self._update_color_swatch(item.text_color)
        finally:
            self._updating = False

    def _update_color_swatch(self, color: QColor) -> None:
        r, g, b = color.red(), color.green(), color.blue()
        # Choose label color that contrasts with swatch
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        text_color = "#000" if luminance > 128 else "#fff"
        self._color_btn.setStyleSheet(
            f"QPushButton#colorBtn {{ background: rgb({r},{g},{b}); color: {text_color}; "
            f"border: 1px solid rgba(70,70,70,180); border-radius: 3px; }}"
            f"QPushButton#colorBtn:hover {{ border: 1px solid rgba(0,200,180,200); }}"
        )
        self._color_btn.setText(color.name().upper())

    # --- Signal handlers ---

    def _on_font_changed(self, font: QFont) -> None:
        if self._updating or self._item is None:
            return
        self._item.set_font_family(font.family())

    def _on_size_changed(self, value: float) -> None:
        if self._updating or self._item is None:
            return
        self._item.set_font_size_pt(value)

    def _on_bold_toggled(self, checked: bool) -> None:
        if self._updating or self._item is None:
            return
        self._item.set_bold(checked)

    def _on_italic_toggled(self, checked: bool) -> None:
        if self._updating or self._item is None:
            return
        self._item.set_italic(checked)

    def _on_color_clicked(self) -> None:
        if self._item is None:
            return
        initial = self._item.text_color
        color = QColorDialog.getColor(initial, self, "Text Color",
                                      QColorDialog.DontUseNativeDialog)
        if color.isValid():
            self._item.set_color(color)
            self._update_color_swatch(color)
