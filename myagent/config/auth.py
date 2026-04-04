"""
Auth mode detection, model selection, and runtime configuration management.

Each model (Claude, Gemini) has:
  - An auth mode:  api  (API key)  |  cli  (OAuth via installed CLI)
  - A model ID:    e.g. "claude-opus-4-6" or "gemini-2.5-flash"

Config is persisted at ~/.myagent/config.json.

Runtime overrides (from CLI flags) take precedence over the persisted config,
which takes precedence over defaults.  Layered lookup order:
  CLI flag  >  ~/.myagent/config.json  >  hardcoded default
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

AuthMode = Literal["api", "cli", "claude"]

API: AuthMode = "api"
CLI: AuthMode = "cli"
CLAUDE_WORKER: AuthMode = "claude"   # worker uses claude CLI instead of gemini

CONFIG_PATH: Path = Path.home() / ".myagent" / "config.json"

# Module-level runtime overrides — populated by apply_overrides() from CLI args
_overrides: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Runtime override (CLI flags)
# ---------------------------------------------------------------------------

def apply_overrides(**kwargs: str | None) -> None:
    """Apply runtime overrides from CLI flags (non-None values only)."""
    for key, val in kwargs.items():
        if val is not None:
            _overrides[key] = val


def get_overrides() -> dict[str, str]:
    return dict(_overrides)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_claude() -> list[AuthMode]:
    """Return available auth modes for Claude (may be empty, one, or both)."""
    modes: list[AuthMode] = []
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        modes.append(API)
    if _claude_cli_ready():
        modes.append(CLI)
    return modes


def detect_gemini() -> list[AuthMode]:
    """Return available worker backends.

    "api"    — fast (~2s/call), requires GEMINI_API_KEY
    "cli"    — SLOW (~40s/call), gemini CLI Node.js overhead
    "claude" — fast (~5s/call), uses claude CLI as worker backend
    """
    modes: list[AuthMode] = []
    if (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
    ):
        modes.append(API)
    if _gemini_cli_ready():
        modes.append(CLI)
    if _claude_cli_ready():
        modes.append(CLAUDE_WORKER)
    return modes


def _claude_cli_ready() -> bool:
    if not shutil.which("claude"):
        return False
    if not (Path.home() / ".claude").exists():
        return False
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _gemini_cli_ready() -> bool:
    if not shutil.which("gemini"):
        return False
    if not (Path.home() / ".gemini").exists():
        return False
    try:
        r = subprocess.run(["gemini", "--version"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(config: dict) -> None:
    """Merge *config* into the existing config file (preserves unrelated keys)."""
    existing = load_config()
    existing.update(config)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def is_configured() -> bool:
    return CONFIG_PATH.exists() and bool(load_config())


# ---------------------------------------------------------------------------
# Getters  (override > config > default)
# ---------------------------------------------------------------------------

def get_claude_mode() -> AuthMode:
    # Env var override (e.g. MYAGENT_CLAUDE_MODE=cli set by Docker or shell)
    env = os.environ.get("MYAGENT_CLAUDE_MODE", "").strip()
    return (_overrides.get("claude_mode") or env or load_config().get("claude_mode", CLI)) or CLI  # type: ignore[return-value]


def get_gemini_mode() -> AuthMode:
    # Env var override — Docker sets MYAGENT_GEMINI_MODE=api (OAuth can't open browser)
    env = os.environ.get("MYAGENT_GEMINI_MODE", "").strip()
    return (_overrides.get("gemini_mode") or env or load_config().get("gemini_mode", CLI)) or CLI  # type: ignore[return-value]


def get_claude_model() -> str:
    from myagent.models import CLAUDE_DEFAULT, resolve_model
    raw = (
        _overrides.get("claude_model")
        or load_config().get("claude_model", CLAUDE_DEFAULT)
    )
    return resolve_model(raw, "claude")


def get_gemini_model() -> str:
    from myagent.models import GEMINI_DEFAULT, resolve_model
    raw = (
        _overrides.get("gemini_model")
        or load_config().get("gemini_model", GEMINI_DEFAULT)
    )
    return resolve_model(raw, "gemini")
