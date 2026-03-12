import sys
import json
import pathlib
from functools import partial

try:
    from PySide2.QtGui import QPalette, QColor
    from PySide2.QtWidgets import QApplication, QMainWindow, QAction
except ImportError:
    from PySide6.QtGui import QPalette, QColor, QAction
    from PySide6.QtWidgets import QApplication, QMainWindow

from CoffeeBoard.core.canvas import CoffeeBoard


_PREFS_PATH = pathlib.Path.home() / ".coffeeboard" / "prefs.json"


def _load_theme() -> str:
    try:
        return json.loads(_PREFS_PATH.read_text()).get("theme", "dark")
    except Exception:
        return "dark"


def _save_theme(theme: str) -> None:
    try:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PREFS_PATH.write_text(json.dumps({"theme": theme}))
    except Exception:
        pass


def _apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")  # Fusion fully respects QPalette on all platforms
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(45, 45, 45))
    palette.setColor(QPalette.WindowText,      QColor(210, 210, 210))
    palette.setColor(QPalette.Base,            QColor(35, 35, 35))
    palette.setColor(QPalette.AlternateBase,   QColor(50, 50, 50))
    palette.setColor(QPalette.ToolTipBase,     QColor(35, 35, 35))
    palette.setColor(QPalette.ToolTipText,     QColor(210, 210, 210))
    palette.setColor(QPalette.Text,            QColor(210, 210, 210))
    palette.setColor(QPalette.Button,          QColor(50, 50, 50))
    palette.setColor(QPalette.ButtonText,      QColor(210, 210, 210))
    palette.setColor(QPalette.BrightText,      QColor(255, 255, 255))
    palette.setColor(QPalette.Highlight,       QColor(0, 180, 160))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.Link,            QColor(0, 200, 180))
    app.setPalette(palette)
    app.setStyleSheet(
        "QMenu { background: #2d2d2d; color: #d2d2d2; border: 1px solid #555; }"
        "QMenu::item:selected { background: #008c78; }"
        "QMenu::separator { height: 1px; background: #555; margin: 2px 4px; }"
        "QToolTip { background: #2d2d2d; color: #d2d2d2; border: 1px solid #555; }"
    )


def _apply_light_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(QPalette())
    app.setStyleSheet("")


def _apply_system_theme(app: QApplication) -> None:
    app.setStyle("")
    app.setPalette(QPalette())
    app.setStyleSheet("")


class CoffeeBoardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CoffeeBoard")
        self.canvas = CoffeeBoard(parent=self)
        self.setCentralWidget(self.canvas)

        # Build View → Theme submenu with exclusive radio actions
        view_menu = self.menuBar().addMenu("View")
        theme_menu = view_menu.addMenu("Theme")
        self._theme_actions = {}
        for name, label in [("dark", "Dark"), ("light", "Light"), ("system", "System")]:
            act = QAction(label, self, checkable=True)
            act.triggered.connect(partial(self._set_theme, name))
            theme_menu.addAction(act)
            self._theme_actions[name] = act

        # Apply saved theme
        saved = _load_theme()
        self._set_theme(saved, save=False)

    def _set_theme(self, name: str, save: bool = True) -> None:
        app = QApplication.instance()
        {"dark": _apply_dark_theme, "light": _apply_light_theme,
         "system": _apply_system_theme}[name](app)
        self.canvas.set_background_for_theme(name)
        for n, act in self._theme_actions.items():
            act.setChecked(n == name)
        if save:
            _save_theme(name)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    window = CoffeeBoardWindow()
    window.resize(1280, 800)
    window.show()
    sys.exit(getattr(app, 'exec_', app.exec)())
