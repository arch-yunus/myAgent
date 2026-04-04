"""
Executor module — parses worker output and applies it safely.

Supports two output types:
  FILE: <name>          → write file to working directory
  BASH: <safe command>  → execute shell command

Security modes:
  Host mode  (MYAGENT_DOCKER unset): whitelist enforced — only mkdir/touch/echo/cat/python/pip/uv
  Docker mode (MYAGENT_DOCKER=1):    all commands allowed — Docker IS the sandbox
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from myagent.config.settings import BASH_TIMEOUT, WORK_DIR

# ---------------------------------------------------------------------------
# Security: command whitelist (host mode only)
# ---------------------------------------------------------------------------

# Set MYAGENT_DOCKER=1 (done automatically by Dockerfile) to disable whitelist.
_DOCKER_MODE: bool = os.environ.get("MYAGENT_DOCKER", "").strip() == "1"

# Commands always allowed on host (safe, non-destructive)
ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "mkdir", "touch", "echo", "cat",
    "python", "python3",          # run scripts (with timeout guard in runner.py)
    "pip", "uv",                  # package install (after user approval via deps.py)
    "ruff", "pytest",             # tooling
})

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    ok: bool
    kind: str                   # "file" | "bash" | "error" | "skip"
    message: str
    details: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_FILE_KEYWORDS = ("FILE:", "DOSYA:", "ФАЙЛ:")   # EN / TR / RU variants Gemini uses
_BASH_KEYWORDS = ("BASH:", "KOMUT:", "КОМАНДА:")


def _strip_prefix(line: str, keywords: tuple[str, ...]) -> str | None:
    """Return text after the first matching keyword (case-insensitive), or None."""
    upper = line.upper()
    for kw in keywords:
        if upper.startswith(kw):
            return line[len(kw):].strip()
        # Handle leading garbage chars (e.g. '棟FILE:' or '===FILE:')
        idx = upper.find(kw)
        if idx != -1 and idx <= 4:   # garbage prefix at most 4 chars
            return line[idx + len(kw):].strip()
    return None


def parse_and_execute(worker_output: str) -> ExecutionResult:
    """Parse *worker_output* and dispatch to the appropriate handler."""
    if not worker_output or not worker_output.strip():
        return ExecutionResult(ok=False, kind="skip", message="Empty worker output — step skipped.")

    lines = worker_output.strip().splitlines()
    first = lines[0].strip()

    filename = _strip_prefix(first, _FILE_KEYWORDS)
    if filename is not None:
        content = "\n".join(lines[1:])
        if content.startswith("\n"):
            content = content[1:]
        return _write_file(filename, content)

    command = _strip_prefix(first, _BASH_KEYWORDS)
    if command is not None:
        return _execute_bash(command)

    # Heuristic fallback: if it looks like "filename.ext\n<code>", treat as FILE
    fallback = _try_infer_file(lines)
    if fallback:
        return fallback

    return ExecutionResult(
        ok=False,
        kind="error",
        message=f"Unrecognized worker output format. First line: {first!r}",
        details={"raw": worker_output[:300]},
    )


# ---------------------------------------------------------------------------
# File writer
# ---------------------------------------------------------------------------

def _write_file(filename: str, content: str) -> ExecutionResult:
    if not filename:
        return ExecutionResult(ok=False, kind="error", message="FILE directive has no filename.")

    # Security: resolve and confirm target stays inside WORK_DIR
    target = (WORK_DIR / filename).resolve()
    work_resolved = WORK_DIR.resolve()

    try:
        target.relative_to(work_resolved)
    except ValueError:
        return ExecutionResult(
            ok=False,
            kind="error",
            message=f"Security: path traversal denied for '{filename}'.",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    return ExecutionResult(
        ok=True,
        kind="file",
        message=f"Created file: {filename}",
        details={"path": str(target), "filename": filename, "size": len(content)},
    )


# ---------------------------------------------------------------------------
# Bash executor
# ---------------------------------------------------------------------------

def _execute_bash(command: str) -> ExecutionResult:
    command = command.strip()
    if not command:
        return ExecutionResult(ok=False, kind="error", message="BASH directive has no command.")

    parts = _split_command(command)
    if not parts:
        return ExecutionResult(ok=False, kind="error", message="Could not parse bash command.")

    cmd_name = parts[0]
    if not _DOCKER_MODE and cmd_name not in ALLOWED_COMMANDS:
        return ExecutionResult(
            ok=False,
            kind="error",
            message=(
                f"Command '{cmd_name}' is not allowed on host. "
                f"Use Docker mode (./run.sh) for unrestricted execution. "
                f"Allowed host commands: {', '.join(sorted(ALLOWED_COMMANDS))}."
            ),
        )

    try:
        result = subprocess.run(
            parts,
            capture_output=True,
            text=True,
            timeout=BASH_TIMEOUT,
            cwd=str(WORK_DIR),
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(ok=False, kind="error", message=f"Command timed out: {command}")
    except Exception as exc:
        return ExecutionResult(ok=False, kind="error", message=f"Execution error: {exc}")

    ok = result.returncode == 0
    message = f"Executed: {command}"
    if result.stdout.strip():
        message += f"\n{result.stdout.strip()}"
    if result.stderr.strip() and not ok:
        message += f"\nstderr: {result.stderr.strip()}"

    return ExecutionResult(
        ok=ok,
        kind="bash",
        message=message,
        details={
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_command(command: str) -> list[str]:
    """Shell-safe split that handles quoted arguments."""
    import shlex
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _try_infer_file(lines: list[str]) -> ExecutionResult | None:
    """If the output looks like '<name.ext>\\n<content>', treat as a file."""
    if len(lines) < 2:
        return None
    candidate = lines[0].strip()
    # Simple heuristic: looks like a filename (has extension, no spaces)
    if re.match(r"^[\w./\\-]+\\.\\w+$", candidate) and " " not in candidate:
        content = "\n".join(lines[1:])
        return _write_file(candidate, content)
    return None


# ---------------------------------------------------------------------------
# Batch parser — splits ===END=== delimited multi-block output
# ---------------------------------------------------------------------------

def parse_batch_and_execute(batch_output: str, expected: int = 0) -> list[ExecutionResult]:
    """Parse a batch worker response containing multiple FILE:/BASH: blocks.

    Each block is terminated by ===END===  (or end of string).
    Returns one ExecutionResult per block, in order.

    If expected > 0 and fewer blocks are found, the last successful FILE/BASH
    result is used to fill the gap (Gemini sometimes consolidates steps).
    """
    results: list[ExecutionResult] = []
    # Split on the delimiter. Pattern is lenient to handle Gemini's garbled output:
    # ===END===        (correct)
    # ===END           (missing trailing ===)
    # ===ENDש / ===ENDбаше  (garbage chars instead of ===)
    # Consume everything after ===END up to (and including) the next newline
    raw_blocks = re.split(r"={3}END[^\n]*\n?", batch_output)
    for raw in raw_blocks:
        raw = raw.strip()
        if not raw:
            continue
        results.append(parse_and_execute(raw))

    # Consolidation recovery: worker wrote fewer blocks than steps
    if expected > 0 and 0 < len(results) < expected:
        last_ok = next(
            (r for r in reversed(results) if r.ok and r.kind in ("file", "bash")),
            None,
        )
        if last_ok:
            fill = ExecutionResult(
                ok=True,
                kind=last_ok.kind,
                message=f"Consolidated with previous step ({last_ok.message})",
                details=last_ok.details.copy(),
            )
            while len(results) < expected:
                results.append(fill)

    return results
