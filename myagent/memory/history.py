"""
Persistent project memory — stores task runs and file ownership.

Layout (all under WORK_DIR/.myagent/):
  history.jsonl   — append-only run log (one JSON record per line)
  files.json      — file → {run_id, task, created_at} index

Public API
----------
save_run(...)                → run_id
load_recent(n)               → list[dict]          newest-first
find_by_keyword(word)        → list[dict]
get_file_owners()            → dict[fname, meta]   only existing files
context_for_planner(n)       → str                 injected into Claude context
format_history_table()       → str                 for `history` REPL command
last_run()                   → dict | None
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from myagent.config.settings import WORK_DIR


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _meta_dir() -> Path:
    d = WORK_DIR / ".myagent"
    d.mkdir(exist_ok=True)
    return d


def _hist_file() -> Path:
    return _meta_dir() / "history.jsonl"


def _files_index() -> Path:
    return _meta_dir() / "files.json"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_run(
    task_original: str,
    task_english: str,
    files_created: list[str],
    success: bool,
    review_approved: bool,
    n_review_rounds: int,
    duration_s: float,
    summary: str,
) -> str:
    """Append a run record. Returns run_id (8-char hex)."""
    run_id = uuid.uuid4().hex[:8]
    record = {
        "id": run_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "task": task_original,
        "task_en": task_english,
        "files": files_created,
        "success": success,
        "review_approved": review_approved,
        "review_rounds": n_review_rounds,
        "duration_s": round(duration_s),
        "summary": summary[:300] if summary else "",
    }

    with _hist_file().open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    _update_file_index(run_id, task_original, files_created)
    return run_id


def _update_file_index(run_id: str, task: str, files: list[str]) -> None:
    try:
        idx: dict = json.loads(_files_index().read_text(encoding="utf-8")) if _files_index().exists() else {}
    except Exception:
        idx = {}
    ts = datetime.now().isoformat(timespec="seconds")
    for f in files:
        idx[f] = {"run_id": run_id, "task": task[:80], "created_at": ts}
    _files_index().write_text(
        json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def load_recent(n: int = 20) -> list[dict]:
    """Return last N runs, newest first."""
    if not _hist_file().exists():
        return []
    try:
        lines = [l for l in _hist_file().read_text(encoding="utf-8").splitlines() if l.strip()]
        records = [json.loads(l) for l in lines]
        return list(reversed(records[-n:]))
    except Exception:
        return []


def last_run() -> dict | None:
    runs = load_recent(1)
    return runs[0] if runs else None


def find_by_keyword(word: str) -> list[dict]:
    """Case-insensitive keyword search over task text."""
    w = word.lower()
    return [r for r in load_recent(50) if w in r.get("task", "").lower()]


def get_file_owners() -> dict[str, dict]:
    """Return file→meta for files that still exist in WORK_DIR."""
    if not _files_index().exists():
        return {}
    try:
        idx = json.loads(_files_index().read_text(encoding="utf-8"))
        return {f: m for f, m in idx.items() if (WORK_DIR / f).exists()}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def context_for_planner(max_runs: int = 5) -> str:
    """Compact history + ownership text injected into Claude's planner prompt."""
    parts: list[str] = []

    recent = load_recent(max_runs)
    if recent:
        parts.append("Recent tasks in this workspace:")
        for r in recent:
            status = "✓" if r.get("review_approved") or r.get("success") else "✗"
            ts = r.get("timestamp", "")[:16].replace("T", " ")
            task = r.get("task", "")[:70]
            files = ", ".join(r.get("files", [])[:6])
            parts.append(f"  [{ts}] {status} \"{task}\"")
            if files:
                parts.append(f"         → files: {files}")

    owners = get_file_owners()
    if owners:
        parts.append("\nFile ownership (which task created each file):")
        for fname, meta in sorted(owners.items()):
            parts.append(f"  {fname:30s} ← \"{meta.get('task', '?')[:55]}\"")

    return "\n".join(parts)


def format_history_table(n: int = 20) -> str:
    """Human-readable history for the `history` REPL command."""
    runs = load_recent(n)
    if not runs:
        return "  (henüz kayıt yok)"

    lines: list[str] = []
    for r in runs:
        status = "✓" if r.get("review_approved") or r.get("success") else "✗"
        ts = r.get("timestamp", "")[:16].replace("T", " ")
        dur = r.get("duration_s", 0)
        dur_s = f"{dur // 60}m{dur % 60:02d}s" if dur >= 60 else f"{dur}s"
        task = r.get("task", "")[:65]
        files = ", ".join(r.get("files", [])[:4])
        rid = r.get("id", "")
        lines.append(f"  [{ts}] {status}  {dur_s:>7}  #{rid}  {task}")
        if files:
            lines.append(f"                              → {files}")
    return "\n".join(lines)
