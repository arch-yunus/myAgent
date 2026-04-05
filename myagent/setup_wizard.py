"""
First-run setup wizard — Rich UI version.
"""

from __future__ import annotations

import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from myagent.config.auth import (
    API, CLI, CLAUDE_WORKER, AuthMode,
    detect_claude, detect_gemini,
    save_config,
)
from myagent.models import (
    CLAUDE_CURATED, CLAUDE_DEFAULT,
    GEMINI_CURATED, GEMINI_DEFAULT,
    ModelInfo,
    fetch_claude_models, fetch_gemini_models,
)

_console = Console()

_MODE_DESC: dict[str, tuple[str, str]] = {
    API:           ("API key",    "~2s/adım  ·  GEMINI_API_KEY"),
    CLI:           ("Gemini CLI", "~40s/adım  ·  Node.js startup yavaş"),
    CLAUDE_WORKER: ("Claude CLI", "~5s/adım  ·  Claude Code auth"),
}
_CLAUDE_MODE_DESC: dict[str, tuple[str, str]] = {
    API: ("API key",  "~3s/plan  ·  ANTHROPIC_API_KEY"),
    CLI: ("CLI auth", "~5s/plan  ·  Claude Code OAuth"),
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_wizard() -> None:
    _header()

    with _console.status("[dim]Mevcut auth seçenekleri taranıyor…[/]", spinner="dots"):
        claude_modes = detect_claude()
        gemini_modes = detect_gemini()

    _print_detection(claude_modes, gemini_modes)

    if not claude_modes:
        _fatal(
            "Claude için auth bulunamadı.\n"
            "  [dim]export ANTHROPIC_API_KEY=sk-ant-…[/]   (API modu)\n"
            "  [dim]claude login[/]                        (CLI modu)"
        )
    if not gemini_modes:
        _fatal(
            "Worker backend bulunamadı.\n"
            "  [dim]export GEMINI_API_KEY=AIza…[/]         (Gemini API)\n"
            "  [dim]claude login[/]                        (Claude worker)"
        )

    claude_mode  = _pick_claude_mode(claude_modes)
    gemini_mode  = _pick_worker_backend(gemini_modes)
    claude_model = _pick_model("Claude (Planner)", claude_mode)

    if gemini_mode == API:
        gemini_model = _pick_model("Gemini (Worker)", gemini_mode)
    elif gemini_mode == CLAUDE_WORKER:
        _console.print(f"  [dim]Worker modeli → planner ile aynı:[/] [medium_purple1]{claude_model}[/]")
        gemini_model = claude_model
    else:
        gemini_model = GEMINI_DEFAULT
        _console.print(f"  [dim]Gemini CLI varsayılan modeli kullanılıyor:[/] [dodger_blue1]{gemini_model}[/]")

    save_config({
        "claude_mode":  claude_mode,
        "claude_model": claude_model,
        "gemini_mode":  gemini_mode,
        "gemini_model": gemini_model,
    })

    _summary(claude_mode, claude_model, gemini_mode, gemini_model)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _header() -> None:
    _console.print()
    _console.print(Panel(
        Text.assemble(
            ("Kurulum Sihirbazı", "bold white"),
            ("  ·  ", "dim"),
            ("myagent", "bold medium_purple1"),
        ),
        border_style="medium_purple1",
        padding=(0, 2),
        subtitle="[dim]Auth ve model seçimi[/]",
    ))
    _console.print()


# ---------------------------------------------------------------------------
# Detection report
# ---------------------------------------------------------------------------

def _print_detection(
    claude_modes: list[AuthMode],
    gemini_modes: list[AuthMode],
) -> None:
    t = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 2))
    t.add_column("Bileşen",  style="dim", min_width=20)
    t.add_column("Mod",      min_width=10)
    t.add_column("Açıklama", style="dim")
    t.add_column("Durum",    justify="right")

    for mode in (API, CLI):
        found = mode in claude_modes
        name, desc = _CLAUDE_MODE_DESC.get(mode, (mode, ""))
        status = "[green3]✓ mevcut[/]" if found else "[red1]✗ yok[/]"
        t.add_row("Claude (Planner)", f"[bold]{mode.upper()}[/]", f"{name}  {desc}", status)

    t.add_row("", "", "", "")

    for mode in (API, CLAUDE_WORKER, CLI):
        found = mode in gemini_modes
        name, desc = _MODE_DESC.get(mode, (mode, ""))
        status = "[green3]✓ mevcut[/]" if found else "[red1]✗ yok[/]"
        rec = "  [green3]← önerilir[/]" if found and mode in (API, CLAUDE_WORKER) else ""
        t.add_row("Worker Backend", f"[bold]{mode.upper()}[/]", f"{name}  {desc}{rec}", status)

    _console.print(Panel(t, title="[bold white]Tespit Sonuçları[/]", border_style="dim", padding=(0, 1), expand=False))
    _console.print()


# ---------------------------------------------------------------------------
# Pickers
# ---------------------------------------------------------------------------

def _pick_claude_mode(available: list[AuthMode]) -> AuthMode:
    opts = [m for m in available if m in (API, CLI)]
    if len(opts) == 1:
        _console.print(f"  Claude Planner  [dim]→ tek seçenek:[/] [medium_purple1 bold]{opts[0].upper()}[/]")
        return opts[0]
    return _pick_from(
        "Claude Planner modu",
        [(m.upper(), f"{_CLAUDE_MODE_DESC.get(m, (m,''))[0]}  [dim]{_CLAUDE_MODE_DESC.get(m, ('',''))[1]}[/]") for m in opts],
        color="medium_purple1",
        values=opts,
    )


def _pick_worker_backend(available: list[AuthMode]) -> AuthMode:
    preferred_order = [API, CLAUDE_WORKER, CLI]
    opts = [m for m in preferred_order if m in available]
    if len(opts) == 1:
        _console.print(f"  Worker Backend  [dim]→ tek seçenek:[/] [dodger_blue1 bold]{opts[0].upper()}[/]")
        return opts[0]

    rows = []
    for m in opts:
        name, desc = _MODE_DESC.get(m, (m, ""))
        rec = "  [green3]← önerilir[/]" if m in (API, CLAUDE_WORKER) and opts[0] == m else ""
        rows.append((m.upper(), f"{name}  [dim]{desc}[/]{rec}"))

    return _pick_from("Worker Backend", rows, color="dodger_blue1", values=opts)


def _pick_model(label: str, mode: AuthMode) -> str:
    is_claude = "Claude" in label
    models = _load_models(label, mode)
    default = CLAUDE_DEFAULT if is_claude else GEMINI_DEFAULT
    color = "medium_purple1" if is_claude else "dodger_blue1"

    rows = []
    for m in models:
        rec = "  [green3]★[/]" if m.is_recommended else ""
        aliases = f"  [dim]{', '.join(m.aliases)}[/]" if m.aliases else ""
        rows.append((m.id + rec, f"{m.description}{aliases}"))
    rows.append(("[dim]Manuel giriş[/]", ""))
    rows.append(("[dim]Varsayılanı kullan[/]", f"[dim]{default}[/]"))

    choice = _pick_from(label + " modeli", rows, color=color, values=None)

    n = len(models)
    if choice == n + 2:
        _console.print(f"  [dim]Varsayılan:[/] [{color}]{default}[/]")
        return default
    if choice == n + 1:
        raw = _console.input(f"  [dim]Model ID:[/] [{color}]").strip()
        _console.print("[/]", end="")
        return raw or default
    selected = models[choice - 1]
    _console.print(f"  [{color}]✓ Seçildi:[/] {selected.id}")
    return selected.id


def _load_models(label: str, mode: AuthMode) -> list[ModelInfo]:
    is_claude = "Claude" in label
    if mode == API:
        api_key = (
            os.environ.get("ANTHROPIC_API_KEY", "")
            if is_claude
            else (os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", ""))
        )
        if api_key:
            with _console.status("[dim]API'den modeller getiriliyor…[/]", spinner="dots"):
                result = fetch_claude_models(api_key) if is_claude else fetch_gemini_models(api_key)
            return result
    return CLAUDE_CURATED if is_claude else GEMINI_CURATED


# ---------------------------------------------------------------------------
# Generic picker (numbered menu)
# ---------------------------------------------------------------------------

def _pick_from(
    title: str,
    rows: list[tuple[str, str]],
    color: str,
    values: list | None,
) -> int | str:
    """Render a numbered menu panel, return the selected value or 1-based index."""
    t = Table.grid(padding=(0, 3))
    t.add_column(style="dim", justify="right", width=4)
    t.add_column(style=f"bold {color}", min_width=16)
    t.add_column(style="dim white")
    for i, (name, desc) in enumerate(rows, 1):
        t.add_row(f"{i})", name, desc)

    _console.print()
    _console.print(Panel(t, title=f"[bold {color}]{title}[/]", border_style=color, padding=(0, 1), expand=False))

    while True:
        raw = _console.input(f"  [dim]Seçim [1-{len(rows)}]:[/] [{color}]").strip()
        _console.print("[/]", end="")
        if raw.isdigit() and 1 <= int(raw) <= len(rows):
            idx = int(raw)
            if values is not None:
                return values[idx - 1]
            return idx
        _console.print(f"  [red1]Geçersiz.[/] [dim]1-{len(rows)} arası bir sayı girin.[/]")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summary(
    claude_mode: str, claude_model: str,
    gemini_mode: str, gemini_model: str,
) -> None:
    t = Table.grid(padding=(0, 3))
    t.add_column(style="dim", min_width=18)
    t.add_column(style="bold white")

    t.add_row("Claude Planner",  f"[medium_purple1]{claude_mode.upper()}[/]  {claude_model}")
    t.add_row("Worker Backend",  f"[dodger_blue1]{gemini_mode.upper()}[/]  {gemini_model}")
    t.add_row("", "")
    t.add_row("Kaydedildi",      "[dim]~/.myagent/config.json[/]")

    _console.print()
    _console.print(Panel(
        t,
        title="[bold green3]✓ Yapılandırma Tamamlandı[/]",
        border_style="green3",
        padding=(0, 2),
        expand=False,
    ))
    _console.print()
    _console.print("  [dim]Değiştirmek için:[/]  myagent> [bold]setup[/]  veya  [bold]myagent --setup[/]")
    _console.print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fatal(message: str) -> None:
    _console.print()
    _console.print(Panel(
        Text.from_markup(f"[red1]✗[/] {message}"),
        border_style="red1",
        title="[red1]Hata[/]",
        padding=(0, 1),
        expand=False,
    ))
    sys.exit(1)
