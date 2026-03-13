# CoffeeBoard

A VFX reference board for CoffeeVein Studio. Drop images onto an infinite canvas, annotate with text and shapes, and apply per-image HDR controls. Runs standalone or docked inside Nuke.

---

## Requirements

- **Python 3.7+** (tested on 3.12)
- **PySide2** (Nuke 15) or **PySide6** (Nuke 16+, standalone)
- **NumPy** — optional; required for HDR tone mapping (exposure/gamma sliders). If missing, images still load but HDR controls are disabled.
- **OpenEXR + imath** — optional; enables full EXR spec support. Falls back to a bundled pure-Python EXR reader (`_pure_exr.py`) for uncompressed and ZIP-scanline EXR files without it.

---

## Installation

### Standalone

1. Clone the repository:
   ```
   git clone https://github.com/CoffeeVeinStudio/CoffeeBoard.git
   ```
   This creates a `CoffeeBoard/` folder. The **parent** of that folder needs to be on your `PYTHONPATH` — e.g. if you cloned into `C:\Tools\`, add `C:\Tools\` to `PYTHONPATH`.

2. Install dependencies:
   ```
   pip install PySide6 numpy
   ```
   (Nuke 15 ships PySide2 — no separate install needed there.)

### Nuke
1. Clone the repository into your `.nuke` folder:
```
   git clone https://github.com/youruser/CoffeeBoard.git ~/.nuke/CoffeeBoard
```
2. In your `~/.nuke/menu.py`, add:
```python
   try:
       import CoffeeBoard.adapters.nuke_adapter
   except Exception as e:
       nuke.warning(f'[CoffeeBoard] failed to load: {e}')
```
3. Restart Nuke. The panel appears in **Window → Add Pane → Coffee Board**.
---

## Running Standalone

**Command line:**
```
cd C:\Tools                  # the parent of CoffeeBoard/
python -m CoffeeBoard
```

The window opens at 1280×800. Theme preference (Dark/Light/System) is saved to `~/.coffeeboard/prefs.json`.

---

## Running in Nuke

1. Open Nuke.
2. Go to **Window → Add Pane → Coffee Board** (or find it in the panel list).
3. Dock it wherever you like — it behaves as a standard Nuke panel tab.

**Smart keyboard overrides** activate whenever the mouse cursor is over the CoffeeBoard canvas:

| Shortcut | Mouse over canvas | Mouse elsewhere |
|---|---|---|
| `Ctrl+Z` | CoffeeBoard undo | Nuke undo |
| `Ctrl+Y` / `Ctrl+Shift+Z` | CoffeeBoard redo | Nuke redo |
| `Ctrl+S` | Save board | Save Nuke script |
| `Ctrl+O` | Open board | Open Nuke script |

---

## Features

### Images
- **Drop images** from the file system or paste from clipboard (`Ctrl+V`)
- Supports JPEG, PNG, BMP, EXR (full spec via OpenEXR or built-in fallback reader)
- EXR files with multiple layers show a layer-selection dialog on load
- **8-handle resize** — drag any corner or edge midpoint; aspect ratio is always maintained
- **Rotation handles** — small circles outside each corner; snap to 45° increments (hold Shift to disable)
- **Double-click** an image to open its per-image settings panel

### Per-image Settings (double-click)
- Input colorspace: sRGB / Linear / LogC3 / LogC4 / S-Log3 / V-Log / Rec.709
- Colorspace is auto-detected from file extension and EXIF data for non-EXR files
- Exposure, Gamma, Tone Mapping (Reinhard / Filmic / Clamp)
- `Ctrl+click` any control to reset that control to its image-type default
- **Reset** button restores all controls to image-type defaults

### Text & Shapes
- Right-click canvas → **Add Text** — enters edit mode immediately; double-click to re-edit
- Text settings panel: font family, size, bold, italic, color picker
- Shape drawing: rectangle, ellipse, line, arrow

### Canvas navigation
- **Pan** — middle-mouse drag, or `Alt+left-mouse`
- **Zoom** — scroll wheel
- **Select** — left-click; `Ctrl+A` selects all; `Escape` deselects
- **Delete** — `Delete` or `Backspace` removes selected items
- **Multi-select** — hold `Shift` to add to selection; drag to box-select

### Z-order
- Right-click → **Bring to Front** / **Send to Back** / **Move Forward** / **Move Back**
- The **Item List** panel shows all items ordered by depth; click a row to select, drag to reorder

### Undo / Redo
- `Ctrl+Z` / `Ctrl+Shift+Z` — 50-step history
- Covers: move, resize, rotate, add, delete, settings changes

### Saving & Loading
- `Ctrl+S` — save board as a `.board` file; images are consolidated next to the board
- `Ctrl+O` — open a saved board
- **File images**: prompted to Move, Copy, or Leave when saving (Move removes originals)
- **Clipboard images**: always written to `<board_name>_images/` on save

### Theme (standalone only)
- **View → Theme → Dark / Light / System** — swaps the application palette at runtime
- Preference is remembered across sessions

---

## File Format

Boards are saved as `.board` files (plain JSON internally). The `_images/` folder next to the `.board` file holds consolidated image files. Moving a board requires moving its `_images/` folder alongside it.

Older boards saved as `.json` can still be opened — the load dialog accepts both extensions.

---

## Keyboard Shortcuts

| Action | Shortcut |
|---|---|
| Undo | `Ctrl+Z` |
| Redo | `Ctrl+Shift+Z` |
| Save board | `Ctrl+S` |
| Open board | `Ctrl+O` |
| Paste image | `Ctrl+V` |
| Select all | `Ctrl+A` |
| Delete selected | `Delete` / `Backspace` |
| Deselect | `Escape` |
| Add Text | Right-click → Add Text |
