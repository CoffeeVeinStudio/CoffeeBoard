'''
CoffeeBoard dependency installer.
Run with the Python interpreter of each DCC you want to support.

Example:
    "C:/Program Files/Nuke14.0v4/python.exe" install.py
    "C:/Program Files/Nuke15.2v5/python.exe" install.py
'''

import sys
import os
import subprocess

PACKAGES = [
    "numpy>=1.24,<2",
    # openexr och imath installeras separat via Nukes python.exe vid behov
]

py_ver = f"cp3{sys.version_info.minor}"
target = os.path.join(os.path.dirname(__file__), "vendor", py_ver)
os.makedirs(target, exist_ok=True)

print(f"Installing for Python {sys.version} into {target}")

subprocess.check_call([
    sys.executable, "-m", "pip", "install",
    *PACKAGES,
    "--target", target
])

print("Done.")
