"""
myagent TUI — Textual-based responsive terminal interface.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from rich.markdown import Markdown
from rich.rule import Rule
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Input, Label, RichLog

from myagent.agent.chat import Chat
from myagent.config.settings import WORK_DIR
from myagent.ui import AgentUI, C_CLAUDE, C_DIM, C_GEMINI, C_OK, C_WARN, C_ERR

if TYPE_CHECKING:
    from myagent.cli import SessionState


# ---------------------------------------------------------------------------
# TUI-specific UI Bridge
# ---------------------------------------------------------------------------

class TuiAgentUI(AgentUI):
    """Bridge between agent pipeline and Textual app via call_from_thread."""

    def __init__(self, app: "MyAgentApp"):
        super().__init__(verbose=app.verbose)
        self.app = app

    def _log(self, renderable: Any) -> None:
        self.app.call_from_thread(self.app.log_message, renderable)

    def header(self, task: str, claude_model: str, gemini_model: str) -> None:
        self._log(Rule(f"[{C_CLAUDE}]{task}[/]", style=C_DIM))

    def plan_done(self, steps: list[str]) -> None:
        t = Text(f"\n  Plan ({len(steps)} adım):\n", style=C_CLAUDE)
        for i, s in enumerate(steps, 1):
            t.append(f"    {i}. ", style=C_DIM)
            t.append(f"{s}\n")
        self._log(t)

    def exec_results(self, steps: list[str], results: list[Any]) -> None:
        t = Text(f"\n  Yürütme:\n", style=C_GEMINI)
        for i, (step, r) in enumerate(zip(steps, results), 1):
            icon = "✓" if r.ok else "✗"
            color = C_OK if r.ok else C_ERR
            t.append(f"    {i}. ", style=C_DIM)
            t.append(f"{icon} ", style=color)
            t.append(f"{r.message}\n")
        self._log(t)

    def chat_answer(self, text: str) -> None:
        self.app._last_answer = text

    def session_context_notice(self, notice: str) -> None:
        self._log(Text(f"  ℹ {notice}", style=C_DIM))

    def summary(self, success: bool, review_approved: bool,
                n_review_rounds: int, created_files: list[str]) -> None:
        status = "✓ Tamamlandı" if success else "✗ Hatalarla tamamlandı"
        color = C_OK if success else C_WARN
        self._log(Text(f"\n  {status}\n", style=f"bold {color}"))

    @contextmanager
    def streaming(self, label: str, color: str = C_DIM):
        yield lambda x: None

    @contextmanager
    def spinner(self, label: str, color: str = C_DIM):
        yield


# ---------------------------------------------------------------------------
# Textual App
# ---------------------------------------------------------------------------

_BANNER = """\
  ╔╦╗╦ ╦╔═╗╔═╗╔═╗╔╗╔╔╦╗
  ║║║╚╦╝╠═╣║ ╦║╣ ║║║ ║
  ╩ ╩ ╩ ╩ ╩╚═╝╚═╝╝╚╝ ╩ """


class MyAgentApp(App):
    """Main myagent TUI."""

    CSS = """
    Screen {
        background: $surface;
    }

    #chat-log {
        height: 1fr;
        padding: 0 2;
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
            yield Input(placeholder="Ne yapmamı istersin?", id="user-input")
        yield Footer()

    def on_mount(self) -> None:
        from myagent.config.auth import get_claude_model, get_gemini_model
        banner = Text(_BANNER, style=f"bold {C_CLAUDE}")
        self.log_message(banner)
        self.log_message(Text.assemble(
            ("  v1.0.0", "dim"),
            ("  ·  ", "dim"),
            ("Claude", f"bold {C_CLAUDE}"),
            (" planlar", "dim"),
            ("  ·  ", "dim"),
            ("Gemini", f"bold {C_GEMINI}"),
            (" yürütür\n", "dim"),
        ))
        self.log_message(Text.assemble(
            ("  ", ""),
            (get_claude_model(), C_CLAUDE),
            ("  /  ", "dim"),
            (get_gemini_model(), C_GEMINI),
            ("\n", ""),
        ))
        self.log_message(Text(
            "  Ctrl+Y kopyala  ·  Ctrl+L temizle  ·  F1 yardım\n",
            style="dim",
        ))
        self.query_one("#user-input").focus()

    def log_message(self, renderable: Any) -> None:
        self.chat_log.write(renderable)

    @on(Input.Submitted)
    async def handle_input(self, event: Input.Submitted) -> None:
        user_text = event.value.strip()
        if not user_text:
            return

        event.input.value = ""

        # User message — right-aligned feel with distinct color
        self.log_message(Text.assemble(
            ("\n  ", ""),
            ("Sen  ", f"bold {C_GEMINI}"),
            (user_text, "bold white"),
            ("\n", ""),
        ))

        if user_text.startswith("/"):
            cmd = user_text[1:].lower().split()[0]
            if cmd in ("exit", "quit", "çıkış"):
                self.exit()
            elif cmd == "help":
                self.action_help()
            elif cmd == "clear":
                self.action_clear_log()
            else:
                self.process_task(user_text[1:])
        else:
            self.process_chat(user_text)

    @work(exclusive=True)
    async def process_chat(self, text: str) -> None:
        self.log_message(Text("  ⊛ düşünüyor…\n", style=f"dim {C_CLAUDE}"))
        t0 = time.time()

        loop = asyncio.get_event_loop()
        route = await loop.run_in_executor(None, self.session.chat.route, text)
        elapsed = time.time() - t0

        if route.action == "answer":
            answer = route.answer
            self._last_answer = answer
            # Assistant message block
            self.log_message(Text.assemble(
                ("  Claude  ", f"bold {C_CLAUDE}"),
                (f"{elapsed:.1f}s\n", "dim"),
            ))
            self.log_message(Markdown(answer))
            self.log_message(Text(""))
        else:
            task = route.task or text
            await self._run_pipeline(task)

    @work(exclusive=True)
    async def process_task(self, task: str) -> None:
        await self._run_pipeline(task)

    async def _run_pipeline(self, task: str) -> None:
        from myagent.agent.pipeline import run
        t0 = time.time()

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, run,
                task,
                self.verbose,
                False,   # dry_run
                True,    # batch
                False,   # clarify
                True,    # review
                2,       # max_review_rounds
                False,   # auto_deps
                True,    # verify_completion
                2,       # max_completion_rounds
                "",      # session_context
                self.ui_bridge,
            )
            elapsed = time.time() - t0
            self.session.update(result)
            if self.session.chat:
                self.session.chat.add_task_result(result.task_original, result.summary_en)
            files = ", ".join(result.created_files[:4]) or "—"
            self.log_message(Text.assemble(
                ("\n  ", ""),
                ("✓ ", f"bold {C_OK}"),
                (f"{elapsed:.1f}s  ", "dim"),
                ("dosyalar: ", "dim"),
                (files, "white"),
                ("\n", ""),
            ))
        except Exception as e:
            self.log_message(Text(f"\n  ✗ Hata: {e}\n", style=f"bold {C_ERR}"))

    def action_clear_log(self) -> None:
        self.chat_log.clear()

    def action_copy_last(self) -> None:
        if not self._last_answer:
            self.notify("Kopyalanacak cevap yok.", severity="warning")
            return
        self.copy_to_clipboard(self._last_answer)
        self.notify("Panoya kopyalandı.")

    def action_help(self) -> None:
        self.log_message(Markdown(
            "### Yardım\n"
            "- **Ctrl+C** → Çıkış\n"
            "- **Ctrl+L** → Ekranı temizle\n"
            "- **Ctrl+Y** → Son cevabı panoya kopyala\n"
            "- **F1** → Bu yardım\n"
            "- `/exit` → Çıkış\n"
        ))


def start_tui(session: "SessionState", verbose: bool = False) -> None:
    app = MyAgentApp(session, verbose=verbose)
    app.run(mouse=False)
