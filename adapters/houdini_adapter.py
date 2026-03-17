"""Houdini adapter for CoffeeBoard.

Registration options:
  - Dockable panel tab: run setup_houdini.py once; panel appears in Pane tab menu.
  - Floating window:    call launch() from $HOUDINI_PATH/scripts/456.py or a shelf tool.

Tested with Houdini Apprentice (free). Should work on any H19+.
"""
try:
    import hou
except ImportError:
    raise ImportError("This adapter requires Houdini")

import sys
from pathlib import Path

_tools = str(Path(__file__).resolve().parents[2])
if _tools not in sys.path:
    sys.path.insert(0, _tools)


def launch():
    """Create and show CoffeeBoard as a floating Houdini window."""
    from CoffeeBoard.core.canvas import CoffeeBoard
    try:
        from PySide2.QtWidgets import QApplication
    except ImportError:
        from PySide6.QtWidgets import QApplication

    try:
        from PySide2.QtCore import Qt
    except ImportError:
        from PySide6.QtCore import Qt

    board = CoffeeBoard(parent=hou.qt.mainWindow())
    board.setWindowFlags(Qt.Window)
    board.setWindowTitle("CoffeeBoard")
    board.resize(1280, 800)
    board.show()
    return board  # caller must keep a reference to prevent GC


def onCreateInterface():
    """Called by Houdini's Python Panel system to create the dockable panel widget."""
    from CoffeeBoard.core.canvas import CoffeeBoard
    return CoffeeBoard()
