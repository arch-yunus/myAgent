"""
Clarifier — Claude asks the user clarifying questions before planning.

If the task is unambiguous, returns it unchanged (CLEAR).
If clarification helps, interactively asks the user and returns an enriched task.
Falls back gracefully when running in non-interactive (piped) mode.
"""

from __future__ import annotations

import re
import subprocess
import sys

from myagent.config.settings import ANTHROPIC_API_KEY, PROMPTS_DIR


def _system_prompt() -> str:
    return (PROMPTS_DIR / "clarifier.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def clarify(task: str, verbose: bool = False) -> str:
    """Ask Claude if clarification is needed.

    Returns the original task (if CLEAR) or an enriched task string
    that includes user answers to clarifying questions.
    Falls back to the original task on any error or in non-TTY mode.
    """
    if not sys.stdin.isatty():
        return task  # non-interactive — skip silently

    raw = _ask_claude(task)
    if verbose:
        print(f"  [clarifier raw]\n{raw}\n", flush=True)

    questions = _parse_questions(raw)
    if not questions:
        return task  # CLEAR

    # ── Ask the user ─────────────────────────────────────────────────────────
    print("\n  Başlamadan önce birkaç sorum var:\n", flush=True)
    answers: list[str] = []
    for i, q in enumerate(questions, 1):
        print(f"  {i}. {q}", flush=True)
        try:
            answer = input("     > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if answer:
            answers.append(f"Q: {q}\nA: {answer}")

    if not answers:
        return task

    qa_block = "\n".join(answers)
    enriched = f"{task}\n\nEk bağlam (kullanıcıdan):\n{qa_block}"
    if verbose:
        print(f"  [clarifier] zenginleştirilmiş görev:\n{enriched}\n", flush=True)
    return enriched


# ---------------------------------------------------------------------------
# Claude call
# ---------------------------------------------------------------------------

def _ask_claude(task: str) -> str:
    from myagent.config.auth import CLI, get_claude_mode, get_claude_model
    mode = get_claude_mode()
    system = _system_prompt()

    if mode == CLI:
        full_prompt = f"{system}\n\nTask: {task}"
        try:
            result = subprocess.run(
                ["claude", "-p", full_prompt, "--model", get_claude_model()],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return "CLEAR"
            return result.stdout.strip()
        except Exception:
            return "CLEAR"
    else:
        if not ANTHROPIC_API_KEY:
            return "CLEAR"
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=get_claude_model(),
                max_tokens=256,
                system=system,
                messages=[{"role": "user", "content": task}],
            )
            return response.content[0].text.strip()
        except Exception:
            return "CLEAR"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse_questions(text: str) -> list[str]:
    """Return list of questions, or empty list if output is CLEAR."""
    first_line = text.strip().splitlines()[0].strip().upper() if text.strip() else ""
    if first_line == "CLEAR":
        return []
    questions = []
    for line in text.splitlines():
        m = re.match(r"^QUESTION:\s*(.+)$", line.strip(), re.IGNORECASE)
        if m:
            questions.append(m.group(1).strip())
    return questions
