"""
Doctor module — diagnostic checks for system health.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
import importlib.util

from rich.text import Text
from myagent.ui import C_OK, C_WARN, C_ERR, C_DIM

def run_diagnostics() -> list[tuple[str, str, str]]:
    """Runs all health checks and returns a list of (category, status_icon, message)."""
    results = []
    
    # 1. Python Environment
    results.append(("Sistem", *check_python()))
    results.append(("Sistem", *check_venv()))
    
    # 2. API Keys
    results.extend([("API", *res) for res in check_api_keys()])
    
    # 3. CLI Tools
    results.extend([("Araçlar", *res) for res in check_cli_tools()])
    
    # 4. Core Packages
    results.extend([("Paketler", *res) for res in check_packages()])
    
    # 5. Infrastructure
    results.append(("Altyapı", *check_docker()))
    
    return results

def check_python() -> tuple[str, str]:
    ver = sys.version_info
    v_str = f"{ver.major}.{ver.minor}.{ver.micro}"
    if ver.major >= 3 and ver.minor >= 10:
        return "✓", f"Python {v_str}"
    return "✗", f"Python {v_str} (3.10+ önerilir)"

def check_venv() -> tuple[str, str]:
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        return "✓", "Sanal ortam (venv) aktif"
    return "!", "Sanal ortam (venv) aktif değil"

def check_api_keys() -> list[tuple[str, str]]:
    claude = os.environ.get("ANTHROPIC_API_KEY")
    gemini = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    
    res = []
    if claude:
        res.append(("✓", f"Claude API Key: {claude[:8]}...{claude[-4:]}"))
    else:
        res.append(("!", "Claude API Key bulunamadı (Claude Code modunda gerekmez)"))
        
    if gemini:
        res.append(("✓", f"Gemini API Key: {gemini[:8]}...{gemini[-4:]}"))
    else:
        res.append(("✗", "Gemini API Key bulunamadı (Google AI Studio'dan alabilirsiniz)"))
        
    return res

def check_cli_tools() -> list[tuple[str, str]]:
    tools = [
        ("claude", "Claude Code CLI"),
        ("gemini", "Gemini CLI"),
        ("ruff",   "Ruff Linter"),
        ("pytest", "Pytest"),
    ]
    res = []
    for cmd, name in tools:
        if shutil.which(cmd):
            res.append(("✓", f"{name} yüklü"))
        else:
            res.append(("!", f"{name} bulunamadı"))
    return res

def check_packages() -> list[tuple[str, str]]:
    pkgs = [
        ("textual", "Textual TUI"),
        ("rich", "Rich Terminal"),
        ("google.generativeai", "Gemini SDK"),
        ("anthropic", "Claude SDK"),
    ]
    res = []
    for mod_name, name in pkgs:
        spec = importlib.util.find_spec(mod_name)
        if spec:
            res.append(("✓", f"{name} paketi hazır"))
        else:
            res.append(("✗", f"{name} paketi eksik"))
    return res

def check_docker() -> tuple[str, str]:
    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "ps"], capture_output=True, timeout=2)
            return "✓", "Docker çalışıyor ve erişilebilir"
        except Exception:
            return "!", "Docker yüklü ama çalışmıyor"
    return "dim content", "Docker bulunamadı (Sandbox modu için gerekir)"
