"""
First-run setup wizard.

Steps:
  1. Detect available auth/backend options for Claude and Gemini worker
  2. Ask which auth mode to use (api / cli) for Claude planner
  3. Ask which worker backend to use (api / cli / claude)
  4. Fetch or show available model variants
  5. Persist to ~/.myagent/config.json

Invoked automatically on first `myagent` run (no config file), and at any
time via:  myagent> setup  or  myagent --setup
"""

from __future__ import annotations

import os
import sys

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

_DETECT_ICON = {True: "✓", False: "✗"}

# Speed labels shown in wizard
_MODE_LABEL: dict[str, str] = {
    API:           "API key      (~2s/adım)   GEMINI_API_KEY env var",
    CLI:           "Gemini CLI   (~40s/adım)  Node.js startup yavaş — önerilmez",
    CLAUDE_WORKER: "Claude CLI   (~5s/adım)   Mevcut Claude Code auth — önerilir",
}
_CLAUDE_MODE_LABEL: dict[str, str] = {
    API: "API key   (~3s/plan)  ANTHROPIC_API_KEY env var",
    CLI: "CLI auth  (~5s/plan)  Mevcut Claude Code OAuth",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_wizard() -> None:
    _header()

    claude_modes = detect_claude()
    gemini_modes = detect_gemini()
    _print_detection_report(claude_modes, gemini_modes)

    if not claude_modes:
        _fatal(
            "Claude için auth bulunamadı.\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...    (API modu)\n"
            "  claude login                            (CLI modu)"
        )
    if not gemini_modes:
        _fatal(
            "Worker backend bulunamadı.\n"
            "  export GEMINI_API_KEY=AIza...           (Gemini API)\n"
            "  claude login                            (Claude worker)"
        )

    # ── Claude planner auth ──────────────────────────────────────────────────
    claude_mode = _pick_claude_mode(claude_modes)

    # ── Worker backend ───────────────────────────────────────────────────────
    gemini_mode = _pick_worker_backend(gemini_modes)

    # ── Model selection ──────────────────────────────────────────────────────
    print()
    claude_model = _pick_model("Claude (Planner)", claude_mode)
    print()

    # Worker model: only relevant for gemini api mode
    if gemini_mode == API:
        gemini_model = _pick_model("Gemini (Worker)", gemini_mode)
    elif gemini_mode == CLAUDE_WORKER:
        print(f"  Worker (Claude): planner ile aynı model kullanılıyor ({claude_model})")
        gemini_model = claude_model
    else:
        print(f"  Worker (Gemini CLI): model seçimi desteklenmiyor, varsayılan kullanılacak.")
        gemini_model = GEMINI_DEFAULT

    # ── Persist ─────────────────────────────────────────────────────────────
    save_config({
        "claude_mode": claude_mode,
        "claude_model": claude_model,
        "gemini_mode": gemini_mode,
        "gemini_model": gemini_model,
    })

    _summary(claude_mode, claude_model, gemini_mode, gemini_model)


# ---------------------------------------------------------------------------
# Detection report
# ---------------------------------------------------------------------------

def _header() -> None:
    print()
    print("╔══════════════════════════════════════════╗")
    print("║        myagent — kurulum sihirbazı       ║")
    print("╚══════════════════════════════════════════╝")
    print()


def _print_detection_report(
    claude_modes: list[AuthMode],
    gemini_modes: list[AuthMode],
) -> None:
    print("Mevcut seçenekler taranıyor...\n")
    print("  Claude (Planner):")
    for mode in (API, CLI):
        found = mode in claude_modes
        print(f"    {_DETECT_ICON[found]}  {mode.upper():<3}  {_CLAUDE_MODE_LABEL.get(mode, mode)}")
    print()
    print("  Worker Backend:")
    for mode in (API, CLI, CLAUDE_WORKER):
        found = mode in gemini_modes
        print(f"    {_DETECT_ICON[found]}  {mode.upper():<6}  {_MODE_LABEL.get(mode, mode)}")
    print()


# ---------------------------------------------------------------------------
# Pickers
# ---------------------------------------------------------------------------

def _pick_claude_mode(available: list[AuthMode]) -> AuthMode:
    planner_opts = [m for m in available if m in (API, CLI)]
    if not planner_opts:
        _fatal("Claude planner için seçenek yok.")
    if len(planner_opts) == 1:
        mode = planner_opts[0]
        print(f"  Claude Planner: tek seçenek → {mode.upper()} otomatik seçildi.")
        return mode
    print("  Claude (Planner) — hangi mod kullanılsın?")
    for i, m in enumerate(planner_opts, 1):
        print(f"    {i})  {m.upper():<3}  {_CLAUDE_MODE_LABEL.get(m, m)}")
    return planner_opts[_prompt_index(len(planner_opts)) - 1]


def _pick_worker_backend(available: list[AuthMode]) -> AuthMode:
    # Prefer: api > claude > cli  (by speed)
    preferred_order = [API, CLAUDE_WORKER, CLI]
    opts = [m for m in preferred_order if m in available]
    if not opts:
        _fatal("Worker backend için seçenek yok.")
    if len(opts) == 1:
        mode = opts[0]
        print(f"  Worker Backend: tek seçenek → {mode.upper()} otomatik seçildi.")
        return mode
    print("  Worker Backend — hangi seçenek kullanılsın?")
    for i, m in enumerate(opts, 1):
        rec = "  ← önerilir" if m in (API, CLAUDE_WORKER) and opts[0] == m else ""
        print(f"    {i})  {m.upper():<6}  {_MODE_LABEL.get(m, m)}{rec}")
    return opts[_prompt_index(len(opts)) - 1]


def _pick_model(label: str, mode: AuthMode) -> str:
    print(f"  {label} — model seçin:")
    models = _load_models(label, mode)
    for i, m in enumerate(models, 1):
        rec = " *" if m.is_recommended else "  "
        aliases = f"  (alias: {', '.join(m.aliases)})" if m.aliases else ""
        print(f"   {i:>2}){rec} {m.id:<38}{aliases}")
        print(f"         {m.description}")
    if any(m.is_recommended for m in models):
        print("       (* = önerilir)")
    n = len(models)
    print(f"    {n+1})  Manuel giriş")
    print(f"    {n+2})  Varsayılanı kullan")

    choice = _prompt_index(n + 2)
    if choice == n + 2:
        default = CLAUDE_DEFAULT if "Claude" in label else GEMINI_DEFAULT
        print(f"  Varsayılan: {default}")
        return default
    if choice == n + 1:
        raw = input("  Model ID: ").strip()
        return raw or (CLAUDE_DEFAULT if "Claude" in label else GEMINI_DEFAULT)
    selected = models[choice - 1]
    print(f"  Seçildi: {selected.id}")
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
            print(f"  API'den modeller getiriliyor...", end=" ", flush=True)
            result = fetch_claude_models(api_key) if is_claude else fetch_gemini_models(api_key)
            print("tamam.")
            return result
    return CLAUDE_CURATED if is_claude else GEMINI_CURATED


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summary(claude_mode: str, claude_model: str, gemini_mode: str, gemini_model: str) -> None:
    print()
    print("─" * 52)
    print("Kaydedildi → ~/.myagent/config.json")
    print()
    print(f"  Claude Planner : {claude_mode.upper():<6}  model: {claude_model}")
    print(f"  Worker Backend : {gemini_mode.upper():<6}  model: {gemini_model}")
    print()
    print("Değiştirmek için:  myagent> setup  veya  myagent --setup")
    print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prompt_index(max_: int) -> int:
    while True:
        raw = input(f"  Seçim [1-{max_}]: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= max_:
            return int(raw)
        print(f"  Geçersiz. 1-{max_} arası bir sayı girin.")


def _fatal(message: str) -> None:
    print(f"\nHata: {message}\n", file=sys.stderr)
    sys.exit(1)
