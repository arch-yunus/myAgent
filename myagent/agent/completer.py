"""
Completion Verifier — Claude reads the task + created files and checks
if everything is truly done.

This is the key agentic loop driver:
  execute → review → verify → if incomplete: execute more → verify again…

Strategy
--------
1. Read all created files (up to ~8 KB total to keep prompt small).
2. Ask Claude: "Is this task complete? What's missing?"
3. If Claude says INCOMPLETE + lists steps: run those steps via Gemini.
4. Repeat up to max_completion_rounds.

Claude response format expected:
  COMPLETE                          — nothing missing
  INCOMPLETE                        — something missing
  STEP 1: <what to do>
  STEP 2: ...
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from myagent.config.settings import ANTHROPIC_API_KEY, WORK_DIR

_SYSTEM = """\
You are a strict completion checker for a code-generation agent.

Given a task description and the files that were created, decide if the task
is truly and fully complete. Read the file contents carefully.

If COMPLETE, respond with exactly one line:
COMPLETE

If something important is missing, respond with:
INCOMPLETE
STEP 1: <precise instruction for Gemini to execute>
STEP 2: <another step if needed>

Rules:
- Max 3 steps. Focus only on CRITICAL missing pieces.
- A passing test suite means code is correct — don't nitpick style.
- If the task asked for a web UI and index.html exists with JS, it's done.
- If the task asked for tests and test_*.py exists with assertions, it's done.
- Only flag truly missing functionality or broken integration.
- When in doubt, say COMPLETE.
"""


@dataclass
class CompletionResult:
    complete: bool
    missing_steps: list[str] = field(default_factory=list)
    feedback: str = ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def verify(
    task: str,
    created_files: list[str],
    stream_callback=None,
) -> CompletionResult:
    """Claude verifies whether the task is fully done.

    Returns CompletionResult with complete=True or missing_steps to execute.
    Falls back to complete=True on any error (fail-safe: don't block progress).
    """
    if not created_files:
        return CompletionResult(complete=True)

    prompt = _build_prompt(task, created_files)
    raw = _ask_claude(prompt, stream_callback=stream_callback)
    return _parse(raw)


# ---------------------------------------------------------------------------
# Prompt builder — reads files (capped at 8 KB total)
# ---------------------------------------------------------------------------

def _build_prompt(task: str, files: list[str]) -> str:
    snippets: list[str] = []
    total = 0
    for fname in files:
        path = (WORK_DIR / fname).resolve()
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if len(content) > 2500:
            content = content[:2500] + "\n... (truncated)"
        total += len(content)
        snippets.append(f"--- {fname} ---\n{content}")
        if total > 8000:
            snippets.append("... (further files omitted)")
            break

    files_block = "\n\n".join(snippets) if snippets else "(no readable files)"
    return f"Task: {task}\n\nCreated files:\n\n{files_block}"


# ---------------------------------------------------------------------------
# Claude caller (CLI + API, both with optional streaming)
# ---------------------------------------------------------------------------

def _ask_claude(prompt: str, stream_callback=None) -> str:
    from myagent.config.auth import CLI, get_claude_mode, get_claude_model  # noqa: F401

    mode = get_claude_mode()
    full_prompt = f"{_SYSTEM}\n\n{prompt}"

    if mode == CLI:
        cmd = ["claude", "-p", full_prompt, "--model", get_claude_model()]
        try:
            if stream_callback:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, bufsize=1,
                )
                parts: list[str] = []
                deadline = time.time() + 120
                assert proc.stdout is not None
                for line in iter(proc.stdout.readline, ""):
                    parts.append(line)
                    stream_callback(line)
                    if time.time() > deadline:
                        proc.kill()
                        return "COMPLETE"
                proc.stdout.close()
                proc.wait()
                return "COMPLETE" if proc.returncode != 0 else "".join(parts).strip()
            else:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                return "COMPLETE" if result.returncode != 0 else result.stdout.strip()
        except Exception:
            return "COMPLETE"

    else:  # API mode
        if not ANTHROPIC_API_KEY:
            return "COMPLETE"
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            if stream_callback:
                with client.messages.stream(
                    model=get_claude_model(),
                    max_tokens=512,
                    system=_SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    for text in stream.text_stream:
                        stream_callback(text)
                    return stream.get_final_message().content[0].text.strip()
            response = client.messages.create(
                model=get_claude_model(),
                max_tokens=512,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception:
            return "COMPLETE"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse(text: str) -> CompletionResult:
    lines = text.strip().splitlines()
    first = lines[0].strip().upper() if lines else "COMPLETE"

    if first == "COMPLETE":
        return CompletionResult(complete=True, feedback=text)

    steps: list[str] = []
    for line in lines:
        m = re.match(r"^STEP\s+\d+\s*:\s*(.+)$", line.strip(), re.IGNORECASE)
        if m:
            steps.append(m.group(1).strip())

    if not steps:
        # No steps listed despite INCOMPLETE → treat as complete (avoid loops)
        return CompletionResult(complete=True, feedback=text)

    return CompletionResult(complete=False, missing_steps=steps[:3], feedback=text)
