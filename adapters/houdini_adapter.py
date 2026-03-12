"""Houdini adapter for CoffeeBoard.

Registration: call launch() from $HOUDINI_PATH/scripts/456.py or a shelf tool.

Tested with Houdini Apprentice (free). Should work on any H19+.
TODO: Replace Qt fallbacks with native hou.ui calls for better integration.
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

    board = CoffeeBoard(parent=hou.qt.mainWindow())
    board.setWindowTitle("CoffeeBoard")
    board.resize(1280, 800)
    board.show()
    return board  # caller must keep a reference to prevent GC

# TODO: Embed as a Python Panel pane tab instead of a floating window.
# See Houdini docs: "Python Panels" > registerFloatingPaneTabType()
