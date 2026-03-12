"""Save/load logic for CoffeeBoard, extracted from canvas.py.

Functions take `board` (a CoffeeBoard instance) as the first argument (duck-typed).
"""

from __future__ import annotations

import os
import json
import shutil
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from CoffeeBoard.core.canvas import CoffeeBoard

try:
    from PySide2.QtCore import QTimer
    from PySide2.QtGui import QColor
    from PySide2.QtWidgets import (QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
                                    QLabel, QComboBox, QPushButton, QScrollArea, QWidget)
except ImportError:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
                                    QLabel, QComboBox, QPushButton, QScrollArea, QWidget)


def save_board(board: 'CoffeeBoard') -> None:
    """Save the current state of the reference board to a JSON file."""
    # Partition items by type
    clipboard_items = [i for i in board.image_items if getattr(i, 'path', None) == "clipboard_image"]
    file_items      = [i for i in board.image_items if getattr(i, 'path', None) != "clipboard_image"]

    # Resolve save path first so we can check which files are already consolidated
    if board.current_save_path:
        file_path = board.current_save_path
    else:
        file_path = board.bridge.get_filename("Save Reference Board", pattern="*.board", type='save')

    if not file_path:
        return  # User cancelled

    # Ensure .board extension
    if not file_path.endswith('.board'):
        file_path += '.board'

    save_dir = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    images_folder = os.path.join(save_dir, f"{base_name}_images")
    norm_folder = os.path.normcase(os.path.abspath(images_folder)) + os.sep

    # Only prompt for files that are NOT already inside the consolidation folder
    outside_items = [
        i for i in file_items
        if not os.path.normcase(os.path.abspath(i.path)).startswith(norm_folder)
    ]

    items_without_action = [i for i in outside_items if not getattr(i, 'consolidation_action', None)]

    if items_without_action:
        result = _prompt_file_consolidation_choice(board, len(items_without_action))
        if result is None:
            return  # user cancelled
        if result == 'per_image':
            actions = _PerImageConsolidationDialog(board, outside_items).run()
            if actions is None:
                return  # user cancelled per-image dialog
            for item, action in actions.items():
                item.consolidation_action = action
        else:  # global: 'move' | 'copy' | 'leave'
            for item in items_without_action:
                item.consolidation_action = result

    try:
        board_data = {"items": []}

        # Create images folder if needed
        any_move_copy = any(
            getattr(i, 'consolidation_action', None) in ('move', 'copy')
            for i in file_items
        )
        need_images_folder = clipboard_items or any_move_copy
        if need_images_folder and not os.path.exists(images_folder):
            os.makedirs(images_folder)

        copied_count = 0
        clipboard_counter = 0

        for item in board.image_items:
            image_path = getattr(item, 'path', None)

            # Handle clipboard images — always consolidated
            if image_path == "clipboard_image":
                # Save pixmap to images_folder
                dn = getattr(item, 'display_name', None)
                if dn:
                    import re
                    stem = re.sub(r'[^\w]', '_', dn.strip())
                    filename = f"{stem}.png"
                    base_filename = filename
                    counter = 1
                    while os.path.exists(os.path.join(images_folder, filename)):
                        filename = f"{stem}_{counter}.png"
                        counter += 1
                else:
                    clipboard_counter += 1
                    filename = f"clipboard_image_{time.strftime('%Y%m%d_%H%M%S')}_{clipboard_counter}.png"
                new_image_path = os.path.join(images_folder, filename)
                try:
                    item.original_pixmap.save(new_image_path, 'PNG')
                    copied_count += 1
                    item.path = new_image_path
                    item.display_name = None
                except Exception as e:
                    print(f"Failed to write clipboard image to {new_image_path}: {e}")
                    new_image_path = None

                rel_path = os.path.join(f"{base_name}_images", filename) if new_image_path else None
                abs_path = new_image_path or ""

            # regular image handling
            else:
                item_action = getattr(item, 'consolidation_action', None)
                # Already inside images_folder — always reuse in place
                norm_image = os.path.normcase(os.path.abspath(image_path))
                if norm_image.startswith(norm_folder):
                    image_filename = os.path.basename(image_path)
                    rel_path = os.path.join(f"{base_name}_images", image_filename)
                    abs_path = image_path
                elif item_action in ('move', 'copy'):
                    image_filename = os.path.basename(image_path)
                    base, ext = os.path.splitext(image_filename)
                    counter = 1
                    new_image_path = os.path.join(images_folder, image_filename)
                    while os.path.exists(new_image_path):
                        image_filename = f"{base}_{counter}{ext}"
                        new_image_path = os.path.join(images_folder, image_filename)
                        counter += 1
                    if item_action == 'copy':
                        shutil.copy2(image_path, new_image_path)
                    else:  # 'move'
                        shutil.move(image_path, new_image_path)
                        item.path = new_image_path
                    copied_count += 1
                    rel_path = os.path.join(f"{base_name}_images", image_filename)
                    abs_path = new_image_path
                else:  # 'leave' or None — store relative path if possible
                    try:
                        rel_path = os.path.relpath(image_path, save_dir)
                    except Exception:
                        rel_path = None
                    abs_path = image_path

            # Add entry for this image
            image_data = {
                "type": "image",
                "path": rel_path if rel_path else abs_path,
                "absolute_path": abs_path,
                "position": [item.pos().x(), item.pos().y()],
                "scale": item.current_scale,
                "z_value": item.zValue(),
                "layer": getattr(item, 'layer', 'rgba'),
                "preview_format": getattr(item, 'preview_format', board.preview_format),
                "exposure": getattr(item, 'exposure', 0.0),
                "gamma": getattr(item, 'gamma', 2.2),
                "tone_mapping": getattr(item, 'tone_mapping', 'reinhard'),
                "colorspace": getattr(item, 'colorspace', 'linear'),
                "is_hdr": getattr(item, 'linear_data', None) is not None,
                "rotation": item.rotation(),
                "display_name": getattr(item, 'display_name', None),
                "consolidation_action": getattr(item, 'consolidation_action', None),
            }
            board_data["items"].append(image_data)

        # Save text items
        for item in board.text_items:
            c = item.text_color
            board_data["items"].append({
                "type": "text",
                "text": item.text_content,
                "font_family": item.font_family,
                "font_size_pt": item.font_size_pt,
                "bold": item.bold,
                "italic": item.italic,
                "color": [c.red(), c.green(), c.blue(), c.alpha()],
                "position": [item.pos().x(), item.pos().y()],
                "scale": item.current_scale,
                "z_value": item.zValue(),
                "rotation": item.rotation(),
            })

        # Save shape items
        for item in board.shape_items:
            sc = item.stroke_color
            fc = item.fill_color
            entry = {
                "type": "shape",
                "shape_type": item.shape_type,
                "stroke_color": [sc.red(), sc.green(), sc.blue(), sc.alpha()],
                "fill_color": [fc.red(), fc.green(), fc.blue(), fc.alpha()] if fc is not None else None,
                "stroke_width": item.stroke_width,
                "position": [item.pos().x(), item.pos().y()],
                "z_value": item.zValue(),
            }
            if item.shape_type in ('line', 'arrow'):
                entry["dx"] = item._dx
                entry["dy"] = item._dy
            else:
                entry["nat_w"] = item._nat_w
                entry["nat_h"] = item._nat_h
                entry["scale"] = item.current_scale
                entry["rotation"] = item.rotation()
            board_data["items"].append(entry)

        # Write JSON
        with open(file_path, 'w') as f:
            json.dump(board_data, f, indent=2)

        board.current_save_path = file_path
        print(f"Reference board saved to: {file_path} (copied {copied_count} files)")

    except Exception as e:
        board.bridge.show_message(f"Save Error: Failed to save reference board:\n{str(e)}")
        print(f"Error saving board: {e}")


def load_board(board: 'CoffeeBoard', path=None) -> None:
    """Load the saved state of a reference board from a JSON file.

    Args:
        board: The CoffeeBoard instance.
        path: Optional path to the JSON file. If None, prompts the user.
    """
    from CoffeeBoard.core.image_item import ImageDisplay
    from CoffeeBoard.core.text_item import TextItem
    from CoffeeBoard.core.shape_item import ShapeItem

    if not path:
        path = board.bridge.get_filename("Load Reference Board", pattern="*.board *.json")

    file_path = path

    if not file_path:
        return

    try:
        # Read the file
        with open(file_path, 'r') as f:
            board_data = json.load(f)

        # Clear existing items
        board.clear_all_images()

        load_dir = os.path.dirname(file_path)
        # Backward compat: old files used "images" key without "type" field
        all_items = board_data.get("items") or board_data.get("images", [])
        total_items = len(all_items)
        missing_images = []
        loaded_count = 0

        # Create progress task
        progress = board.bridge.create_progress("Loading Reference Board")
        progress.setMessage(f"Loading {total_items} items...")

        try:
            for idx, entry in enumerate(all_items):
                if progress.isCancelled():
                    print("Load cancelled by user")
                    break

                progress_percent = int((idx / float(total_items)) * 100) if total_items else 100
                progress.setProgress(progress_percent)
                progress.setMessage(f"Loading item {idx + 1} of {total_items}...")

                item_type = entry.get("type", "image")

                if item_type == "text":
                    try:
                        color_data = entry.get("color", [255, 255, 255, 255])
                        color = QColor(*color_data)
                        text_item = TextItem(
                            text=entry.get("text", ""),
                            font_family=entry.get("font_family", "Arial"),
                            font_size_pt=entry.get("font_size_pt", 24.0),
                            color=color,
                        )
                        board.scene.addItem(text_item)
                        board.text_items.append(text_item)

                        if entry.get("bold", False):
                            text_item.set_bold(True)
                        if entry.get("italic", False):
                            text_item.set_italic(True)

                        pos = entry.get("position", [0, 0])
                        text_item.setPos(pos[0], pos[1])
                        text_item.resize_item(entry.get("scale", 1.0))
                        text_item.setRotation(entry.get("rotation", 0.0))
                        text_item.setZValue(entry.get("z_value", 0))

                        loaded_count += 1
                    except Exception as e:
                        print(f"Failed to restore text item: {e}")

                elif item_type == "shape":
                    try:
                        sc_data = entry.get("stroke_color", [0, 200, 180, 220])
                        stroke_color = QColor(*sc_data)
                        fc_data = entry.get("fill_color")
                        fill_color = QColor(*fc_data) if fc_data is not None else None
                        shape_type = entry.get("shape_type", "rect")
                        if shape_type in ('line', 'arrow'):
                            # Backward compat: old files may have nat_w/nat_h instead of dx/dy
                            shape_item = ShapeItem(
                                shape_type=shape_type,
                                dx=entry.get("dx", entry.get("nat_w", 100.0)),
                                dy=entry.get("dy", entry.get("nat_h", 0.0)),
                                stroke_color=stroke_color,
                                fill_color=fill_color,
                                stroke_width=entry.get("stroke_width", 2.0),
                            )
                            pos = entry.get("position", [0, 0])
                            shape_item.setPos(pos[0], pos[1])
                        else:
                            shape_item = ShapeItem(
                                shape_type=shape_type,
                                nat_w=entry.get("nat_w", 100.0),
                                nat_h=entry.get("nat_h", 80.0),
                                stroke_color=stroke_color,
                                fill_color=fill_color,
                                stroke_width=entry.get("stroke_width", 2.0),
                            )
                            pos = entry.get("position", [0, 0])
                            shape_item.setPos(pos[0], pos[1])
                            shape_item.resize_item(entry.get("scale", 1.0))
                            shape_item.setRotation(entry.get("rotation", 0.0))
                        board.scene.addItem(shape_item)
                        board.shape_items.append(shape_item)
                        shape_item.setZValue(entry.get("z_value", 0))

                        loaded_count += 1
                    except Exception as e:
                        print(f"Failed to restore shape item: {e}")

                else:  # "image" (including old entries without "type")
                    # Try relative path first, then absolute
                    image_path = None
                    rel_path = entry.get("path")
                    abs_path = entry.get("absolute_path")

                    if rel_path:
                        test_path = os.path.join(load_dir, rel_path)
                        if os.path.exists(test_path):
                            image_path = test_path

                    if not image_path and abs_path and os.path.exists(abs_path):
                        image_path = abs_path

                    if image_path:
                        try:
                            layer = entry.get("layer", "rgba")
                            preview_format = entry.get("preview_format", board.preview_format)

                            image_item = ImageDisplay(image_path, layer, preview_format)
                            board.scene.addItem(image_item)
                            board.image_items.append(image_item)

                            pos = entry.get("position", [0, 0])
                            image_item.setPos(pos[0], pos[1])
                            image_item.resize_image(entry.get("scale", 1.0))
                            image_item.setRotation(entry.get('rotation', 0.0))
                            image_item.setZValue(entry.get("z_value", 0))

                            image_item.display_name = entry.get('display_name')
                            image_item.consolidation_action = entry.get('consolidation_action')

                            image_item.colorspace   = entry.get('colorspace',   image_item.colorspace)
                            image_item.exposure     = entry.get('exposure',     image_item.exposure)
                            image_item.gamma        = entry.get('gamma',        image_item.gamma)
                            image_item.tone_mapping = entry.get('tone_mapping', image_item.tone_mapping)
                            if image_item.linear_data is not None:
                                image_item._update_display_transform()

                            loaded_count += 1

                        except Exception as e:
                            print(f"Failed to load {image_path}: {e}")
                            missing_images.append(f"{rel_path or abs_path} (Error: {str(e)})")
                    else:
                        missing_images.append(rel_path or abs_path)

            progress.setProgress(100)

        finally:
            del progress

        # Update scene rect
        if board.image_items or board.text_items or board.shape_items:
            items_rect = board.scene.itemsBoundingRect()
            padded_rect = items_rect.adjusted(-50, -50, 50, 50)
            board.scene.setSceneRect(padded_rect)

        board.current_save_path = file_path

        if missing_images:
            message = f"Warning: {len(missing_images)} images could not be found:\n"
            message += "\n".join(missing_images[:5])
            if len(missing_images) > 5:
                message += f"\n... and {len(missing_images) - 5} more"
            board.bridge.show_message(message)

        if hasattr(board, '_item_list_panel'):
            board._item_list_panel.refresh()

        # Defer fit to next event-loop iteration so Qt has processed all
        # pending geometry/paint events before computing fitInView.
        QTimer.singleShot(0, board.fit_all_to_view)

        print(f"Reference board loaded from: {file_path}")
        print(f"Loaded: {loaded_count}, Missing: {len(missing_images)}")

    except Exception as e:
        board.bridge.show_message(f"Failed to load reference board:\n{str(e)}")
        print(f"Error loading board: {e}")


def _prompt_file_consolidation_choice(board: 'CoffeeBoard', n_files: int):
    """Prompt user on how to handle file-based images during save.

    Returns:
        'move' | 'copy' | 'leave' | 'per_image' | None (cancel)
    """
    msg = QMessageBox(board)
    msg.setWindowTitle("File Images on Board")
    msg.setText(
        f"You have {n_files} file-based image(s) on this board.\n"
        "How would you like to handle them?"
    )
    msg.setIcon(QMessageBox.Question)

    btn_move  = msg.addButton("Move",       QMessageBox.AcceptRole)
    btn_copy  = msg.addButton("Copy",       QMessageBox.AcceptRole)
    btn_leave = msg.addButton("Leave",      QMessageBox.AcceptRole)
    btn_per   = msg.addButton("Per Image…", QMessageBox.AcceptRole)
    msg.setStandardButtons(QMessageBox.Cancel)
    msg.setDefaultButton(btn_copy)
    getattr(msg, 'exec_', msg.exec)()

    clicked = msg.clickedButton()
    if clicked == btn_move:  return 'move'
    if clicked == btn_copy:  return 'copy'
    if clicked == btn_leave: return 'leave'
    if clicked == btn_per:   return 'per_image'
    return None


class _PerImageConsolidationDialog(QDialog):
    """Dialog for setting a consolidation action per image."""

    _ACTION_OPTIONS = ['Copy', 'Move', 'Leave']
    _ACTION_MAP = {'Copy': 'copy', 'Move': 'move', 'Leave': 'leave'}
    _ACTION_MAP_INV = {'copy': 'Copy', 'move': 'Move', 'leave': 'Leave'}

    def __init__(self, parent, items: list) -> None:
        super().__init__(parent)
        self.setWindowTitle("Per-Image Consolidation")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet("""
            QDialog {
                background: rgba(30, 30, 30, 255);
                color: #e0e0e0;
            }
            QLabel {
                color: #e0e0e0;
            }
            QComboBox {
                background: rgba(50, 50, 50, 255);
                color: #e0e0e0;
                border: 1px solid rgba(0, 200, 180, 160);
                padding: 2px 6px;
            }
            QComboBox QAbstractItemView {
                background: rgba(40, 40, 40, 255);
                color: #e0e0e0;
                selection-background-color: rgba(0, 200, 180, 120);
            }
            QPushButton {
                background: rgba(50, 50, 50, 255);
                color: #e0e0e0;
                border: 1px solid rgba(0, 200, 180, 160);
                padding: 4px 16px;
            }
            QPushButton:hover {
                background: rgba(0, 200, 180, 80);
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
            QWidget#scroll_contents {
                background: transparent;
            }
        """)

        self._items = items
        self._combos: list = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Set an action for each image:"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        contents.setObjectName("scroll_contents")
        rows_layout = QVBoxLayout(contents)
        rows_layout.setSpacing(4)

        for item in items:
            row = QHBoxLayout()
            name = os.path.basename(str(item.path))
            if len(name) > 45:
                name = name[:21] + '…' + name[-21:]
            lbl = QLabel(name)
            lbl.setFixedWidth(300)
            combo = QComboBox()
            combo.addItems(self._ACTION_OPTIONS)
            saved = getattr(item, 'consolidation_action', None)
            if saved and saved in self._ACTION_MAP_INV:
                combo.setCurrentText(self._ACTION_MAP_INV[saved])
            else:
                combo.setCurrentText('Copy')
            row.addWidget(lbl)
            row.addWidget(combo)
            rows_layout.addLayout(row)
            self._combos.append(combo)

        rows_layout.addStretch()
        scroll.setWidget(contents)
        layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def run(self):
        """Show dialog and return {item: action_str} dict, or None if cancelled."""
        result = getattr(self, 'exec_', self.exec)()
        accepted = result == QDialog.Accepted
        if not accepted:
            return None
        return {
            item: self._ACTION_MAP[combo.currentText()]
            for item, combo in zip(self._items, self._combos)
        }
