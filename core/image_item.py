from __future__ import annotations

import os
import math
import enum
from typing import Union, Any, Optional


def _detect_file_colorspace(path: str) -> str:
    """Best-effort colorspace detection: ICC/EXIF first, then extension heuristic."""
    ext = os.path.splitext(path)[1].lower()
    try:
        from PIL import Image as _PILImage
        img = _PILImage.open(path)
        if ext in ('.jpg', '.jpeg'):
            exif = getattr(img, '_getexif', lambda: None)() or {}
            cs_tag = exif.get(40961)
            if cs_tag == 1:
                return 'srgb'
            if cs_tag == 2:
                return 'linear'
        icc = img.info.get('icc_profile', b'')
        if icc:
            profile_lower = icc[:128].lower()
            if b'rec. 709' in profile_lower or b'rec709' in profile_lower:
                return 'rec709'
            if b'srgb' in profile_lower or b'iec 61966' in profile_lower:
                return 'srgb'
    except Exception:
        pass
    if ext in ('.jpg', '.jpeg', '.png', '.bmp'):
        return 'srgb'
    return 'linear'

from CoffeeBoard.ui.platform_bridge import get_bridge

try:
    from PySide2.QtCore import Qt, QPointF, QRectF
    from PySide2.QtGui import QPixmap, QBrush, QColor, QPen, QPainter, QMouseEvent, QImage
    from PySide2.QtWidgets import QGraphicsPixmapItem, QGraphicsItem, QGraphicsEllipseItem, QGraphicsRectItem
except ImportError:
    from PySide6.QtCore import Qt, QPointF, QRectF
    from PySide6.QtGui import QPixmap, QBrush, QColor, QPen, QPainter, QMouseEvent, QImage
    from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsItem, QGraphicsEllipseItem, QGraphicsRectItem

# Kontrollera om QImage stödjer 16-bit RGBA (Qt 5.12+)
HAS_RGBA64 = hasattr(QImage, 'Format_RGBA64')

# Typanteckningar för nuke-objekt
NukeNode = Any
NukeKnob = Any

_ROFF = 22.0 / math.sqrt(2.0)


class HandlePos(enum.IntEnum):
    TL = 0; TM = 1; TR = 2
    LM = 3; RM = 4
    BL = 5; BM = 6; BR = 7


def _get_view_scale(item) -> float:
    """Return the current view zoom so handles can be sized in screen pixels."""
    if item.scene() and item.scene().views():
        m = item.scene().views()[0].transform().m11()
        return abs(m) if m else 1.0
    return 1.0


def _rotate_vec(v: QPointF, angle_deg: float) -> QPointF:
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    return QPointF(v.x() * c - v.y() * s, v.x() * s + v.y() * c)


class _SelectionBorder(QGraphicsRectItem):
    def __init__(self, parent_image: 'ImageDisplay') -> None:
        super().__init__(0, 0, 0, 0, parent_image)
        self.setBrush(QBrush(Qt.NoBrush))
        self.setPen(QPen(QColor(0, 200, 180, 220), 1.5))
        self.setZValue(999)
        self.setVisible(False)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)


class _Handle(QGraphicsRectItem):
    def __init__(self, parent_image: 'ImageDisplay', pos: HandlePos) -> None:
        super().__init__(-5, -5, 10, 10, parent_image)
        self.parent_image = parent_image
        self.handle_pos = pos
        self.setBrush(QBrush(QColor(0, 200, 180, 220)))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setZValue(1001)
        self.setVisible(False)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptHoverEvents(True)
        self._set_cursor()
        self.dragging = False

    def _set_cursor(self):
        hp = self.handle_pos
        if hp in (HandlePos.TL, HandlePos.BR):
            self.setCursor(Qt.SizeFDiagCursor)
        elif hp in (HandlePos.TR, HandlePos.BL):
            self.setCursor(Qt.SizeBDiagCursor)
        elif hp in (HandlePos.TM, HandlePos.BM):
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.setCursor(Qt.SizeHorCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            item = self.parent_image
            s = item.current_scale
            orig_w = item.base_width()
            orig_h = item.base_height()
            self._drag_start_scale = s
            self._drag_start_pos = item.pos()
            self._anchor_TL = item.mapToScene(QPointF(0, 0))
            self._anchor_TR = item.mapToScene(QPointF(orig_w * s, 0))
            self._anchor_BL = item.mapToScene(QPointF(0, orig_h * s))
            self._anchor_BR = item.mapToScene(QPointF(orig_w * s, orig_h * s))
            self._anchor_TM = item.mapToScene(QPointF(orig_w * s / 2, 0))
            self._anchor_BM = item.mapToScene(QPointF(orig_w * s / 2, orig_h * s))
            self._anchor_LM = item.mapToScene(QPointF(0, orig_h * s / 2))
            self._anchor_RM = item.mapToScene(QPointF(orig_w * s, orig_h * s / 2))
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self._apply_resize(event.scenePos())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            new_scale = self.parent_image.current_scale
            new_pos = self.parent_image.pos()
            if new_scale != self._drag_start_scale:
                views = self.parent_image.scene().views() if self.parent_image.scene() else []
                if views and hasattr(views[0], 'undo_stack'):
                    from CoffeeBoard.core.undo_commands import ResizeCommand
                    views[0].undo_stack.push(ResizeCommand(
                        self.parent_image,
                        self._drag_start_scale, new_scale,
                        self._drag_start_pos, new_pos
                    ))
            event.accept()

    def _apply_resize(self, mouse_scene: QPointF):
        item = self.parent_image
        s = self._drag_start_scale
        orig_w = item.base_width()
        orig_h = item.base_height()
        hp = self.handle_pos
        rotation = item.rotation()

        if hp == HandlePos.BR:
            anchor = self._anchor_TL
            orig_diag = math.hypot(orig_w * s, orig_h * s)
            dist = math.hypot(mouse_scene.x() - anchor.x(), mouse_scene.y() - anchor.y())
            new_scale = (dist / orig_diag) * s if orig_diag > 0 else s
            new_scale = max(0.05, min(20.0, new_scale))
            w_new = orig_w * new_scale
            h_new = orig_h * new_scale
            anchor_local_new = QPointF(0, 0)

        elif hp == HandlePos.BL:
            anchor = self._anchor_TR
            orig_diag = math.hypot(orig_w * s, orig_h * s)
            dist = math.hypot(mouse_scene.x() - anchor.x(), mouse_scene.y() - anchor.y())
            new_scale = (dist / orig_diag) * s if orig_diag > 0 else s
            new_scale = max(0.05, min(20.0, new_scale))
            w_new = orig_w * new_scale
            h_new = orig_h * new_scale
            anchor_local_new = QPointF(w_new, 0)

        elif hp == HandlePos.TR:
            anchor = self._anchor_BL
            orig_diag = math.hypot(orig_w * s, orig_h * s)
            dist = math.hypot(mouse_scene.x() - anchor.x(), mouse_scene.y() - anchor.y())
            new_scale = (dist / orig_diag) * s if orig_diag > 0 else s
            new_scale = max(0.05, min(20.0, new_scale))
            w_new = orig_w * new_scale
            h_new = orig_h * new_scale
            anchor_local_new = QPointF(0, h_new)

        elif hp == HandlePos.TL:
            anchor = self._anchor_BR
            orig_diag = math.hypot(orig_w * s, orig_h * s)
            dist = math.hypot(mouse_scene.x() - anchor.x(), mouse_scene.y() - anchor.y())
            new_scale = (dist / orig_diag) * s if orig_diag > 0 else s
            new_scale = max(0.05, min(20.0, new_scale))
            w_new = orig_w * new_scale
            h_new = orig_h * new_scale
            anchor_local_new = QPointF(w_new, h_new)

        elif hp == HandlePos.RM:
            anchor = self._anchor_LM
            diff = QPointF(mouse_scene.x() - anchor.x(), mouse_scene.y() - anchor.y())
            rad = math.radians(rotation)
            right_axis = QPointF(math.cos(rad), math.sin(rad))
            proj = diff.x() * right_axis.x() + diff.y() * right_axis.y()
            new_scale = abs(proj) / orig_w if orig_w > 0 else s
            new_scale = max(0.05, min(20.0, new_scale))
            w_new = orig_w * new_scale
            h_new = orig_h * new_scale
            anchor_local_new = QPointF(0, h_new / 2)

        elif hp == HandlePos.LM:
            anchor = self._anchor_RM
            diff = QPointF(mouse_scene.x() - anchor.x(), mouse_scene.y() - anchor.y())
            rad = math.radians(rotation)
            right_axis = QPointF(math.cos(rad), math.sin(rad))
            proj = diff.x() * right_axis.x() + diff.y() * right_axis.y()
            new_scale = abs(proj) / orig_w if orig_w > 0 else s
            new_scale = max(0.05, min(20.0, new_scale))
            w_new = orig_w * new_scale
            h_new = orig_h * new_scale
            anchor_local_new = QPointF(w_new, h_new / 2)

        elif hp == HandlePos.BM:
            anchor = self._anchor_TM
            diff = QPointF(mouse_scene.x() - anchor.x(), mouse_scene.y() - anchor.y())
            rad = math.radians(rotation)
            down_axis = QPointF(-math.sin(rad), math.cos(rad))
            proj = diff.x() * down_axis.x() + diff.y() * down_axis.y()
            new_scale = abs(proj) / orig_h if orig_h > 0 else s
            new_scale = max(0.05, min(20.0, new_scale))
            w_new = orig_w * new_scale
            h_new = orig_h * new_scale
            anchor_local_new = QPointF(w_new / 2, 0)

        elif hp == HandlePos.TM:
            anchor = self._anchor_BM
            diff = QPointF(mouse_scene.x() - anchor.x(), mouse_scene.y() - anchor.y())
            rad = math.radians(rotation)
            down_axis = QPointF(-math.sin(rad), math.cos(rad))
            proj = diff.x() * down_axis.x() + diff.y() * down_axis.y()
            new_scale = abs(proj) / orig_h if orig_h > 0 else s
            new_scale = max(0.05, min(20.0, new_scale))
            w_new = orig_w * new_scale
            h_new = orig_h * new_scale
            anchor_local_new = QPointF(w_new / 2, h_new)

        else:
            return

        # anchor_scene = new_pos + rotate(anchor_local_new - origin_new, R) + origin_new
        # → new_pos = anchor_scene - origin_new - rotate(anchor_local_new - origin_new, R)
        origin_new = QPointF(orig_w * new_scale / 2, orig_h * new_scale / 2)
        item.resize_item(new_scale)
        rotated = _rotate_vec(
            QPointF(anchor_local_new.x() - origin_new.x(),
                    anchor_local_new.y() - origin_new.y()),
            rotation
        )
        new_pos = QPointF(
            anchor.x() - origin_new.x() - rotated.x(),
            anchor.y() - origin_new.y() - rotated.y()
        )
        item.setPos(new_pos)


class _RotationHandle(QGraphicsEllipseItem):
    def __init__(self, parent_image: 'ImageDisplay', corner: HandlePos) -> None:
        super().__init__(-4, -4, 8, 8, parent_image)
        self.parent_image = parent_image
        self.corner = corner
        self.setBrush(QBrush(QColor(0, 200, 180, 150)))
        self.setPen(QPen(Qt.NoPen))
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(1002)
        self.setVisible(False)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.dragging = False
        self._start_angle = 0.0
        self._base_rotation = 0.0

    def _item_center_scene(self) -> QPointF:
        item = self.parent_image
        s = item.current_scale
        orig_w = item.base_width()
        orig_h = item.base_height()
        return item.mapToScene(QPointF(orig_w * s / 2, orig_h * s / 2))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            center = self._item_center_scene()
            sp = event.scenePos()
            self._start_angle = math.degrees(math.atan2(sp.y() - center.y(), sp.x() - center.x()))
            self._base_rotation = self.parent_image.rotation()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            center = self._item_center_scene()
            cp = event.scenePos()
            current_angle = math.degrees(math.atan2(cp.y() - center.y(), cp.x() - center.x()))
            delta = current_angle - self._start_angle
            new_rotation = self._base_rotation + delta
            if not (event.modifiers() & Qt.ShiftModifier):
                remainder = new_rotation % 45.0
                if remainder > 22.5:
                    remainder -= 45.0
                if abs(remainder) <= 3.0:
                    new_rotation -= remainder
            self.parent_image.setRotation(new_rotation)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            new_rotation = self.parent_image.rotation()
            if new_rotation != self._base_rotation:
                views = self.parent_image.scene().views() if self.parent_image.scene() else []
                if views and hasattr(views[0], 'undo_stack'):
                    from CoffeeBoard.core.undo_commands import RotateCommand
                    views[0].undo_stack.push(RotateCommand(self.parent_image, self._base_rotation, new_rotation))
            event.accept()


class ImageDisplay(QGraphicsPixmapItem):
    """A selectable and resizable QGraphicsPixmapItem used for displaying reference images.

    This class handles image loading via the tiered image_loader (OIIO for EXR,
    Qt float32 for standard formats). All image types get HDR controls.

    Attributes:
        path (Union[str, os.PathLike]): The file path of the original asset, or "clipboard_image".
        layer (str): The specific layer/channel loaded from the source file (e.g., 'rgba').
        original_pixmap (QPixmap): The unscaled version of the loaded image data.
        current_scale (float): The current scale factor applied to the pixmap (1.0 = original size).
    """

    # --- ATTRIBUTE TYPE HINTS ---
    path: Union[str, os.PathLike]
    layer: str
    original_pixmap: QPixmap
    current_scale: float
    linear_data: Any  # np.ndarray float32 eller None
    linear_data_preview: Any  # downscaled float32 for real-time preview, or None
    exposure: float
    gamma: float
    tone_mapping: str
    colorspace: str
    display_name: Optional[str]
    _display_buffer: Any  # numpy-referens för QImage GC-skydd
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
            preview_format (str, optional): Kept for JSON save/load backwards-compat.
                                            Defaults to 'jpg'.

        Raises:
            TypeError: If the source is neither a path nor a QPixmap.
        """
        # If source is a path, load via tiered image_loader
        if isinstance(source, (str, bytes, os.PathLike)):
            self.path = source
            self.layer = layer
            self.preview_format = preview_format
            pixmap = self._load_image_data(source, layer, preview_format)
        # If source is already a QPixmap, use it directly
        elif isinstance(source, QPixmap):
            self.path = "clipboard_image"  # Placeholder path for clipboard images
            self.layer = 'rgba'  # Default layer for clipboard images
            self.preview_format = 'png'  # Clipboard images are always saved as PNG
            pixmap = source
            # Build float32 data so exposure/gamma controls work on clipboard images
            try:
                import numpy as np
                qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
                ptr = qimg.constBits()
                arr = np.frombuffer(ptr, dtype=np.uint8).reshape(qimg.height(), qimg.width(), 4).copy()
                self.linear_data = arr.astype(np.float32) / 255.0
            except Exception:
                pass
        else:
            raise TypeError(f"Expected str or QPixmap, got {type(source)}")

        super().__init__(pixmap)

        self.original_pixmap = pixmap
        self.current_scale = 1.0
        self._init_handles()

        # HDR display transform-attribut
        if not hasattr(self, 'linear_data'):
            self.linear_data = None
        self.linear_data_preview = None
        self.exposure = 0.0
        self.gamma = 2.2
        self.tone_mapping = 'reinhard'
        self.colorspace = 'linear'
        self.display_name = None  # Optional custom label shown in Item List
        self.consolidation_action: Optional[str] = None
        self._display_buffer = None

        # Auto-detect colorspace for non-EXR file-based images.
        if self.path != 'clipboard_image':
            ext = os.path.splitext(str(self.path))[1].lower()
            if ext != '.exr':
                self.colorspace = _detect_file_colorspace(str(self.path))
                if self.linear_data is not None:
                    self.tone_mapping = 'clamp'
                    self.gamma = 2.2
                    self._update_display_transform()
        else:
            # Clipboard images are sRGB — set up so display controls work
            if self.linear_data is not None:
                self.colorspace = 'srgb'
                self.tone_mapping = 'clamp'
                self._make_preview_data()

        # Configure item interaction flags
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self._drag_start_pos = None

    def _init_handles(self):
        self._selection_border = _SelectionBorder(self)
        self._handles = [_Handle(self, hp) for hp in HandlePos]
        self._rotation_handles = [_RotationHandle(self, c)
                                   for c in (HandlePos.TL, HandlePos.TR,
                                             HandlePos.BL, HandlePos.BR)]
        w = self.base_width()
        h = self.base_height()
        self.setTransformOriginPoint(w / 2, h / 2)

    def _load_image_data(self, path: str,
                            layer: str = 'rgba',
                            preview_format: str = 'jpg') -> QPixmap:
        """Load image via the tiered image_loader.

        Args:
            path (str): The file path to the image asset.
            layer (str, optional): The layer to extract for EXR files. Defaults to 'rgba'.
            preview_format (str, optional): Kept for backwards-compat. Defaults to 'jpg'.

        Returns:
            QPixmap: The loaded image, or a placeholder QPixmap if loading fails.
        """
        from CoffeeBoard.core.image_loader import load_image
        pixmap, linear = load_image(path, layer)
        self.linear_data = linear
        self._make_preview_data()
        return pixmap

    _PREVIEW_MAX_PX = 1024

    def _make_preview_data(self) -> None:
        if self.linear_data is None:
            self.linear_data_preview = None
            return
        h, w = self.linear_data.shape[:2]
        if max(h, w) <= self._PREVIEW_MAX_PX:
            self.linear_data_preview = None  # full-res is fast enough
            return
        step = max(2, int(max(h, w) / self._PREVIEW_MAX_PX))
        self.linear_data_preview = self.linear_data[::step, ::step].copy()

    def _update_display_fast(self) -> None:
        """Quick preview using downscaled data — for real-time slider feedback."""
        data = self.linear_data_preview if self.linear_data_preview is not None else self.linear_data
        if data is None:
            return
        from CoffeeBoard.core.display_pipeline import apply_display_transform
        pixels_16bit = apply_display_transform(
            data, self.exposure, self.gamma, self.tone_mapping,
            colorspace=self.colorspace
        )
        qimage = self._numpy_to_qimage(pixels_16bit)
        preview_pixmap = QPixmap.fromImage(qimage)
        target_w = int(self.original_pixmap.width() * self.current_scale)
        target_h = int(self.original_pixmap.height() * self.current_scale)
        self.setPixmap(preview_pixmap.scaled(
            target_w, target_h, Qt.KeepAspectRatio, Qt.FastTransformation
        ))

    def hoverEnterEvent(self, event: QMouseEvent) -> None:
        """Changes the cursor to a pointing hand when hovering over the item."""
        self.setCursor(Qt.PointingHandCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QMouseEvent) -> None:
        """Restores the cursor when the mouse leaves the item area."""
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.ItemSelectedChange:
            if value:
                self.show_handles()
            else:
                self.hide_handles()
        return super().itemChange(change, value)

    def show_handles(self) -> None:
        self._selection_border.setVisible(True)
        for h in self._handles:
            h.setVisible(True)
        for rh in self._rotation_handles:
            rh.setVisible(True)
        self.update_handles()

    def hide_handles(self) -> None:
        self._selection_border.setVisible(False)
        for h in self._handles:
            h.setVisible(False)
        for rh in self._rotation_handles:
            rh.setVisible(False)

    def update_handles(self) -> None:
        w = self.base_width() * self.current_scale
        h = self.base_height() * self.current_scale

        # Scale handles so they remain a fixed ~12px on screen regardless of zoom.
        vs = _get_view_scale(self)
        hs = max(5.0, 12.0 / vs)   # resize handle half-size in scene coords
        rs = max(5.0, 12.0 / vs)   # rotation handle half-size
        roff = max(_ROFF, 18.0 / vs)  # rotation handle offset from corner

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

    def base_width(self) -> float:
        return self.original_pixmap.width()

    def base_height(self) -> float:
        return self.original_pixmap.height()

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
        self.setTransformOriginPoint(
            self.original_pixmap.width() * scale_factor / 2,
            self.original_pixmap.height() * scale_factor / 2
        )
        self.update_handles()

    resize_item = resize_image

    def _numpy_to_qimage(self, pixels) -> QImage:
        """Konvertera numpy uint16 array till QImage.

        Stödjer Format_RGBA64 (16-bit) med fallback till Format_RGBA8888 (8-bit).
        Hanterar både 3-kanals (RGB) och 4-kanals (RGBA) input.

        Args:
            pixels: numpy array med shape (H, W, 3 eller 4), dtype uint16.

        Returns:
            QImage redo att konverteras till QPixmap.
        """
        import numpy as np

        height, width, channels = pixels.shape

        # Säkerställ RGBA (4 kanaler)
        if channels == 3:
            rgba = np.zeros((height, width, 4), dtype=pixels.dtype)
            rgba[:, :, :3] = pixels
            max_val = 65535 if pixels.dtype == np.uint16 else 255
            rgba[:, :, 3] = max_val
            pixels = rgba

        # Säkerställ sammanhängande minne
        pixels = np.ascontiguousarray(pixels)

        if HAS_RGBA64 and pixels.dtype == np.uint16:
            bytes_per_line = width * 8  # 4 kanaler * 2 bytes
            fmt = QImage.Format_RGBA64
        else:
            # Nedkonvertera till 8-bit
            if pixels.dtype == np.uint16:
                pixels = (pixels >> 8).astype(np.uint8)
                pixels = np.ascontiguousarray(pixels)
            fmt = QImage.Format_RGBA8888
            bytes_per_line = width * 4

        qimage = QImage(pixels.data, width, height, bytes_per_line, fmt)

        # Behåll numpy-referens för att förhindra GC
        self._display_buffer = pixels

        return qimage

    def set_exposure(self, ev: float) -> None:
        """Uppdatera exponering och rendera om.

        Args:
            ev: Exponeringsjustering i stops.
        """
        if self.linear_data is None:
            return
        self.exposure = ev
        self._update_display_transform()

    def set_gamma(self, gamma: float) -> None:
        """Uppdatera gamma och rendera om.

        Args:
            gamma: Display-gamma (t.ex. 2.2).
        """
        if self.linear_data is None:
            return
        self.gamma = gamma
        self._update_display_transform()

    def set_colorspace(self, colorspace: str) -> None:
        if self.linear_data is None:
            return
        self.colorspace = colorspace
        self._update_display_transform()

    def set_tone_mapping(self, method: str) -> None:
        """Byt tone mapping-operator och rendera om.

        Args:
            method: Operatornamn ('reinhard', 'filmic', 'clamp').
        """
        if self.linear_data is None:
            return
        self.tone_mapping = method
        self._update_display_transform()

    def _update_display_transform(self) -> None:
        """Kör om display transform från cachad linjär data och uppdatera pixmap."""
        from CoffeeBoard.core.display_pipeline import apply_display_transform

        pixels_16bit = apply_display_transform(
            self.linear_data, self.exposure, self.gamma, self.tone_mapping,
            colorspace=self.colorspace
        )
        qimage = self._numpy_to_qimage(pixels_16bit)
        self.original_pixmap = QPixmap.fromImage(qimage)
        self.resize_image(self.current_scale)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = self.pos()
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
        if event.button() == Qt.LeftButton:
            views = self.scene().views()
            if views and hasattr(views[0], 'open_settings_panel'):
                views[0].open_settings_panel(self)
        event.accept()
