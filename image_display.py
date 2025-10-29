from __future__ import annotations

import os
import tempfile
import nuke
from typing import Union, Any, Optional

from PySide2.QtCore import Qt, QPointF, QRectF
from PySide2.QtGui import QPixmap, QBrush, QColor, QPen, QPainter, QMouseEvent
from PySide2.QtWidgets import QGraphicsPixmapItem, QGraphicsItem, QGraphicsEllipseItem

# Typanteckningar för nuke-objekt
NukeNode = Any
NukeKnob = Any 


class _ResizeHandle(QGraphicsEllipseItem):
    """A draggable handle (circular shape) for interactively resizing the ImageDisplay object.

    The scaling is calculated based on the handle's distance from the image's top-left 
    corner, which provides intuitive diagonal scaling. The handle is always visible 
    on top of the image and can be activated/deactivated upon selection of the parent item.

    Attributes:
        parent_image ('ImageDisplay'): Reference to the parent object (the image to be scaled).
        dragging (bool): Flag indicating if scaling is currently active.
        start_pos (QPointF): The scene position where the scaling drag started.
        start_scale (float): The image's scale factor at the start of the drag.
    """
    
    # --- ATTRIBUTE TYPE HINTS ---
    parent_image: 'ImageDisplay'
    dragging: bool
    start_pos: QPointF
    start_scale: float
    
    
    def __init__(self, parent_image: 'ImageDisplay') -> None:
        """Initializes the handle as a centered circle and sets its appearance and behavior.

        The handle is set as a child of 'parent_image' but is not movable itself; 
        instead, its position is updated by the parent object.

        Args:
            parent_image ('ImageDisplay'): The ImageDisplay instance that the handle is attached to.
        """
        
        # Circle: (-50, -50) to (50, 50) creates a centered circle with radius 50.
        super().__init__(-50, -50, 100, 100)  # Small circle, centered on 0,0
        self.parent_image = parent_image
        
        # Appearance and interaction
        self.setBrush(QBrush(QColor(100, 150, 255, 200)))
        self.setPen(QPen(QColor(255, 255, 255), 2))
        self.setCursor(Qt.SizeFDiagCursor)
        
        # Flags and Z-order
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(1000)  # Always on top
        self.setParentItem(parent_image)
        self.setAcceptHoverEvents(True)
        
        # Scaling state
        self.dragging = False
        self.start_pos = QPointF()
        self.start_scale = 1.0
        
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handles mouse click and initializes the scaling drag (dragging).

        Stores the current scene position and the image's scale factor as the starting point.

        Args:
            event (QMouseEvent): The mouse press event.
        """
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.start_pos = event.scenePos()
            self.start_scale = self.parent_image.current_scale
            event.accept()
    
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Calculates and applies the new scale factor during a drag.

        The scale factor is based on the ratio between the diagonal from the image's 
        top-left corner to the new mouse position and the original image diagonal 
        at the start of the drag.

        Args:
            event (QMouseEvent): The mouse move event.
        """
        if self.dragging:
            # Calculate distance moved from the start position
            current_pos = event.scenePos()
            
            # Get the image's original diagonal at start
            original_rect = QRectF(0, 0, 
                                         self.parent_image.original_pixmap.width() * self.start_scale,
                                         self.parent_image.original_pixmap.height() * self.start_scale)
            original_diagonal = (original_rect.width() ** 2 + original_rect.height() ** 2) ** 0.5
            
            # Calculate new diagonal based on mouse position relative to image top-left
            image_top_left = self.parent_image.mapToScene(self.parent_image.boundingRect().topLeft())
            new_diagonal = ((current_pos.x() - image_top_left.x()) ** 2 + 
                           (current_pos.y() - image_top_left.y()) ** 2) ** 0.5
            
            # Calculate scale - this ratio should now be 1:1
            if original_diagonal > 0:
                new_scale = (new_diagonal / original_diagonal) * self.start_scale
                new_scale = max(0.1, min(10.0, new_scale))
                
                # Apply the scale
                self.parent_image.resize_image(new_scale)
            event.accept()
    
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finishes the scaling drag and resets the 'dragging' flag.

        Args:
            event (QMouseEvent): The mouse release event.
        """
        if event.button() == Qt.LeftButton:
            self.dragging = False
            event.accept()


class ImageDisplay(QGraphicsPixmapItem):
    """A selectable and resizable QGraphicsPixmapItem used for displaying reference images.

    This class handles image loading, utilizing Nuke's Read and Write nodes for robust 
    support of multi-channel formats like EXR to extract a viewable preview. It also 
    manages the item's interaction flags, scale, and a resize handle for the GUI.

    Attributes:
        path (Union[str, os.PathLike]): The file path of the original asset, or "clipboard_image".
        layer (str): The specific layer/channel loaded from the source file (e.g., 'rgba').
        original_pixmap (QPixmap): The unscaled version of the loaded image data.
        current_scale (float): The current scale factor applied to the pixmap (1.0 = original size).
        resize_handle (Optional[_ResizeHandle]): The graphical handle used for user-driven resizing.
    """
    
    # --- ATTRIBUTE TYPE HINTS ---
    path: Union[str, os.PathLike]
    layer: str
    original_pixmap: QPixmap
    current_scale: float
    resize_handle: Optional[_ResizeHandle]
    # --------------------------
    
    def __init__(self, source: Union[str, os.PathLike, QPixmap], 
                 layer: str = 'rgba', 
                 preview_format: str = 'jpg') -> None:
        """Initializes the image display item.

        Args:
            source (Union[str, os.PathLike, QPixmap]): Either the file path to load 
                                                        or a pre-loaded QPixmap (e.g., from clipboard).
            layer (str, optional): The layer to extract if the source is a multi-channel file 
                                   (like EXR). Defaults to 'rgba'.
            preview_format (str, optional): The file format to use when generating a temporary 
                                            preview image via Nuke. Defaults to 'jpg'.
                                            
        Raises:
            TypeError: If the source is neither a path nor a QPixmap.
        """
        # If source is a path (i.e an image not nativly suported by QPixmap), load via Nuke
        if isinstance(source, (str, bytes, os.PathLike)):
            self.path = source
            self.layer = layer
            pixmap = self._load_image_data(source, layer, preview_format)
        # If source is already a QPixmap, use it directly
        elif isinstance(source, QPixmap):
            self.path = "clipboard_image"  # Placeholder path for clipboard images
            self.layer = 'rgba'  # Default layer for clipboard images
            pixmap = source
        else:
            raise TypeError(f"Expected str or QPixmap, got {type(source)}")
            
        super().__init__(pixmap)
        
        self.original_pixmap = pixmap
        self.current_scale = 1.0
        self.resize_handle = None
        
        # Configure item interaction flags
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

    def _load_image_data(self, path: str, 
                            layer: str = 'rgba', 
                            preview_format: str = 'jpg') -> QPixmap:
        """Internal method to load image data, using Qt for standard formats and Nuke for robust handling of multi-channel files (e.g., EXR).

        For multi-channel files like EXR, this method creates a temporary Nuke script (Read -> Shuffle -> Write) 
        to extract the specified layer and save it as a low-overhead preview file (e.g., JPG). 
        The preview file is then loaded into a QPixmap. The Nuke nodes and temp file are cleaned up.

        Args:
            path (str): The file path to the image asset.
            layer (str, optional): The layer to extract if the source is a multi-channel file 
                                   (like EXR). Defaults to 'rgba'.
            preview_format (str, optional): The desired format for the temporary preview 
                                            (e.g., 'jpg', 'png'). Defaults to 'jpg'.

        Returns:
            QPixmap: The loaded image, or a placeholder QPixmap if loading fails.
        """
        ext = os.path.splitext(path)[1].lower()
        
        # For non-EXR formats, use Qt directly (faster)
        if ext not in ['.exr']:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                return pixmap
            # Fall through to Nuke method if Qt fails or it's an EXR
        
        # Use Nuke to read the image
        read_node: Optional[NukeNode] = None
        shuffle_node: Optional[NukeNode] = None
        write_node: Optional[NukeNode] = None
        temp_path: Optional[str] = None
        
        try:
            # Create temporary Read node
            read_node = nuke.nodes.Read(file=path)
            read_node.knob('file').evaluate()
            
            # Get available channels
            channels = read_node.channels()
            
            # Set up shuffle node to extract the correct layer
            last_node: NukeNode = read_node
            
            if layer and layer != 'rgba':
                # Create shuffle to map the layer to rgba
                shuffle_node = nuke.nodes.Shuffle(inputs=[read_node])
                
                # Map the layer channels to rgba
                # Try different channel naming conventions
                for suffix in ['red', 'R', 'r']:
                    red_ch = f'{layer}.{suffix}'
                    if red_ch in channels:
                        shuffle_node['in'].setValue(layer)
                        break
                
                last_node = shuffle_node
            
            
            # Create a temp file for the preview

            
            # Get format extension and settings
            format_map = {
                'jpg': ('.jpg', 'jpeg', {'_jpeg_quality': 0.85}),
                'png': ('.png', 'png', {}),
                'tiff': ('.tif', 'tiff', {}),
                'bmp': ('.bmp', 'bmp', {})
            }
            
            suffix, file_type, write_settings = format_map.get(preview_format, format_map['jpg'])
            
            temp_fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=tempfile.gettempdir())
            os.close(temp_fd)
            
            # Make sure path uses forward slashes for Nuke
            temp_path = temp_path.replace('\\', '/')
            
            print(f"Writing temp preview to: {temp_path} (format: {file_type}, layer: {layer})")
            
            # Write to temp file
            write_node = nuke.nodes.Write(
                file=temp_path, 
                file_type=file_type,
                inputs=[last_node],
                **write_settings
            )
            
            # Get the first frame from the read node
            first_frame = int(read_node['first'].value())
            
            
            # Execute the write
            nuke.execute(write_node, first_frame, first_frame)
            
            # Small delay to ensure file is written
            import time
            time.sleep(0.1)
            
            # Load the temp image with Qt
            pixmap = QPixmap(temp_path)
            
            # Clean up temp file
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    print(f"Failed to delete temp file {temp_path}: {e}")
                    pass
            
            # Clean up nodes
            if write_node:
                nuke.delete(write_node)
            if shuffle_node:
                nuke.delete(shuffle_node)
            if read_node:
                nuke.delete(read_node)
            
            if not pixmap.isNull():
                print(f"Successfully loaded via Nuke: {path} ({pixmap.width()}x{pixmap.height()})")
                return pixmap
            
        except Exception as e:
            print(f"Nuke read failed for {path}: {e}")
            import traceback
            traceback.print_exc()
            
            # Clean up any nodes that might have been created
            try:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
            except Exception as e:
                print(f"Failed to delete temp file {temp_path}: {e}")
                pass
            try:
                if write_node:
                    nuke.delete(write_node)
            except Exception as e:
                print(f"Failed to delete write node: {e}")
                pass
            try:
                if shuffle_node:
                    nuke.delete(shuffle_node)
            except Exception as e:
                print(f"Failed to delete shuffle node: {e}")
                pass
            try:
                if read_node:
                    nuke.delete(read_node)
            except Exception as e:
                print(f"Failed to delete read node: {e}")
                pass
        
        # Final fallback: try Qt again
        print("Trying Qt fallback")
        pixmap = QPixmap(path)
        if pixmap.isNull():
            print("Qt fallback failed, creating placeholder")
            # Create a placeholder image
            pixmap = QPixmap(400, 300)
            pixmap.fill(QColor(60, 60, 60))
            painter = QPainter(pixmap)
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(pixmap.rect(), Qt.AlignCenter, 
                           f"Failed to load:\n{os.path.basename(path)}")
            painter.end()
        
        return pixmap

    def hoverEnterEvent(self, event: QMouseEvent) -> None:
        """Changes the cursor to a pointing hand when hovering over the item."""
        self.setCursor(Qt.PointingHandCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QMouseEvent) -> None:
        """Restores the cursor when the mouse leaves the item area."""
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        """Handles changes to the item's state, such as selection state.

        Toggles the visibility of the resize handle when the image item is selected or deselected.

        Args:
            change (QGraphicsItem.GraphicsItemChange): The type of change occurring.
            value (Any): The new value for the changed item state.

        Returns:
            Any: The modified value, which is then used by the base class.
        """
        if change == QGraphicsItem.ItemSelectedChange:
            if value:  # Being selected
                self.show_resize_handle()
            else:  # Being deselected
                self.hide_resize_handle()
            
        ### Ifrån annan AI ###    
        elif change == QGraphicsItem.ItemPositionChange and self.resize_handle and self.resize_handle.isVisible():
            self.update_handle_position()
            
        return super().itemChange(change, value)
    
    def show_resize_handle(self) -> None:
        """Creates and shows the resize handle at the bottom-right corner."""
        if not self.resize_handle:
            self.resize_handle = _ResizeHandle(self)
        self.update_handle_position()
        self.resize_handle.setVisible(True)
    
    def hide_resize_handle(self) -> None:
        """Hide the resize handle"""
        if self.resize_handle:
            self.resize_handle.setVisible(False)
    
    def update_handle_position(self) -> None:
        """Position the handle at the bottom-right corner"""
        if self.resize_handle:
            rect = self.boundingRect()
            self.resize_handle.setPos(rect.width(), rect.height())
    
    def resize_image(self, scale_factor: float) -> None:
        """Resizes the displayed image using a scale factor relative to the original pixmap.

        Args:
            scale_factor (float): The new scale factor to apply (e.g., 0.5 for half size).
        """
        self.current_scale = scale_factor
        scaled_pixmap = self.original_pixmap.scaled(
            self.original_pixmap.size() * scale_factor,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.setPixmap(scaled_pixmap)
        self.update_handle_position()  # Update handle position after resize
