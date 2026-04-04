"""
Dependency Manager — AST-based import scanner + optional auto-install.

Strategy:
  1. Parse all .py files with ast to extract top-level imports.
  2. Filter out stdlib and already-installed packages.
  3. In interactive mode: ask user (y/n) per missing package.
     In auto mode (--auto-deps): install without asking.
  4. Install via `uv pip install <package>` (falls back to pip if uv absent).

Import-to-package name mapping covers the most common mismatches
(e.g. "import cv2" → "opencv-python"). Unknown packages are tried as-is.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

from myagent.config.settings import WORK_DIR

# ---------------------------------------------------------------------------
# Common import-name → pip-package-name mismatches
# ---------------------------------------------------------------------------
_IMPORT_TO_PIP: dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "bs4": "beautifulsoup4",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "google.cloud": "google-cloud",
    "attr": "attrs",
    "Crypto": "pycryptodome",
    "jwt": "PyJWT",
    "magic": "python-magic",
    "usb": "pyusb",
    "serial": "pyserial",
    "gi": "PyGObject",
    "wx": "wxPython",
    "gtk": "PyGTK",
}

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scan_and_install(
    py_files: list[str],
    auto: bool = False,
    verbose: bool = False,
    ui=None,
) -> list[str]:
    """Scan py_files for missing third-party imports and optionally install them.

    Returns list of package names that were installed (or approved for install).
    """
    if not py_files:
        return []

    imports = _collect_imports(py_files)
    missing = _find_missing(imports)

    if not missing:
        return []

    if ui:
        ui.dep_found(missing)
    else:
        print(f"  [deps] eksik: {', '.join(missing)}", flush=True)

    to_install: list[str] = []
    for pkg in missing:
        pip_name = _IMPORT_TO_PIP.get(pkg, pkg)
        if auto:
            to_install.append(pip_name)
        else:
            try:
                answer = input(f"  '{pip_name}' kurulsun mu? (y/n): ").strip().lower()
            except EOFError:
                answer = "n"
            if answer in ("y", "yes", "e", "evet"):
                to_install.append(pip_name)
            else:
                if ui:
                    ui.dep_skipped(pip_name)

    installed: list[str] = []
    for pip_name in to_install:
        ok = _install(pip_name, verbose=verbose)
        if ok:
            installed.append(pip_name)
            if ui:
                ui.dep_installed(pip_name)
        else:
            if ui:
                ui.dep_error(pip_name, "kurulum başarısız")

    return installed


# ---------------------------------------------------------------------------
# Import collector
# ---------------------------------------------------------------------------

def _collect_imports(py_files: list[str]) -> set[str]:
    """Return top-level module names imported in the given files."""
    # Local modules: any .py file in WORK_DIR — don't try to pip-install these
    local_modules = {Path(f).stem for f in py_files}
    local_modules |= {p.stem for p in WORK_DIR.glob("*.py")}

    names: set[str] = set()
    for fname in py_files:
        path = (WORK_DIR / fname).resolve()
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if mod not in local_modules:
                        names.add(mod)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:   # absolute import only
                    mod = node.module.split(".")[0]
                    if mod not in local_modules:
                        names.add(mod)
    return names


# ---------------------------------------------------------------------------
# Missing package detector
# ---------------------------------------------------------------------------

def _find_missing(imports: set[str]) -> list[str]:
    """Return import names that are not stdlib and not importable."""
    stdlib = sys.stdlib_module_names   # Python 3.10+
    missing: list[str] = []
    for name in sorted(imports):
        if not name or name.startswith("_"):
            continue
        if name in stdlib:
            continue
        spec = importlib.util.find_spec(name)
        if spec is None:
            missing.append(name)
    return missing


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------

def _install(pip_name: str, verbose: bool = False) -> bool:
    """Install pip_name with uv (fallback: pip). Returns True on success."""
    import os
    # In Docker (no venv) uv needs --system; on host with venv it's not needed
    in_docker = os.environ.get("MYAGENT_DOCKER", "") == "1"
    uv_cmd = ["uv", "pip", "install", "--system"] if in_docker else ["uv", "pip", "install"]
    # Prefer uv for speed
    for installer in (uv_cmd, ["pip", "install"]):
        cmd = installer + [pip_name]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                print(f"  [deps] '{pip_name}' kuruldu.", flush=True)
                if verbose and result.stdout.strip():
                    print(f"  {result.stdout.strip()}", flush=True)
                return True
            # uv not found → try pip next iteration
            if "No such file" in result.stderr or result.returncode == 127:
                continue
            print(f"  [deps] '{pip_name}' kurulum hatası: {result.stderr.strip()[:200]}", flush=True)
            return False
        except FileNotFoundError:
            continue   # uv not installed, try pip
        except subprocess.TimeoutExpired:
            print(f"  [deps] '{pip_name}' kurulum zaman aşımı.", flush=True)
            return False
    print(f"  [deps] uv ve pip bulunamadı — '{pip_name}' kurulamadı.", flush=True)
    return False
