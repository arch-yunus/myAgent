"""
Terminal UI — rich-based live display for the myagent pipeline.

Shows:
  • Spinner while waiting for Claude / Gemini
  • Plan steps table
  • Per-step execution results with icons
  • Dependency installs
  • Review rounds (ruff / test / Claude feedback)
  • Fix steps
  • Timing summary

Verbose mode (--verbose / --thinking): also prints raw model I/O
in dimmed panels so you can see exactly what each model received/returned.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from myagent.agent.executor import ExecutionResult

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
C_CLAUDE  = "medium_purple1"
C_GEMINI  = "dodger_blue1"
C_OK      = "green3"
C_WARN    = "yellow3"
C_ERR     = "red1"
C_DIM     = "grey50"
C_RUFF    = "cyan2"
C_TASK    = "bold white"

_SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _live_status(label: str, color: str, start: float, tokens: list):
    """Rich renderable: spinner + label + elapsed + token count.
    Called by Live on every refresh — auto-updates time and spinner frame.
    """
    class _R:
        def __rich__(self_r) -> Text:
            elapsed = time.time() - start
            secs = int(elapsed)
            e = f"{secs // 60}m {secs % 60:02d}s" if secs >= 60 else f"{secs}s"
            ch = _SPIN[int(elapsed * 10) % len(_SPIN)]
            parts: list = [
                (f"  {ch} ", color),
                (label, f"bold {color}"),
                (f"   {e}", "dim"),
            ]
            if tokens[0]:
                parts.append((f"  ↓ {tokens[0]:,}", "dim"))
            return Text.assemble(*parts)
    return _R()


class AgentUI:
    def __init__(self, verbose: bool = False):
        self.console = Console(highlight=False)
        self.verbose = verbose
        self._t0 = time.time()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _elapsed(self) -> str:
        s = int(time.time() - self._t0)
        return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"

    def _icon(self, ok: bool) -> str:
        return "✓" if ok else "✗"

    # ── Header ───────────────────────────────────────────────────────────────

    def header(self, task: str, claude_model: str, gemini_model: str) -> None:
        self.console.print()
        self.console.print(Rule(
            f"[{C_CLAUDE}]Claude[/] [{C_DIM}]↔[/] [{C_GEMINI}]Gemini[/]  "
            f"[{C_DIM}]{claude_model}  /  {gemini_model}[/]",
            style=C_DIM,
        ))
        self.console.print(f"\n[{C_TASK}]Görev:[/] {escape(task)}\n")

    # ── Spinner context manager (non-model ops: ruff, deps, pytest…) ────────

    @contextmanager
    def spinner(self, label: str, color: str = C_DIM):
        start = time.time()
        tokens: list[int] = [0]
        status = _live_status(label, color, start, tokens)
        with Live(status, console=self.console, refresh_per_second=10, transient=True):
            yield
        secs = int(time.time() - start)
        e = f"{secs // 60}m {secs % 60:02d}s" if secs >= 60 else f"{secs}s"
        self.console.print(f"  [{C_DIM}]↳ {escape(label)}[/]  [{C_DIM}]{e}[/]")

    # ── Streaming context manager (model calls: Gemini / Claude) ────────────

    @contextmanager
    def streaming(self, label: str, color: str = C_DIM):
        """Live streaming display with resize-responsive status bar.

        Yields a write(text) callable. Streamed lines are printed to the
        console (scrollback); a live status bar at the bottom shows the
        operation label, elapsed time, and estimated token count. The bar
        updates at 10 fps and redraws on terminal resize automatically.
        ESC or Ctrl+C raises Interrupted.
        """
        from myagent import interrupt

        start = time.time()
        pending: list[str] = []
        tokens: list[int] = [0]
        status = _live_status(label, color, start, tokens)

        def write(chunk: str) -> None:
            if not chunk:
                return
            tokens[0] += max(1, len(chunk) // 4)
            pending.append(chunk)
            text = "".join(pending)
            parts = text.split("\n")
            for line in parts[:-1]:
                s = line.rstrip()
                if s:
                    self.console.print(f"    [grey42]{escape(s)}[/]")
            pending.clear()
            pending.append(parts[-1])

        def _flush() -> None:
            tail = "".join(pending).rstrip()
            if tail:
                self.console.print(f"    [grey42]{escape(tail)}[/]")
            pending.clear()

        # interrupt.context() is managed at the REPL level (cli.py) so ESC is
        # detected across the entire command, not just during streaming calls.
        try:
            with Live(status, console=self.console, refresh_per_second=10, transient=True):
                try:
                    yield write
                except interrupt.Interrupted:
                    _flush()
                    raise
                finally:
                    _flush()
        except interrupt.Interrupted:
            secs = int(time.time() - start)
            e = f"{secs // 60}m {secs % 60:02d}s" if secs >= 60 else f"{secs}s"
            self.console.print(f"  [{C_ERR}]⊗ İptal edildi[/]  [{C_DIM}]({e})[/]")
            raise

        secs = int(time.time() - start)
        e = f"{secs // 60}m {secs % 60:02d}s" if secs >= 60 else f"{secs}s"
        tc = f"  [{C_DIM}]↓ {tokens[0]:,}[/]" if tokens[0] else ""
        self.console.print(f"  [{C_DIM}]({e})[/]{tc}")

    # ── Planning ─────────────────────────────────────────────────────────────

    def plan_done(self, steps: list[str]) -> None:
        t = Table.grid(padding=(0, 2))
        t.add_column(style=C_DIM, justify="right")
        t.add_column()
        for i, s in enumerate(steps, 1):
            t.add_row(f"[{C_CLAUDE}]{i}[/]", escape(s))
        self.console.print(Panel(
            t,
            title=f"[{C_CLAUDE}]Plan — {len(steps)} adım[/]",
            border_style=C_CLAUDE,
            padding=(0, 1),
        ))

    # ── Execution ────────────────────────────────────────────────────────────

    def exec_results(self, steps: list[str], results: list[ExecutionResult]) -> None:
        t = Table.grid(padding=(0, 1))
        t.add_column(style=C_DIM, justify="right", width=4)
        t.add_column(width=2)
        t.add_column()
        for i, (step, r) in enumerate(zip(steps, results), 1):
            icon_style = C_OK if r.ok else C_ERR
            icon = self._icon(r.ok)
            detail = r.message if not r.ok else (
                r.details.get("filename", r.message) if r.kind == "file" else r.message
            )
            t.add_row(f"[{C_DIM}]{i}[/]", f"[{icon_style}]{icon}[/]", escape(detail))
        self.console.print(Panel(
            t,
            title=f"[{C_GEMINI}]Yürütme[/]",
            border_style=C_GEMINI,
            padding=(0, 1),
        ))

    # ── Missing-file retry ───────────────────────────────────────────────────

    def missing_files_retry(self, steps: list[str]) -> None:
        self.console.print(
            f"  [{C_WARN}]⚠ Eksik dosya(lar) — yeniden deneniyor: "
            + ", ".join(escape(s[:60]) for s in steps)
            + "[/]"
        )

    # ── Dependencies ─────────────────────────────────────────────────────────

    def dep_found(self, packages: list[str]) -> None:
        self.console.print(
            f"  [{C_WARN}]⬡ Eksik paket:[/] {', '.join(packages)}"
        )

    def dep_installed(self, pip_name: str) -> None:
        self.console.print(f"  [{C_OK}]✓ {escape(pip_name)} kuruldu[/]")

    def dep_skipped(self, pip_name: str) -> None:
        self.console.print(f"  [{C_DIM}]– {escape(pip_name)} atlandı[/]")

    def dep_error(self, pip_name: str, msg: str) -> None:
        self.console.print(f"  [{C_ERR}]✗ {escape(pip_name)}: {escape(msg[:120])}[/]")

    # ── Review ───────────────────────────────────────────────────────────────

    def review_ruff_clean(self) -> None:
        self.console.print(f"  [{C_RUFF}]✓ ruff — temiz[/]")

    def review_ruff_issues(self, n: int) -> None:
        self.console.print(f"  [{C_WARN}]⚠ ruff — {n} sorun[/]")

    def review_ruff_fixed(self) -> None:
        self.console.print(f"  [{C_RUFF}]✓ ruff --fix uygulandı[/]")

    def review_test_pass(self, fname: str) -> None:
        self.console.print(f"  [{C_OK}]✓ test geçti: {escape(fname)}[/]")

    def review_test_fail(self, fname: str) -> None:
        self.console.print(f"  [{C_ERR}]✗ test başarısız: {escape(fname)}[/]")

    def review_approved(self, round_num: int) -> None:
        self.console.print(
            f"  [{C_OK}]✓ Review onaylandı[/] [{C_DIM}](tur {round_num})[/]"
        )

    def review_fix_steps(self, steps: list[str]) -> None:
        self.console.print(f"  [{C_WARN}]↻ Düzeltme gerekiyor ({len(steps)} adım):[/]")
        for i, s in enumerate(steps, 1):
            self.console.print(f"    [{C_DIM}]{i}.[/] {escape(s[:100])}")

    def review_stuck(self, n_errors: int) -> None:
        self.console.print(
            f"  [{C_ERR}]⚠ Kısır döngü ({n_errors} hata, azalmıyor) — durduruluyor[/]"
        )

    def review_max_rounds(self, n: int) -> None:
        self.console.print(f"  [{C_WARN}]⚠ Max review turu doldu ({n})[/]")

    # ── Completion verification ──────────────────────────────────────────────

    def completion_verified(self) -> None:
        self.console.print(f"  [{C_OK}]✓ Tamamlama doğrulandı[/]")

    def completion_missing(self, steps: list[str]) -> None:
        self.console.print(f"  [{C_WARN}]⚠ Eksiklikler tespit edildi ({len(steps)} adım):[/]")
        for i, s in enumerate(steps, 1):
            self.console.print(f"    [{C_DIM}]{i}.[/] {escape(s[:120])}")

    def completion_max_rounds(self, n: int) -> None:
        self.console.print(f"  [{C_WARN}]⚠ Max tamamlama turu doldu ({n})[/]")

    # ── Session context ──────────────────────────────────────────────────────

    def session_context_notice(self, notice: str) -> None:
        self.console.print(f"  [{C_DIM}]ℹ {escape(notice)}[/]")

    # ── History display ──────────────────────────────────────────────────────

    def history_table(self, text: str) -> None:
        from rich.text import Text as RText
        self.console.print(Panel(
            RText(text),
            title=f"[{C_CLAUDE}]Görev Geçmişi[/]",
            border_style=C_CLAUDE,
            padding=(0, 1),
        ))

    # ── Chat answer display ──────────────────────────────────────────────────

    def chat_answer(self, text: str) -> None:
        from rich.markdown import Markdown
        # Cap at 120 cols: looks good on wide terminals, stays intact when
        # user resizes to ~half-screen. Scrollback content can't reflow so
        # full-terminal-width panels break if the terminal is later narrowed.
        w = min(self.console.width, 120)
        self.console.print()
        self.console.print(Panel(
            Markdown(text),
            title=f"[{C_CLAUDE}]Claude[/]",
            title_align="left",
            border_style=C_CLAUDE,
            padding=(1, 2),
            width=w,
        ))
        self.console.print()

    # ── Raw model output (verbose) ────────────────────────────────────────────

    def raw(self, label: str, text: str, color: str = C_DIM) -> None:
        if not self.verbose:
            return
        self.console.print(Panel(
            Text(text.strip(), style=C_DIM),
            title=f"[{color}]{escape(label)}[/]",
            border_style=C_DIM,
            padding=(0, 1),
        ))

    # ── Summary ──────────────────────────────────────────────────────────────

    def summary(self, success: bool, review_approved: bool,
                n_review_rounds: int, created_files: list[str]) -> None:
        self.console.print()
        status_icon = f"[{C_OK}]✓[/]" if success else f"[{C_ERR}]✗[/]"
        rev_icon = f"[{C_OK}]✓[/]" if review_approved else f"[{C_WARN}]~[/]"

        cols = Table.grid(padding=(0, 3))
        cols.add_column()
        cols.add_column()
        cols.add_row(
            f"{status_icon} {'Tamamlandı' if success else 'Hatalarla tamamlandı'}",
            f"{rev_icon} {'Review onaylı' if review_approved else 'Review kısmen'}",
        )
        if created_files:
            cols.add_row(
                f"[{C_DIM}]Dosyalar:[/] {', '.join(escape(f) for f in created_files)}",
                f"[{C_DIM}]Süre:[/] {self._elapsed()}",
            )

        self.console.print(Panel(
            cols,
            border_style=C_OK if success else C_WARN,
            padding=(0, 1),
        ))
        self.console.print()


# ---------------------------------------------------------------------------
# Null UI — used when rich is unavailable or output is piped
# ---------------------------------------------------------------------------

class NullUI:
    """Fallback: plain print() behaviour, no rich formatting."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def header(self, task, claude_model, gemini_model): pass

    @contextmanager
    def spinner(self, label, color=None):
        print(f"  {label}...", flush=True)
        yield

    @contextmanager
    def streaming(self, label, color=None):
        print(f"  {label}...", flush=True)

        def write(chunk: str) -> None:
            print(chunk, end="", flush=True)

        yield write
        print(flush=True)

    def plan_done(self, steps):
        print(f"  Plan ({len(steps)} adım):")
        for i, s in enumerate(steps, 1):
            print(f"    {i}. {s}")

    def exec_results(self, steps, results):
        for i, r in enumerate(results, 1):
            print(f"  adım {i}: {r.message}")

    def missing_files_retry(self, steps):
        print(f"  Eksik dosya retry: {len(steps)} adım")

    def dep_found(self, packages):
        print(f"  [deps] eksik: {', '.join(packages)}")

    def dep_installed(self, pip_name):
        print(f"  [deps] {pip_name} kuruldu")

    def dep_skipped(self, pip_name):
        print(f"  [deps] {pip_name} atlandı")

    def dep_error(self, pip_name, msg):
        print(f"  [deps] hata: {pip_name}: {msg}")

    def review_ruff_clean(self):
        print("  [ruff] temiz")

    def review_ruff_issues(self, n):
        print(f"  [ruff] {n} sorun")

    def review_ruff_fixed(self):
        print("  [ruff --fix] uygulandı")

    def review_test_pass(self, fname):
        print(f"  [test] geçti: {fname}")

    def review_test_fail(self, fname):
        print(f"  [test] başarısız: {fname}")

    def review_approved(self, round_num):
        print(f"  onaylandı (tur {round_num})")

    def review_fix_steps(self, steps):
        print(f"  düzeltme ({len(steps)} adım):")
        for i, s in enumerate(steps, 1):
            print(f"    {i}. {s}")

    def review_stuck(self, n):
        print(f"  kısır döngü ({n} hata) — durduruluyor")

    def review_max_rounds(self, n):
        print(f"  max tur ({n})")

    def completion_verified(self):
        print("  tamamlama doğrulandı")

    def completion_missing(self, steps):
        print(f"  eksik ({len(steps)} adım):")
        for i, s in enumerate(steps, 1):
            print(f"    {i}. {s}")

    def completion_max_rounds(self, n):
        print(f"  max tamamlama turu ({n})")

    def session_context_notice(self, notice):
        print(f"  ℹ {notice}")

    def history_table(self, text):
        print(text)

    def chat_answer(self, text: str) -> None:
        print(text)

    def raw(self, label, text, color=None):
        if self.verbose:
            print(f"\n--- {label} ---\n{text}\n")

    def summary(self, success, review_approved, n_review_rounds, created_files):
        status = "Tamamlandı" if success else "Hatalarla tamamlandı"
        print(f"\n{status}. Dosyalar: {', '.join(created_files)}\n")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_ui(verbose: bool = False) -> AgentUI | NullUI:
    """Return AgentUI if rich is available and stdout is a TTY, else NullUI."""
    import sys
    try:
        import rich  # noqa: F401
        if sys.stdout.isatty():
            return AgentUI(verbose=verbose)
    except ImportError:
        pass
    return NullUI(verbose=verbose)
