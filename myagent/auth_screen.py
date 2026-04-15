"""
AuthScreen — Textual full-screen auth & mode configuration.

Supports:
  Claude planner : API key  |  Claude Code CLI (OAuth, subscription)
  Gemini worker  : API key  |  Claude Code (worker)  |  Gemini CLI
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, RadioButton, RadioSet, Static

from myagent.config.auth import (
    API, CLI, CLAUDE_WORKER,
    detect_claude, detect_gemini,
    load_config, save_config,
)
from myagent.ui import C_CLAUDE, C_DIM, C_ERR, C_GEMINI, C_OK, C_WARN

ENV_FILE = Path.home() / ".myagent" / ".env"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _radio_select(radio_set: RadioSet, index: int) -> None:
    """Programmatically select RadioButton at index inside a RadioSet."""
    buttons = list(radio_set.query(RadioButton))
    if 0 <= index < len(buttons):
        buttons[index].value = True


def _save_env(key: str, value: str) -> None:
    """Persist an env var to ~/.myagent/.env (upsert)."""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def _load_env_file() -> None:
    """Load ~/.myagent/.env into os.environ (called on startup)."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k and v and not os.environ.get(k):
            os.environ[k] = v


def _claude_cli_state() -> str:
    """Return 'ready' | 'no_auth' | 'not_installed'."""
    if not shutil.which("claude"):
        return "not_installed"
    if not (Path.home() / ".claude").exists():
        return "no_auth"
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, timeout=5)
        return "ready" if r.returncode == 0 else "no_auth"
    except Exception:
        return "no_auth"


def _gemini_cli_state() -> str:
    if not shutil.which("gemini"):
        return "not_installed"
    if not (Path.home() / ".gemini").exists():
        return "no_auth"
    try:
        r = subprocess.run(["gemini", "--version"], capture_output=True, timeout=5)
        return "ready" if r.returncode == 0 else "no_auth"
    except Exception:
        return "no_auth"


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------

class AuthScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "İptal"),
        ("ctrl+s",  "save",          "Kaydet"),
    ]

    CSS = """
    AuthScreen { background: $surface; }

    #auth-scroll { padding: 1 3; }

    .auth-title {
        text-style: bold;
        color: $primary;
        margin-top: 1;
        margin-bottom: 0;
    }

    .auth-subtitle { color: $text-muted; margin-bottom: 1; }

    RadioSet { margin: 0 0 1 2; }

    .key-input { margin: 0 0 1 2; }

    .cli-status { margin: 0 0 0 2; }

    .cli-install-hint {
        margin: 0 0 1 2;
        color: $text-muted;
    }

    .login-btn { margin: 0 0 1 2; width: auto; }

    .save-btn {
        margin-top: 2;
        width: 100%;
        dock: bottom;
    }

    .divider { margin: 1 0; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="auth-scroll"):

            yield Static("Kimlik Doğrulama & Bağlantı Ayarları\n", classes="auth-title")

            # ── Claude (Planner) ──────────────────────────────────────────────
            yield Static("PLANLAYAN  —  Claude", classes="auth-title")
            yield Static(
                "  Aboneliğinle kullan (Claude Code) ya da API key gir (pay-as-you-go)",
                classes="auth-subtitle",
            )
            with RadioSet(id="claude-radio"):
                yield RadioButton("API Anahtarı       ~3 s/plan  · pay-as-you-go", id="claude-api-rb")
                yield RadioButton("Claude Code CLI    ~5 s/plan  · abonelik (Pro/Max)", id="claude-cli-rb")

            yield Input(
                password=True,
                placeholder="sk-ant-api03-…",
                id="claude-key-input",
                classes="key-input",
            )
            yield Static("", id="claude-cli-status", classes="cli-status")
            yield Static("", id="claude-cli-hint",   classes="cli-install-hint")
            yield Button("claude login", id="claude-login-btn", classes="login-btn", variant="primary")

            yield Static("─" * 60, classes="divider")

            # ── Worker (Gemini / Claude) ──────────────────────────────────────
            yield Static("ÇALIŞAN  —  Worker", classes="auth-title")
            yield Static(
                "  Görevleri kimin yürüteceğini seç",
                classes="auth-subtitle",
            )
            with RadioSet(id="worker-radio"):
                yield RadioButton("Gemini API         ~2 s/adım  · hızlı, GEMINI_API_KEY gerekli", id="worker-api-rb")
                yield RadioButton("Claude Code        ~5 s/adım  · aynı aboneliği kullanır",        id="worker-claude-rb")
                yield RadioButton("Gemini CLI         ~40 s/adım · yavaş, Node.js CLI",             id="worker-cli-rb")

            yield Input(
                password=True,
                placeholder="AIzaSy…",
                id="gemini-key-input",
                classes="key-input",
            )
            yield Static("", id="worker-cli-status", classes="cli-status")
            yield Static("", id="worker-cli-hint",   classes="cli-install-hint")
            yield Button("gemini login", id="gemini-login-btn", classes="login-btn", variant="primary")

            yield Button("  Kaydet ve Devam Et  ", id="save-btn", classes="save-btn", variant="success")

        yield Footer()

    # ── Mount: load current state ─────────────────────────────────────────────

    def on_mount(self) -> None:
        self._claude_cli = _claude_cli_state()
        self._gemini_cli = _gemini_cli_state()

        cfg = load_config()
        self._current_claude_mode = cfg.get("claude_mode", CLI)
        self._current_worker_mode = cfg.get("gemini_mode", API)

        # Pre-fill API keys if set
        ck = os.environ.get("ANTHROPIC_API_KEY", "")
        if ck:
            self.query_one("#claude-key-input", Input).value = ck

        gk = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
        if gk:
            self.query_one("#gemini-key-input", Input).value = gk

        # Select correct radio buttons
        claude_idx = 0 if self._current_claude_mode == API else 1
        _radio_select(self.query_one("#claude-radio", RadioSet), claude_idx)

        worker_idx = {API: 0, CLAUDE_WORKER: 1, CLI: 2}.get(self._current_worker_mode, 0)
        _radio_select(self.query_one("#worker-radio", RadioSet), worker_idx)

        self._refresh_claude_ui(self._current_claude_mode)
        self._refresh_worker_ui(self._current_worker_mode)

    # ── Radio change handlers ─────────────────────────────────────────────────

    @on(RadioSet.Changed, "#claude-radio")
    def claude_radio_changed(self, event: RadioSet.Changed) -> None:
        mode = API if event.index == 0 else CLI
        self._refresh_claude_ui(mode)

    @on(RadioSet.Changed, "#worker-radio")
    def worker_radio_changed(self, event: RadioSet.Changed) -> None:
        mode = [API, CLAUDE_WORKER, CLI][event.index]
        self._refresh_worker_ui(mode)

    # ── UI state updaters ─────────────────────────────────────────────────────

    def _refresh_claude_ui(self, mode: str) -> None:
        key_input   = self.query_one("#claude-key-input", Input)
        cli_status  = self.query_one("#claude-cli-status", Static)
        cli_hint    = self.query_one("#claude-cli-hint", Static)
        login_btn   = self.query_one("#claude-login-btn", Button)

        if mode == API:
            key_input.display  = True
            cli_status.display = False
            cli_hint.display   = False
            login_btn.display  = False
        else:
            key_input.display = False
            if self._claude_cli == "ready":
                cli_status.update(Text("  ✓ Claude Code kurulu ve giriş yapılmış", style=C_OK))
                cli_status.display = True
                cli_hint.display   = False
                login_btn.display  = False
            elif self._claude_cli == "no_auth":
                cli_status.update(Text("  ⚠ Claude Code kurulu ama giriş yapılmamış", style=C_WARN))
                cli_hint.update("  Aşağıdaki butona tıklayarak tarayıcı üzerinden giriş yapın.")
                cli_status.display = True
                cli_hint.display   = True
                login_btn.display  = True
            else:  # not_installed
                cli_status.update(Text("  ✗ Claude Code kurulu değil", style=C_ERR))
                cli_hint.update(
                    "  Kurmak için:  curl -fsSL https://claude.ai/install.sh | sh\n"
                    "  Kurduktan sonra bu ekranı yenileyin."
                )
                cli_status.display = True
                cli_hint.display   = True
                login_btn.display  = False

    def _refresh_worker_ui(self, mode: str) -> None:
        key_input   = self.query_one("#gemini-key-input", Input)
        cli_status  = self.query_one("#worker-cli-status", Static)
        cli_hint    = self.query_one("#worker-cli-hint", Static)
        login_btn   = self.query_one("#gemini-login-btn", Button)

        if mode == API:
            key_input.display  = True
            cli_status.display = False
            cli_hint.display   = False
            login_btn.display  = False
        elif mode == CLAUDE_WORKER:
            key_input.display = False
            if self._claude_cli == "ready":
                cli_status.update(Text("  ✓ Claude Code hazır, worker olarak kullanılacak", style=C_OK))
                cli_status.display = True
                cli_hint.display   = False
                login_btn.display  = False
            else:
                cli_status.update(Text("  ✗ Claude Code kurulu değil ya da giriş yapılmamış", style=C_ERR))
                cli_hint.update("  Önce yukarıdaki Claude bölümünden giriş yapın.")
                cli_status.display = True
                cli_hint.display   = True
                login_btn.display  = False
        else:  # Gemini CLI
            key_input.display = False
            if self._gemini_cli == "ready":
                cli_status.update(Text("  ✓ Gemini CLI kurulu ve hazır", style=C_OK))
                cli_status.display = True
                cli_hint.display   = False
                login_btn.display  = False
            elif self._gemini_cli == "no_auth":
                cli_status.update(Text("  ⚠ Gemini CLI kurulu ama giriş yapılmamış", style=C_WARN))
                cli_hint.update("  Aşağıdaki butona tıklayarak giriş yapın.")
                cli_status.display = True
                cli_hint.display   = True
                login_btn.display  = True
            else:
                cli_status.update(Text("  ✗ Gemini CLI kurulu değil", style=C_ERR))
                cli_hint.update("  Kurmak için:  npm install -g @google/gemini-cli")
                cli_status.display = True
                cli_hint.display   = True
                login_btn.display  = False

    # ── Button handlers ───────────────────────────────────────────────────────

    @on(Button.Pressed, "#claude-login-btn")
    async def claude_login(self) -> None:
        with self.app.suspend():
            subprocess.run(["claude", "login"], check=False)
        self._claude_cli = _claude_cli_state()
        cidx = self.query_one("#claude-radio", RadioSet).pressed_index or 0
        self._refresh_claude_ui(API if cidx == 0 else CLI)
        widx = self.query_one("#worker-radio", RadioSet).pressed_index or 0
        self._refresh_worker_ui([API, CLAUDE_WORKER, CLI][widx])

    @on(Button.Pressed, "#gemini-login-btn")
    async def gemini_login(self) -> None:
        with self.app.suspend():
            subprocess.run(["gemini", "login"], check=False)
        self._gemini_cli = _gemini_cli_state()
        idx = self.query_one("#worker-radio", RadioSet).pressed_index or 0
        self._refresh_worker_ui([API, CLAUDE_WORKER, CLI][idx])

    @on(Button.Pressed, "#save-btn")
    def save_pressed(self) -> None:
        self.action_save()

    # ── Save ──────────────────────────────────────────────────────────────────

    def action_save(self) -> None:
        claude_idx = self.query_one("#claude-radio", RadioSet).pressed_index or 0
        worker_idx = self.query_one("#worker-radio", RadioSet).pressed_index or 0

        claude_mode = API if claude_idx == 0 else CLI
        worker_mode = [API, CLAUDE_WORKER, CLI][worker_idx]

        # Save API keys if provided
        ck = self.query_one("#claude-key-input", Input).value.strip()
        if ck and claude_mode == API:
            _save_env("ANTHROPIC_API_KEY", ck)

        gk = self.query_one("#gemini-key-input", Input).value.strip()
        if gk and worker_mode == API:
            _save_env("GEMINI_API_KEY", gk)

        save_config({
            "claude_mode": claude_mode,
            "gemini_mode": worker_mode,
        })

        self.app.notify("✓ Ayarlar kaydedildi.", severity="information", timeout=3)
        self.app.pop_screen()
