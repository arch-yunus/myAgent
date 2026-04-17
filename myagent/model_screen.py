"""
ModelScreen — Textual full-screen model selection for Claude and Gemini.
"""

from __future__ import annotations

import asyncio
import os

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, RadioButton, RadioSet, Static

from myagent.config.auth import get_claude_model, get_gemini_model, save_config
from myagent.models import (
    CLAUDE_CURATED, CLAUDE_DEFAULT,
    GEMINI_CURATED, GEMINI_DEFAULT,
    ModelInfo,
    fetch_claude_models, fetch_gemini_models,
)
from myagent.ui import C_CLAUDE, C_DIM, C_GEMINI, C_OK


def _radio_select(radio_set: RadioSet, index: int) -> None:
    buttons = list(radio_set.query(RadioButton))
    if 0 <= index < len(buttons):
        buttons[index].value = True


def _model_label(m: ModelInfo, current_id: str) -> str:
    rec = "  ★" if m.is_recommended else ""
    cur = "  (mevcut)" if m.id == current_id else ""
    return f"{m.id}{rec}{cur}  —  {m.description}"


class ModelScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "İptal"),
        ("ctrl+s",  "save",          "Kaydet"),
    ]

    CSS = """
    ModelScreen { background: $surface; }

    #model-scroll { padding: 1 4; }

    .model-title {
        text-style: bold;
        color: $primary;
        margin-top: 1;
    }

    .model-subtitle { margin-bottom: 1; }

    .nav-hint { margin-bottom: 1; }

    RadioSet {
        margin: 0 0 1 2;
        width: auto;
        max-width: 80;
    }

    .loading { margin: 0 0 1 2; }

    .save-btn {
        margin-top: 2;
        margin-bottom: 1;
        width: 30;
    }

    .divider { margin: 1 0; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="model-scroll"):
            yield Static("Model Seçimi", classes="model-title")
            yield Static(
                "  ↑ ↓ model değiştir  ·  Tab sonraki bölüm  ·  ★ önerilen model\n",
                classes="nav-hint",
            )

            # ── Claude ────────────────────────────────────────────────────────
            yield Static(
                f"PLANLAYAN  —  Claude  [dim]( ↑ ↓ ile seç )[/dim]",
                classes="model-title",
            )
            yield Static("  Modeller yükleniyor…", id="claude-loading", classes="loading")
            yield RadioSet(id="claude-radio")

            yield Static("─" * 60, classes="divider")

            # ── Gemini ────────────────────────────────────────────────────────
            yield Static(
                f"ÇALIŞAN  —  Gemini  [dim]( ↑ ↓ ile seç · Tab ile bu bölüme geç )[/dim]",
                classes="model-title",
            )
            yield Static("  Modeller yükleniyor…", id="gemini-loading", classes="loading")
            yield RadioSet(id="gemini-radio")

            yield Button("  Kaydet ve Devam Et  ", id="save-btn", classes="save-btn", variant="success")

        yield Footer()

    # ── Mount ─────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._current_claude = get_claude_model()
        self._current_gemini = get_gemini_model()
        self._claude_models: list[ModelInfo] = []
        self._gemini_models: list[ModelInfo] = []
        self._load_models()

    @work(thread=True)
    def _load_models(self) -> None:
        claude_key = os.environ.get("ANTHROPIC_API_KEY", "")
        gemini_key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))

        claude_models = fetch_claude_models(claude_key) if claude_key else CLAUDE_CURATED
        gemini_models = fetch_gemini_models(gemini_key) if gemini_key else GEMINI_CURATED

        self.app.call_from_thread(self._populate_claude, claude_models)
        self.app.call_from_thread(self._populate_gemini, gemini_models)

    def _populate_claude(self, models: list[ModelInfo]) -> None:
        self._claude_models = models
        loading = self.query_one("#claude-loading", Static)
        radio   = self.query_one("#claude-radio", RadioSet)

        loading.display = False
        radio.clear_options() if hasattr(radio, "clear_options") else None

        for m in models:
            radio.mount(RadioButton(_model_label(m, self._current_claude)))

        self.call_after_refresh(lambda: self._init_claude_selection(models))

    def _populate_gemini(self, models: list[ModelInfo]) -> None:
        self._gemini_models = models
        loading = self.query_one("#gemini-loading", Static)
        radio   = self.query_one("#gemini-radio", RadioSet)

        loading.display = False
        radio.clear_options() if hasattr(radio, "clear_options") else None

        for m in models:
            radio.mount(RadioButton(_model_label(m, self._current_gemini)))

        self.call_after_refresh(lambda: self._init_gemini_selection(models))

    def _init_claude_selection(self, models: list[ModelInfo]) -> None:
        ids = [m.id for m in models]
        idx = ids.index(self._current_claude) if self._current_claude in ids else 0
        rec = next((i for i, m in enumerate(models) if m.is_recommended), 0)
        _radio_select(self.query_one("#claude-radio", RadioSet), idx if idx >= 0 else rec)
        self.query_one("#claude-radio", RadioSet).focus()

    def _init_gemini_selection(self, models: list[ModelInfo]) -> None:
        ids = [m.id for m in models]
        idx = ids.index(self._current_gemini) if self._current_gemini in ids else 0
        rec = next((i for i, m in enumerate(models) if m.is_recommended), 0)
        _radio_select(self.query_one("#gemini-radio", RadioSet), idx if idx >= 0 else rec)

    # ── Save ──────────────────────────────────────────────────────────────────

    @on(Button.Pressed, "#save-btn")
    def save_pressed(self) -> None:
        self.action_save()

    def action_save(self) -> None:
        claude_idx  = self.query_one("#claude-radio", RadioSet).pressed_index or 0
        gemini_idx  = self.query_one("#gemini-radio", RadioSet).pressed_index or 0

        claude_model = (
            self._claude_models[claude_idx].id
            if self._claude_models and claude_idx < len(self._claude_models)
            else CLAUDE_DEFAULT
        )
        gemini_model = (
            self._gemini_models[gemini_idx].id
            if self._gemini_models and gemini_idx < len(self._gemini_models)
            else GEMINI_DEFAULT
        )

        save_config({"claude_model": claude_model, "gemini_model": gemini_model})

        # Apply immediately to running session
        os.environ["CLAUDE_MODEL"] = claude_model
        os.environ["GEMINI_MODEL"] = gemini_model

        self.app.notify(
            f"✓ Claude: {claude_model}  ·  Gemini: {gemini_model}",
            severity="information",
            timeout=4,
        )
        self.app.pop_screen()
