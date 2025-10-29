from __future__ import annotations

import os
import json
import shutil
import time
from functools import partial

from typing import List, Optional , Tuple

import nuke

from PySide2.QtCore import Qt, QRectF, QPointF, QPoint, QEvent
from PySide2.QtGui import (
    QPixmap, QKeySequence, 
    QDragEnterEvent, QDragMoveEvent, QDropEvent, QWheelEvent, 
    QMouseEvent, QKeyEvent
)
from PySide2.QtWidgets import (
    QGraphicsView, QGraphicsScene, QDialog, QApplication, QShortcut, QAction, QMenu, QMessageBox, QWidget
)

from image_display import ImageDisplay
from dialog import EXRImportDialog



class CoffeeBoard(QGraphicsView):
    """A custom QGraphicsView designed as an interactive reference board for VFX workflows.

    The board acts as a central canvas for visual reference gathering. It supports 
    drag-and-drop file loading (including EXR files), copying images from the system 
    clipboard, and manages image items via the ImageDisplay class. Key functionality 
    includes pan/zoom navigation, asset consolidation for portability, and saving 
    the board's layout state to JSON.

    Attributes (State Variables):
        scene (QGraphicsScene): The scene object managed by the view, containing all image items.
        image_items (List[ImageDisplayType]): Internal list tracking all loaded 
                                              ImageDisplay instances.
        scale_factor (float): The current overall zoom level of the viewport.
        panning (bool): Flag indicating if the user is currently panning the view (Middle Mouse Button).
        pan_origin (QtCore.QPointF): The initial mouse position when panning began.
        current_save_path (Optional[str]): The file path where the board was last saved or loaded.
    
    Attributes (Configuration/Constants):
        min_scale (float): The minimum zoom factor allowed (e.g., 0.0001).
        max_scale (float): The maximum zoom factor allowed (e.g., 10.0).
        columns (int): The default number of columns used when automatically laying out images.
        preview_format (str): The default file extension used when consolidating clipboard 
                              images (e.g., 'png').
    """
    
    # --- ATTRIBUTE TYPE HINTS ---
    
    # State Variables (Initialized in __init__)
    scene: QGraphicsScene
    image_items: List['ImageDisplay']
    scale_factor: float
    panning: bool
    pan_origin: QPointF
    current_save_path: Optional[str]

    # Configuration Constants
    min_scale: float = 0.001
    max_scale: float = 100.0
    columns: int = 4
    preview_format: str = 'jpg'
    
    # --------------------------
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initializes the Coffee Board, a custom QGraphicsView.

        This class sets up the drawing scene, initializes core variables,
        and configures the view properties specifically to handle the display
        and manipulation of reference images and assets.

        Args:
            parent (QObject | None, optional):  The parent object in the Qt hierarchy. 
                                                If set, the parent manages the memory 
                                                for the CoffeeBoard instance. Defaults to None.
        """
        
        super().__init__(parent)
        self.setWindowTitle("Coffee Board")
        self.setMinimumSize(600, 400)
        self.setAcceptDrops(True)

        
        SCENE_SIZE = 1000000
        huge_rect = QRectF(-SCENE_SIZE, -SCENE_SIZE, 2*SCENE_SIZE, 2*SCENE_SIZE)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        self.scene.setSceneRect(huge_rect)

        # Set up rendering and interaction
        #self.setRenderHint(QPainter.Antialiasing)
        #self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)

        # Hide scrollbars
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Enable drag mode for item selection, but we'll override for panning
        self.setDragMode(QGraphicsView.RubberBandDrag)

        # State variables
        self.pan_origin = QPointF()
        self.panning = False
        self.image_items = []
        self.current_save_path = None
        self.scale_factor = 1.0
        
        # Keyboard shortcuts
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.activated.connect(self.save_board)
        self.fit_all_to_view_shortcut = QShortcut(QKeySequence("F"), self)
        self.fit_all_to_view_shortcut.activated.connect(self.fit_all_to_view)
        self.past_shortcut = QShortcut(QKeySequence("Ctrl+V"), self)
        self.past_shortcut.activated.connect(self.paste_from_clipboard)
        
        # Actions
        self._resize_scales = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]
        self.resize_actions = []
        for scale in self._resize_scales:
            act = QAction(f"{int(scale * 100)}%", self)
            act.setData(scale)
            # bind scale directly to avoid late-binding lambda problems
            act.triggered.connect(partial(self.resize_selected_images, scale))
            self.resize_actions.append(act)


        self.bring_front_action = QAction("Bring to Front", self)
        self.bring_front_action.triggered.connect(self.bring_to_front)
        
        self.send_back_action = QAction("Send to Back", self)
        self.send_back_action.triggered.connect(self.send_to_back)

        self.delete_action = QAction("Delete")
        self.delete_action.triggered.connect(self.delete_selected_images)
        
        self.save_action = QAction("Save Reference Board...", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.triggered.connect(self.save_board)
        
        self.load_action = QAction("Load Reference Board...", self)
        self.load_action.triggered.connect(self.load_board)
        
        self.consolidate_action = QAction("Consolidate Assets...", self)
        self.consolidate_action.triggered.connect(self.consolidate_assets)
        
        self.clear_action = QAction("Clear All Images", self)
        self.clear_action.triggered.connect(self.clear_all_images)
        
        self.fit_action = QAction("Fit All to View", self)
        self.fit_action.setShortcut("f")
        self.fit_action.triggered.connect(self.fit_all_to_view)
         
        self.paste_action = QAction("Paste Image", self)
        self.paste_action.setShortcut("Ctrl+V")
        self.paste_action.triggered.connect(self.paste_from_clipboard)


    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Handles the drag-enter event when external data is dragged into the view.

        This method checks if the data being dragged contains URLs (file paths). 
        If valid file paths are present, the drag action is accepted, allowing 
        the user to drop the files. Otherwise, the event is ignored.

        Args:
            event (QDragEnterEvent): The event object containing information about 
                                     the data being dragged.
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Handles the drag-move event while external data is moved over the view.

        This method continuously checks the data being dragged to maintain 
        visual feedback that a drop action is possible. If the data contains 
        valid file URLs, the proposed action is accepted.

        Args:
            event (QDragMoveEvent): The event object containing information about 
                                    the current position of the dragged data.
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Handles the drop event, validating files and importing them as image items.

        This is the core import method. It filters dropped files for supported image 
        formats (JPG, PNG, EXR, TIFF, BMP), handles Nuke-specific progress tracking, 
        and manages user prompts for multi-layer files (like EXRs) using internal 
        methods (`_prompt_for_layer`). It temporarily disables view updates for 
        large batches (>10 files) to improve performance during loading.

        Upon successful loading, the image items are positioned using the 
        internal `_layout_images` method.

        Args:
            event (QDropEvent): The event object containing the dropped data, including file URLs.
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            
            files_to_load = []
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                ext = os.path.splitext(path)[1].lower()
                if ext in [".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".exr"]:
                    files_to_load.append(path)
                else:
                    nuke.message(f"Unsupported file type dropped:\n{path}\n\nOnly supports JPG, PNG, EXR, TIFF, BMP.")
            
            if not files_to_load:
                event.ignore()
                return
            
            total_files = len(files_to_load)
            
            # Check if we have multiple EXRs
            exr_files = [f for f in files_to_load if f.lower().endswith('.exr')]
            has_multiple_exrs = len(exr_files) > 1
            
            batch_layer = None
            batch_format = None
            apply_to_all = False
            
            progress = None
            
            progress = nuke.ProgressTask(f"Importing {total_files} images")
            progress.setMessage("Starting import...")
            
            try:
                # Disable updates for faster loading
                if total_files > 10:
                    self.setUpdatesEnabled(False)
                
                loaded_count = 0
                
                for idx, path in enumerate(files_to_load):
                    # Update progress
                    if progress:
                        if progress.isCancelled():
                            print(f"Import cancelled by user. Loaded {loaded_count} of {total_files} images.")
                            break
                        
                        progress_percent = int((idx / float(total_files)) * 100)
                        progress.setProgress(progress_percent)
                        progress.setMessage(f"Loading {idx + 1} of {total_files}: {os.path.basename(path)}")
                    
                    ext = os.path.splitext(path)[1].lower()
                    
                    try:
                    # For EXR files
                        if ext == '.exr':
                            if apply_to_all and batch_layer and batch_format:
                                self.add_image(path, layer=batch_layer, preview_format=batch_format)
                                loaded_count += 1
                            else:
                                layer, fmt, apply_all = self._prompt_for_layer(path, is_batch=has_multiple_exrs)
                                
                                if layer is None:
                                    continue  # User cancelled this file
                                
                                # Save settings if user checked "apply to all"
                                if apply_all:
                                    apply_to_all = True
                                    batch_layer = layer
                                    batch_format = fmt
                                
                                self.add_image(path, layer=layer, preview_format=fmt)
                                loaded_count += 1
                        else:
                        # Regular image
                            self.add_image(path)
                            loaded_count += 1
                            
                    except Exception as e:
                        print(f"Failed to load {path}: {e}")
                        nuke.message(f"Failed to load image:\n{path}\n\nError: {str(e)}")
                
                # Complete progress
                if progress:
                    progress.setProgress(100)
                
                print(f"Successfully loaded {loaded_count} of {total_files} images")
                
            finally:
                # Clean up progress
                if progress:
                    del progress
                
                # Re-enable updates
                if total_files > 10:
                    self.setUpdatesEnabled(True)
            
            # Layout all images at once
            self._layout_images()
        else:
            event.ignore()
                    
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handles zooming in and out of the view using the mouse wheel.

        The zoom is centered around the mouse cursor's current position.
        The function determines the direction of the wheel movement to apply 
        either an increase (zoom in) or decrease (zoom out) factor to the view's transformation.

        Args:
            event (QWheelEvent): The event object containing the wheel movement data, 
                                 including angle and position.
        """
        # Zoom with smooth scaling
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor

        old_pos = self.mapToScene(event.pos())
        
        # Determine zoom factor
        if event.angleDelta().y() > 0:
            zoom_factor = zoom_in_factor
        else:
            zoom_factor = zoom_out_factor

        # Apply scaling around the mouse position
        self.scale(zoom_factor, zoom_factor)
        
        # Update the cumulative scale factor
        self.scale_factor *= zoom_factor
        
        # Clamp scale_factor to min/max
        if self.scale_factor < self.min_scale:
            correction = self.min_scale / self.scale_factor
            self.scale(correction, correction)
            self.scale_factor = self.min_scale
        elif self.scale_factor > self.max_scale:
            correction = self.max_scale / self.scale_factor
            self.scale(correction, correction)
            self.scale_factor = self.max_scale
        
        new_pos = self.mapToScene(event.pos())

        # Calculate the difference and translate to keep mouse position fixed
        delta = new_pos - old_pos
        self.translate(delta.x(), delta.y())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handles mouse button presses for panning, context menu, and selection.

        This method overrides the standard QGraphicsView behavior to implement:
        1. Middle Button: Starts the panning state by setting the cursor to a closed hand.
        2. Right Button: Triggers the display of the view's context menu.
        3. Left Button: Clears the selection if the click is on the background, 
        otherwise delegates to the base class for standard item selection.

        Args:
            event (QMouseEvent): The event object containing mouse button and position data.
        """
        if event.button() == Qt.MiddleButton:
            # Start panning
            self.panning = True
            self.pan_origin = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        elif event.button() == Qt.RightButton:
            # Show context menu
            self.show_context_menu(event.pos())
            event.accept()
        elif event.button() == Qt.LeftButton:
            # Check if clicking on background
            if not self.itemAt(event.pos()):
                self.scene.clearSelection()
            # Let the default behavior handle item selection/movement
            super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handles mouse movement for the custom panning feature.

        If the `self.panning` state is active (triggered by the middle mouse button), 
        the method calculates the delta movement from the previous position (`self.pan_origin`). 
        It then translates the view using the `translate` method, normalizing the 
        movement by the current `self.scale_factor` to ensure speed is consistent 
        regardless of zoom level.

        If not panning, the event is passed to the base class for standard behaviors 
        (e.g., moving selected items).

        Args:
            event (QMouseEvent): The event object containing the current mouse position.
        """
        if self.panning:
            # Calculate delta in view coordinates
            delta = event.pos() - self.pan_origin
            
            # Update the pan origin for the next move
            self.pan_origin = event.pos()
            
            # Just translate directly with the sensitivity factor
            self.translate(delta.x() / self.scale_factor, 
                         delta.y() / self.scale_factor)
            
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Handles mouse button releases, primarily for stopping panning.

        If the middle mouse button is released and the view is currently in the 
        panning state (`self.panning` is True), this method resets the panning 
        flag and restores the mouse cursor to the standard arrow.

        Other button releases are passed to the base class for default behavior.

        Args:
            event (QMouseEvent): The event object containing the released mouse button data.
        """
        if event.button() == Qt.MiddleButton and self.panning:
            self.panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Handles the event when the mouse cursor leaves the view's widget area.

        This method is a critical cleanup step for the panning state. It checks 
        if the view is currently panning (`self.panning` is True) but the middle 
        mouse button has *not* been held down. If the mouse leaves while the 
        button is no longer pressed, it resets the panning state and restores 
        the standard arrow cursor to prevent hanging state.

        Args:
            event (QEvent): The base event object for the mouse leaving the widget.
        """
        if self.panning:
            if not (QApplication.instance().mouseButtons() & Qt.MiddleButton):
                self.panning = False
                self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def enterEvent(self, event: QEvent) -> None:
        """Handles the event when the mouse cursor enters the view's widget area.

        This method acts as a recovery or cleanup mechanism. If the view is in the 
        panning state (`self.panning` is True) but the middle mouse button is no 
        longer physically pressed (checked via `QApplication.instance().mouseButtons()`),
        it resets the panning state and restores the mouse cursor to the standard arrow. 
        This prevents a "stuck" closed-hand cursor if the button was released 
        outside the view boundary.

        Args:
            event (QEvent): The event object signaling that the mouse cursor 
                                 has entered the widget.
        """
        if self.panning and not (QApplication.instance().mouseButtons() & Qt.MiddleButton):
            self.panning = False
            self.setCursor(Qt.ArrowCursor)
        super().enterEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handles key press events, primarily for deleting selected items.

        If the Delete or Backspace key is pressed, the method iterates through all 
        selected items in the scene. If the selected item is an instance of 
        `ImageDisplay`, it is removed from both the scene and the internal 
        `self.image_items` tracking list.

        All other key presses are delegated to the base `QGraphicsView` class 
        for default handling (e.g., arrow key navigation).

        Args:
            event (QKeyEvent): The event object containing the specific key that was pressed.
        """
        # Delete selected items with Delete or Backspace
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            for item in self.scene.selectedItems():
                if isinstance(item, ImageDisplay):
                    self.scene.removeItem(item)
                    if item in self.image_items:
                        self.image_items.remove(item)
            #self._update_scene_rect_after_item_move()
        else:
            super().keyPressEvent(event)



    def show_context_menu(self, pos: QPoint) -> None:
        """Shows the context menu at the specified view coordinate.

        The menu content is dynamically generated based on the click location:
        
        1. Click on Image Item: Displays the full menu, including actions for 
           resize, layer ordering (bring to front/send to back), deletion, 
           and file operations (save/load/consolidate). If multiple images 
           are selected, the menu ensures the clicked item is selected first.
        2. Click on Background: Displays a simplified menu with global actions 
           like clear all, fit view, paste, save, load, and consolidate.

        The method handles coordinate transformation (`self.mapToGlobal(pos)`) 
        to ensure the menu appears correctly under the mouse cursor across 
        different monitors or desktop environments.

        Args:
            pos (QPoint): The local coordinate point within the QGraphicsView 
                          where the mouse event occurred.
        """
        menu = QMenu(self)

        # Get item at click position
        item = self.itemAt(pos)

        if item and isinstance(item, ImageDisplay):
            selected_images = [i for i in self.scene.selectedItems() if isinstance(i, ImageDisplay)]
            if item not in selected_images:
                # deselect others and select the clicked one
                for si in selected_images:
                    si.setSelected(False)
                item.setSelected(True)

        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, ImageDisplay)]


        show_image_menu = bool(selected_items) or (item and isinstance(item, ImageDisplay))


        # Menu for when clicking on an image
        if show_image_menu:
            if len(selected_items) > 1:
                menu.addSection(f"{len(selected_items)} images selected")
            # Resize submenu
            resize_menu = menu.addMenu("Resize")
            for act in self.resize_actions:
                resize_menu.addAction(act)
            menu.addSeparator()
                        
            menu.addAction(self.bring_front_action)
            menu.addAction(self.send_back_action)
            
            menu.addSeparator()
            
            menu.addAction(self.delete_action)
            menu.addAction(self.clear_action)
            
            menu.addSeparator()
            
            menu.addAction(self.fit_action)
            
            menu.addSeparator()
            
            menu.addAction(self.paste_action)
                        
            menu.addSeparator()
            
            menu.addAction(self.save_action)
            menu.addAction(self.load_action)
            menu.addAction(self.consolidate_action)



        # Menu for when clicking on background
        else:
            menu.addAction(self.clear_action)
            
            menu.addSeparator()
            
            menu.addAction(self.fit_action)
            
            menu.addSeparator()
            
            menu.addAction(self.paste_action)
            
            menu.addSeparator()
            
            menu.addAction(self.save_action)
            menu.addAction(self.load_action)
            menu.addAction(self.consolidate_action)

        # Show the menu at cursor position
        menu.exec_(self.mapToGlobal(pos))



    def _layout_images(self) -> None:
        """Arranges all currently tracked image items in a grid layout.

        This private method iterates through the `self.image_items` list and 
        positions them based on the configured `self.columns` and `spacing`. 
        It tracks the maximum height of items in the current row to ensure 
        subsequent rows start correctly below the tallest image.

        The method calculates positions directly in scene coordinates. 
        It handles the edge case where no images are loaded by simply returning.
        
        Note:
            The layout logic is directly implemented within this method.
        """
        x, y = 0.0, 0.0
        max_row_height = 0.0
        spacing = 10.0

        if not self.image_items:
            #self.scene.setSceneRect(QRectF(0, 0, 800, 600))
            return

        for i, item in enumerate(self.image_items):
            item_width = item.boundingRect().width()
            item_height = item.boundingRect().height()

            item.setPos(x, y)
            x += item_width + spacing
            max_row_height = max(max_row_height, item_height)

            if (i + 1) % self.columns == 0:
                y += max_row_height + spacing
                x = 0.0
                max_row_height = 0.0
        
        # Add padding to scene rect
        """
        items_rect = self.scene.itemsBoundingRect()
        padded_rect = items_rect.adjusted(-50, -50, 50, 50)
        self.scene.setSceneRect(padded_rect)
        """

    def _update_scene_rect_after_item_move(self) -> None:
        """(Inactive) Placeholder for dynamic scene boundary adjustment.

        This private method was originally designed to recalculate the scene's 
        bounding box (`sceneRect`) based on the current position of all items 
        (`itemsBoundingRect`). This ensures that the view's scroll area and panning 
        limits automatically expand as items are moved further out.

        Note:
            The logic within this method is currently commented out (`pass`), 
            meaning the scene boundary is static or managed elsewhere.
        """
        # Optionally update scene bounds - not called during item moves anymore
        """
        items_rect = self.scene.itemsBoundingRect()
        padded_rect = items_rect.adjusted(-50, -50, 50, 50)
        self.scene.setSceneRect(padded_rect)
        """
        pass
    
    
    def _prompt_for_layer(self, path: str, is_batch: bool = False) -> Tuple[str | None, str | None, bool]:
        """Prompts the user to select the layer and preview format for an EXR file.

        This private helper method is exclusively used during the drop event for EXR 
        files. It performs the following steps:
        1. **Reads Layers:** Creates a temporary Nuke Read node to inspect the file's 
           available channels and parses them to identify unique layers (e.g., 'rgba', 'depth', 'world_p').
        2. **Displays Dialog:** Shows a custom `EXRImportDialog` where the user selects 
           the layer to display and the desired preview format.
        3. **Batch Handling:** Adapts the dialog based on the `is_batch` flag to allow 
           the user to apply the selection to all dropped EXR files in the current batch.

        Args:
            path (str): The full file path to the EXR image.
            is_batch (bool, optional): True if multiple EXR files are being dropped 
                                       simultaneously, enabling the "Apply to All" option. 
                                       Defaults to False.

        Returns:
            Tuple[str | None, str | None, bool]: A tuple containing:
                - layer (str | None): The selected layer name (e.g., 'diffuse') or None if cancelled.
                - format (str | None): The selected preview format string (e.g., 'sRGB').
                - apply_to_all (bool): True if the user selected to apply these settings to the entire batch.
        """
        try:
            # Create temporary Read node to get available layers
            read_node = nuke.nodes.Read(file=path)
            read_node.knob('file').evaluate()
            channels = read_node.channels()
            nuke.delete(read_node)
            
            # Parse channels to find layers
            layers = set()
            for ch in channels:
                if '.' in ch:
                    layer_name = ch.split('.')[0]
                    layers.add(layer_name)
                else:
                    layers.add('rgba')
            
            if not layers:
                return ('rgba', self.preview_format, False)
            
            layer_list = sorted(list(layers))
            
            # Show custom dialog
            dialog = EXRImportDialog(path, layer_list, is_batch, parent=self)
            
            if dialog.exec_() == QDialog.Accepted:
                layer, fmt, apply_all = dialog.get_values()
                return (layer, fmt, apply_all)
            else:
                return (None, None, False)
                
        except Exception as e:
            print(f"Error getting layers from {path}: {e}")
            import traceback
            traceback.print_exc()
            return ('rgba', self.preview_format, False)

    def _prompt_clipboard_save_choice(self) -> Optional[str]:
        """Prompts the user on how to handle temporary clipboard images during a save operation.

        When a save action is triggered, this private method checks the internal 
        image list for any items marked with the special path 'clipboard_image'. 
        If such items exist, a custom QMessageBox is displayed, offering the user 
        three consolidation choices:

        1. 'Consolidate_All': Consolidate all images (including those with file paths).
        2. 'Consolidate_Clipboard_Only': Only consolidate clipboard images into new files.
        3. 'Ignore_Clipboard': Exclude clipboard images from the save operation entirely.

        Args:
            None: The method determines its state internally from `self.image_items`.

        Returns:
            str | None: The selected action string, or 'None' if no clipboard images 
                        were found, or None if the user cancelled the dialog.
        """
        clipboard_items = [i for i in self.image_items if getattr(i, 'path', None) == "clipboard_image"]
        if not clipboard_items:
            return 'None'  # no clipboard images; caller can treat as 'no special handling'

        msg = QMessageBox(self)
        msg.setWindowTitle("Clipboard Images Detected")
        msg.setText(f"{len(clipboard_items)} clipboard image(s) detected. Choose how to save them:")
        msg.setIcon(QMessageBox.Question)

        btn_consolidate_all = msg.addButton("Consolidate All", QMessageBox.AcceptRole)
        btn_consolidate_clip = msg.addButton("Consolidate Clipboard Only", QMessageBox.AcceptRole)
        btn_ignore = msg.addButton("Ignore Clipboard Images", QMessageBox.DestructiveRole)
        msg.setStandardButtons(QMessageBox.Cancel)

        msg.setDefaultButton(btn_consolidate_all)
        msg.exec_()

        clicked = msg.clickedButton()
        if clicked == btn_consolidate_all:
            return 'Consolidate_All'
        if clicked == btn_consolidate_clip:
            return 'Consolidate_Clipboard_Only'
        if clicked == btn_ignore:
            return 'Ignore_Clipboard'
        # Cancel or closed
        return None



    def add_image(self, path: str, layer: str = 'rgba', preview_format: str = 'jpg') -> None:
        """Adds a new ImageDisplay item to the board.

        This is the primary method for creating visual image references. It handles 
        file validation and instantiation of the visual element.

        The process is:
        1. **Validation:** Checks if the file exists and raises an IOError if not.
        2. **EXR Layer Prompting:** If the file is an EXR and no specific layer is 
           provided (`layer='rgba'`), it triggers the `_prompt_for_layer` dialog 
           to let the user choose the desired layer and a consolidation file format. 
           If the user cancels, the operation stops.
        3. **Instantiation:** Creates an `ImageDisplay` instance with the provided 
           path, layer, and format.
        4. **Scene Update:** Adds the new item to the `self.scene` and tracks it 
           in the `self.image_items` list.

        Args:
            path (str): The full file path to the image, or a special marker like 
                        'clipboard_image'.
            layer (str, optional): The specific layer to load for multi-channel 
                                   formats (e.g., 'diffuse', 'rgba'). Defaults to 'rgba'.
            preview_format (str, optional): The default file extension 
                                            (e.g., 'jpg', 'png', 'tif') to be used 
                                            if this image needs to be **consolidated** (saved to a new file). Defaults to 'jpg'.

        Raises:
            IOError: If the specified file path does not exist.
            Exception: If the image item fails to be created (e.g., problem with Nuke Read).
        """
        # Check if file exists
        if not os.path.exists(path):
            raise IOError(f"File does not exist: {path}")
        
        ext = os.path.splitext(path)[1].lower()
        
        # For EXR files, prompt for layer selection
        if ext == '.exr' and layer == 'rgba':
            layer, preview_format, _ = self._prompt_for_layer(path, is_batch=False)
            if layer is None:
                return  # User cancelled
        
        print(f"Loading {path} with layer: {layer}, format: {preview_format}")
    
        try:
            image_item = ImageDisplay(path, layer, preview_format)
            self.scene.addItem(image_item)
            self.image_items.append(image_item)
        except Exception as e:
            print(f"Failed to add image {path}: {e}")
            raise
    
    def paste_from_clipboard(self) -> None:
        """Handles the pasting of image data directly from the system clipboard.

        This method is typically connected to a menu action (e.g., 'Paste') or 
        a keyboard shortcut (e.g., Ctrl+V/Cmd+V).

        The process is:
        1. **Check Data:** Retrieves data from `QApplication.clipboard()` and checks 
           if it contains an image (`mimeData.hasImage()`).
        2. **Process Image:** Converts the clipboard image into a `QPixmap`.
        3. **Create Item:** Instantiates a new `ImageDisplay` item using the `QPixmap`.
        4. **Positioning:** Centers the new image item relative to the current 
           view center, allowing the user to immediately see the pasted image 
           regardless of their current pan/zoom state.
        5. **Tracking:** Adds the new item to the scene and the internal tracking list.
        
        Note:
            If no image data is found, a Nuke message box is displayed to the user.
        """

        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasImage():
            # Get image from clipboard
            image = clipboard.image()
            if not image.isNull():
                # Convert to pixmap
                pixmap = QPixmap.fromImage(image)
                
                # Create ImageDisplay item
                image_item = ImageDisplay(pixmap)
                self.scene.addItem(image_item)
                
                # Position at view center
                view_center = self.mapToScene(self.viewport().rect().center())
                image_item.setPos(view_center)
                
                # Add to image list if you're tracking them
                self.image_items.append(image_item)
        else:
            nuke.message("No image data found in clipboard.")


    def resize_selected_images(self, scale: float) -> None:
        """Resizes all currently selected ImageDisplay items to the specified scale factor.

        This method is invoked by the 'Resize' submenu actions in the context menu. 
        It iterates over the scene's current selection and ensures that only items 
        of the type `ImageDisplay` are processed. The actual transformation (resizing) 
        is delegated to the `resize_image` method of each individual item.

        Args:
            scale (float): The multiplicative factor by which the image size 
                           should be adjusted (e.g., 0.5 for half size, 2.0 for double size).
        """
        for item in self.scene.selectedItems():
            if isinstance(item, ImageDisplay):
                item.resize_image(scale)

    def bring_to_front(self) -> None:
        """Brings all currently selected ImageDisplay items to the foreground.

        This method controls the Z-stacking order (layering) of the items in the scene. 
        It operates by:
        1. **Finding Max Z:** Calculating the current highest Z-value among *all* tracked 
           image items (`self.image_items`).
        2. **Setting Z-Value:** Setting the Z-value of all selected images to be 
           one unit higher than the previous maximum (`max_z + 1`). This ensures 
           the selected items are visually displayed above all other items on the board.

        The operation safely filters the selection to only process `ImageDisplay` items.
        """
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, ImageDisplay)]
        if not selected_items:
            return
        
        # Find the highest z-value
        max_z = max([item.zValue() for item in self.image_items])
        
        for item in selected_items:
            item.setZValue(max_z + 1)

    def send_to_back(self) -> None:
        """Sends all currently selected ImageDisplay items to the background.

        This method adjusts the Z-stacking order (layering) to place selected items 
        behind all other items in the scene. It operates by:
        1. **Finding Min Z:** Calculating the current lowest Z-value among *all* tracked 
           image items (`self.image_items`).
        2. **Setting Z-Value:** Setting the Z-value of all selected images to be 
           one unit lower than the previous minimum (`min_z - 1`). This ensures 
           the selected items are visually displayed furthest back on the board.

        The operation safely filters the selection to only process `ImageDisplay` items.
        """
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, ImageDisplay)]
        if not selected_items:
            return
        
        # Find the lowest z-value
        min_z = min([item.zValue() for item in self.image_items])
        
        for item in selected_items:
            item.setZValue(min_z - 1)

    def delete_selected_images(self) -> None:
        """Removes all currently selected ImageDisplay items from the board.

        This method is invoked by the 'Delete' context menu action and the Delete/Backspace 
        key event. It performs a controlled deletion process:
        1. **Iteration:** Safely iterates over a copy of the currently selected items.
        2. **Removal:** For each item that is an `ImageDisplay` instance, it is removed 
           from the QGraphicsScene using `self.scene.removeItem(item)`.
        3. **Cleanup:** The item is also explicitly removed from the internal tracking 
           list (`self.image_items`) to maintain a clean state.
        
        Note:
            The use of `list()` ensures that the iteration is safe even while 
            modifying the underlying scene selection.
        """
        for item in list(self.scene.selectedItems()):
            if isinstance(item, ImageDisplay):
                self.scene.removeItem(item)
                if item in self.image_items:
                    self.image_items.remove(item)
        #self._update_scene_rect_after_item_move()

    def clear_all_images(self) -> None:
        """Removes all ImageDisplay items from the scene and resets the board state.

        This method is invoked by the 'Clear All' context menu action. It iterates 
        over the internal tracking list (`self.image_items`) and removes each item 
        from the QGraphicsScene. After removal, it clears the tracking list itself 
        and resets the QGraphicsSceneRect to the initial default bounds (0, 0, 800, 600).
        """
        for item in list(self.image_items):
            self.scene.removeItem(item)
        self.image_items.clear()
        self.scene.setSceneRect(QRectF(0, 0, 800, 600))

    def fit_all_to_view(self) -> None:
        """Resets the view transform and scales it to fit all images within the viewport.

        This method is invoked by the 'Fit View' context menu action. It performs 
        the following steps to ensure all content is visible:
        1. **Reset Transform:** Clears any existing pan or zoom by calling `resetTransform()`.
        2. **Update Internal Scale:** Resets the internal `self.scale_factor` to 1.0 
           before fitting the view.
        3. **Fit View:** Calls `self.fitInView()` using the bounding rectangle of 
           all items in the scene (`scene.itemsBoundingRect()`). It maintains the 
           aspect ratio (`Qt.KeepAspectRatio`).
        4. **Recalculate Scale:** Updates `self.scale_factor` to the new, accurate 
           scaling value applied by the `fitInView` operation, ensuring that 
           subsequent panning and zooming (`wheelEvent`, `mouseMoveEvent`) remain 
           correctly calibrated.

        Note:
            If no images are present on the board, the method exits immediately.
        """
        if not self.image_items:
            return
        
        # Reset transform
        self.resetTransform()
        self.scale_factor = 1.0
        
        # Fit the scene rect in view
        self.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)
        
        # Update scale factor
        self.scale_factor = self.transform().m11()


    def save_board(self, consolidate: bool = False) -> None:
        """Saves the current state of the reference board, including all images and their metadata, to a JSON file.

        The core functionality serializes the position, scale, Z-value, and file path 
        of every ImageDisplay item.

        This method supports **consolidation**, which means copying non-local files 
        (like clipboard images) or optionally all files into a subdirectory 
        (named '{boardname}_images') next to the saved JSON file to ensure portability.

        The process includes:
        1. **Clipboard Prompting:** If `consolidate` is False, the user is prompted 
           via `_prompt_clipboard_save_choice` on how to handle temporary clipboard images.
        2. **Path Resolution:** Determines the save path, using `self.current_save_path` 
           if available, or prompts the user via `nuke.getFilename`.
        3. **Consolidation Logic:** Creates the images subdirectory if any consolidation 
           action ('Consolidate_All' or 'Consolidate_Clipboard_Only') is selected.
        4. **Image Serialization:** Iterates through `self.image_items`:
           - **Clipboard Images:** If marked 'clipboard_image', the internal `QPixmap` is saved 
             to the consolidation folder as a new PNG file.
           - **Regular Images:** Stores paths as relative if consolidation is not requested 
             or copies them and stores the new relative path if 'Consolidate_All' is selected.
        5. **Metadata Recording:** Stores all necessary item metadata (position, scale, z-value) 
           in a structured JSON format, prioritizing relative paths for portability.

        Args:
            consolidate (bool, optional): If True, forces consolidation of all items 
                                          and skips the clipboard handling prompt. 
                                          Defaults to False.
        """
        # Prompt about clipboard images unless consolidate was explicitly requested
        if consolidate:
            action = 'Consolidate_All'
        else:
            action = self._prompt_clipboard_save_choice()
            if action is None:
                return  # user cancelled

        if self.current_save_path:
            file_path = self.current_save_path
        else:
            file_path = nuke.getFilename("Save Reference Board", pattern="*.json", type='save')

        if not file_path:
            return  # User cancelled

        # Ensure .json extension
        if not file_path.endswith('.json'):
            file_path += '.json'

        try:
            save_dir = os.path.dirname(file_path)
            board_data = {"images": []}

            # Prepare images folder only if we will consolidate any images
            will_consolidate_any = (action == 'Consolidate_All') or (action == 'Consolidate_Clipboard_Only')
            images_folder = None
            base_name = None
            if will_consolidate_any:
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                images_folder = os.path.join(save_dir, f"{base_name}_images")
                if not os.path.exists(images_folder):
                    os.makedirs(images_folder)

            copied_count = 0
            clipboard_counter = 0

            for item in self.image_items:
                image_path = getattr(item, 'path', None)

                # Handle clipboard images
                if image_path == "clipboard_image":
                    if not will_consolidate_any:
                        continue
                
                    # Save pixmap to images_folder
                    clipboard_counter += 1
                    filename = f"clipboard_image_{time.strftime('%Y%m%d_%H%M%S')}_{clipboard_counter}.png"
                    new_image_path = os.path.join(images_folder, filename)
                    try:
                        # save QPixmap to file
                        item.original_pixmap.save(new_image_path, 'PNG')
                        copied_count += 1
                    except Exception as e:
                        print(f"Failed to write clipboard image to {new_image_path}: {e}")
                        # create fallback empty file entry and continue
                        new_image_path = None

                    rel_path = os.path.join(f"{base_name}_images", filename) if new_image_path else None
                    abs_path = new_image_path or ""
                    

                # regular image handling
                else:
                    if action == 'Consolidate_All':
                        # copy regular files into images_folder
                        image_filename = os.path.basename(image_path)
                        base, ext = os.path.splitext(image_filename)
                        counter = 1
                        new_image_path = os.path.join(images_folder, image_filename)
                        while os.path.exists(new_image_path):
                            image_filename = f"{base}_{counter}{ext}"
                            new_image_path = os.path.join(images_folder, image_filename)
                            counter += 1
                        shutil.copy2(image_path, new_image_path)
                        copied_count += 1
                        rel_path = os.path.join(f"{base_name}_images", image_filename)
                        abs_path = new_image_path
                    else:
                        # Not consolidating regular files: store relative if possible
                        try:
                            rel_path = os.path.relpath(image_path, save_dir)
                        except Exception:
                            rel_path = None
                        abs_path = image_path

                # Add entry for this image
                image_data = {
                    "path": rel_path if rel_path else abs_path,
                    "absolute_path": abs_path,
                    "position": [item.pos().x(), item.pos().y()],
                    "scale": item.current_scale,
                    "z_value": item.zValue(),
                    "layer": getattr(item, 'layer', 'rgba')
                }
                board_data["images"].append(image_data)

            # Write JSON
            with open(file_path, 'w') as f:
                json.dump(board_data, f, indent=2)

            self.current_save_path = file_path
            print(f"Reference board saved to: {file_path} (copied {copied_count} files)")

        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save reference board:\n{str(e)}")
            print(f"Error saving board: {e}")

    def load_board(self) -> None:
        """Loads the saved state of a reference board from a specified JSON file.

        The method handles file reading, state restoration, and path resolution for all images.

        The process includes:
        1. **File Selection:** Prompts the user using `nuke.getFilename` to select a JSON file.
        2. **State Cleanup:** Clears all existing images via `self.clear_all_images()` before loading.
        3. **Performance Optimization:** Temporarily disables scene updates and initializes 
           a `nuke.ProgressTask` to provide feedback during potentially long loading times.
        4. **Path Resolution:** For each image entry, it attempts to resolve the file path:
           - **First:** Tries the **relative path** (`path` field) joined with the directory of the 
             loaded JSON file (`load_dir`).
           - **Second:** Falls back to the stored **absolute path** (`absolute_path` field).
        5. **Item Restoration:** Successfully resolved images are loaded into new 
           `ImageDisplay` objects, and their position, scale, and Z-stacking order are restored 
           using the metadata from the JSON.
        6. **Finalization:** Updates are re-enabled, the scene bounds are calculated, 
           the save path is stored, and the view is fitted to the loaded content.
        7. **Error Reporting:** Notifies the user via a `nuke.message` box if any images 
           could not be found or failed to load.

        Args:
            None: The file path is determined by a user prompt via Nuke's GUI.
        """
        file_path = nuke.getFilename("Load Reference Board", pattern="*.json")
        
        if not file_path:
            return
        
        try:
            # Read the file
            with open(file_path, 'r') as f:
                board_data = json.load(f)
            
            # Clear existing images
            self.clear_all_images()
            
            # Disable updates for faster loading
            self.setUpdatesEnabled(False)
            
            load_dir = os.path.dirname(file_path)
            images_data = board_data.get("images", [])
            total_images = len(images_data)
            missing_images = []
            loaded_count = 0
            
            # Create progress task
            progress = nuke.ProgressTask("Loading Reference Board")
            progress.setMessage(f"Loading {total_images} images...")
            
            try:
                # Load each image
                for idx, img_data in enumerate(images_data):
                    # Check if user cancelled
                    if progress.isCancelled():
                        print("Load cancelled by user")
                        break
                    
                    # Update progress (0-100 scale)
                    progress_percent = int((idx / float(total_images)) * 100)
                    progress.setProgress(progress_percent)
                    progress.setMessage(f"Loading image {idx + 1} of {total_images}...")
                    
                    # Try relative path first, then absolute
                    image_path = None
                    rel_path = img_data.get("path")
                    abs_path = img_data.get("absolute_path")
                    
                    if rel_path:
                        test_path = os.path.join(load_dir, rel_path)
                        if os.path.exists(test_path):
                            image_path = test_path
                    
                    if not image_path and abs_path and os.path.exists(abs_path):
                        image_path = abs_path
                    
                    if image_path:
                        try:
                            # Get layer info
                            layer = img_data.get("layer", "rgba")
                            
                            # Create image item
                            image_item = ImageDisplay(image_path, layer, self.preview_format)
                            self.scene.addItem(image_item)
                            self.image_items.append(image_item)
                            
                            # Restore properties
                            pos = img_data.get("position", [0, 0])
                            image_item.setPos(pos[0], pos[1])
                            
                            scale = img_data.get("scale", 1.0)
                            image_item.resize_image(scale)
                            
                            z_value = img_data.get("z_value", 0)
                            image_item.setZValue(z_value)
                            
                            loaded_count += 1
                            
                        except Exception as e:
                            print(f"Failed to load {image_path}: {e}")
                            missing_images.append(f"{rel_path or abs_path} (Error: {str(e)})")
                    else:
                        missing_images.append(rel_path or abs_path)
                
                # Set progress to complete
                progress.setProgress(100)
                
            finally:
                # Always clean up progress task
                del progress
            
            # Re-enable updates
            self.setUpdatesEnabled(True)
            
            # Update scene rect
            if self.image_items:
                items_rect = self.scene.itemsBoundingRect()
                padded_rect = items_rect.adjusted(-50, -50, 50, 50)
                self.scene.setSceneRect(padded_rect)
            
            self.current_save_path = file_path
            
            # Show warnings for missing images
            if missing_images:
                message = f"Warning: {len(missing_images)} images could not be found:\n"
                message += "\n".join(missing_images[:5])
                if len(missing_images) > 5:
                    message += f"\n... and {len(missing_images) - 5} more"
                nuke.message(message)
            
            # Fit to view
            self.fit_all_to_view()
            
            print(f"Reference board loaded from: {file_path}")
            print(f"Loaded: {loaded_count}, Missing: {len(missing_images)}")
            
        except Exception as e:
            nuke.message(f"Failed to load reference board:\n{str(e)}")
            print(f"Error loading board: {e}")
            # Re-enable updates in case of error
            self.setUpdatesEnabled(True)
 
    def consolidate_assets(self) -> None:
        """Saves the current reference board while explicitly forcing asset consolidation.

        This method is typically connected to a dedicated 'Consolidate Assets' menu 
        item, giving the user a quick way to ensure project portability. It achieves 
        this by internally calling `self.save_board()` with the boolean flag set to True.

        Calling this method ensures that:
        1. All clipboard images are converted into saved files.
        2. All regular images are copied into the board's asset subdirectory.
        3. All paths in the resulting JSON file point to the local, consolidated copies.
        """
        self.save_board(consolidate=True)



"""
To Do List:
BUGS TO FIX:
- [X] Mose cursor changes to pionting hand but not back to arrow on leaving the view
- [X] panings sensitivity is odd, needs fixing
- [X] losses the abilaty to pan after zooming

PRIORITY 1 FEATURES:
- [X] Implement resize handles for images
        Not fully functional yet
- [X] Improve performance with many images
- [X] Add option to save/load board state
    [X] Add function to copy imported images to a folder along side save file
            Fix so it first checks if board is saved, if not prompt to save
    [X] Remove missing images from save file when loading it cant find them
- [X] Fix exr images not displaying correctly
- [X] Add option to import images from clipboard
- [X] Right-click context menu effects based on click target
- [X] Fine-tune what conext menu shows based on click target
- [X] undersök omkoden väljer rätt lager i en exr fil, rad 691
- [X] Selected format on an exr is not forwarded after the panel is closed
- [X] test load multiple exr with different layers
- [X] Add try/except around clipboard paste - In case clipboard has weird data
- [X] if a file is missing, is it deleted from the json on skiped on loading?
- [X] Improve zooming behavior to 'infinite' grid
        I think
- [ ] shortcuts for save and load ar not working
- [ ] What did _update_scene_rect_after_item_move do? is it needed?
- [ ] Remove preview_format save what user selected for each image instead


PRIORITY 2 FEATURES:
- [ ] Saving what board was last opened and restoring it on panel open
- [ ] Refine context menu options and layout
        Change so it is dependent what is clicked not what is selected
- [ ] add options to change defalult behavior  
        default resize scale for new images
        default number of columns (how manny colums to layout when adding multiple images)
        See below for more ideas
- [ ] droping a .json file onto the board should load that file if it is a coffeeboard file
- [ ] optimize board loading time

NICE TO HAVE FEATURES:        
- [ ] Add keyboard shortcuts for common actions
- [ ] Add option to rotate images
- [ ] Add option to export board as a single image
- [ ] Add option to change image opacity
- [ ] integration with Nuke nodes
        e.g., link images to Read nodes
- [ ] Test extensively in Nuke environment
        add a lot of images and see how it performs
        add high res images and see how it performs
        test on different OS
        test with different Nuke versions
- [ ] include all supported file formats nuke can write.



How to Make Settings Change Dynamically in NukeWhen you move configuration variables like min_scale, 
max_scale, columns, and preview_format out of the __init__, they become class attributes. 
While they are now clean Python constants, they are still only read once when the CoffeeBoard instance is created.

To allow users to change them without a restart, you need a configuration interface that tells the running instance 
to update its state.

Option 1: Using Nuke's Knob/Panel System (Recommended)
    Since you are a VFX Artist and comfortable with Nuke, the most idiomatic way is to create a separate 
    settings panel or a small window that links directly to your class instance.
    Create a Settings Widget: 
        Build a QDialog or Nuke custom panel with input fields (like QSpinBox for columns or QLineEdit for preview_format).
    Access the Instance: 
        When the user changes a value and clicks "Apply" (or on every change):
            Find the running instance of your ReferenceBoard.
            Directly set the attribute on the instance.
    Setting     Example Code to Update (inside a Settings Dialog)
    columns     board_instance.columns = new_value
    max_scale   board_instance.max_scale = float(new_value)

    Effect: This change takes effect immediately because you are updating the variable on the active, running object instance.
    No restart is needed.

Option 2: Using User Preferences/Files
    If you want the settings to be persistent (remembered between Nuke sessions), you would:
    Read on Init: 
        In CoffeeBoard.__init__, read the initial values for min_scale, max_scale, etc., from a
        configuration file (like a JSON file in the user's Nuke directory or a setting saved via nuke.preference()).
    Write on Change:
        When the user updates the settings (via the interface mentioned in Option 1), 
        write the new values back to the configuration file.
    
    Effect: This allows settings to persist across sessions, but still requires a restart to take effect since the instance reads them only on initialization.
"""