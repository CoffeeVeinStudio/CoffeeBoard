"""One-time setup script: installs coffeeboard.pypanel into every Houdini version
found in the user's preferences directory.

Run with any Python interpreter — Houdini does not need to be running:
    python setup_houdini.py
"""
from pathlib import Path
import re

COFFEEBOARD_PARENT = Path(__file__).parent.parent  # parent of the CoffeeBoard/ folder

PYPANEL_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<pythonPanelDocument>
  <interface name="CoffeeBoard" label="Coffee Board" icon="MISC_python" showNetworkNavigationBar="false" help_url="">
    <script><![CDATA[
import sys
_cb_path = '{cb_path}'
if _cb_path not in sys.path:
    sys.path.insert(0, _cb_path)

def onCreateInterface():
    from CoffeeBoard.adapters.houdini_adapter import onCreateInterface as _fn
    return _fn()
    ]]></script>
    <includeInToolbarMenu menu_position="0" create_separator="false"/>
    <help><![CDATA[CoffeeBoard — VFX reference board. Drop images, annotate with text and shapes.]]></help>
  </interface>
</pythonPanelDocument>
"""


def _find_houdini_pref_dirs():
    """Return all houdiniX.Y preference directories found on this machine."""
    candidates = []
    home = Path.home()
    # Windows: ~/Documents/houdiniX.Y  and  ~/houdiniX.Y
    search_roots = [home / "Documents", home]
    pattern = re.compile(r"^houdini\d+\.\d+$", re.IGNORECASE)
    for root in search_roots:
        if not root.exists():
            continue
        for entry in root.iterdir():
            if entry.is_dir() and pattern.match(entry.name):
                candidates.append(entry)
    return candidates


def main():
    pref_dirs = _find_houdini_pref_dirs()
    if not pref_dirs:
        print("No Houdini preference directories found.")
        print("Expected locations: ~/Documents/houdiniX.Y  or  ~/houdiniX.Y")
        return

    cb_path = Path(__file__).resolve().parent.parent.as_posix()
    pypanel_content = PYPANEL_TEMPLATE.format(cb_path=cb_path)

    for pref_dir in pref_dirs:
        panels_dir = pref_dir / "python_panels"
        panels_dir.mkdir(exist_ok=True)
        dest = panels_dir / "coffeeboard.pypanel"
        dest.write_text(pypanel_content, encoding="utf-8")
        print(f"Installed: {dest}")

    print("\nDone. Restart Houdini, then open via:")
    print("  Pane tab menu (+) → Python Panel → Coffee Board")


if __name__ == "__main__":
    main()
