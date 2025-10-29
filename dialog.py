from __future__ import annotations

import os

from typing import List, Optional, Tuple

from PySide2.QtCore import QObject
from PySide2.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                QLabel, QComboBox, QCheckBox, QPushButton)


class EXRImportDialog(QDialog):
    """Custom dialog for EXR import settings.

    This dialog prompts the user to select the specific layer and preview format 
    when importing EXR files, which commonly contain multiple channels (layers). 
    It also provides an option to apply the current settings to all remaining files 
    during a batch import process.

    Attributes (Results):
        selected_layer (Optional[str]): The layer chosen by the user (e.g., 'rgba', 'diffuse'). 
                                        This is set just before the dialog is accepted.
        selected_format (str): The file extension chosen for preview generation 
                               (e.g., 'jpg', 'png').
        apply_to_all (bool): True if the user checked the "Apply to all" box (only visible 
                             during batch operations).
    """
    
    # --- ATTRIBUTE TYPE HINTS ---
    selected_layer: Optional[str]
    selected_format: str
    apply_to_all: bool
    layer_combo: QComboBox
    format_combo: QComboBox
    apply_all_checkbox: Optional[QCheckBox]
    
    def __init__(self, path: str, layers: List[str], is_batch: bool = False, parent: Optional[QObject] = None) -> None:
        """Initializes the EXR Import Dialog.

        Args:
            path (str): The full path to the EXR file being imported.
            layers (List[str]): A list of all available layers/channels in the EXR file.
            is_batch (bool, optional): If True, shows the "apply to all" checkbox 
                                       for batch operations. Defaults to False.
            parent (Optional[QObject], optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.setWindowTitle("EXR Import Settings")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        self.selected_layer = None
        self.selected_format = 'jpg'
        self.apply_to_all = False
        
        # Main layout
        layout = QVBoxLayout(self)
        
        # File name display
        file_label = QLabel(f"<b>File:</b> {os.path.basename(path)}")
        file_label.setWordWrap(True)
        layout.addWidget(file_label)
        
        # Full path (smaller text)
        path_label = QLabel(f"<small>{path}</small>")
        path_label.setStyleSheet("color: gray;")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        
        layout.addSpacing(10)
        
        # Layer selection
        layer_layout = QHBoxLayout()
        layer_layout.addWidget(QLabel("Layer:"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(layers)
        layer_layout.addWidget(self.layer_combo)
        layout.addLayout(layer_layout)
        
        # Format selection
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Preview Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(['JPG', 'PNG', 'TIFF', 'BMP'])
        format_layout.addWidget(self.format_combo)
        layout.addLayout(format_layout)
        
        layout.addSpacing(10)
        
        # "Apply to all" checkbox (only shown if batch)
        if is_batch:
            self.apply_all_checkbox = QCheckBox("Use these settings for all remaining EXR files")
            layout.addWidget(self.apply_all_checkbox)
            layout.addSpacing(10)
        else:
            self.apply_all_checkbox = None
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._collect_results_and_accept)
        button_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def get_values(self) -> Tuple[str, str, bool]:
        """Retrieves the currently selected layer, format, and batch flag directly from controls.

        This method reads the live state of the ComboBoxes and Checkbox. It is 
        useful for fetching the result in one tuple, particularly when the dialog 
        is used synchronously.

        Returns:
            Tuple[str, str, bool]: A tuple containing:
                1. The currently selected layer name (str).
                2. The selected preview format, lowercased (str, e.g., 'jpg').
                3. The status of the 'apply to all' checkbox (bool).
        """
        return (
            self.layer_combo.currentText(),
            self.format_combo.currentText().lower(),
            self.apply_all_checkbox.isChecked() if self.apply_all_checkbox else False
        )
    
    def _collect_results_and_accept(self):
        """Helper function to guarantee that documented result attributes are updated 
        with the final user selections before the dialog is accepted and closed.
        
        This prevents the calling code from potentially reading stale data 
        from the instance attributes.
        """
        # 1. Hämta de aktuella värdena från kontrollerna
        layer, fmt, apply_all = self.get_values()
        
        # 2. Uppdatera de dokumenterade instansattributen
        self.selected_layer = layer
        self.selected_format = fmt
        self.apply_to_all = apply_all
        
        # 3. Stäng dialogrutan
        self.accept()
