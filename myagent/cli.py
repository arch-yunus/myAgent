"""
CLI entry point — interactive REPL and one-shot mode.

Usage
-----
Interactive REPL:
  myagent [OPTIONS]

One-shot (non-interactive):
  myagent run "create a python port scanner" [OPTIONS]

Utility:
  myagent --list-models
  myagent --config
  myagent --setup

Options
-------
  --claude-model MODEL      Claude model to use (alias or full ID)
  --gemini-model MODEL      Gemini model to use (alias or full ID)
  --claude-mode  api|cli    Override Claude auth mode
  --gemini-mode  api|cli    Override Gemini auth mode
  --work-dir PATH           Working directory for file operations
  --max-steps N             Maximum plan steps (default: 10)
  --lang tr|en              Force output language
  --dry-run                 Show plan without executing
  --verbose, -v             Show raw model output and step details
  --list-models             Print available models and exit
  --config                  Print current configuration and exit
  --setup                   Run setup wizard and exit
  --version                 Print version and exit

Model aliases (Claude):
  opus, sonnet, haiku

Model aliases (Gemini):
  2.5-pro, 2.5-flash, flash (2.0), 1.5-pro
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myagent.agent.chat import Chat
    from myagent.agent.pipeline import RunResult
    from myagent.ui import AgentUI

__version__ = "1.0.0"


# ---------------------------------------------------------------------------
# Session state — accumulates context within one REPL session
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    """Holds context across REPL turns within a single session."""
    last_result: "RunResult | None" = None
    last_task: str = ""
    run_count: int = 0
    chat: "Chat | None" = None
    ui: "AgentUI | None" = None  # persistent UI — holds Live panel between turns

    # ── Pronoun / continuation resolution ───────────────────────────────────

    # Keywords that mean "keep going on the last project"
    _CONTINUE_KW = frozenset({"devam", "devam et", "continue", "devam ettr"})

    # Keywords that mean "fix the last project"
    _FIX_KW = frozenset({
        "düzelt", "düzeltle", "fix", "hataları düzelt", "hataları gider",
        "fix it", "fix bugs", "bugs", "bug fix",
    })

    # Keywords that mean "add tests"
    _TEST_KW = frozenset({
        "test", "test ekle", "testler yaz", "add tests", "write tests", "testleri yaz",
    })

    # Keywords that mean "run / launch"
    _RUN_KW = frozenset({
        "çalıştır", "başlat", "run", "start", "çalıştırır mısın", "başlatır mısın",
    })

    # Pronouns that refer to the last project
    _PRONOUNS = ("bunu", "buna", "bunu", "onu", "bu proje", "önceki", "son proje",
                 "o proje", "onu", "bu kodu", "bu dosyaları")

    def resolve(self, raw: str) -> tuple[str, str]:
        """Parse user input.

        Returns (resolved_task, session_context_hint).
        session_context_hint is injected into Claude's planning context.
        """
        lower = raw.strip().lower()

        if not self.last_result:
            return raw, ""

        files = self.last_result.created_files
        fnames = ", ".join(files[:6]) if files else "(yok)"
        prev_note = (
            f"The user previously ran: \"{self.last_task}\"\n"
            f"Files created: {fnames}\n"
            f"Treat any continuation as extending/fixing that project."
        )

        if lower in self._CONTINUE_KW:
            return (
                f"Continue and fully complete the previous task: {self.last_task}",
                prev_note,
            )

        if lower in self._FIX_KW:
            return (
                f"Fix all issues in the previous project. Files: {fnames}. "
                f"Original task: {self.last_task}",
                prev_note,
            )

        if lower in self._TEST_KW:
            return (
                f"Add comprehensive tests for the previous project ({fnames}). "
                f"Original task: {self.last_task}",
                prev_note,
            )

        if lower in self._RUN_KW:
            return (
                f"Run the main application from the previous project ({fnames}).",
                prev_note,
            )

        # Check for pronoun references — inject context but keep original wording
        if any(p in lower for p in self._PRONOUNS):
            return raw, prev_note

        # No continuation detected — plain new task, no extra context
        return raw, ""

    def update(self, result: "RunResult") -> None:
        self.last_result = result
        self.last_task = result.task_original
        self.run_count += 1

def _ui_console() -> "Console":
    from rich.console import Console
    return Console()


def _print_banner() -> None:
    from rich.panel import Panel
    from rich.text import Text
    console = _ui_console()
    console.print()
    console.print(Panel(
        Text.assemble(
            ("myagent ", "bold white"),
            (f"v{__version__}", "dim white"),
            ("  ·  ", "dim"),
            ("Claude", "bold medium_purple1"),
            (" planlar  ", "dim"),
            ("·", "dim"),
            ("  Gemini", "bold dodger_blue1"),
            (" yürütür", "dim"),
        ),
        border_style="dim",
        padding=(0, 2),
        expand=False,
        subtitle="[dim]/help → yardım   /exit → çıkış[/]",
    ))
    console.print()


def _print_help() -> None:
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = _ui_console()

    def _section(title: str, rows: list[tuple[str, str]], color: str) -> Panel:
        t = Table.grid(padding=(0, 3))
        t.add_column(style=f"bold {color}", min_width=22)
        t.add_column(style="dim white")
        for cmd, desc in rows:
            t.add_row(cmd, desc)
        return Panel(t, title=f"[bold {color}]{title}[/]", border_style=color,
                     padding=(0, 1), expand=False)

    console.print()
    console.print(Panel(
        Text.assemble(
            ("Herhangi bir şey yaz", "bold white"),
            (" — Claude soru mu görev mi olduğuna karar verir.", "dim"),
        ),
        border_style="dim",
        padding=(0, 1),
        expand=False,
    ))
    console.print()

    console.print(_section("Görevler", [
        ("<herhangi bir şey>",   "Doğal dil — Claude yönlendirir"),
        ("/run <görev>",         "Chat'i atlayarak doğrudan çalıştır"),
        ("/devam",               "Son projeye devam et"),
        ("/düzelt  /fix",        "Son projede hataları düzelt"),
        ("/test",                "Son projeye test yaz"),
    ], "dodger_blue1"))

    console.print(_section("Proje & Geçmiş", [
        ("/geçmiş  /history",   "Geçmiş görevleri listele"),
        ("/son  /last",         "Son görevin detayları"),
        ("/dosyalar  /ls",      "Çalışma dizinindeki dosyalar"),
        ("/temizle",            "Çalışma dizinini temizle"),
    ], "cyan2"))

    console.print(_section("Sistem", [
        ("/setup",              "Auth ve model ayarlarını yeniden yapılandır"),
        ("/models",             "Mevcut modelleri listele"),
        ("/config",             "Yapılandırmayı göster"),
        ("/clear",              "Ekranı temizle"),
        ("/help",               "Bu ekranı göster"),
        ("/exit",               "Çıkış"),
    ], "grey70"))

    from rich.syntax import Syntax
    examples = "\n".join([
        "myagent ❯ basit bir şifre üreteci yaz",
        "myagent ❯ fibonacci nedir, nasıl çalışır?",
        "myagent ❯ buna GUI ekle",
        "myagent ❯ az önce yazdığın kodu açıkla",
        "myagent ❯ /düzelt",
        "myagent ❯ /geçmiş",
    ])
    console.print(Panel(
        Syntax(examples, "text", theme="monokai", background_color="default"),
        title="[bold white]Örnekler[/]",
        border_style="dim",
        padding=(0, 1),
        expand=False,
    ))
    console.print()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="myagent",
        description="Terminal AI agent: Claude plans, Gemini executes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── Model flags ──────────────────────────────────────────────────────────
    model_grp = p.add_argument_group("Model selection")
    model_grp.add_argument(
        "--claude-model", metavar="MODEL",
        help="Claude model alias or full ID (e.g. opus, sonnet, claude-opus-4-6)",
    )
    model_grp.add_argument(
        "--gemini-model", metavar="MODEL",
        help="Gemini model alias or full ID (e.g. 2.5-pro, flash, gemini-2.5-flash)",
    )

    # ── Auth mode flags ──────────────────────────────────────────────────────
    auth_grp = p.add_argument_group("Auth mode override")
    auth_grp.add_argument(
        "--claude-mode", metavar="api|cli", choices=["api", "cli"],
        help="Override Claude auth mode for this session",
    )
    auth_grp.add_argument(
        "--gemini-mode", metavar="api|cli|claude", choices=["api", "cli", "claude"],
        help="Worker backend: api (fast, needs key), cli (slow ~40s), claude (fast, uses Claude Code auth)",
    )

    # ── Behaviour flags ──────────────────────────────────────────────────────
    beh_grp = p.add_argument_group("Behaviour")
    beh_grp.add_argument(
        "--work-dir", metavar="PATH",
        help="Working directory for file/command execution (overrides MYAGENT_WORK_DIR)",
    )
    beh_grp.add_argument(
        "--max-steps", type=int, metavar="N",
        help="Maximum number of plan steps (default: 10)",
    )
    beh_grp.add_argument(
        "--lang", metavar="tr|en", choices=["tr", "en"],
        help="Force output language (default: auto-detect from system locale)",
    )
    beh_grp.add_argument(
        "--dry-run", action="store_true",
        help="Show plan steps without executing them",
    )
    beh_grp.add_argument(
        "--sequential", action="store_true",
        help="Execute steps one-by-one instead of batch (more context passing, more calls)",
    )
    beh_grp.add_argument(
        "--clarify", action="store_true",
        help="Ask clarifying questions before planning (default: off)",
    )
    beh_grp.add_argument(
        "--no-review", action="store_true",
        help="Skip the review and fix loop after execution",
    )
    beh_grp.add_argument(
        "--max-review-rounds", type=int, default=2, metavar="N",
        help="Maximum review/fix iterations (default: 2)",
    )
    beh_grp.add_argument(
        "--auto-deps", action="store_true",
        help="Automatically install missing Python packages without asking (default: ask)",
    )
    beh_grp.add_argument(
        "--no-complete", action="store_true",
        help="Skip the completion verification step after review",
    )
    beh_grp.add_argument(
        "--max-completion-rounds", type=int, default=2, metavar="N",
        help="Maximum completion verification iterations (default: 2)",
    )
    beh_grp.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show raw model output and per-step details",
    )
    beh_grp.add_argument(
        "--tui", action="store_true", default=True,
        help="Start with Textual TUI (default: on)",
    )
    beh_grp.add_argument(
        "--no-tui", action="store_false", dest="tui",
        help="Use classic REPL instead of TUI",
    )

    # ── Utility flags ────────────────────────────────────────────────────────
    util_grp = p.add_argument_group("Utility")
    util_grp.add_argument(
        "--list-models", action="store_true",
        help="List available models for Claude and Gemini, then exit",
    )
    util_grp.add_argument(
        "--config", action="store_true",
        help="Show current configuration and exit",
    )
    util_grp.add_argument(
        "--setup", action="store_true",
        help="Run the setup wizard and exit",
    )
    util_grp.add_argument(
        "--version", action="version", version=f"myagent {__version__}",
    )

    # ── Positional (one-shot mode) ───────────────────────────────────────────
    p.add_argument(
        "task", nargs="?", metavar="TASK",
        help="Run a single task non-interactively (skips REPL)",
    )

    return p


# ---------------------------------------------------------------------------
# Utility actions
# ---------------------------------------------------------------------------

def _show_models() -> None:
    from myagent.config.auth import get_claude_model, get_gemini_model, get_claude_mode, get_gemini_mode
    from myagent.models import (
        CLAUDE_CURATED, GEMINI_CURATED,
        fetch_claude_models, fetch_gemini_models,
        format_model_table,
    )
    import os

    cur_claude = get_claude_model()
    cur_gemini = get_gemini_model()

    # Claude
    print("\nClaude models:")
    if get_claude_mode() == "api":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            print("  (API üzerinden getiriliyor...)", end="\r", flush=True)
            models = fetch_claude_models(api_key)
            print("                                   ")
        else:
            models = CLAUDE_CURATED
    else:
        models = CLAUDE_CURATED
    print(format_model_table(models, cur_claude))

    # Gemini
    print("\nGemini models:")
    if get_gemini_mode() == "api":
        api_key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
        if api_key:
            print("  (API üzerinden getiriliyor...)", end="\r", flush=True)
            models = fetch_gemini_models(api_key)
            print("                                   ")
        else:
            models = GEMINI_CURATED
    else:
        models = GEMINI_CURATED
    print(format_model_table(models, cur_gemini))
    print()


def _show_config() -> None:
    from rich.panel import Panel
    from rich.table import Table

    from myagent.config.auth import (
        CONFIG_PATH, get_claude_mode, get_claude_model,
        get_gemini_mode, get_gemini_model, get_overrides,
    )
    from myagent.config.settings import WORK_DIR, MAX_STEPS
    from myagent.i18n.locale import SYSTEM_LANGUAGE

    ovr = get_overrides()
    console = _ui_console()
    t = Table.grid(padding=(0, 3))
    t.add_column(style="dim", min_width=18)
    t.add_column(style="bold white")

    claude_mode = get_claude_mode()
    claude_model = get_claude_model()
    gemini_mode = get_gemini_mode()
    gemini_model = get_gemini_model()

    t.add_row("Config",        str(CONFIG_PATH))
    t.add_row("",              "")
    t.add_row("Claude mode",   f"[medium_purple1]{claude_mode}[/]")
    t.add_row("Claude model",  f"[medium_purple1]{claude_model}[/]")
    t.add_row("Gemini mode",   f"[dodger_blue1]{gemini_mode}[/]")
    t.add_row("Gemini model",  f"[dodger_blue1]{gemini_model}[/]")
    t.add_row("",              "")
    t.add_row("Work dir",      str(WORK_DIR))
    t.add_row("Max steps",     str(MAX_STEPS))
    t.add_row("Language",      SYSTEM_LANGUAGE)
    if ovr:
        t.add_row("Overrides", str(ovr))

    console.print()
    console.print(Panel(
        t,
        title="[bold white]Yapılandırma[/]",
        border_style="dim",
        padding=(0, 2),
        expand=False,
    ))
    console.print()


# ---------------------------------------------------------------------------
# Run handler (shared by REPL and one-shot)
# ---------------------------------------------------------------------------

def _handle_run(
    task: str,
    verbose: bool = False,
    dry_run: bool = False,
    lang: str | None = None,
    batch: bool = True,
    clarify: bool = True,
    review: bool = True,
    max_review_rounds: int = 2,
    auto_deps: bool = False,
    verify_completion: bool = True,
    max_completion_rounds: int = 2,
    session: "SessionState | None" = None,
    session_context: str = "",
) -> "RunResult | None":
    if not task.strip():
        print("Kullanım: /run <görev açıklaması>")
        return None

    from myagent.agent.pipeline import run
    from myagent.i18n.locale import SYSTEM_LANGUAGE

    # ── Session context / continuation resolution ──────────────────────────
    resolved_task = task
    if not session_context and session and session.last_result:
        resolved_task, session_context = session.resolve(task)
        if resolved_task != task:
            from myagent.ui import make_ui
            _ui = make_ui(verbose=verbose)
            _ui.session_context_notice(f"Bağlam → \"{resolved_task[:80]}\"")

    try:
        result = run(
            resolved_task,
            verbose=verbose,
            dry_run=dry_run,
            batch=batch,
            clarify=clarify,
            review=review,
            max_review_rounds=max_review_rounds,
            auto_deps=auto_deps,
            verify_completion=verify_completion,
            max_completion_rounds=max_completion_rounds,
            session_context=session_context,
        )
    except RuntimeError as exc:
        print(f"Hata: {exc}")
        return None

    if session:
        session.update(result)

    # In TTY mode the rich UI already rendered a full summary panel — don't duplicate.
    # In non-TTY mode (piped / CI) print the plain-text summary for scripting use.
    if not sys.stdout.isatty():
        output_lang = lang or SYSTEM_LANGUAGE
        if output_lang == "tr":
            print(f"\n{result.summary_tr}\n")
        else:
            print(f"\n{result.summary_en}\n")

    return result


# ---------------------------------------------------------------------------
# Agentic helper commands
# ---------------------------------------------------------------------------

def _show_history(arg: str = "") -> None:
    """Display past task history."""
    from myagent.memory.history import format_history_table, load_recent
    from myagent.ui import make_ui

    n = 20
    if arg.strip().isdigit():
        n = int(arg.strip())

    text = format_history_table(n)
    ui = make_ui()
    ui.history_table(text)


def _show_last(session: "SessionState") -> None:
    """Show the last task result in this session (or from history if session empty)."""
    from myagent.memory.history import last_run
    from myagent.ui import make_ui
    from myagent.config.settings import WORK_DIR

    ui = make_ui()

    # Prefer live session data
    r = None
    if session.last_result:
        r_live = session.last_result
        files = "\n".join(f"  • {f}" for f in r_live.created_files) or "  (yok)"
        status = "✓" if r_live.success else "✗"
        rev = "✓ review onaylı" if r_live.review_approved else ""
        compl = "✓ tamamlama doğrulandı" if r_live.completion_verified else ""
        flags = "  ".join(filter(None, [rev, compl]))
        msg = (
            f"Son görev: {r_live.task_original}\n"
            f"Durum   : {status}  {flags}\n"
            f"Dosyalar:\n{files}"
        )
        ui.session_context_notice(msg)
        return

    # Fall back to history
    r = last_run()
    if not r:
        print("  (henüz kayıt yok)")
        return

    status = "✓" if r.get("review_approved") or r.get("success") else "✗"
    files = "\n".join(f"  • {f}" for f in r.get("files", [])) or "  (yok)"
    msg = (
        f"Son görev ({r.get('timestamp','')[:16]}): {r.get('task','')}\n"
        f"Durum   : {status}  ID: {r.get('id','')}\n"
        f"Dosyalar:\n{files}"
    )
    ui.session_context_notice(msg)


def _clean_workspace(arg: str = "") -> None:
    """Remove all non-hidden files/dirs from WORK_DIR (asks for confirmation)."""
    from myagent.config.settings import WORK_DIR

    if arg.strip().lower() not in ("--force", "-f", "force"):
        answer = input(
            f"  {WORK_DIR} içindeki tüm dosyalar silinecek. Emin misiniz? (evet/hayır): "
        ).strip().lower()
        if answer not in ("evet", "e", "yes", "y"):
            print("  İptal edildi.")
            return

    import shutil
    removed: list[str] = []
    for p in WORK_DIR.iterdir():
        if p.name.startswith("."):
            continue  # keep .myagent history
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            removed.append(p.name)
        except Exception as exc:
            print(f"  ✗ {p.name}: {exc}")

    if removed:
        print(f"  Silindi: {', '.join(removed)}")
    else:
        print("  Zaten temiz.")


def _handle_chat(
    raw: str,
    session: "SessionState",
    verbose: bool = False,
    dry_run: bool = False,
    lang: str | None = None,
    batch: bool = True,
    clarify: bool = True,
    review: bool = True,
    max_review_rounds: int = 2,
    auto_deps: bool = False,
    verify_completion: bool = True,
    max_completion_rounds: int = 2,
) -> None:
    """Route user input through Chat — either answer directly or execute a task."""
    from myagent.agent.chat import Chat
    from myagent.ui import make_ui

    if session.chat is None:
        session.chat = Chat()

    if session.ui is None:
        session.ui = make_ui(verbose=verbose)
    ui = session.ui

    # Use spinner (no raw streaming) — avoids leaking routing metadata to screen
    with ui.spinner("Claude düşünüyor…", color="medium_purple1"):
        route = session.chat.route(raw)

    if route.action == "answer":
        ui.chat_answer(route.answer)
        return

    # TASK — run through the pipeline
    task = route.task or raw
    result = _handle_run(
        task,
        verbose=verbose,
        dry_run=dry_run,
        lang=lang,
        batch=batch,
        clarify=clarify,
        review=review,
        max_review_rounds=max_review_rounds,
        auto_deps=auto_deps,
        verify_completion=verify_completion,
        max_completion_rounds=max_completion_rounds,
        session=session,
    )

    # Feed result summary back into chat history for context
    if result and session.chat:
        session.chat.add_task_result(
            task=result.task_original,
            summary=result.summary_en,
        )


def _handle_devam(session: "SessionState", run_kwargs: dict) -> None:
    """Show a numbered menu of recent tasks and continue the selected one."""
    from myagent.memory.history import load_recent
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console()

    # Build candidate list: current session first, then history (skip duplicates)
    candidates: list[tuple[str, str, str]] = []  # (label, task, context_hint)

    if session.last_task:
        candidates.append(("Bu oturum", session.last_task, ""))

    seen = {session.last_task}
    for rec in load_recent(8):
        task = rec.get("task", "").strip()
        if not task or task in seen:
            continue
        seen.add(task)
        ts = rec.get("timestamp", "")[:16].replace("T", " ")
        candidates.append((ts, task, ""))

    if not candidates:
        console.print("\n  [dim]Henüz tamamlanmış görev yok.[/]\n")
        return

    # Render selection table
    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold dodger_blue1", min_width=3)
    t.add_column(style="dim", min_width=14)
    t.add_column(style="white")
    for i, (label, task, _) in enumerate(candidates, 1):
        t.add_row(f"[{i}]", label, task[:70] + ("…" if len(task) > 70 else ""))

    w = min(console.width, 76)
    console.print()
    console.print(Panel(
        t,
        title="[bold dodger_blue1]/devam — hangi göreve devam edelim?[/]",
        title_align="left",
        border_style="dodger_blue1",
        padding=(0, 1),
        width=w,
    ))
    console.print(f"  [dim]Seç (1–{len(candidates)}) veya Enter = 1, q = iptal:[/] ", end="")

    try:
        choice = input().strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return

    if choice == "" :
        idx = 0
    elif choice.lower() in ("q", "quit", "iptal"):
        return
    elif choice.isdigit() and 1 <= int(choice) <= len(candidates):
        idx = int(choice) - 1
    else:
        console.print("  [dim]Geçersiz seçim.[/]")
        return

    _, task, ctx = candidates[idx]
    resolved, extra_ctx = session.resolve(task) if session.last_result else (task, "")
    combined_ctx = "\n".join(filter(None, [ctx, extra_ctx]))

    _handle_run(
        resolved,
        session=session,
        session_context=combined_ctx,
        **run_kwargs,
    )


def _show_workspace_files() -> None:
    """List files in WORK_DIR with their owning task."""
    from myagent.config.settings import WORK_DIR
    from myagent.memory.history import get_file_owners

    owners = get_file_owners()
    print(f"\n  Çalışma dizini: {WORK_DIR}")
    any_file = False
    for p in sorted(WORK_DIR.iterdir()):
        if p.name.startswith("."):
            continue
        meta = owners.get(p.name, {})
        task_hint = f"  ← {meta['task'][:50]}" if meta else ""
        print(f"  {'d' if p.is_dir() else 'f'}  {p.name}{task_hint}")
        any_file = True
    if not any_file:
        print("  (boş)")
    print()


# ---------------------------------------------------------------------------
# Readline — arrow keys, history, tab completion
# ---------------------------------------------------------------------------

_COMMANDS = [
    "/help", "/exit", "/quit", "/clear", "/cls",
    "/run", "/devam", "/düzelt", "/fix", "/test",
    "/geçmiş", "/history", "/son", "/last",
    "/dosyalar", "/ls", "/temizle", "/setup",
    "/models", "/config",
]


def _setup_readline() -> None:
    try:
        import readline
        import atexit
        from pathlib import Path

        history_file = Path.home() / ".myagent" / "repl_history"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            pass

        readline.set_history_length(500)
        atexit.register(readline.write_history_file, history_file)

        def _completer(text: str, state: int) -> str | None:
            matches = [c for c in _COMMANDS if c.startswith(text)]
            return matches[state] if state < len(matches) else None

        readline.set_completer(_completer)
        readline.parse_and_bind("tab: complete")

    except ImportError:
        pass  # Windows fallback — no readline, silent


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def _repl(
    verbose: bool,
    dry_run: bool,
    lang: str | None,
    batch: bool = True,
    clarify: bool = True,
    review: bool = True,
    max_review_rounds: int = 2,
    auto_deps: bool = False,
    verify_completion: bool = True,
    max_completion_rounds: int = 2,
) -> None:
    _setup_readline()
    _print_banner()

    session = SessionState()
    _run_kwargs = dict(
        verbose=verbose, dry_run=dry_run, lang=lang, batch=batch,
        clarify=clarify, review=review, max_review_rounds=max_review_rounds,
        auto_deps=auto_deps, verify_completion=verify_completion,
        max_completion_rounds=max_completion_rounds,
    )

    from myagent import interrupt as _interrupt

    while True:
        # Commit any Live panel before showing the prompt
        if session.ui is not None:
            session.ui.stop_live()
        try:
            raw = input("\033[1;35mmyagent\033[0m \033[35m❯\033[0m ").strip()
        except EOFError:
            print("\nGoodbye.")
            break
        except KeyboardInterrupt:
            print()
            continue

        if not raw:
            continue

        # Strip leading "/" — support /command style like Claude Code / Gemini
        if raw.startswith("/"):
            raw = raw[1:]
            if not raw:
                continue

        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        # Wrap entire command in interrupt context so ESC is detected across
        # all steps of a pipeline, not only inside individual streaming calls.
        with _interrupt.context():
            try:
                if cmd in ("exit", "quit", "çıkış", "cikis"):
                    print("Goodbye.")
                    break

                elif cmd in ("help", "yardım", "yardim"):
                    _print_help()

                elif cmd == "run":
                    _handle_run(arg, session=session, **_run_kwargs)

                elif cmd in ("devam", "continue") or raw.lower() == "devam et":
                    _handle_devam(session, _run_kwargs)

                elif cmd in ("düzelt", "duzeltle", "fix", "düzeltle"):
                    resolved, ctx = session.resolve("düzelt")
                    _handle_run(resolved, session=session, session_context=ctx, **_run_kwargs)

                elif raw.lower() in ("test ekle", "testler yaz", "add tests"):
                    resolved, ctx = session.resolve("test ekle")
                    _handle_run(resolved, session=session, session_context=ctx, **_run_kwargs)

                elif cmd in ("geçmiş", "gecmis", "history", "hist"):
                    _show_history(arg)

                elif cmd in ("son", "last"):
                    _show_last(session)

                elif cmd in ("temizle", "clean", "clear-workspace"):
                    _clean_workspace(arg)

                elif cmd in ("dosyalar", "files", "ls"):
                    _show_workspace_files()

                elif cmd == "setup":
                    from myagent.setup_wizard import run_wizard
                    run_wizard()

                elif cmd in ("models", "list-models"):
                    _show_models()

                elif cmd in ("config", "cfg"):
                    _show_config()

                elif cmd in ("clear", "cls"):
                    import os
                    os.system("clear")
                    _print_banner()

                else:
                    _handle_chat(raw, session=session, **_run_kwargs)

            except SystemExit:
                raise
            except _interrupt.Interrupted:
                pass  # cancel message already printed by streaming()
            except KeyboardInterrupt:
                print()
            except Exception as exc:
                print(f"  Hata: {exc}")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # ── 1. Apply runtime overrides from flags ────────────────────────────────
    from myagent.config.auth import apply_overrides
    apply_overrides(
        claude_model=args.claude_model,
        gemini_model=args.gemini_model,
        claude_mode=args.claude_mode,
        gemini_mode=args.gemini_mode,
    )

    # ── 2. Apply env/settings overrides ─────────────────────────────────────
    if args.work_dir:
        import os
        os.environ["MYAGENT_WORK_DIR"] = str(Path(args.work_dir).resolve())

    if args.max_steps is not None:
        import myagent.config.settings as _s
        _s.MAX_STEPS = args.max_steps

    # ── 3. Utility-only flags (no wizard needed) ─────────────────────────────
    if args.setup:
        from myagent.setup_wizard import run_wizard
        run_wizard()
        return

    if args.list_models:
        _show_models()
        return

    if args.config:
        _show_config()
        return

    # ── 4. First-run wizard ──────────────────────────────────────────────────
    from myagent.config.auth import is_configured
    if not is_configured():
        print("\nİlk çalıştırma — kurulum sihirbazı başlatılıyor...")
        from myagent.setup_wizard import run_wizard
        run_wizard()

    # ── 5. Validate required credentials ────────────────────────────────────
    from myagent.config.settings import validate
    missing = validate()
    if missing:
        print(
            f"\nHata: şu ortam değişkenleri tanımlı değil: {', '.join(missing)}\n"
            + "\n".join(f"  export {v}=değer" for v in missing)
            + "\n  veya  myagent --setup  ile auth modunu değiştirin.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── 6. One-shot mode ─────────────────────────────────────────────────────
    batch = not args.sequential
    clarify = args.clarify
    review = not args.no_review
    max_review_rounds = args.max_review_rounds
    auto_deps = args.auto_deps
    verify_completion = not getattr(args, "no_complete", False)
    max_completion_rounds = getattr(args, "max_completion_rounds", 2)

    if args.task:
        _handle_run(
            args.task,
            verbose=args.verbose,
            dry_run=args.dry_run,
            lang=args.lang,
            batch=batch,
            clarify=clarify,
            review=review,
            max_review_rounds=max_review_rounds,
            auto_deps=auto_deps,
            verify_completion=verify_completion,
            max_completion_rounds=max_completion_rounds,
            session=None,   # no session state in one-shot mode
        )
        return

    # ── 7. Interactive TUI or REPL ────────────────────────────────────────────
    if args.tui and sys.stdout.isatty():
        from myagent.tui import start_tui
        session = SessionState()
        start_tui(session, verbose=args.verbose)
    else:
        _repl(
            verbose=args.verbose,
            dry_run=args.dry_run,
            lang=args.lang,
            batch=batch,
            clarify=clarify,
            review=review,
            max_review_rounds=max_review_rounds,
            auto_deps=auto_deps,
            verify_completion=verify_completion,
            max_completion_rounds=max_completion_rounds,
        )


if __name__ == "__main__":
    main()
