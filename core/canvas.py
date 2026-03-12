from __future__ import annotations

import math
import os
import json
from functools import partial

from typing import List, Optional, Tuple

from CoffeeBoard.core.image_item import ImageDisplay
from CoffeeBoard.core.text_item import TextItem
from CoffeeBoard.core.shape_item import ShapeItem
from CoffeeBoard.ui.dialogs import EXRImportDialog
from CoffeeBoard.ui.image_settings_panel import ImageSettingsPanel
from CoffeeBoard.ui.text_settings_panel import TextSettingsPanel
from CoffeeBoard.ui.platform_bridge import get_bridge
from CoffeeBoard.core.image_loader import get_exr_layers

try:
    from PySide2.QtCore import Qt, QRectF, QPointF, QPoint, QEvent
    from PySide2.QtGui import (
        QPixmap, QKeySequence, QBrush, QColor,
        QDragEnterEvent, QDragMoveEvent, QDropEvent, QWheelEvent,
        QMouseEvent, QKeyEvent
    )
    from PySide2.QtWidgets import (
        QGraphicsView, QGraphicsScene, QDialog, QApplication, QShortcut, QAction, QMenu, QMessageBox, QWidget,
    )
except ImportError:
    from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, QEvent
    from PySide6.QtGui import (
        QPixmap, QKeySequence, QShortcut, QAction, QBrush, QColor,
        QDragEnterEvent, QDragMoveEvent, QDropEvent, QWheelEvent,
        QMouseEvent, QKeyEvent,
    )
    from PySide6.QtWidgets import (
        QGraphicsView, QGraphicsScene, QDialog, QApplication, QMenu, QMessageBox, QWidget,
    )


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

        Args:
            parent (QObject | None, optional): The parent object in the Qt hierarchy.
                                               Defaults to None.
        """
        super().__init__(parent)
        self.bridge = get_bridge()
        self.setWindowTitle("Coffee Board")
        self.setMinimumSize(600, 400)
        self.setAcceptDrops(True)


        SCENE_SIZE = 1000000
        huge_rect = QRectF(-SCENE_SIZE, -SCENE_SIZE, 2*SCENE_SIZE, 2*SCENE_SIZE)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.scene.setSceneRect(huge_rect)
        self.setBackgroundBrush(QBrush(QColor(35, 35, 35)))

        # Set up rendering and interaction
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
        self.text_items = []
        self.shape_items = []
        self._last_context_pos = QPointF()
        self.current_save_path = None
        self.scale_factor = 1.0

        # Draw mode state
        self._draw_mode = None
        self._draw_start_scene = None
        self._draw_preview = None

        # Keyboard shortcuts — use WidgetWithChildrenShortcut so these only fire
        # when CoffeeBoard (or a child) has focus, not globally across Nuke.

        self.paste_shortcut = QShortcut(QKeySequence("Ctrl+V"), self)
        self.paste_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.paste_shortcut.activated.connect(self.paste_from_clipboard)

        self.fit_shortcut = QShortcut(QKeySequence("F"), self)
        self.fit_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.fit_shortcut.activated.connect(self.fit_all_to_view)

        from CoffeeBoard.core.undo_commands import CoffeeBoardUndoStack
        self.undo_stack = CoffeeBoardUndoStack()
        self.undo_stack.setUndoLimit(50)

        # Ctrl+Z / Ctrl+Shift+Z are Nuke application-level shortcuts (Undo/Redo).
        # Registering them as QShortcuts causes Nuke to intercept them before the
        # shortcut resolver sees them. Handled in keyPressEvent instead (same fix as Ctrl+S/O).

        # Ctrl+S and Ctrl+O are Nuke application-level shortcuts (Save/Open Script).
        # Registering them as QShortcuts causes Qt ambiguity detection, suppressing
        # both Nuke's action and ours. Handled in keyPressEvent instead.

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

        self.move_forward_action = QAction("Move Forward", self)
        self.move_forward_action.triggered.connect(self.move_forward_one)

        self.move_back_action = QAction("Move Back", self)
        self.move_back_action.triggered.connect(self.move_backward_one)

        self.send_back_action = QAction("Send to Back", self)
        self.send_back_action.triggered.connect(self.send_to_back)

        self.rename_action = QAction("Rename...", self)
        self.rename_action.triggered.connect(self._rename_selected_image)

        self.delete_action = QAction("Delete")
        self.delete_action.triggered.connect(self.delete_selected_images)

        self.save_action = QAction("Save Reference Board...", self)
        self.save_action.triggered.connect(self.save_board)

        self.load_action = QAction("Load Reference Board...", self)
        self.load_action.triggered.connect(self.load_board)

        self.consolidate_action = QAction("Consolidate Assets...", self)
        self.consolidate_action.triggered.connect(self.consolidate_assets)

        self.clear_action = QAction("Clear All Images", self)
        self.clear_action.triggered.connect(self.clear_all_images)

        self.fit_action = QAction("Fit All to View", self)
        self.fit_action.triggered.connect(self.fit_all_to_view)

        self.paste_action = QAction("Paste Image", self)
        self.paste_action.triggered.connect(self.paste_from_clipboard)

        self.add_text_action = QAction("Add Text", self)
        self.add_text_action.triggered.connect(self._add_text_at_last_pos)

        # Per-image settings panel — floating, opened on double-click
        self._settings_panel = ImageSettingsPanel(self)
        self._settings_panel.raise_()

        # Per-text-item settings panel — opened via right-click → "Text Properties"
        self._text_settings_panel = TextSettingsPanel(self)
        self._text_settings_panel.raise_()

        # Per-shape settings panel — opened via right-click → "Shape Properties" or double-click
        from CoffeeBoard.ui.shape_settings_panel import ShapeSettingsPanel
        self._shape_settings_panel = ShapeSettingsPanel(self)
        self._shape_settings_panel.raise_()

        # Z-order item list panel
        from CoffeeBoard.ui.item_list_panel import ItemListPanel
        self._item_list_panel = ItemListPanel(self)
        self._item_list_panel.raise_()

        self.undo_stack.changed_callback = self._item_list_panel.refresh
        self.scene.selectionChanged.connect(self._item_list_panel._sync_selection_from_scene)

        self._item_list_action = QAction("Item List", self)
        self._item_list_action.setCheckable(True)
        self._item_list_action.triggered.connect(self._toggle_item_list_panel)

    def set_background_for_theme(self, theme: str) -> None:
        color = QColor(35, 35, 35) if theme != "light" else QColor(220, 220, 220)
        self.setBackgroundBrush(QBrush(color))

    # --- Draw mode ---

    def activate_draw_mode(self, shape_type: str) -> None:
        self._draw_mode = shape_type
        self.setDragMode(QGraphicsView.NoDrag)
        self.setCursor(Qt.CrossCursor)

    def _cancel_draw(self) -> None:
        if self._draw_preview is not None:
            self.scene.removeItem(self._draw_preview)
            self._draw_preview = None
        self._draw_mode = None
        self._draw_start_scene = None
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setCursor(Qt.ArrowCursor)

    def _start_draw_preview(self, scene_pos: QPointF) -> None:
        self._draw_start_scene = scene_pos
        if self._draw_mode in ('line', 'arrow'):
            preview = ShapeItem(shape_type=self._draw_mode, dx=0.0, dy=0.0)
        else:
            preview = ShapeItem(shape_type=self._draw_mode, nat_w=1.0, nat_h=1.0)
        preview.set_preview_mode()
        preview.setPos(scene_pos)
        self.scene.addItem(preview)
        self._draw_preview = preview

    def _commit_draw(self, end_scene: QPointF) -> None:
        sx, sy = self._draw_start_scene.x(), self._draw_start_scene.y()
        ex, ey = end_scene.x(), end_scene.y()

        if self._draw_preview is not None:
            self.scene.removeItem(self._draw_preview)
            self._draw_preview = None

        shape_type = self._draw_mode
        self._draw_mode = None
        self._draw_start_scene = None
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setCursor(Qt.ArrowCursor)

        if shape_type in ('line', 'arrow'):
            length = math.hypot(ex - sx, ey - sy)
            if length < 4:
                return
            item = ShapeItem(shape_type=shape_type, dx=ex - sx, dy=ey - sy)
            item.setPos(QPointF(sx, sy))
        else:
            w = max(4.0, abs(ex - sx))
            h = max(4.0, abs(ey - sy))
            if w < 4 and h < 4:
                return
            item = ShapeItem(shape_type=shape_type, nat_w=w, nat_h=h)
            item.setPos(QPointF(min(sx, ex), min(sy, ey)))

        from CoffeeBoard.core.undo_commands import AddItemCommand
        cmd = AddItemCommand(self, item, self.shape_items)
        self.undo_stack.push(cmd)

        self.scene.clearSelection()
        item.setSelected(True)

    # ---------------

    def closeEvent(self, event) -> None:
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._settings_panel.isVisible() and self._settings_panel._image is not None:
            img = self._settings_panel._image
            s = img.current_scale
            tr_scene = img.mapToScene(QPointF(img.original_pixmap.width() * s, 0))
            self._settings_panel._clamp_and_place(self.mapFromScene(tr_scene))
        if self._text_settings_panel.isVisible() and self._text_settings_panel._item is not None:
            ti = self._text_settings_panel._item
            s = ti.current_scale
            tr_scene = ti.mapToScene(QPointF(ti.base_width() * s, 0))
            self._text_settings_panel._clamp_and_place(self.mapFromScene(tr_scene))
        if self._shape_settings_panel.isVisible() and self._shape_settings_panel._item is not None:
            si = self._shape_settings_panel._item
            s = si.current_scale
            tr_scene = si.mapToScene(QPointF(si.base_width() * s, 0))
            self._shape_settings_panel._clamp_and_place(self.mapFromScene(tr_scene))

    def open_settings_panel(self, image: 'ImageDisplay') -> None:
        s = image.current_scale
        orig_w = image.original_pixmap.width()
        tr_scene = image.mapToScene(QPointF(orig_w * s, 0))
        tr_view  = self.mapFromScene(tr_scene)
        self._settings_panel.show_for_image(image, tr_view)

    def open_text_settings_panel(self, item: 'TextItem') -> None:
        s = item.current_scale
        tr_scene = item.mapToScene(QPointF(item.base_width() * s, 0))
        tr_view = self.mapFromScene(tr_scene)
        self._text_settings_panel.show_for_item(item, tr_view)

    def open_shape_settings_panel(self, item: 'ShapeItem') -> None:
        s = item.current_scale
        tr_scene = item.mapToScene(QPointF(item.base_width() * s, 0))
        tr_view = self.mapFromScene(tr_scene)
        self._shape_settings_panel.show_for_item(item, tr_view)

    def _toggle_item_list_panel(self) -> None:
        if self._item_list_panel.isVisible():
            self._item_list_panel.hide_panel()
            self._item_list_action.setChecked(False)
        else:
            self._item_list_panel.refresh()
            self._item_list_panel.show_panel()
            self._item_list_action.setChecked(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Handles the drag-enter event when external data is dragged into the view.

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

        Args:
            event (QDropEvent): The event object containing the dropped data, including file URLs.
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

            all_paths = [url.toLocalFile() for url in event.mimeData().urls()]

            # If any .json file is dropped, treat it as a board load and ignore image files.
            json_files = [p for p in all_paths if os.path.splitext(p)[1].lower() == ".json"]
            if json_files:
                json_path = json_files[0]
                try:
                    with open(json_path, 'r') as f:
                        data = json.load(f)
                    if "items" not in data and "images" not in data:
                        self.bridge.show_message(
                            f"Not a valid CoffeeBoard file:\n{json_path}"
                        )
                        return
                except Exception as e:
                    self.bridge.show_message(
                        f"Could not read JSON file:\n{json_path}\n\nError: {e}"
                    )
                    return
                self.load_board(json_path)
                return

            files_to_load = []
            for path in all_paths:
                ext = os.path.splitext(path)[1].lower()
                if ext in [".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".exr"]:
                    files_to_load.append(path)
                else:
                    self.bridge.show_message(f"Unsupported file type dropped:\n{path}\n\nOnly supports JPG, PNG, EXR, TIFF, BMP.")

            if not files_to_load:
                event.ignore()
                return

            total_files = len(files_to_load)

            # Check if we have multiple EXRs
            exr_files = [f for f in files_to_load if f.lower().endswith('.exr')]
            has_multiple_exrs = len(exr_files) > 1

            # --- Phase 1: collect import settings ---
            # All EXR layer dialogs are shown here, before the progress window
            # appears, so they are never obscured by it.
            apply_to_all = False
            batch_layer = None
            batch_format = None
            file_load_queue = []  # [(path, layer, fmt), ...]

            for path in files_to_load:
                ext = os.path.splitext(path)[1].lower()
                if ext == '.exr':
                    if apply_to_all and batch_layer and batch_format:
                        file_load_queue.append((path, batch_layer, batch_format))
                    else:
                        layer, fmt, apply_all = self._prompt_for_layer(path, is_batch=has_multiple_exrs)
                        if layer is None:
                            continue  # user cancelled this file
                        if apply_all:
                            apply_to_all = True
                            batch_layer = layer
                            batch_format = fmt
                        file_load_queue.append((path, layer, fmt))
                else:
                    file_load_queue.append((path, 'rgba', self.preview_format))

            if not file_load_queue:
                return

            # --- Phase 2: load with progress ---
            total_queued = len(file_load_queue)
            progress = self.bridge.create_progress(f"Importing {total_queued} images")
            progress.setMessage("Starting import...")

            try:
                if total_queued > 10:
                    self.setUpdatesEnabled(False)

                loaded_count = 0

                for idx, (path, layer, fmt) in enumerate(file_load_queue):
                    if progress.isCancelled():
                        print(f"Import cancelled by user. Loaded {loaded_count} of {total_queued} images.")
                        break

                    progress.setProgress(int((idx / float(total_queued)) * 100))
                    progress.setMessage(f"Loading {idx + 1} of {total_queued}: {os.path.basename(path)}")

                    try:
                        self.add_image(path, layer=layer, preview_format=fmt)
                        loaded_count += 1
                    except Exception as e:
                        print(f"Failed to load {path}: {e}")
                        self.bridge.show_message(f"Failed to load image:\n{path}\n\nError: {str(e)}")

                progress.setProgress(100)
                print(f"Successfully loaded {loaded_count} of {total_queued} images")

            finally:
                del progress
                if total_queued > 10:
                    self.setUpdatesEnabled(True)

            # Layout all images at once
            self._layout_images()
        else:
            event.ignore()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handles zooming in and out of the view using the mouse wheel.

        Args:
            event (QWheelEvent): The event object containing the wheel movement data.
        """
        # Zoom with smooth scaling
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor

        # PySide6 removed QWheelEvent.pos() — use position() which exists in both Qt5.14+ and Qt6
        epos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        old_pos = self.mapToScene(epos)

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

        new_pos = self.mapToScene(epos)

        # Calculate the difference and translate to keep mouse position fixed
        delta = new_pos - old_pos
        self.translate(delta.x(), delta.y())

        # Resize handles on selected items so they stay ~12px on screen
        for item in self.scene.selectedItems():
            if hasattr(item, 'update_handles'):
                item.update_handles()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handles mouse button presses for panning, context menu, and selection.

        Args:
            event (QMouseEvent): The event object containing mouse button and position data.
        """
        self.viewport().setFocus(Qt.MouseFocusReason)
        if self._draw_mode is not None:
            if event.button() == Qt.LeftButton:
                self._start_draw_preview(self.mapToScene(event.pos()))
                return
            elif event.button() == Qt.RightButton:
                self._cancel_draw()
                return
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
            item_at = self.itemAt(event.pos())
            modifiers = event.modifiers()
            if not item_at:
                self.scene.clearSelection()
                self._settings_panel.hide_panel()
                self._text_settings_panel.hide_panel()
                super().mousePressEvent(event)
            elif modifiers & Qt.ShiftModifier and not (modifiers & Qt.ControlModifier):
                # Treat Shift+click as Ctrl+click: toggle individual item selection
                item_at.setSelected(not item_at.isSelected())
            else:
                # Let the default behavior handle item selection/movement
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handles mouse movement for the custom panning feature.

        Args:
            event (QMouseEvent): The event object containing the current mouse position.
        """
        if self._draw_mode is not None and self._draw_preview is not None:
            cur = self.mapToScene(event.pos())
            sx, sy = self._draw_start_scene.x(), self._draw_start_scene.y()
            ex, ey = cur.x(), cur.y()
            if self._draw_mode in ('line', 'arrow'):
                self._draw_preview.update_line_vector(ex - sx, ey - sy)
            else:
                self._draw_preview.setPos(QPointF(min(sx, ex), min(sy, ey)))
                self._draw_preview.update_natural_size(max(1.0, abs(ex - sx)), max(1.0, abs(ey - sy)))
            event.accept()
            return
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

        Args:
            event (QMouseEvent): The event object containing the released mouse button data.
        """
        if self._draw_mode is not None and event.button() == Qt.LeftButton and self._draw_start_scene is not None:
            self._commit_draw(self.mapToScene(event.pos()))
            event.accept()
            return
        if event.button() == Qt.MiddleButton and self.panning:
            self.panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Handles the event when the mouse cursor leaves the view's widget area.

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

        Args:
            event (QEvent): The event object signaling that the mouse cursor has entered the widget.
        """
        if self.panning and not (QApplication.instance().mouseButtons() & Qt.MiddleButton):
            self.panning = False
            self.setCursor(Qt.ArrowCursor)
        super().enterEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handles key press events, primarily for deleting selected items.

        Args:
            event (QKeyEvent): The event object containing the specific key that was pressed.
        """
        # Delete selected items with Delete or Backspace
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            # If a TextItem is currently being edited, let the key pass to the text editor
            if any(isinstance(i, TextItem) and getattr(i, '_in_edit_mode', False)
                   for i in self.scene.selectedItems()):
                super().keyPressEvent(event)
                return
            from CoffeeBoard.core.undo_commands import DeleteItemCommand
            for item in self.scene.selectedItems():
                if isinstance(item, ImageDisplay):
                    if item is self._settings_panel._image:
                        self._settings_panel.hide_panel()
                    cmd = DeleteItemCommand(self, item, self.image_items)
                    self.undo_stack.push(cmd)
                elif isinstance(item, TextItem):
                    if item is self._text_settings_panel._item:
                        self._text_settings_panel.hide_panel()
                    cmd = DeleteItemCommand(self, item, self.text_items)
                    self.undo_stack.push(cmd)
                elif isinstance(item, ShapeItem):
                    if item is self._shape_settings_panel._item:
                        self._shape_settings_panel.hide_panel()
                    cmd = DeleteItemCommand(self, item, self.shape_items)
                    self.undo_stack.push(cmd)
        elif event.key() == Qt.Key_Escape:
            if self._draw_mode is not None:
                self._cancel_draw()
                event.accept()
                return
            self._settings_panel.hide_panel()
            self._text_settings_panel.hide_panel()
            self._shape_settings_panel.hide_panel()
            event.accept()
        elif event.key() == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
            self.save_board()
            event.accept()
        elif event.key() == Qt.Key_O and event.modifiers() & Qt.ControlModifier:
            self.load_board()
            event.accept()
        elif event.key() == Qt.Key_Z and event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier):
            self.undo_stack.redo()
            event.accept()
        elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
            self.undo_stack.undo()
            event.accept()
        else:
            super().keyPressEvent(event)



    def show_context_menu(self, pos: QPoint) -> None:
        """Shows the context menu at the specified view coordinate.

        Args:
            pos (QPoint): The local coordinate point within the QGraphicsView
                          where the mouse event occurred.
        """
        self._last_context_pos = self.mapToScene(pos)
        menu = QMenu(self)

        # Get item at click position (walk up to find a TextItem, ImageDisplay, or ShapeItem parent)
        raw_item = self.itemAt(pos)
        clicked_text = None
        clicked_image = None
        clicked_shape = None
        if raw_item is not None:
            candidate = raw_item
            while candidate is not None:
                if isinstance(candidate, TextItem):
                    clicked_text = candidate
                    break
                if isinstance(candidate, ImageDisplay):
                    clicked_image = candidate
                    break
                if isinstance(candidate, ShapeItem):
                    clicked_shape = candidate
                    break
                candidate = candidate.parentItem()

        if clicked_image:
            selected_images = [i for i in self.scene.selectedItems() if isinstance(i, ImageDisplay)]
            if clicked_image not in selected_images:
                for si in selected_images:
                    si.setSelected(False)
                clicked_image.setSelected(True)

        selected_images = [i for i in self.scene.selectedItems() if isinstance(i, ImageDisplay)]
        show_image_menu = bool(selected_images) or clicked_image is not None

        # --- TextItem context menu ---
        if clicked_text is not None and not show_image_menu:
            if not clicked_text.isSelected():
                self.scene.clearSelection()
                clicked_text.setSelected(True)
            text_props_action = QAction("Text Properties", self)
            text_props_action.triggered.connect(lambda: self.open_text_settings_panel(clicked_text))
            menu.addAction(text_props_action)
            menu.addSeparator()
            menu.addAction(self.bring_front_action)
            menu.addAction(self.move_forward_action)
            menu.addAction(self.move_back_action)
            menu.addAction(self.send_back_action)
            menu.addSeparator()
            menu.addAction(self.delete_action)
            menu.addSeparator()
            menu.addAction(self.fit_action)
            menu.addAction(self._item_list_action)
            menu.addSeparator()
            menu.addAction(self.add_text_action)
            menu.addSeparator()
            menu.addAction(self.save_action)
            menu.addAction(self.load_action)

        # --- ShapeItem context menu ---
        elif clicked_shape is not None and not show_image_menu:
            if not clicked_shape.isSelected():
                self.scene.clearSelection()
                clicked_shape.setSelected(True)
            shape_props_action = QAction("Shape Properties", self)
            shape_props_action.triggered.connect(lambda: self.open_shape_settings_panel(clicked_shape))
            menu.addAction(shape_props_action)
            menu.addSeparator()
            menu.addAction(self.bring_front_action)
            menu.addAction(self.move_forward_action)
            menu.addAction(self.move_back_action)
            menu.addAction(self.send_back_action)
            menu.addSeparator()
            menu.addAction(self.delete_action)
            menu.addSeparator()
            menu.addAction(self.fit_action)
            menu.addAction(self._item_list_action)
            menu.addSeparator()
            draw_menu = menu.addMenu("Draw Shape")
            for shape_type, label in [('rect', 'Rectangle'), ('ellipse', 'Ellipse'), ('line', 'Line'), ('arrow', 'Arrow')]:
                act = QAction(label, self)
                act.triggered.connect(partial(self.activate_draw_mode, shape_type))
                draw_menu.addAction(act)
            menu.addSeparator()
            menu.addAction(self.save_action)
            menu.addAction(self.load_action)

        # --- Image context menu ---
        elif show_image_menu:
            if len(selected_images) > 1:
                menu.addSection(f"{len(selected_images)} images selected")
            resize_menu = menu.addMenu("Resize")
            for act in self.resize_actions:
                resize_menu.addAction(act)
            menu.addSeparator()

            menu.addAction(self.bring_front_action)
            menu.addAction(self.move_forward_action)
            menu.addAction(self.move_back_action)
            menu.addAction(self.send_back_action)
            if len(selected_images) == 1:
                menu.addAction(self.rename_action)

            menu.addSeparator()

            menu.addAction(self.delete_action)
            menu.addAction(self.clear_action)

            menu.addSeparator()

            menu.addAction(self.fit_action)
            menu.addAction(self._item_list_action)

            menu.addSeparator()

            menu.addAction(self.paste_action)
            menu.addAction(self.add_text_action)

            menu.addSeparator()

            menu.addAction(self.save_action)
            menu.addAction(self.load_action)
            menu.addAction(self.consolidate_action)

        # --- Background context menu ---
        else:
            menu.addAction(self.clear_action)

            menu.addSeparator()

            menu.addAction(self.fit_action)
            menu.addAction(self._item_list_action)

            menu.addSeparator()

            menu.addAction(self.paste_action)
            menu.addAction(self.add_text_action)
            draw_menu = menu.addMenu("Draw Shape")
            for shape_type, label in [('rect', 'Rectangle'), ('ellipse', 'Ellipse'), ('line', 'Line'), ('arrow', 'Arrow')]:
                act = QAction(label, self)
                act.triggered.connect(partial(self.activate_draw_mode, shape_type))
                draw_menu.addAction(act)

            menu.addSeparator()

            menu.addAction(self.save_action)
            menu.addAction(self.load_action)
            menu.addAction(self.consolidate_action)

        # Show the menu at cursor position
        # getattr default is evaluated eagerly — use None sentinel to avoid AttributeError on PySide2
        (getattr(menu, 'exec_', None) or getattr(menu, 'exec'))(self.mapToGlobal(pos))



    def _layout_images(self) -> None:
        """Arranges all currently tracked image items in a grid layout."""
        x, y = 0.0, 0.0
        max_row_height = 0.0
        spacing = 10.0

        if not self.image_items:
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


    def _prompt_for_layer(self, path: str, is_batch: bool = False) -> Tuple[str | None, str | None, bool]:
        """Prompts the user to select the layer and preview format for an EXR file.

        Uses get_exr_layers() from image_loader for layer discovery.

        Args:
            path (str): The full file path to the EXR image.
            is_batch (bool, optional): True if multiple EXR files are being dropped
                                       simultaneously. Defaults to False.

        Returns:
            Tuple[str | None, str | None, bool]: (layer, format, apply_to_all).
        """
        layer_list = get_exr_layers(path)

        if not layer_list:
            return ('rgba', self.preview_format, False)

        # Show dialog (hide format dropdown if OIIO is available)
        dialog = EXRImportDialog(
            path, layer_list, is_batch,
            hide_format=self.bridge.has_oiio or self.bridge.has_native_exr,
            parent=self
        )

        if (getattr(dialog, 'exec_', None) or getattr(dialog, 'exec'))() == QDialog.Accepted:
            layer, fmt, apply_all = dialog.get_values()
            return (layer, fmt, apply_all)
        else:
            return (None, None, False)


    def add_image(self, path: str, layer: str = 'rgba', preview_format: str = 'jpg') -> None:
        """Adds a new ImageDisplay item to the board.

        Args:
            path (str): The full file path to the image.
            layer (str, optional): The specific layer to load for EXR files. Defaults to 'rgba'.
            preview_format (str, optional): The default file extension for consolidation. Defaults to 'jpg'.

        Raises:
            IOError: If the specified file path does not exist.
        """
        # Check if file exists
        if not os.path.exists(path):
            raise IOError(f"File does not exist: {path}")

        print(f"Loading {path} with layer: {layer}, format: {preview_format}")

        try:
            image_item = ImageDisplay(path, layer, preview_format)
            from CoffeeBoard.core.undo_commands import AddItemCommand
            cmd = AddItemCommand(self, image_item, self.image_items)
            self.undo_stack.push(cmd)
        except Exception as e:
            print(f"Failed to add image {path}: {e}")
            raise

    def paste_from_clipboard(self) -> None:
        """Handles the pasting of image data directly from the system clipboard."""

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

                # Position at view center
                view_center = self.mapToScene(self.viewport().rect().center())
                image_item.setPos(view_center)

                from CoffeeBoard.core.undo_commands import AddItemCommand
                cmd = AddItemCommand(self, image_item, self.image_items)
                self.undo_stack.push(cmd)
        else:
            self.bridge.show_message("No image data found in clipboard.")


    def _add_text_at_last_pos(self) -> None:
        from CoffeeBoard.core.undo_commands import AddItemCommand
        item = TextItem()
        w = item.base_width() * item.current_scale
        h = item.base_height() * item.current_scale
        item.setPos(self._last_context_pos - QPointF(w / 2, h / 2))
        cmd = AddItemCommand(self, item, self.text_items)
        self.undo_stack.push(cmd)
        self.scene.clearSelection()
        item.setSelected(True)
        item.enter_edit_mode()

    def resize_selected_images(self, scale: float) -> None:
        """Resizes all currently selected ImageDisplay items to the specified scale factor.

        Args:
            scale (float): The multiplicative factor for image size.
        """
        for item in self.scene.selectedItems():
            if isinstance(item, ImageDisplay):
                item.resize_image(scale)

    def bring_to_front(self) -> None:
        """Brings all currently selected items to the foreground."""
        selected_items = [i for i in self.scene.selectedItems()
                          if isinstance(i, (ImageDisplay, TextItem, ShapeItem))]
        if not selected_items:
            return

        all_items = self.image_items + self.text_items + self.shape_items
        if not all_items:
            return
        max_z = max(item.zValue() for item in all_items)

        for item in selected_items:
            item.setZValue(max_z + 1)

        self._item_list_panel.refresh()

    def send_to_back(self) -> None:
        """Sends all currently selected items to the background."""
        selected_items = [i for i in self.scene.selectedItems()
                          if isinstance(i, (ImageDisplay, TextItem, ShapeItem))]
        if not selected_items:
            return

        all_items = self.image_items + self.text_items + self.shape_items
        if not all_items:
            return
        min_z = min(item.zValue() for item in all_items)

        for item in selected_items:
            item.setZValue(min_z - 1)

        self._item_list_panel.refresh()

    def move_forward_one(self) -> None:
        from CoffeeBoard.core.undo_commands import ZOrderCommand
        selected_items = [i for i in self.scene.selectedItems()
                          if isinstance(i, (ImageDisplay, TextItem, ShapeItem))]
        if not selected_items:
            return
        all_items = self.image_items + self.text_items + self.shape_items
        if len(all_items) < 2:
            return

        before = [(i, i.zValue()) for i in all_items]
        sorted_items = sorted(all_items, key=lambda i: i.zValue())

        selected_set = set(selected_items)
        # Process from highest index downward so earlier swaps don't displace later items
        indices = sorted([sorted_items.index(item) for item in selected_items], reverse=True)
        changed = False
        for idx in indices:
            if idx == len(sorted_items) - 1:
                continue
            if sorted_items[idx + 1] in selected_set:
                continue  # neighbour is also selected — move as a group
            sorted_items[idx], sorted_items[idx + 1] = sorted_items[idx + 1], sorted_items[idx]
            changed = True

        if not changed:
            return
        for new_z, i in enumerate(sorted_items):
            i.setZValue(float(new_z))
        after = [(i, i.zValue()) for i in all_items]
        self.undo_stack.push(ZOrderCommand(before, after))
        self._item_list_panel.refresh()

    def move_backward_one(self) -> None:
        from CoffeeBoard.core.undo_commands import ZOrderCommand
        selected_items = [i for i in self.scene.selectedItems()
                          if isinstance(i, (ImageDisplay, TextItem, ShapeItem))]
        if not selected_items:
            return
        all_items = self.image_items + self.text_items + self.shape_items
        if len(all_items) < 2:
            return

        before = [(i, i.zValue()) for i in all_items]
        sorted_items = sorted(all_items, key=lambda i: i.zValue())

        selected_set = set(selected_items)
        # Process from lowest index upward so earlier swaps don't displace later items
        indices = sorted([sorted_items.index(item) for item in selected_items])
        changed = False
        for idx in indices:
            if idx == 0:
                continue
            if sorted_items[idx - 1] in selected_set:
                continue  # neighbour is also selected — move as a group
            sorted_items[idx], sorted_items[idx - 1] = sorted_items[idx - 1], sorted_items[idx]
            changed = True

        if not changed:
            return
        for new_z, i in enumerate(sorted_items):
            i.setZValue(float(new_z))
        after = [(i, i.zValue()) for i in all_items]
        self.undo_stack.push(ZOrderCommand(before, after))
        self._item_list_panel.refresh()

    def _rename_selected_image(self) -> None:
        selected = [i for i in self.image_items if i.isSelected()]
        if not selected:
            return
        item = selected[0]
        if not self._item_list_panel.isVisible():
            self._item_list_panel.show_panel()
        panel = self._item_list_panel
        for row_idx in range(panel._list.count()):
            row = panel._list.item(row_idx)
            if row.data(Qt.UserRole) is item:
                panel._editing = True
                panel._list.editItem(row)
                break

    def delete_selected_images(self) -> None:
        """Removes all currently selected items from the board."""
        from CoffeeBoard.core.undo_commands import DeleteItemCommand
        for item in list(self.scene.selectedItems()):
            if isinstance(item, ImageDisplay):
                if item is self._settings_panel._image:
                    self._settings_panel.hide_panel()
                cmd = DeleteItemCommand(self, item, self.image_items)
                self.undo_stack.push(cmd)
            elif isinstance(item, TextItem):
                if item is self._text_settings_panel._item:
                    self._text_settings_panel.hide_panel()
                cmd = DeleteItemCommand(self, item, self.text_items)
                self.undo_stack.push(cmd)
            elif isinstance(item, ShapeItem):
                if item is self._shape_settings_panel._item:
                    self._shape_settings_panel.hide_panel()
                cmd = DeleteItemCommand(self, item, self.shape_items)
                self.undo_stack.push(cmd)

    def clear_all_images(self) -> None:
        """Removes all items from the scene and resets the board state."""
        self._settings_panel.hide_panel()
        self._text_settings_panel.hide_panel()
        self._shape_settings_panel.hide_panel()
        for item in list(self.image_items):
            self.scene.removeItem(item)
        self.image_items.clear()
        for item in list(self.text_items):
            self.scene.removeItem(item)
        self.text_items.clear()
        for item in list(self.shape_items):
            self.scene.removeItem(item)
        self.shape_items.clear()
        self.scene.setSceneRect(QRectF(0, 0, 800, 600))
        self._item_list_panel.refresh()

    def fit_all_to_view(self) -> None:
        """Resets the view transform and scales it to fit all items within the viewport."""
        if not self.image_items and not self.text_items and not self.shape_items:
            return

        # Reset transform
        self.resetTransform()
        self.scale_factor = 1.0

        # Fit the scene rect in view
        self.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)

        # Restore huge scene rect so panning is not locked to content bounds
        SCENE_SIZE = 1000000
        self.scene.setSceneRect(QRectF(-SCENE_SIZE, -SCENE_SIZE, 2 * SCENE_SIZE, 2 * SCENE_SIZE))

        # Update scale factor and force repaint
        self.scale_factor = self.transform().m11()
        self.viewport().update()

    def save_board(self) -> None:
        """Delegate to board_file.save_board."""
        from CoffeeBoard.core.board_file import save_board
        save_board(self)

    def load_board(self, path=None) -> None:
        """Delegate to board_file.load_board."""
        from CoffeeBoard.core.board_file import load_board
        load_board(self, path)

    def consolidate_assets(self) -> None:
        """Saves the current reference board, prompting for file consolidation."""
        self.save_board()
