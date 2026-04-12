"""
myagent TUI — Textual-based responsive terminal interface.

Features:
  • Flexbox layout (responsive to terminal resize)
  • Scrollable chat log
  • Real-time model output streaming
  • Interactive workspace file tree
  • Tab completion and command history
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    RichLog,
)

from myagent.agent.chat import Chat
from myagent.agent.pipeline import RunResult, run
from myagent.config.auth import get_claude_model, get_gemini_model
from myagent.config.settings import WORK_DIR
from myagent.i18n.locale import SYSTEM_LANGUAGE
from myagent.ui import AgentUI, C_CLAUDE, C_DIM, C_GEMINI, C_OK, C_WARN, C_ERR

if TYPE_CHECKING:
    from myagent.cli import SessionState


# ---------------------------------------------------------------------------
# TUI-specific UI Bridge
# ---------------------------------------------------------------------------

class TuiAgentUI(AgentUI):
    """Bridge between agent pipeline and Textual app via message passing."""
    def __init__(self, app: "MyAgentApp"):
        super().__init__(verbose=app.verbose)
        self.app = app

    def _log(self, renderable: Any) -> None:
        self.app.call_from_thread(self.app.log_message, renderable)

    def header(self, task: str, claude_model: str, gemini_model: str) -> None:
        self._log(Rule(f"Task: {task}", style=C_DIM))

    def plan_done(self, steps: list[str]) -> None:
        t = Text.assemble(
            (f"\n  Plan ({len(steps)} adım):\n", C_CLAUDE),
        )
        for i, s in enumerate(steps, 1):
            t.append(f"    {i}. ", style=C_DIM)
            t.append(f"{s}\n")
        self._log(t)

    def exec_results(self, steps: list[str], results: list[Any]) -> None:
        t = Text.assemble((f"\n  Yürütme:\n", C_GEMINI))
        for i, (step, r) in enumerate(zip(steps, results), 1):
            icon = "✓" if r.ok else "✗"
            color = C_OK if r.ok else C_ERR
            t.append(f"    {i}. ", style=C_DIM)
            t.append(f"{icon} ", style=color)
            t.append(f"{r.message}\n")
        self._log(t)

    def chat_answer(self, text: str) -> None:
        self.app._last_answer = text
        self._log(Markdown(text))

    def session_context_notice(self, notice: str) -> None:
        self._log(Text(f"  ℹ {notice}", style=C_DIM))

    def summary(self, success: bool, review_approved: bool, 
                n_review_rounds: int, created_files: list[str]) -> None:
        status = "✓ Tamamlandı" if success else "✗ Hatalarla tamamlandı"
        color = C_OK if success else C_WARN
        self._log(Text(f"\n{status}\n", style=f"bold {color}"))
        if created_files:
            self.app.call_from_thread(self.app.refresh_tree)

    @contextmanager
    def streaming(self, label: str, color: str = C_DIM):
        """No-op for TUI — pipeline output goes through log_message."""
        yield lambda x: None

    @contextmanager
    def spinner(self, label: str, color: str = C_DIM):
        """No-op for TUI — spinner not needed in async context."""
        yield

# ---------------------------------------------------------------------------
# Textual App
# ---------------------------------------------------------------------------

class MyAgentApp(App):
    """Main myagent TUI."""

    CSS = """
    Screen {
        background: $surface;
    }

    #chat-log {
        height: 1fr;
        padding: 1 2;
    }

    #input-container {
        height: 3;
        dock: bottom;
        border-top: solid $primary;
        padding: 0 1;
    }

    Input {
        border: none;
        background: $surface;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Çıkış"),
        ("ctrl+l", "clear_log", "Temizle"),
        ("ctrl+y", "copy_last", "Kopyala"),
        ("f1", "help", "Yardım"),
    ]

    def __init__(self, session_state: "SessionState", verbose: bool = False):
        super().__init__()
        self.session = session_state
        self.verbose = verbose
        self._last_answer: str = ""
        if not self.session.chat:
            self.session.chat = Chat()
        self.ui_bridge = TuiAgentUI(self)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        self.chat_log = RichLog(id="chat-log", highlight=True, markup=True)
        yield self.chat_log
        with Horizontal(id="input-container"):
            yield Label(" ❯ ", variant="bold")
            yield Input(placeholder="Nasıl yardımcı olabilirim?", id="user-input")
        yield Footer()

    def on_mount(self) -> None:
        self.log_message(Text.assemble(
            ("myagent ", "bold white"),
            ("v1.0.0", "dim"),
            ("  ·  Claude planlar  ·  Gemini yürütür", "dim"),
        ))
        self.log_message(Text("  Ctrl+Y → son cevabı kopyala  |  Ctrl+L → temizle  |  F1 → yardım", style="dim"))
        self.query_one("#user-input").focus()

    def log_message(self, renderable: Any) -> None:
        self.chat_log.write(renderable)

    @on(Input.Submitted)
    async def handle_input(self, event: Input.Submitted) -> None:
        user_text = event.value.strip()
        if not user_text:
            return

        event.input.value = ""
        self.log_message(f"\n[bold white]Siz:[/] {user_text}")

        if user_text.startswith("/"):
            # Handle commands
            cmd = user_text[1:].lower()
            if cmd in ("exit", "quit"):
                self.exit()
            elif cmd == "help":
                self.log_message(Markdown("# Yardım\n- /exit: Çıkış\n- /clear: Ekranı temizle"))
            else:
                self.run_task(user_text[1:])
        else:
            # Normal chat
            self.process_chat(user_text)

    @work(exclusive=True)
    async def process_chat(self, text: str) -> None:
        self.log_message(Text("\n  ⊛ Claude düşünüyor…", style="medium_purple1"))
        
        # We need to run model calls in a thread to avoid blocking the UI
        loop = asyncio.get_event_loop()
        route = await loop.run_in_executor(None, self.session.chat.route, text)

        if route.action == "answer":
            self.log_message(Markdown(route.answer))
        else:
            # TASK
            task = route.task or text
            await self.run_agent_pipeline(task)

    @work(exclusive=True)
    async def run_task(self, task: str) -> None:
        await self.run_agent_pipeline(task)

    async def run_agent_pipeline(self, task: str) -> None:
        from myagent.agent.pipeline import run
        
        self.log_message(Text(f"\n  ⊛ Görev başlatıldı: {task}", style="bold white"))
        
        loop = asyncio.get_event_loop()
        try:
            # Run the pipeline with our TUI-aware UI bridge
            result = await loop.run_in_executor(
                None, 
                run, 
                task, 
                self.verbose, 
                False, # dry_run
                True,  # batch
                True,  # clarify
                True,  # review
                2,     # max_review_rounds
                False, # auto_deps
                True,  # verify_completion
                2,     # max_completion_rounds
                "",    # session_context
                self.ui_bridge
            )
            self.session.update(result)
            self.session.chat.add_task_result(result.task_original, result.summary_en)
        except Exception as e:
            self.log_message(f"[bold red]Hata:[/] {str(e)}")

    def action_clear_log(self) -> None:
        self.chat_log.clear()

    def action_copy_last(self) -> None:
        if not self._last_answer:
            self.notify("Kopyalanacak cevap yok.", severity="warning")
            return
        self.copy_to_clipboard(self._last_answer)
        self.notify("Son cevap panoya kopyalandı.")

    def action_help(self) -> None:
        self.log_message(Markdown(
            "## Yardım\n"
            "- **Ctrl+C**: Çıkış\n"
            "- **Ctrl+L**: Ekranı temizle\n"
            "- **Ctrl+Y**: Son cevabı panoya kopyala\n"
            "- **F1**: Yardım\n"
            "- `/exit`: Çıkış\n"
        ))

def start_tui(session: SessionState, verbose: bool = False) -> None:
    app = MyAgentApp(session, verbose=verbose)
    app.run()
