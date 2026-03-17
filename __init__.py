import sys
from pathlib import Path

# --- Vendor path (always inject first, before any import attempt) ---
_py_ver = f"cp3{sys.version_info.minor}"
_vendor = Path(__file__).parent / 'vendor' / _py_ver
if _vendor.exists():
    _vp = str(_vendor)
    if _vp not in sys.path:
        sys.path.insert(0, _vp)

# Add bundled _libs/ to sys.path so OpenImageIO can be imported without
# any user-level installation.
_libs = Path(__file__).parent / '_libs'
if _libs.exists():
    p = str(_libs)
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import OpenEXR
    version = getattr(OpenEXR, 'OPENEXR_VERSION', getattr(OpenEXR, '__version__', '?'))
    print(f"[CoffeeBoard] OpenEXR {version} loaded — all EXR compression types supported")
except ImportError:
    pass  # Pure-Python fallback handles ZIP/uncompressed EXR silently.


# --- numpy auto-discovery ---
# Nuke's Python may not include numpy. Try to find it in the system Python that
# matches Nuke's Python version (major.minor must match for binary extensions).
try:
    import numpy  # noqa: fast path — already available
except ImportError:
    # --- Auto-discovery (subprocess) ---
    _found = False
    try:
        import subprocess, os
        _ver = f'{sys.version_info.major}.{sys.version_info.minor}'
        # Try 'py -3.X' (Windows Launcher), then 'python', then 'python3'
        for _cmd in (['py', f'-{_ver}'], ['python'], ['python3']):
            try:
                _r = subprocess.run(
                    _cmd + [
                        '-c',
                        'import sys, numpy, os; '
                        f'assert sys.version_info[:2] == ({sys.version_info.major}, {sys.version_info.minor}); '
                        'print(os.path.dirname(os.path.dirname(numpy.__file__)))'
                    ],
                    capture_output=True, text=True, timeout=3
                )
                if _r.returncode == 0:
                    _sp = _r.stdout.strip()
                    if _sp and os.path.isdir(_sp) and _sp not in sys.path:
                        sys.path.insert(0, _sp)
                        try:
                            import numpy  # noqa
                            print(f'[CoffeeBoard] numpy auto-detected ({_sp})')
                            _found = True
                            break
                        except ImportError:
                            sys.path.remove(_sp)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
    except Exception:
        pass
    if not _found:
        print(f'[CoffeeBoard] numpy not found — run install.py with this Python to enable HDR controls')
