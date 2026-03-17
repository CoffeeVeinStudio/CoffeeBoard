'''
CoffeeBoard dependency installer.
Run with the Python interpreter of each DCC you want to support.

Examples:
    "C:/Program Files/Nuke14.0v4/python.exe" install.py
    "C:/Program Files/Nuke15.2v5/python.exe" install.py
    "C:/Program Files/Houdini 20.5.332/bin/hython.exe" install.py
    python install.py  (standalone)
'''

import sys
import os
import subprocess


def detect_dcc():
    exe = sys.executable.lower().replace('\\', '/')
    if 'nuke' in exe:
        return 'nuke'
    if 'houdini' in exe or 'hython' in exe:
        return 'houdini'
    return 'standalone'


# Packages bundled by each DCC — skip these to avoid conflicts.
BUNDLED = {
    'nuke':       set(),
    'houdini':    {'numpy'},
    'standalone': set(),
}

ALL_PACKAGES = [
    "numpy>=1.24,<2",
]

dcc = detect_dcc()
bundled = BUNDLED[dcc]
packages = [p for p in ALL_PACKAGES if not any(b in p for b in bundled)]

py_ver = f"cp3{sys.version_info.minor}"
target = os.path.join(os.path.dirname(__file__), "vendor", py_ver)

print(f"Detected DCC : {dcc}")
print(f"Python       : {sys.version}")
print(f"Install dir  : {target}")

if not packages:
    print("Nothing to install — all dependencies are bundled by this DCC.")
    sys.exit(0)

os.makedirs(target, exist_ok=True)
print(f"Installing   : {', '.join(packages)}\n")

subprocess.check_call([
    sys.executable, "-m", "pip", "install",
    *packages,
    "--target", target,
])

print("\nDone.")
