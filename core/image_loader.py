"""Tiered image loader — returns (QPixmap, linear_data_or_None).

Tier 1 — OIIO (EXR only): full float32 linear data, HDR controls available.
Tier 2 — Qt float32 (JPEG/PNG/TIFF/BMP): 8-bit source promoted to float32,
          display-transformed to uint16 pixmap, HDR controls available.
Tier 3 — Qt plain (EXR fallback when no OIIO): no linear_data, HDR unavailable.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# EXR layer discovery (re-exported so canvas.py can use it directly)
# ---------------------------------------------------------------------------

def get_exr_layers(path: str) -> List[str]:
    """Return unique layer names for an EXR file.

    Tier 1: OIIO. Tier 2: pure_exr header read. Falls back to ['rgba'].
    """
    try:
        import OpenEXR
        import Imath
        f = OpenEXR.InputFile(path)
        try:
            channel_names = list(f.header()['channels'].keys())
            layers = set()
            for ch in channel_names:
                if '.' in ch:
                    layers.add(ch.split('.')[0])
                else:
                    layers.add('rgba')
            return sorted(layers) if layers else ['rgba']
        finally:
            f.close()
    except Exception:
        pass
    # Tier 2: pure_exr header-only read
    try:
        from CoffeeBoard.core._pure_exr import get_exr_layers as _pexr_layers
        return _pexr_layers(path)
    except Exception:
        pass
    return ['rgba']


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_exr_via_oiio(path: str, layer: str = 'rgba') -> np.ndarray:
    """Load an EXR layer as float32 numpy array via OpenEXR + Imath."""
    import OpenEXR
    import Imath

    f = OpenEXR.InputFile(path)
    try:
        header = f.header()
        dw = header['dataWindow']
        width  = dw.max.x - dw.min.x + 1
        height = dw.max.y - dw.min.y + 1

        channel_names = list(header['channels'].keys())
        float_pt = Imath.PixelType(Imath.PixelType.FLOAT)

        if layer == 'rgba':
            r_ch = 'R' if 'R' in channel_names else None
            g_ch = 'G' if 'G' in channel_names else None
            b_ch = 'B' if 'B' in channel_names else None
            a_ch = 'A' if 'A' in channel_names else None
        else:
            r_ch = f'{layer}.R' if f'{layer}.R' in channel_names else None
            g_ch = f'{layer}.G' if f'{layer}.G' in channel_names else None
            b_ch = f'{layer}.B' if f'{layer}.B' in channel_names else None
            a_ch = f'{layer}.A' if f'{layer}.A' in channel_names else None

        if not all([r_ch, g_ch, b_ch]):
            available = ', '.join(channel_names)
            raise RuntimeError(
                f"Layer '{layer}' missing RGB channels in {path}. "
                f"Available: {available}"
            )

        target = [r_ch, g_ch, b_ch]
        if a_ch:
            target.append(a_ch)

        raw = [f.channel(ch, float_pt) for ch in target]
        arrays = [np.frombuffer(d, dtype=np.float32).reshape(height, width)
                  for d in raw]
        return np.stack(arrays, axis=-1).astype(np.float32)
    finally:
        f.close()


def _load_exr_via_nuke(path: str, layer: str = 'rgba') -> np.ndarray:
    """Re-encode EXR via Nuke's internal reader, then decode with _pure_exr.

    Handles PIZ, DWAA, and any other compression Nuke supports.
    Creates and immediately deletes temporary Read/Write nodes.
    """
    import nuke
    import tempfile
    import os

    fd, tmp = tempfile.mkstemp(suffix='.exr')
    os.close(fd)
    tmp_posix = tmp.replace('\\', '/')
    src_posix = str(path).replace('\\', '/')

    nuke.Undo.disable()
    read_node = write_node = None
    try:
        read_node = nuke.createNode('Read', inpanel=False)
        read_node['file'].setValue(src_posix)

        write_node = nuke.createNode('Write', inpanel=False)
        write_node['file'].setValue(tmp_posix)
        write_node['file_type'].setValue('exr')
        write_node['compression'].setValue(0)  # 0 = no compression — _pure_exr reads raw bytes
        write_node.setInput(0, read_node)

        first = int(read_node['first'].value())
        nuke.execute(write_node, first, first)

        from CoffeeBoard.core._pure_exr import read_exr
        return read_exr(tmp_posix, layer)
    finally:
        if write_node is not None:
            nuke.delete(write_node)
        if read_node is not None:
            nuke.delete(read_node)
        nuke.Undo.enable()
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _numpy_to_pixmap(arr_16bit, width, height):
    """Convert a uint16 (H, W, 4) numpy array to QPixmap."""
    try:
        from PySide2.QtGui import QImage, QPixmap
    except ImportError:
        from PySide6.QtGui import QImage, QPixmap

    has_rgba64 = hasattr(QImage, 'Format_RGBA64')
    arr = np.ascontiguousarray(arr_16bit)

    if has_rgba64:
        bytes_per_line = width * 8
        qimage = QImage(arr.data, width, height, bytes_per_line, QImage.Format_RGBA64)
    else:
        arr8 = (arr >> 8).astype(np.uint8)
        arr8 = np.ascontiguousarray(arr8)
        bytes_per_line = width * 4
        qimage = QImage(arr8.data, width, height, bytes_per_line, QImage.Format_RGBA8888)

    return QPixmap.fromImage(qimage)


def _placeholder_pixmap(filename: str):
    """Return a gray placeholder pixmap with the filename as text."""
    try:
        from PySide2.QtGui import QPixmap, QColor, QPainter
        from PySide2.QtCore import Qt
    except ImportError:
        from PySide6.QtGui import QPixmap, QColor, QPainter
        from PySide6.QtCore import Qt

    pixmap = QPixmap(400, 300)
    pixmap.fill(QColor(60, 60, 60))
    painter = QPainter(pixmap)
    painter.setPen(QColor(150, 150, 150))
    painter.drawText(pixmap.rect(), Qt.AlignCenter,
                     f"Failed to load:\n{filename}")
    painter.end()
    return pixmap


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_image(path: str, layer: str = 'rgba') -> Tuple[object, Optional[np.ndarray]]:
    """Load an image file and return (QPixmap, linear_data_or_None).

    Tier 1 — OIIO (EXR): full float32 linear, HDR controls active.
    Tier 2 — Qt float32 (JPEG/PNG/TIFF/BMP): promoted to float32, HDR active.
    Tier 3 — Qt plain (EXR without OIIO): no linear_data, HDR inactive.
    Fallback — gray placeholder on total failure.
    """
    from CoffeeBoard.core.display_pipeline import apply_display_transform

    ext = os.path.splitext(path)[1].lower()

    # --- Tier 1: OIIO for EXR ---
    if ext == '.exr':
        try:
            linear = _load_exr_via_oiio(path, layer)
            pixels_16 = apply_display_transform(linear, 0.0, 2.2, 'reinhard')

            h, w, c = pixels_16.shape
            if c == 3:
                alpha = np.full((h, w, 1), 65535, dtype=np.uint16)
                pixels_16 = np.concatenate([pixels_16, alpha], axis=2)

            pixmap = _numpy_to_pixmap(pixels_16, w, h)
            if not pixmap.isNull():
                return pixmap, linear
        except ImportError:
            pass  # OIIO not installed — fall through to Tier 2
        except Exception as e:
            print(f"[CoffeeBoard] OIIO load failed for {path}: {e}")

        # --- Tier 2: pure-Python EXR (no compiled deps) ---
        try:
            from CoffeeBoard.core._pure_exr import read_exr, UnsupportedCompression
            linear = read_exr(path, layer)
            pixels_16 = apply_display_transform(linear, 0.0, 2.2, 'reinhard')

            h, w, c = pixels_16.shape
            if c == 3:
                alpha = np.full((h, w, 1), 65535, dtype=np.uint16)
                pixels_16 = np.concatenate([pixels_16, alpha], axis=2)

            pixmap = _numpy_to_pixmap(pixels_16, w, h)
            if not pixmap.isNull():
                return pixmap, linear
        except UnsupportedCompression:
            pass  # PIZ/DWAA → try Nuke tier
        except Exception as e:
            print(f'[CoffeeBoard] pure_exr failed for {path}: {e}')

        # --- Tier 2b: Nuke native EXR (handles PIZ/DWAA/any Nuke-supported compression) ---
        try:
            linear = _load_exr_via_nuke(path, layer)
            pixels_16 = apply_display_transform(linear, 0.0, 2.2, 'reinhard')

            h, w, c = pixels_16.shape
            if c == 3:
                alpha = np.full((h, w, 1), 65535, dtype=np.uint16)
                pixels_16 = np.concatenate([pixels_16, alpha], axis=2)

            pixmap = _numpy_to_pixmap(pixels_16, w, h)
            if not pixmap.isNull():
                return pixmap, linear
        except ImportError:
            pass  # Not running in Nuke
        except Exception as e:
            print(f'[CoffeeBoard] Nuke EXR load failed for {path}: {e}')

    # --- Tier 2: Qt float32 for standard formats ---
    if ext in ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp'):
        try:
            try:
                from PySide2.QtGui import QImage, QPixmap
            except ImportError:
                from PySide6.QtGui import QImage, QPixmap

            img = QImage(path).convertToFormat(QImage.Format_RGBA8888)
            w, h = img.width(), img.height()
            if w > 0 and h > 0:
                ptr = img.constBits()
                try:
                    arr = np.frombuffer(ptr, dtype=np.uint8, count=w * h * 4)
                except TypeError:
                    arr = np.array(ptr, dtype=np.uint8)  # PySide2 sip.voidptr fallback
                arr = arr.reshape(h, w, 4).astype(np.float32) / 255.0
                arr = arr.copy()  # detach from Qt memory before img goes out of scope

                pixels_16 = apply_display_transform(arr, 0.0, 2.2, 'reinhard')

                # Ensure RGBA (4 channels)
                ph, pw, pc = pixels_16.shape
                if pc == 3:
                    alpha = np.full((ph, pw, 1), 65535, dtype=np.uint16)
                    pixels_16 = np.concatenate([pixels_16, alpha], axis=2)

                pixmap = _numpy_to_pixmap(pixels_16, pw, ph)
                if not pixmap.isNull():
                    return pixmap, arr
        except Exception as e:
            print(f"[CoffeeBoard] Qt float32 load failed for {path}: {e}")

    # --- Tier 3: Qt plain fallback (EXR without OIIO, or any format Qt supports) ---
    try:
        try:
            from PySide2.QtGui import QPixmap
        except ImportError:
            from PySide6.QtGui import QPixmap

        pixmap = QPixmap(path)
        if not pixmap.isNull():
            return pixmap, None
    except Exception as e:
        print(f"[CoffeeBoard] Qt plain load failed for {path}: {e}")

    # --- Total failure: gray placeholder ---
    return _placeholder_pixmap(os.path.basename(path)), None
