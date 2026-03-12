"""Platform abstraction layer for multi-DCC deployment."""

import sys
from typing import Optional, Callable, Any


def _import_qt():
    """Import Qt modules with PySide2/PySide6 compatibility.

    Nuke 15 bundles PySide2, Nuke 16+ bundles PySide6.
    Standalone installs may have either.
    """
    try:
        from PySide2 import QtWidgets, QtCore
    except ImportError:
        from PySide6 import QtWidgets, QtCore

    # Ensure QApplication exists (DCCs provide one, standalone does not)
    if QtWidgets.QApplication.instance() is None:
        QtWidgets.QApplication(sys.argv)

    return QtWidgets, QtCore


class PlatformBridge:
    """Handles platform-specific functionality with fallbacks."""

    def __init__(self):
        self.platform = self._detect_platform()
        self._init_platform_functions()

    def _detect_platform(self) -> str:
        """Detect which DCC we're running in."""
        if 'nuke' in sys.modules:
            return 'nuke'
        elif 'hou' in sys.modules:
            return 'houdini'
        elif 'maya.cmds' in sys.modules:
            return 'maya'
        else:
            return 'standalone'

    def _init_platform_functions(self):
        """Initialize platform-specific functions."""
        if self.platform == 'nuke':
            import nuke
            self.show_message = nuke.message
            self.get_filename = nuke.getFilename
            self.create_progress = lambda title: nuke.ProgressTask(title)
            self.has_native_exr = True
        elif self.platform == 'houdini':
            import hou
            # Qt dialogs work in Houdini (it ships PySide2/Qt). Native hou.ui calls are
            # possible but not required — left as TODO for future improvement.
            self.show_message = self._qt_message_box
            self.get_filename = self._qt_file_dialog
            self.create_progress = self._qt_progress_dialog
            self.has_native_exr = False
        else:
            # Fallbacks for standalone
            self.show_message = self._qt_message_box
            self.get_filename = self._qt_file_dialog
            self.create_progress = self._qt_progress_dialog
            self.has_native_exr = False

        # Check HDR EXR support (openexr + imath, VFX Platform compatible)
        try:
            import OpenEXR
            self.has_oiio = True
        except ImportError:
            self.has_oiio = False

    def _qt_message_box(self, message: str) -> None:
        """Qt fallback for message dialogs."""
        QtWidgets, _ = _import_qt()
        box = QtWidgets.QMessageBox()
        box.setText(message)
        getattr(box, 'exec_', box.exec)()

    def _qt_file_dialog(self, title: str, pattern: str = "*.*",
                       type: str = 'open') -> Optional[str]:
        """Qt fallback for file dialogs."""
        QtWidgets, _ = _import_qt()
        if type == 'open':
            path, _ = QtWidgets.QFileDialog.getOpenFileName(None, title, "", pattern)
        else:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(None, title, "", pattern)
        return path if path else None

    def _qt_progress_dialog(self, title: str):
        """Qt fallback for progress dialogs — returns a wrapper matching Nuke's ProgressTask API."""
        QtWidgets, QtCore = _import_qt()
        dlg = QtWidgets.QProgressDialog(title, "Cancel", 0, 100)
        dlg.setWindowModality(QtCore.Qt.WindowModal)
        dlg.setMinimumDuration(0)
        class _Wrapper:
            def setMessage(self, msg): dlg.setLabelText(msg)
            def setProgress(self, n):  dlg.setValue(n)
            def isCancelled(self):     return dlg.wasCanceled()
            def __del__(self):         dlg.close()
        return _Wrapper()

    def check_dependencies(self) -> list:
        """Check for optional dependencies."""
        missing = []

        try:
            import OpenEXR
        except ImportError:
            missing.append({
                'name': 'OpenEXR',
                'install': 'pip install openexr imath',
                'impact': 'HDR/EXR support limited to 8-bit'
            })

        try:
            import numpy
        except ImportError:
            missing.append({
                'name': 'NumPy',
                'install': 'pip install numpy',
                'impact': 'Tone mapping unavailable'
            })

        return missing


# Global singleton
_bridge = None

def get_bridge() -> PlatformBridge:
    """Get or create the platform bridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = PlatformBridge()
    return _bridge


def show_dependency_warnings(bridge: PlatformBridge):
    """Show warnings for missing dependencies on startup."""
    missing = bridge.check_dependencies()
    if missing:
        msg = "Optional dependencies missing:\n\n"
        for dep in missing:
            msg += f"• {dep['name']}\n"
            msg += f"  Install: {dep['install']}\n"
            msg += f"  Impact: {dep['impact']}\n\n"
        msg += "CoffeeBoard will work but with reduced functionality."
        bridge.show_message(msg)
