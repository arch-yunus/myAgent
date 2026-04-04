"""
Pipeline — orchestrates the full clarify → plan → execute → review → verify cycle.

Agentic loop:
  1. Clarify (optional)
  2. Plan   (Claude, with workspace + history context)
  3. Execute (Gemini, streaming)
  4. Deps   (auto-install missing packages)
  5. Review  (ruff + pytest + Claude fix loop)
  6. Verify  (Claude checks if task is truly complete; executes extra steps if not)
  7. Save   (persist run to history)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from myagent.agent.executor import ExecutionResult, parse_and_execute, parse_batch_and_execute
from myagent.agent.planner import plan
from myagent.agent.worker import execute_all_steps, execute_step
from myagent.i18n.translator import en_to_tr

if TYPE_CHECKING:
    from myagent.ui import AgentUI, NullUI


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class StepRecord:
    index: int
    description: str
    worker_output: str
    result: ExecutionResult


@dataclass
class ReviewRecord:
    round_num: int
    approved: bool
    fix_steps: list[str]
    feedback_raw: str = ""


@dataclass
class CompletionRecord:
    round_num: int
    complete: bool
    missing_steps: list[str]
    feedback: str = ""


@dataclass
class RunResult:
    task_original: str
    task_english: str
    steps: list[StepRecord] = field(default_factory=list)
    plan_steps: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    review_records: list[ReviewRecord] = field(default_factory=list)
    completion_records: list[CompletionRecord] = field(default_factory=list)
    summary_en: str = ""
    summary_tr: str = ""
    success: bool = True
    dry_run: bool = False
    batch: bool = True
    clarified_task: str = ""
    review_approved: bool = False
    completion_verified: bool = False
    run_id: str = ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    task: str,
    verbose: bool = False,
    dry_run: bool = False,
    batch: bool = True,
    clarify: bool = False,
    review: bool = True,
    max_review_rounds: int = 2,
    auto_deps: bool = False,
    verify_completion: bool = True,
    max_completion_rounds: int = 2,
    session_context: str = "",
    ui: AgentUI | NullUI | None = None,
) -> RunResult:
    """Execute the full agentic pipeline for *task*."""
    from myagent.ui import make_ui
    from myagent.config.auth import get_claude_model, get_gemini_model

    if ui is None:
        ui = make_ui(verbose=verbose)

    t_start = time.time()
    result = RunResult(task_original=task, task_english=task, dry_run=dry_run, batch=batch)

    ui.header(task, get_claude_model(), get_gemini_model())

    # ── 1. Clarification ────────────────────────────────────────────────────
    if clarify and not dry_run:
        from myagent.agent.clarifier import clarify as ask_clarify
        with ui.spinner("Netleştirme soruları hazırlanıyor…", color="medium_purple1"):
            pass  # clarify is interactive — spinner shows intent
        task = ask_clarify(task, verbose=verbose)
    result.clarified_task = task

    # ── 2. Plan ─────────────────────────────────────────────────────────────
    _planner_buf: list[str] = []

    def _planner_write(chunk: str) -> None:
        _planner_buf.append(chunk)
        write(chunk)  # forward to streaming UI

    with ui.streaming("Claude planlıyor…", color="medium_purple1") as write:
        steps = plan(
            task, verbose=False,
            stream_callback=_planner_write,
            session_context=session_context,
        )
    result.plan_steps = steps
    _last_raw["planner"] = "".join(_planner_buf)

    if verbose:
        from myagent.config.auth import get_claude_model as gcm
        ui.raw(f"Planner raw ({gcm()})", _last_raw["planner"], color="medium_purple1")

    if not steps:
        result.summary_en = "No steps were generated."
        result.summary_tr = en_to_tr(result.summary_en)
        result.success = False
        return result

    ui.plan_done(steps)

    if dry_run:
        result.summary_en = f"Dry run: {len(steps)} steps planned (not executed)."
        result.summary_tr = en_to_tr(result.summary_en)
        return result

    # ── 3. Execute ───────────────────────────────────────────────────────────
    lines_en = _execute(steps, task, batch, verbose, result, ui)

    # ── 3a. Missing-file recovery ────────────────────────────────────────────
    retry_steps = _find_missing_steps(steps, result.created_files)
    if retry_steps:
        ui.missing_files_retry(retry_steps)
        extra_lines = _execute(retry_steps, task, batch, verbose, result, ui)
        lines_en.extend(extra_lines)

    # ── 3b. Dependency management ─────────────────────────────────────────────
    if result.created_files:
        from myagent.agent.deps import scan_and_install
        py_files = [f for f in result.created_files if f.endswith(".py")]
        if py_files:
            scan_and_install(py_files, auto=auto_deps, verbose=verbose, ui=ui)

    # ── 4. Review loop ────────────────────────────────────────────────────────
    # Run review whenever files were created — BASH step failures (e.g. a pytest
    # run that fails) are exactly what the reviewer is meant to catch and fix.
    if review and result.created_files:
        lines_en = _review_loop(task, result, lines_en, max_review_rounds, verbose, ui)

    # ── 5. Completion verification loop ──────────────────────────────────────
    if verify_completion and result.created_files:
        lines_en = _completion_loop(
            task, result, lines_en, max_completion_rounds, ui,
        )

    # ── 6. Summary ────────────────────────────────────────────────────────────
    # If review approved the output, promote overall success regardless of any
    # intermediate BASH step failures (e.g. a pytest run that failed before the fix).
    if result.review_approved or result.completion_verified:
        result.success = True
    status = "All steps completed." if result.success else "Completed with errors."
    if result.review_records:
        last = result.review_records[-1]
        if last.approved:
            status += f" Review: approved in {last.round_num} round(s)."
        else:
            status += f" Review: not fully resolved after {len(result.review_records)} round(s)."
    if result.completion_verified:
        status += " Completion verified."
    result.summary_en = status + "\n" + "\n".join(lines_en)
    result.summary_tr = en_to_tr(result.summary_en)

    ui.summary(
        success=result.success,
        review_approved=result.review_approved,
        n_review_rounds=len(result.review_records),
        created_files=result.created_files,
    )

    # ── 7. Save to history ────────────────────────────────────────────────────
    try:
        from myagent.memory.history import save_run
        result.run_id = save_run(
            task_original=result.task_original,
            task_english=result.task_english,
            files_created=result.created_files,
            success=result.success,
            review_approved=result.review_approved,
            n_review_rounds=len(result.review_records),
            duration_s=time.time() - t_start,
            summary=result.summary_en,
        )
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Raw output store (used by verbose mode to retrieve last model output)
# ---------------------------------------------------------------------------
_last_raw: dict[str, str] = {"planner": "", "worker": "", "reviewer": ""}


# ---------------------------------------------------------------------------
# Missing-step detector
# ---------------------------------------------------------------------------

_FILE_PATTERN = re.compile(r"\b([\w./\\-]+\.(?:py|js|ts|json|yaml|yml|toml|txt|md|sh|html|css))\b")

# Steps that run commands rather than create files — skip these in missing-file detection
_BASH_STEP_PREFIX = re.compile(r"^\s*(run|execute|test|verify|check|lint|install)\b", re.IGNORECASE)
_BASH_CMD_IN_STEP = re.compile(r"\bpython\s+-[mc]\b|\bpytest\b|\bruff\b|\bpip\b|\buv\s+pip\b", re.IGNORECASE)


def _find_missing_steps(steps: list[str], created_files: list[str]) -> list[str]:
    """Return steps that mention a file that was never created.

    Excludes steps that are clearly BASH execution steps (pytest, python -m, etc.)
    rather than file-creation steps — those won't produce files and should never
    trigger a retry.
    """
    created_set = set(created_files)
    missing: list[str] = []
    for step in steps:
        # Skip steps whose primary action is running a command, not creating a file
        if _BASH_STEP_PREFIX.match(step) or _BASH_CMD_IN_STEP.search(step):
            continue
        for fname in _FILE_PATTERN.findall(step):
            if fname not in created_set:
                missing.append(step)
                break
    return missing


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------

def _execute(
    steps: list[str],
    task: str,
    batch: bool,
    verbose: bool,
    result: RunResult,
    ui,
) -> list[str]:
    lines_en: list[str] = []
    seen_files: dict[str, bool] = {}

    if batch:
        with ui.streaming(f"Gemini yürütüyor — {len(steps)} adım…", color="dodger_blue1") as write:
            worker_out = execute_all_steps(steps, task, verbose=False, stream_callback=write)

        if verbose:
            ui.raw("Worker raw (Gemini)", worker_out, color="dodger_blue1")

        exec_results = parse_batch_and_execute(worker_out, expected=len(steps))
        while len(exec_results) < len(steps):
            exec_results.append(ExecutionResult(
                ok=False, kind="skip",
                message=f"Step {len(exec_results) + 1}: no output from worker",
            ))

        for i, (step_desc, exec_result) in enumerate(zip(steps, exec_results), 1):
            result.steps.append(StepRecord(
                index=i, description=step_desc,
                worker_output=worker_out, result=exec_result,
            ))
            lines_en.append(f"Step {i}: {exec_result.message}")
            if exec_result.kind == "file" and "filename" in exec_result.details:
                seen_files[exec_result.details["filename"]] = True
            if not exec_result.ok:
                result.success = False

        ui.exec_results(steps, exec_results)

    else:
        context_lines: list[str] = [f"Overall task: {task}"]
        all_results = []
        for i, step_desc in enumerate(steps, start=1):
            with ui.streaming(f"Gemini — adım {i}/{len(steps)}: {step_desc[:55]}…", color="dodger_blue1") as write:
                worker_out = execute_step(step_desc, "\n".join(context_lines), verbose=False, stream_callback=write)
            exec_result = parse_and_execute(worker_out)
            all_results.append(exec_result)

            result.steps.append(StepRecord(
                index=i, description=step_desc,
                worker_output=worker_out, result=exec_result,
            ))
            lines_en.append(f"Step {i}: {exec_result.message}")
            context_lines.append(f"Step {i} ({step_desc}): {exec_result.message}")
            if exec_result.kind == "file" and "filename" in exec_result.details:
                seen_files[exec_result.details["filename"]] = True
            if not exec_result.ok:
                result.success = False

        ui.exec_results(steps, all_results)

    result.created_files = list(seen_files.keys())
    return lines_en


# ---------------------------------------------------------------------------
# Review loop
# ---------------------------------------------------------------------------

def _review_loop(
    task: str,
    result: RunResult,
    lines_en: list[str],
    max_rounds: int,
    verbose: bool,
    ui,
) -> list[str]:
    from myagent.agent.reviewer import review as do_review

    prev_error_count: int | None = None

    for round_num in range(1, max_rounds + 1):
        with ui.streaming(f"Review — Claude analiz ediyor (tur {round_num}/{max_rounds})…", color="cyan2") as write:
            rev = do_review(
                task, result.created_files,
                round_num=round_num, verbose=False, ui=ui,
                stream_callback=write,
            )

        if verbose and rev.feedback_raw:
            ui.raw(f"Reviewer raw (tur {round_num})", rev.feedback_raw, color="cyan2")

        rec = ReviewRecord(
            round_num=round_num, approved=rev.approved,
            fix_steps=rev.fix_steps, feedback_raw=rev.feedback_raw,
        )
        result.review_records.append(rec)

        if rev.approved:
            result.review_approved = True
            ui.review_approved(round_num)
            break

        if not rev.fix_steps:
            result.review_approved = False
            break

        if prev_error_count is not None and rev.error_count >= prev_error_count:
            ui.review_stuck(rev.error_count)
            result.review_approved = False
            break
        prev_error_count = rev.error_count

        ui.review_fix_steps(rev.fix_steps)

        with ui.streaming("Gemini düzeltiyor…", color="dodger_blue1") as write:
            fix_worker_out = execute_all_steps(rev.fix_steps, task, verbose=False, stream_callback=write)
        fix_results = parse_batch_and_execute(fix_worker_out, expected=len(rev.fix_steps))

        base = len(result.steps)
        for j, (fix_desc, fix_result) in enumerate(zip(rev.fix_steps, fix_results), 1):
            result.steps.append(StepRecord(
                index=base + j,
                description=f"[fix tur {round_num}] {fix_desc}",
                worker_output=fix_worker_out,
                result=fix_result,
            ))
            lines_en.append(f"Fix {round_num}.{j}: {fix_result.message}")
            if fix_result.kind == "file" and "filename" in fix_result.details:
                fname = fix_result.details["filename"]
                if fname not in result.created_files:
                    result.created_files.append(fname)
            if not fix_result.ok:
                result.success = False

        if round_num == max_rounds:
            result.review_approved = False
            ui.review_max_rounds(max_rounds)

    return lines_en


# ---------------------------------------------------------------------------
# Completion verification loop
# ---------------------------------------------------------------------------

def _completion_loop(
    task: str,
    result: RunResult,
    lines_en: list[str],
    max_rounds: int,
    ui,
) -> list[str]:
    """Ask Claude to verify the task is truly complete; run extra steps if not."""
    from myagent.agent.completer import verify as do_verify

    for round_num in range(1, max_rounds + 1):
        with ui.streaming(
            f"Claude tamamlanma doğruluyor (tur {round_num}/{max_rounds})…",
            color="medium_purple1",
        ) as write:
            cv = do_verify(task, result.created_files, stream_callback=write)

        rec = CompletionRecord(
            round_num=round_num,
            complete=cv.complete,
            missing_steps=cv.missing_steps,
            feedback=cv.feedback,
        )
        result.completion_records.append(rec)

        if cv.complete:
            result.completion_verified = True
            ui.completion_verified()
            break

        if not cv.missing_steps:
            result.completion_verified = True
            break

        ui.completion_missing(cv.missing_steps)

        with ui.streaming("Gemini eksiklikleri tamamlıyor…", color="dodger_blue1") as write:
            extra_out = execute_all_steps(
                cv.missing_steps, task, verbose=False, stream_callback=write,
            )
        extra_results = parse_batch_and_execute(extra_out, expected=len(cv.missing_steps))

        base = len(result.steps)
        for j, (desc, er) in enumerate(zip(cv.missing_steps, extra_results), 1):
            result.steps.append(StepRecord(
                index=base + j,
                description=f"[completion tur {round_num}] {desc}",
                worker_output=extra_out,
                result=er,
            ))
            lines_en.append(f"Completion {round_num}.{j}: {er.message}")
            if er.kind == "file" and "filename" in er.details:
                fname = er.details["filename"]
                if fname not in result.created_files:
                    result.created_files.append(fname)
            if not er.ok:
                result.success = False

        if round_num == max_rounds:
            ui.completion_max_rounds(max_rounds)

    return lines_en
