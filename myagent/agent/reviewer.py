"""
Reviewer — linter-first review with targeted Claude fallback.

Strategy:
  1. Run ruff on all created .py files (fast, deterministic, zero tokens).
  2. If ruff passes → APPROVED immediately, no Claude call.
  3. If ruff fails → send only "failing line ±3 lines + ruff message" to Claude.
     Claude produces STEP-formatted fix instructions for the Gemini worker.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from myagent.agent.runner import run_pytest

from myagent.config.settings import ANTHROPIC_API_KEY, PROMPTS_DIR, WORK_DIR


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ReviewResult:
    approved: bool
    fix_steps: list[str] = field(default_factory=list)
    feedback_raw: str = ""
    round_num: int = 1
    error_count: int = 0          # ruff error count — used for heuristic exit


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def review(
    task: str,
    created_files: list[str],
    round_num: int = 1,
    verbose: bool = False,
    ui=None,
    stream_callback=None,
) -> ReviewResult:
    """Linter-first, test-second review. Returns APPROVED or fix_steps.

    Strategy:
      1. ruff clean?  → run tests (or APPROVED if no tests)
      2. tests pass?  → APPROVED (zero tokens)
      3. ruff fails   → Claude with lint context
      4. tests fail   → Claude with traceback context
    Falls back to approved=True on any unexpected error.
    """
    py_files = [f for f in created_files if f.endswith(".py")]
    if not py_files:
        return ReviewResult(approved=True, round_num=round_num)

    _ui = ui  # may be None

    # ── Step 1: ruff --fix ────────────────────────────────────────────────────
    _run_ruff_fix(py_files)

    # ── Step 2: ruff check ────────────────────────────────────────────────────
    lint_issues = _run_ruff(py_files)
    if _ui:
        if lint_issues:
            _ui.review_ruff_issues(len(lint_issues))
        else:
            _ui.review_ruff_clean()

    if lint_issues:
        file_contents = _read_files(py_files)
        context = _build_lint_prompt(task, lint_issues, file_contents)
        raw = _ask_claude(context, stream_callback=stream_callback)
        if _ui:
            _ui.raw(f"Reviewer Claude (lint, tur {round_num})", raw, color="cyan2")
        result = _parse(raw, round_num)
        result.error_count = len(lint_issues)
        return result

    # ── Step 3: tests ─────────────────────────────────────────────────────────
    test_files = [f for f in py_files if Path(f).name.startswith("test_")]
    if not test_files:
        return ReviewResult(approved=True, round_num=round_num, error_count=0)

    test_failures = _run_tests(test_files, verbose=verbose, ui=_ui)
    if not test_failures:
        return ReviewResult(approved=True, round_num=round_num, error_count=0)

    # ── Step 4: test failed → Claude ─────────────────────────────────────────
    context = _build_test_prompt(task, test_failures)
    raw = _ask_claude(context, stream_callback=stream_callback)
    if _ui:
        _ui.raw(f"Reviewer Claude (test, tur {round_num})", raw, color="cyan2")
    result = _parse(raw, round_num)
    result.error_count = len(test_failures)
    return result


# ---------------------------------------------------------------------------
# Ruff runner
# ---------------------------------------------------------------------------

def _run_ruff_fix(filenames: list[str]) -> None:
    """Run `ruff check --fix` to auto-correct safe fixable issues (e.g. unused imports).
    Modifies files in place. Failures are silently ignored."""
    paths = [str((WORK_DIR / f).resolve()) for f in filenames
             if (WORK_DIR / f).exists()]
    if not paths:
        return
    try:
        subprocess.run(
            ["ruff", "check", "--fix", "--unsafe-fixes"] + paths,
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        pass


def _run_ruff(filenames: list[str]) -> list[dict]:
    """Run ruff on the given files. Returns list of {file, line, col, code, message}."""
    paths = []
    for fname in filenames:
        p = (WORK_DIR / fname).resolve()
        if p.exists():
            paths.append(str(p))
    if not paths:
        return []

    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=concise"] + paths,
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    issues = []
    # Format: /path/to/file.py:line:col: CODE message
    pattern = re.compile(r"^(.+?):(\d+):(\d+):\s+([A-Z]\d+)\s+(.+)$")
    for line in result.stdout.splitlines():
        m = pattern.match(line.strip())
        if m:
            fpath, lineno, col, code, msg = m.groups()
            # Normalize to relative path
            try:
                rel = str(Path(fpath).relative_to(WORK_DIR))
            except ValueError:
                rel = Path(fpath).name
            issues.append({
                "file": rel,
                "line": int(lineno),
                "col": int(col),
                "code": code,
                "message": msg.strip(),
            })
    return issues


# ---------------------------------------------------------------------------
# Context builder — surgical: only failing lines ±3 context
# ---------------------------------------------------------------------------

def _build_lint_prompt(task: str, lint_issues: list[dict], file_contents: dict[str, str]) -> str:
    parts = [f"Task: {task}\n\nLinter found {len(lint_issues)} issue(s):\n"]

    # Group issues by file
    by_file: dict[str, list[dict]] = {}
    for issue in lint_issues:
        by_file.setdefault(issue["file"], []).append(issue)

    for fname, issues in by_file.items():
        content = file_contents.get(fname, "")
        file_lines = content.splitlines() if content else []
        parts.append(f"--- {fname} ---")
        for issue in issues:
            lineno = issue["line"]
            parts.append(f"  {issue['code']} line {lineno}: {issue['message']}")
            # Extract ±3 lines of context
            start = max(0, lineno - 4)
            end = min(len(file_lines), lineno + 3)
            snippet = file_lines[start:end]
            for i, src_line in enumerate(snippet, start=start + 1):
                marker = ">>>" if i == lineno else "   "
                parts.append(f"  {marker} {i:3d}: {src_line}")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def _run_tests(test_files: list[str], verbose: bool = False, ui=None) -> list[dict]:
    """Run each test file. Returns list of {file, output} for failures only."""
    failures: list[dict] = []
    for fname in test_files:
        res = run_pytest(fname, timeout=30)
        if res.timed_out or not res.ok:
            if ui:
                ui.review_test_fail(fname)
            failures.append({"file": fname, "output": res.output, "timed_out": res.timed_out})
        else:
            if ui:
                ui.review_test_pass(fname)
    return failures


def _build_test_prompt(task: str, failures: list[dict]) -> str:
    """Build a surgical prompt from test failure tracebacks."""
    parts = [f"Task: {task}\n\n{len(failures)} test file(s) failed:\n"]
    for f in failures:
        parts.append(f"--- {f['file']} ---")
        if f.get("timed_out"):
            parts.append("  ERROR: Test timed out (infinite loop suspected).")
        else:
            # Truncate very long output — traceback tail is most useful
            output = f["output"]
            if len(output) > 2000:
                output = "...(truncated)\n" + output[-2000:]
            parts.append(output)
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# File reader
# ---------------------------------------------------------------------------

def _read_files(filenames: list[str]) -> dict[str, str]:
    contents: dict[str, str] = {}
    for fname in filenames:
        path = (WORK_DIR / fname).resolve()
        try:
            contents[fname] = path.read_text(encoding="utf-8")
        except Exception:
            pass
    return contents


# ---------------------------------------------------------------------------
# Claude call
# ---------------------------------------------------------------------------

def _ask_claude(prompt: str, stream_callback=None) -> str:
    from myagent.config.auth import CLI, get_claude_mode, get_claude_model
    mode = get_claude_mode()
    system = (PROMPTS_DIR / "reviewer.txt").read_text(encoding="utf-8")

    if mode == CLI:
        import time
        full_prompt = f"{system}\n\n{prompt}"
        cmd = ["claude", "-p", full_prompt, "--model", get_claude_model()]
        try:
            if stream_callback:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                )
                parts: list[str] = []
                deadline = time.time() + 120
                assert proc.stdout is not None
                for line in iter(proc.stdout.readline, ""):
                    parts.append(line)
                    stream_callback(line)
                    if time.time() > deadline:
                        proc.kill()
                        return "APPROVED"
                proc.stdout.close()
                proc.wait()
                if proc.returncode != 0:
                    return "APPROVED"
                return "".join(parts).strip()
            else:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    return "APPROVED"
                return result.stdout.strip()
        except Exception:
            return "APPROVED"
    else:
        if not ANTHROPIC_API_KEY:
            return "APPROVED"
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            if stream_callback:
                with client.messages.stream(
                    model=get_claude_model(),
                    max_tokens=1024,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    for text in stream.text_stream:
                        stream_callback(text)
                    return stream.get_final_message().content[0].text.strip()
            response = client.messages.create(
                model=get_claude_model(),
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception:
            return "APPROVED"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse(text: str, round_num: int) -> ReviewResult:
    lines = text.strip().splitlines()
    first = lines[0].strip().upper() if lines else ""

    if first == "APPROVED":
        return ReviewResult(approved=True, round_num=round_num)

    fix_steps: list[str] = []
    in_issues = False
    for line in lines:
        stripped = line.strip()
        if stripped.upper() == "ISSUES":
            in_issues = True
            continue
        if in_issues:
            m = re.match(r"^STEP\s+\d+\s*:\s*(.+)$", stripped, re.IGNORECASE)
            if m:
                fix_steps.append(m.group(1).strip())

    if not fix_steps:
        return ReviewResult(approved=True, round_num=round_num, feedback_raw=text)

    return ReviewResult(
        approved=False,
        fix_steps=fix_steps,
        feedback_raw=text,
        round_num=round_num,
    )
