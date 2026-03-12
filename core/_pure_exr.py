"""Pure-Python EXR reader — no compiled dependencies.

Handles:
- Uncompressed scanline EXR (compression=0)
- ZIPS: 1 scanline/block, zlib-compressed (compression=2)
- ZIP: 16 scanlines/block, zlib-compressed (compression=3)
- HALF (float16) and FLOAT (float32) channels
- Single-part, flat scanline EXR only

Raises UnsupportedCompression for PIZ, DWAA, multi-part → caller falls to next tier.
"""

from __future__ import annotations

import io
import struct
import zlib

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAGIC = 20000630
_COMP_NONE, _COMP_ZIPS, _COMP_ZIP = 0, 2, 3
_HALF, _FLOAT = 1, 2


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ExrError(Exception):
    pass


class UnsupportedCompression(ExrError):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rstr(f) -> str:
    """Read a null-terminated string from a binary file-like object."""
    buf = []
    while True:
        c = f.read(1)
        if not c or c == b'\x00':
            return b''.join(buf).decode('latin-1')
        buf.append(c)


def _read_header(f) -> dict:
    """Read EXR header → dict of {attr_name: (type_str, raw_bytes)}."""
    magic, version_word = struct.unpack('<II', f.read(8))
    if magic != _MAGIC:
        raise ExrError('Not an EXR file')
    if version_word & 0x200:   # bit 9 = tiled (block layout differs from scanline)
        raise UnsupportedCompression('Tiled EXR not supported by _pure_exr')
    if version_word & 0x800:   # bit 11 = deep data
        raise UnsupportedCompression('Deep EXR not supported by _pure_exr')
    if version_word & 0x1000:  # bit 12 = multi-part
        raise UnsupportedCompression('Multi-part EXR not supported by _pure_exr')
    attrs = {}
    while True:
        name = _rstr(f)
        if not name:
            break
        typ = _rstr(f)
        size = struct.unpack('<i', f.read(4))[0]
        attrs[name] = (typ, f.read(size))
    return attrs


def _parse_channels(data: bytes) -> dict:
    """Parse chlist attribute bytes → {name: {'type': int}}."""
    f = io.BytesIO(data)
    channels = {}
    while True:
        name = _rstr(f)
        if not name:
            break
        pixel_type = struct.unpack('<i', f.read(4))[0]
        f.read(4)   # pLinear (uint8) + 3 reserved bytes
        f.read(8)   # xSampling (int32) + ySampling (int32)
        channels[name] = {'type': pixel_type}
    return channels


def _select_channels(channels: dict, layer: str) -> list | None:
    """Return [R_name, G_name, B_name, (A_name)] for layer, or None if not found."""
    if layer == 'rgba':
        r = 'R' if 'R' in channels else None
        g = 'G' if 'G' in channels else None
        b = 'B' if 'B' in channels else None
        a = 'A' if 'A' in channels else None
    else:
        r = f'{layer}.R' if f'{layer}.R' in channels else None
        g = f'{layer}.G' if f'{layer}.G' in channels else None
        b = f'{layer}.B' if f'{layer}.B' in channels else None
        a = f'{layer}.A' if f'{layer}.A' in channels else None

    if not all([r, g, b]):
        return None
    result = [r, g, b]
    if a:
        result.append(a)
    return result


def _decompress_zip(data: bytes) -> bytes:
    """Undo OpenEXR's ZIP predictor: inflate → undo delta → undo byte-reorder.

    OpenEXR encoder order: byte-interleave → delta-predict → zlib.
    Decoder reverses: zlib → undo delta-predict → undo byte-interleave.
    """
    raw = bytearray(zlib.decompress(data))
    n = len(raw)

    # Step 1: undo delta-predict (on the interleaved sequence)
    p = raw[0]
    for i in range(1, n):
        d = (raw[i] - 128) & 0xFF
        p = (p + d) & 0xFF
        raw[i] = p

    # Step 2: undo byte-interleave
    # After delta, raw[:half] holds the even-index values, raw[half:] the odd-index values.
    # Restore: even positions ← first half, odd positions ← second half.
    half = (n + 1) // 2
    out = bytearray(n)
    t1, t2, s = 0, half, 0
    while True:
        if s < n:
            out[s] = raw[t1]; t1 += 1; s += 1
        else:
            break
        if s < n:
            out[s] = raw[t2]; t2 += 1; s += 1
        else:
            break

    return bytes(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_exr_layers(path: str) -> list:
    """Read EXR header only (fast) and return sorted unique layer names."""
    with open(path, 'rb') as f:
        attrs = _read_header(f)
    channels = _parse_channels(attrs['channels'][1])
    layers: set = set()
    for name in channels:
        if '.' in name:
            layers.add(name.split('.')[0])
        else:
            layers.add('rgba')
    return sorted(layers) if layers else ['rgba']


def read_exr(path: str, layer: str = 'rgba') -> np.ndarray:
    """Return (H, W, 3|4) float32 array in linear space, or raise ExrError."""
    with open(path, 'rb') as f:
        attrs = _read_header(f)

        comp = struct.unpack('<B', attrs['compression'][1])[0]
        if comp not in (_COMP_NONE, _COMP_ZIPS, _COMP_ZIP):
            raise UnsupportedCompression(
                f'Compression type {comp} (PIZ/DWAA/etc.) not supported'
            )

        x0, y0, x1, y1 = struct.unpack('<4i', attrs['dataWindow'][1])
        w, h = x1 - x0 + 1, y1 - y0 + 1

        channels = _parse_channels(attrs['channels'][1])
        ch_names = _select_channels(channels, layer)
        if ch_names is None:
            raise ExrError(f"Layer '{layer}' not found in {path}")

        spb = 16 if comp == _COMP_ZIP else 1   # scanlines per block
        n_blocks = (h + spb - 1) // spb
        offsets = struct.unpack(f'<{n_blocks}Q', f.read(8 * n_blocks))

        out = np.zeros((h, w, len(ch_names)), dtype=np.float32)
        ch_sorted = sorted(channels)  # alphabetical = file order

        for bi in range(n_blocks):
            f.seek(offsets[bi])
            _y = struct.unpack('<i', f.read(4))[0]
            dsz = struct.unpack('<i', f.read(4))[0]
            data = f.read(dsz)
            if comp != _COMP_NONE:
                data = _decompress_zip(data)

            pos = 0
            y0b = bi * spb
            for row in range(min(spb, h - y0b)):
                y = y0b + row
                for ch in ch_sorted:
                    ct = channels[ch]['type']
                    bpp = 2 if ct == _HALF else 4
                    chunk = data[pos:pos + w * bpp]
                    pos += w * bpp
                    if ch not in ch_names:
                        continue
                    ci = ch_names.index(ch)
                    if ct == _HALF:
                        out[y, :, ci] = np.frombuffer(chunk, dtype=np.float16).astype(np.float32)
                    else:
                        out[y, :, ci] = np.frombuffer(chunk, dtype=np.float32)

    return out
