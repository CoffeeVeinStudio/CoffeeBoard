from __future__ import annotations

from typing import List, Optional

try:
    from PySide2.QtCore import Qt
    from PySide2.QtWidgets import (
        QFrame, QHBoxLayout, QLabel, QSlider,
        QComboBox, QPushButton, QWidget
    )
except ImportError:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QFrame, QHBoxLayout, QLabel, QSlider,
        QComboBox, QPushButton, QWidget
    )


class HDRControlsBar(QFrame):
    """Overlay toolbar for HDR display controls.

    Parented directly to CoffeeBoard (QGraphicsView), positioned flush with
    the bottom edge. Auto-shows when HDR images are selected, auto-hides
    when none are selected.

    Two visible states:
    - Active       : sliders/combo visible — image has linear_data set
    - Unavailable  : info message only     — EXR loaded without OIIO
    """

    # Slider integer encoding: stored int / 10.0 = float value
    EXPOSURE_MIN = -40    # -4.0 EV
    EXPOSURE_MAX =  40    # +4.0 EV
    GAMMA_MIN    =  10    # 1.0
    GAMMA_MAX    =  30    # 3.0

    TONE_MAP_OPTIONS = ['reinhard', 'filmic', 'clamp']
    TONE_MAP_LABELS  = ['Reinhard', 'Filmic', 'Clamp']

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # Required for stylesheet background-color to render on a custom QFrame subclass
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._images = []
        self._updating = False  # re-entry guard: blocks signal cascade during set_images()
        self._build_ui()
        self._apply_style()
        self.hide()

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- Controls container ---
        self._controls_widget = QWidget()
        layout = QHBoxLayout(self._controls_widget)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        # Exposure
        self._exp_label = QLabel("Exp: +0.0 EV")
        self._exp_label.setMinimumWidth(95)
        self._exp_slider = QSlider(Qt.Horizontal)
        self._exp_slider.setRange(self.EXPOSURE_MIN, self.EXPOSURE_MAX)
        self._exp_slider.setValue(0)
        self._exp_slider.setFixedWidth(140)
        self._exp_slider.setTickInterval(10)
        layout.addWidget(self._exp_label)
        layout.addWidget(self._exp_slider)
        layout.addSpacing(12)

        # Gamma
        self._gam_label = QLabel("Gamma: 2.2")
        self._gam_label.setMinimumWidth(80)
        self._gam_slider = QSlider(Qt.Horizontal)
        self._gam_slider.setRange(self.GAMMA_MIN, self.GAMMA_MAX)
        self._gam_slider.setValue(22)  # 2.2 * 10
        self._gam_slider.setFixedWidth(100)
        layout.addWidget(self._gam_label)
        layout.addWidget(self._gam_slider)
        layout.addSpacing(12)

        # Tone Map
        layout.addWidget(QLabel("Tone Map:"))
        self._tm_combo = QComboBox()
        self._tm_combo.addItems(self.TONE_MAP_LABELS)
        self._tm_combo.setFixedWidth(90)
        layout.addWidget(self._tm_combo)

        # Reset
        layout.addStretch()
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setFixedWidth(55)
        layout.addWidget(self._reset_btn)

        # Connect signals
        self._exp_slider.valueChanged.connect(self._on_exposure_changed)
        self._gam_slider.valueChanged.connect(self._on_gamma_changed)
        self._tm_combo.currentIndexChanged.connect(self._on_tone_map_changed)
        self._reset_btn.clicked.connect(self._on_reset)

        # --- Unavailable label (shown instead of controls when OIIO is missing) ---
        self._unavail_label = QLabel("EXR loaded without OpenImageIO — HDR controls unavailable")
        self._unavail_label.setObjectName("unavail")
        self._unavail_label.setAlignment(Qt.AlignCenter)
        self._unavail_label.hide()

        outer.addWidget(self._controls_widget)
        outer.addWidget(self._unavail_label)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            HDRControlsBar {
                background-color: rgba(20, 20, 20, 200);
                border-top: 1px solid rgba(80, 80, 80, 180);
            }
            QLabel {
                color: rgba(220, 220, 220, 255);
                font-size: 11px;
            }
            QLabel#unavail {
                color: rgba(160, 160, 160, 200);
                font-size: 11px;
                font-style: italic;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: rgba(80, 80, 80, 200);
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 12px;
                height: 12px;
                margin: -4px 0;
                background: rgba(160, 190, 255, 230);
                border-radius: 6px;
            }
            QSlider::sub-page:horizontal {
                background: rgba(100, 140, 220, 200);
                border-radius: 2px;
            }
            QComboBox {
                background: rgba(50, 50, 50, 220);
                color: rgba(220, 220, 220, 255);
                border: 1px solid rgba(80, 80, 80, 180);
                border-radius: 3px;
                padding: 1px 4px;
                font-size: 11px;
            }
            QPushButton {
                background: rgba(60, 60, 60, 220);
                color: rgba(220, 220, 220, 255);
                border: 1px solid rgba(80, 80, 80, 180);
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(80, 80, 80, 240);
            }
            QPushButton:pressed {
                background: rgba(40, 40, 40, 255);
            }
        """)

    # --- Public API ---

    def set_images(self, images: list) -> None:
        """Update controls to reflect the given list of HDR ImageDisplay items.

        - Empty list  → bar hides.
        - Single image → shows that image's exact values.
        - Multiple     → shows averaged exposure/gamma; tone map if unanimous.
        """
        self._images = images

        if not images:
            self.hide()
            return

        # Switch to active state (guard against coming from unavailable state)
        self._unavail_label.hide()
        self._controls_widget.show()
        self.show()

        self._updating = True
        try:
            exposures = [img.exposure for img in images]
            gammas    = [img.gamma    for img in images]
            tone_maps = [img.tone_mapping for img in images]

            avg_exp   = sum(exposures) / len(exposures)
            avg_gamma = sum(gammas)    / len(gammas)

            self._exp_slider.setValue(round(avg_exp * 10))
            self._gam_slider.setValue(round(avg_gamma * 10))

            # Update labels directly — don't rely on valueChanged firing while _updating
            self._exp_label.setText(f"Exp: {avg_exp:+.1f} EV")
            self._gam_label.setText(f"Gamma: {avg_gamma:.1f}")

            # Tone map: unanimous → show it; mixed → show reinhard without applying
            dominant = tone_maps[0] if len(set(tone_maps)) == 1 else 'reinhard'
            idx = self.TONE_MAP_OPTIONS.index(dominant) if dominant in self.TONE_MAP_OPTIONS else 0
            self._tm_combo.setCurrentIndex(idx)
        finally:
            self._updating = False

    def set_unavailable(self) -> None:
        """Show bar in informational state when selected EXR has no OIIO linear data."""
        self._images = []
        self._controls_widget.hide()
        self._unavail_label.show()
        self.show()

    # --- Signal handlers ---

    def _on_exposure_changed(self, int_value: int) -> None:
        if self._updating:
            return
        ev = int_value / 10.0
        self._exp_label.setText(f"Exp: {ev:+.1f} EV")
        for img in self._images:
            img.set_exposure(ev)

    def _on_gamma_changed(self, int_value: int) -> None:
        if self._updating:
            return
        gamma = int_value / 10.0
        self._gam_label.setText(f"Gamma: {gamma:.1f}")
        for img in self._images:
            img.set_gamma(gamma)

    def _on_tone_map_changed(self, index: int) -> None:
        if self._updating:
            return
        method = self.TONE_MAP_OPTIONS[index]
        for img in self._images:
            img.set_tone_mapping(method)

    def _on_reset(self) -> None:
        for img in self._images:
            img.set_exposure(0.0)
            img.set_gamma(2.2)
            img.set_tone_mapping('reinhard')
        # Re-drive sliders to defaults without triggering per-image updates
        self.set_images(self._images)
