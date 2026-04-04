"""
Python file runner — safe execution with hard timeout + SIGKILL.

Used by the reviewer to physically verify that test files pass.
A Gemini-written test can contain infinite loops; this module guarantees
the process is killed after `timeout` seconds regardless.

Usage:
    result = run_file("test_fibonacci.py", timeout=30)
    if result.ok:
        # zero tokens spent
    else:
        # send result.output (traceback) to Claude reviewer
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from myagent.config.settings import WORK_DIR

_DEFAULT_TIMEOUT = 30  # seconds — raised per-call if needed


@dataclass
class RunResult:
    ok: bool          # True = exit code 0
    output: str       # stdout + stderr combined
    timed_out: bool = False


def run_file(filename: str, timeout: int = _DEFAULT_TIMEOUT) -> RunResult:
    """Run a Python file inside WORK_DIR with a hard timeout.

    Guarantees the subprocess is killed (SIGKILL on POSIX, TerminateProcess
    on Windows) after *timeout* seconds. Safe against infinite loops.

    Returns RunResult(ok, output, timed_out).
    """
    path = (WORK_DIR / filename).resolve()
    if not path.exists():
        return RunResult(ok=False, output=f"File not found: {filename}")

    # Verify path stays inside WORK_DIR (path traversal guard)
    try:
        path.relative_to(WORK_DIR.resolve())
    except ValueError:
        return RunResult(ok=False, output=f"Security: path outside WORK_DIR: {filename}")

    try:
        proc = subprocess.Popen(
            [sys.executable, str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(WORK_DIR),
            # New process group so we can kill the whole tree
            **_pgroup_kwargs(),
        )
        try:
            stdout, _ = proc.communicate(timeout=timeout)
            output = stdout.decode(errors="replace").strip()
            return RunResult(ok=proc.returncode == 0, output=output)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.wait()
            return RunResult(
                ok=False,
                output=f"Timed out after {timeout}s — possible infinite loop.",
                timed_out=True,
            )
    except Exception as exc:
        return RunResult(ok=False, output=f"Runner error: {exc}")


def run_pytest(filename: str, timeout: int = _DEFAULT_TIMEOUT) -> RunResult:
    """Run a file with pytest (preferred for test_*.py files).

    Falls back to plain python if pytest is not installed.
    Returns RunResult(ok, output, timed_out).
    """
    path = (WORK_DIR / filename).resolve()
    if not path.exists():
        return RunResult(ok=False, output=f"File not found: {filename}")

    try:
        path.relative_to(WORK_DIR.resolve())
    except ValueError:
        return RunResult(ok=False, output=f"Security: path outside WORK_DIR: {filename}")

    # Try pytest first (better output), fallback to python -m unittest
    for cmd in (
        [sys.executable, "-m", "pytest", str(path), "-v", "--tb=short", "--no-header"],
        [sys.executable, "-m", "unittest", str(path)],
    ):
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(WORK_DIR),
                **_pgroup_kwargs(),
            )
            try:
                stdout, _ = proc.communicate(timeout=timeout)
                output = stdout.decode(errors="replace").strip()
                return RunResult(ok=proc.returncode == 0, output=output)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                proc.wait()
                return RunResult(
                    ok=False,
                    output=f"Tests timed out after {timeout}s — possible infinite loop.",
                    timed_out=True,
                )
        except FileNotFoundError:
            continue  # try next runner
        except Exception as exc:
            return RunResult(ok=False, output=f"Runner error: {exc}")

    return RunResult(ok=False, output="Could not find pytest or unittest runner.")


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

def _pgroup_kwargs() -> dict:
    """Return kwargs to create a new process group (for clean tree kill)."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process and all its children."""
    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except Exception:
            pass
