from __future__ import annotations

from typing import Optional, TYPE_CHECKING

try:
    from PySide2.QtCore import Qt, QPoint, QTimer, QEvent
    from PySide2.QtWidgets import (
        QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QSlider, QComboBox, QPushButton, QWidget,
    )
except ImportError:
    from PySide6.QtCore import Qt, QPoint, QTimer, QEvent
    from PySide6.QtWidgets import (
        QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QSlider, QComboBox, QPushButton, QWidget,
    )

if TYPE_CHECKING:
    from CoffeeBoard.core.image_item import ImageDisplay


COLORSPACE_OPTIONS = ['linear', 'srgb', 'rec709', 'logc3', 'logc4', 'slog3', 'vlog']
COLORSPACE_LABELS  = ['Linear', 'sRGB', 'Rec.709', 'LogC3', 'LogC4', 'S-Log3', 'V-Log']
TONE_MAP_OPTIONS   = ['reinhard', 'filmic', 'clamp']
TONE_MAP_LABELS    = ['Reinhard', 'Filmic', 'Clamp']

EXPOSURE_MIN = -40   # -4.0 EV
EXPOSURE_MAX =  40   # +4.0 EV
GAMMA_MIN    =  10   # 1.0
GAMMA_MAX    =  30   # 3.0


class ImageSettingsPanel(QFrame):
    """Floating per-image display settings panel.

    Opens on double-click of an ImageDisplay item, anchors near the image's
    top-right corner, and provides colorspace, exposure, gamma, and tone map controls.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(280)
        self.setMinimumHeight(200)
        self._image: Optional['ImageDisplay'] = None
        self._old_settings = None
        self._updating = False
        self._drag_offset = None
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(60)
        self._debounce_timer.timeout.connect(self._apply_pending_update)
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

        self._title_label = QLabel("Image Settings")
        self._title_label.setObjectName("titleLabel")
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.clicked.connect(self.hide_panel)
        title_layout.addWidget(self._close_btn)

        outer.addWidget(title_bar)

        # --- Controls container ---
        self._controls_widget = QWidget()
        grid = QGridLayout(self._controls_widget)
        grid.setContentsMargins(10, 6, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        # Row 0: Colorspace
        grid.addWidget(QLabel("Colorspace:"), 0, 0)
        self._cs_combo = QComboBox()
        self._cs_combo.addItems(COLORSPACE_LABELS)
        grid.addWidget(self._cs_combo, 0, 1, 1, 2)

        # Row 1: Exposure
        grid.addWidget(QLabel("Exposure:"), 1, 0)
        self._exp_slider = QSlider(Qt.Horizontal)
        self._exp_slider.setRange(EXPOSURE_MIN, EXPOSURE_MAX)
        self._exp_slider.setValue(0)
        grid.addWidget(self._exp_slider, 1, 1)
        self._exp_label = QLabel("+0.0 EV")
        self._exp_label.setObjectName("valueLabel")
        self._exp_label.setMinimumWidth(55)
        grid.addWidget(self._exp_label, 1, 2)

        # Row 2: Gamma
        grid.addWidget(QLabel("Gamma:"), 2, 0)
        self._gam_slider = QSlider(Qt.Horizontal)
        self._gam_slider.setRange(GAMMA_MIN, GAMMA_MAX)
        self._gam_slider.setValue(22)
        grid.addWidget(self._gam_slider, 2, 1)
        self._gam_label = QLabel("2.2")
        self._gam_label.setObjectName("valueLabel")
        self._gam_label.setMinimumWidth(55)
        grid.addWidget(self._gam_label, 2, 2)

        # Row 3: Tone Map
        grid.addWidget(QLabel("Tone Map:"), 3, 0)
        self._tm_combo = QComboBox()
        self._tm_combo.addItems(TONE_MAP_LABELS)
        grid.addWidget(self._tm_combo, 3, 1, 1, 2)

        # Row 4: Reset button
        self._reset_btn = QPushButton("Reset")
        grid.addWidget(self._reset_btn, 4, 0, 1, 3)

        outer.addWidget(self._controls_widget)

        # --- Unavailable label ---
        self._unavail_label = QLabel("HDR controls not available\n(image has no linear data)")
        self._unavail_label.setObjectName("unavail")
        self._unavail_label.setAlignment(Qt.AlignCenter)
        self._unavail_label.setContentsMargins(10, 8, 10, 8)
        self._unavail_label.hide()
        outer.addWidget(self._unavail_label)

        # Ctrl+click resets individual control to image-type default
        for w in (self._exp_slider, self._gam_slider, self._cs_combo, self._tm_combo):
            w.installEventFilter(self)

        # Connect signals
        self._cs_combo.currentIndexChanged.connect(self._on_colorspace_changed)
        self._exp_slider.valueChanged.connect(self._on_exposure_changed)
        self._exp_slider.sliderReleased.connect(self._apply_final_update)
        self._gam_slider.valueChanged.connect(self._on_gamma_changed)
        self._gam_slider.sliderReleased.connect(self._apply_final_update)
        self._tm_combo.currentIndexChanged.connect(self._on_tone_map_changed)
        self._reset_btn.clicked.connect(self._on_reset)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            ImageSettingsPanel {
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
            QLabel {
                color: rgba(210, 210, 210, 255);
                font-size: 11px;
            }
            QLabel#valueLabel {
                color: rgba(160, 210, 200, 255);
                font-size: 11px;
            }
            QLabel#unavail {
                color: rgba(150, 150, 150, 200);
                font-size: 11px;
                font-style: italic;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: rgba(70, 70, 70, 200);
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 12px;
                height: 12px;
                margin: -4px 0;
                background: rgba(0, 200, 180, 230);
                border-radius: 6px;
            }
            QSlider::sub-page:horizontal {
                background: rgba(0, 160, 140, 200);
                border-radius: 2px;
            }
            QComboBox {
                background: rgba(40, 40, 40, 220);
                color: rgba(210, 210, 210, 255);
                border: 1px solid rgba(70, 70, 70, 180);
                border-radius: 3px;
                padding: 1px 4px;
                font-size: 11px;
            }
            QPushButton {
                background: rgba(50, 50, 50, 220);
                color: rgba(210, 210, 210, 255);
                border: 1px solid rgba(70, 70, 70, 180);
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(70, 70, 70, 240);
            }
            QPushButton:pressed {
                background: rgba(30, 30, 30, 255);
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

    # --- Helpers ---

    def _get_image_defaults(self) -> Optional[dict]:
        """Return per-image-type default display settings."""
        if self._image is None:
            return None
        import os
        path = str(getattr(self._image, 'path', ''))
        ext = os.path.splitext(path)[1].lower()
        if ext == '.exr':
            return {'exposure': 0.0, 'gamma': 2.2, 'tone_mapping': 'reinhard', 'colorspace': 'linear'}
        from CoffeeBoard.core.image_item import _detect_file_colorspace
        cs = _detect_file_colorspace(path) if path and path != 'clipboard_image' else 'srgb'
        return {'exposure': 0.0, 'gamma': 2.2, 'tone_mapping': 'clamp', 'colorspace': cs}

    def _ctrl_click_reset(self, widget) -> None:
        """Reset a single control to its image-type default and do a full render."""
        defaults = self._get_image_defaults()
        if defaults is None:
            return
        self._debounce_timer.stop()
        self._updating = True
        if widget is self._exp_slider:
            self._exp_slider.setValue(round(defaults['exposure'] * 10))
            self._exp_label.setText(f"{defaults['exposure']:+.1f} EV")
        elif widget is self._gam_slider:
            self._gam_slider.setValue(round(defaults['gamma'] * 10))
            self._gam_label.setText(f"{defaults['gamma']:.1f}")
        elif widget is self._cs_combo:
            cs = defaults['colorspace']
            self._cs_combo.setCurrentIndex(COLORSPACE_OPTIONS.index(cs) if cs in COLORSPACE_OPTIONS else 0)
        elif widget is self._tm_combo:
            tm = defaults['tone_mapping']
            self._tm_combo.setCurrentIndex(TONE_MAP_OPTIONS.index(tm) if tm in TONE_MAP_OPTIONS else 0)
        self._updating = False
        self._apply_final_update()

    # --- Draggable title bar ---

    def eventFilter(self, obj, event) -> bool:
        # Ctrl+click on any control resets it to image-type default
        if (event.type() == QEvent.MouseButtonPress
                and (event.modifiers() & Qt.ControlModifier)
                and obj in (self._exp_slider, self._gam_slider, self._cs_combo, self._tm_combo)):
            self._ctrl_click_reset(obj)
            return True

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

    def show_for_image(self, image: 'ImageDisplay', anchor_viewport_pos: QPoint) -> None:
        self._image = image
        self._old_settings = {
            'colorspace':   image.colorspace,
            'exposure':     image.exposure,
            'gamma':        image.gamma,
            'tone_mapping': image.tone_mapping,
        }
        if image.linear_data is not None:
            self._controls_widget.show()
            self._unavail_label.hide()
            self._populate_controls(image)
        else:
            self._controls_widget.hide()
            self._unavail_label.show()
        self.adjustSize()
        self._clamp_and_place(anchor_viewport_pos)
        self.show()
        self.raise_()

    def hide_panel(self) -> None:
        if self._image is not None and self._old_settings is not None:
            new_settings = {
                'colorspace':   self._image.colorspace,
                'exposure':     self._image.exposure,
                'gamma':        self._image.gamma,
                'tone_mapping': self._image.tone_mapping,
            }
            if new_settings != self._old_settings:
                canvas = self.parent()
                if hasattr(canvas, 'undo_stack'):
                    from CoffeeBoard.core.undo_commands import ChangeSettingsCommand
                    canvas.undo_stack.push(ChangeSettingsCommand(self._image, self._old_settings, new_settings))
        self._old_settings = None
        self._image = None
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

    def _populate_controls(self, image: 'ImageDisplay') -> None:
        self._updating = True
        try:
            # Colorspace
            cs = getattr(image, 'colorspace', 'linear')
            cs_idx = COLORSPACE_OPTIONS.index(cs) if cs in COLORSPACE_OPTIONS else 0
            self._cs_combo.setCurrentIndex(cs_idx)

            # Exposure
            ev = getattr(image, 'exposure', 0.0)
            self._exp_slider.setValue(round(ev * 10))
            self._exp_label.setText(f"{ev:+.1f} EV")

            # Gamma
            gm = getattr(image, 'gamma', 2.2)
            self._gam_slider.setValue(round(gm * 10))
            self._gam_label.setText(f"{gm:.1f}")

            # Tone map
            tm = getattr(image, 'tone_mapping', 'reinhard')
            tm_idx = TONE_MAP_OPTIONS.index(tm) if tm in TONE_MAP_OPTIONS else 0
            self._tm_combo.setCurrentIndex(tm_idx)
        finally:
            self._updating = False

    # --- Signal handlers ---

    def _apply_pending_update(self) -> None:
        """Real-time draft render — called by debounce timer during drag."""
        if self._image is None:
            return
        self._debounce_timer.stop()
        self._image.colorspace = COLORSPACE_OPTIONS[self._cs_combo.currentIndex()]
        self._image.exposure = self._exp_slider.value() / 10.0
        self._image.gamma = self._gam_slider.value() / 10.0
        self._image.tone_mapping = TONE_MAP_OPTIONS[self._tm_combo.currentIndex()]
        self._image._update_display_fast()

    def _apply_final_update(self) -> None:
        """Full-quality render — called on slider release."""
        if self._image is None:
            return
        self._debounce_timer.stop()
        self._image.colorspace = COLORSPACE_OPTIONS[self._cs_combo.currentIndex()]
        self._image.exposure = self._exp_slider.value() / 10.0
        self._image.gamma = self._gam_slider.value() / 10.0
        self._image.tone_mapping = TONE_MAP_OPTIONS[self._tm_combo.currentIndex()]
        self._image._update_display_transform()

    def _on_colorspace_changed(self, index: int) -> None:
        if self._updating or self._image is None:
            return
        # Combo changes are discrete — apply immediately, full quality
        self._apply_final_update()

    def _on_exposure_changed(self, int_value: int) -> None:
        if self._updating or self._image is None:
            return
        # Update label immediately (cheap), debounce the heavy numpy render
        self._exp_label.setText(f"{int_value / 10.0:+.1f} EV")
        self._debounce_timer.start()

    def _on_gamma_changed(self, int_value: int) -> None:
        if self._updating or self._image is None:
            return
        self._gam_label.setText(f"{int_value / 10.0:.1f}")
        self._debounce_timer.start()

    def _on_tone_map_changed(self, index: int) -> None:
        if self._updating or self._image is None:
            return
        self._apply_final_update()

    def _on_reset(self) -> None:
        if self._image is None:
            return
        self._debounce_timer.stop()
        defaults = self._get_image_defaults()
        if defaults is None:
            return
        self._updating = True
        self._exp_slider.setValue(round(defaults['exposure'] * 10))
        self._exp_label.setText(f"{defaults['exposure']:+.1f} EV")
        self._gam_slider.setValue(round(defaults['gamma'] * 10))
        self._gam_label.setText(f"{defaults['gamma']:.1f}")
        cs = defaults['colorspace']
        self._cs_combo.setCurrentIndex(COLORSPACE_OPTIONS.index(cs) if cs in COLORSPACE_OPTIONS else 0)
        tm = defaults['tone_mapping']
        self._tm_combo.setCurrentIndex(TONE_MAP_OPTIONS.index(tm) if tm in TONE_MAP_OPTIONS else 0)
        self._updating = False
        self._apply_final_update()
