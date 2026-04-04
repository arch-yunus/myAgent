"""
Worker — executes plan steps.

Two execution strategies:
  sequential  — one Gemini/Claude call per step (N calls total)
  batch       — one call for ALL steps at once (1 call, default)

Worker backend options (gemini_mode in config):
  api     — Google GenerativeAI SDK (~2s/call, needs GEMINI_API_KEY)
  cli     — gemini CLI subprocess (~40s/call, Node.js startup — SLOW per call)
  claude  — claude CLI subprocess (~5s/call, uses Claude Code auth — WASTES Claude tokens)

Token strategy:
  Batch + gemini CLI  =  1 Claude plan call + 1 Gemini call  →  minimum Claude tokens
  Batch + gemini api  =  1 Claude plan call + 1 Gemini call  →  fastest overall
"""

from __future__ import annotations

import os
import subprocess

from myagent.config.settings import GEMINI_API_KEY, PROMPTS_DIR


def _system_prompt() -> str:
    return (PROMPTS_DIR / "worker.txt").read_text(encoding="utf-8")


def _batch_system_prompt() -> str:
    return (PROMPTS_DIR / "worker_batch.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Single-step entry point (sequential mode)
# ---------------------------------------------------------------------------

def execute_step(
    step: str,
    context: str = "",
    verbose: bool = False,
    stream_callback=None,
) -> str:
    """Execute one plan step; returns raw FILE:/BASH: output."""
    from myagent.config.auth import CLI, CLAUDE_WORKER, get_gemini_mode
    mode = get_gemini_mode()
    if verbose:
        from myagent.config.auth import get_gemini_model
        print(f"  [worker] mode={mode}  model={get_gemini_model()}", flush=True)
        print(f"  [worker step] {step}", flush=True)

    if mode == CLAUDE_WORKER:
        result = _claude_single(step, context, stream_callback=stream_callback)
    elif mode == CLI:
        result = _gemini_cli_single(step, context, stream_callback=stream_callback)
    else:
        result = _gemini_api_single(step, context, stream_callback=stream_callback)

    if verbose:
        print(f"  [worker raw]\n{result}\n", flush=True)
    return result.strip()


# ---------------------------------------------------------------------------
# Batch entry point — all steps in ONE call
# ---------------------------------------------------------------------------

def execute_all_steps(
    steps: list[str],
    task: str = "",
    verbose: bool = False,
    stream_callback=None,
) -> str:
    """Send ALL steps to the worker in a single call.

    Returns the raw multi-block response (===END=== delimited).
    This is the preferred mode: minimises both call count and Claude token usage.
    If stream_callback is provided, each output chunk is passed to it in real time.
    """
    from myagent.config.auth import CLI, CLAUDE_WORKER, get_gemini_mode
    mode = get_gemini_mode()
    if verbose:
        from myagent.config.auth import get_gemini_model
        print(f"  [batch worker] mode={mode}  model={get_gemini_model()}", flush=True)

    prompt = _build_batch_prompt(steps, task)

    if mode == CLAUDE_WORKER:
        result = _claude_batch(prompt, stream_callback=stream_callback)
    elif mode == CLI:
        result = _gemini_cli_batch(prompt, stream_callback=stream_callback)
    else:
        result = _gemini_api_batch(prompt, stream_callback=stream_callback)

    if verbose:
        print(f"  [batch raw output]\n{result}\n", flush=True)
    return result.strip()


def _build_batch_prompt(steps: list[str], task: str) -> str:
    lines = []
    if task:
        lines.append(f"Overall task: {task}\n")
    lines.append("Execute ALL of the following steps in order:\n")
    for i, step in enumerate(steps, 1):
        lines.append(f"STEP {i}: {step}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gemini API  (~2s/call)
# ---------------------------------------------------------------------------

def _gemini_api_single(step: str, context: str = "", stream_callback=None) -> str:
    api_key = GEMINI_API_KEY or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "Gemini API modu seçili fakat GEMINI_API_KEY tanımlı değil.\n"
            "  export GEMINI_API_KEY=AIza...  ya da  myagent> setup"
        )
    import google.generativeai as genai
    from myagent.config.auth import get_gemini_model

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model_name=get_gemini_model(),
        system_instruction=_system_prompt(),
    )
    prompt = (
        f"Context:\n{context}\n\nStep to execute: {step}"
        if context
        else f"Step to execute: {step}"
    )
    cfg = genai.GenerationConfig(temperature=0.1)
    if stream_callback:
        parts = []
        for chunk in m.generate_content(prompt, generation_config=cfg, stream=True):
            t = chunk.text
            if t:
                parts.append(t)
                stream_callback(t)
        return "".join(parts)
    response = m.generate_content(prompt, generation_config=cfg)
    return response.text


def _gemini_api_batch(prompt: str, stream_callback=None) -> str:
    api_key = GEMINI_API_KEY or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY tanımlı değil.")
    import google.generativeai as genai
    from myagent.config.auth import get_gemini_model

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model_name=get_gemini_model(),
        system_instruction=_batch_system_prompt(),
    )
    cfg = genai.GenerationConfig(temperature=0.1)
    if stream_callback:
        parts = []
        for chunk in m.generate_content(prompt, generation_config=cfg, stream=True):
            t = chunk.text
            if t:
                parts.append(t)
                stream_callback(t)
        return "".join(parts)
    response = m.generate_content(prompt, generation_config=cfg)
    return response.text


# ---------------------------------------------------------------------------
# Gemini CLI  (~40s/call — use batch to limit to 1 call)
# ---------------------------------------------------------------------------

def _gemini_cli_single(step: str, context: str = "", stream_callback=None) -> str:
    parts = [_system_prompt(), ""]
    if context:
        parts.append(f"Context:\n{context}")
    parts.append(f"Step to execute: {step}")
    return _gemini_cli_run("\n".join(parts), stream_callback=stream_callback)


def _gemini_cli_batch(prompt: str, stream_callback=None) -> str:
    full = _batch_system_prompt() + "\n\n" + prompt
    return _gemini_cli_run(full, stream_callback=stream_callback)


def _gemini_cli_run(full_prompt: str, stream_callback=None) -> str:
    """Run Gemini CLI, optionally streaming output via callback."""
    if stream_callback:
        return _gemini_cli_stream(full_prompt, stream_callback)

    result = _gemini_flag(full_prompt) or _gemini_stdin(full_prompt)
    if result.returncode != 0:
        raise RuntimeError(
            f"Gemini CLI hata (kod {result.returncode}):\n"
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result.stdout


def _gemini_cli_stream(full_prompt: str, callback) -> str:
    """Popen-based streaming version of _gemini_cli_run."""
    import time
    from myagent.config.auth import get_gemini_model

    m = get_gemini_model()
    cmd = ["gemini", "-m", m, "-p", full_prompt] if m else ["gemini", "-p", full_prompt]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,   # line-buffered; Node may still chunk, but flushes per \\n
        )
    except FileNotFoundError:
        raise RuntimeError("`gemini` komutu bulunamadı.")

    output_parts: list[str] = []
    deadline = time.time() + 600
    try:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            output_parts.append(line)
            callback(line)
            if time.time() > deadline:
                proc.kill()
                raise RuntimeError("Gemini CLI zaman aşımına uğradı.")
        proc.stdout.close()
        stderr = proc.stderr.read() if proc.stderr else ""
        proc.wait()
    except Exception:
        try:
            proc.kill()
        except OSError:
            pass
        raise

    if proc.returncode != 0:
        raise RuntimeError(
            f"Gemini CLI hata (kod {proc.returncode}):\n{stderr.strip()[:300]}"
        )
    return "".join(output_parts)


def _gemini_flag(prompt: str, model: str = ""):
    from myagent.config.auth import get_gemini_model
    m = model or get_gemini_model()
    cmd = ["gemini", "-m", m, "-p", prompt] if m else ["gemini", "-p", prompt]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _gemini_stdin(prompt: str, model: str = ""):
    from myagent.config.auth import get_gemini_model
    m = model or get_gemini_model()
    cmd = ["gemini", "-m", m] if m else ["gemini"]
    try:
        return subprocess.run(
            cmd,
            input=prompt,
            capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError:
        raise RuntimeError("`gemini` komutu bulunamadı.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Gemini CLI zaman aşımına uğradı.")


# ---------------------------------------------------------------------------
# Claude CLI  (~5s/call — wastes Claude tokens, use only if no Gemini)
# ---------------------------------------------------------------------------

def _claude_single(step: str, context: str = "", stream_callback=None) -> str:
    parts = [_system_prompt(), ""]
    if context:
        parts.append(f"Context:\n{context}")
    parts.append(f"Step to execute: {step}")
    return _claude_run("\n".join(parts), stream_callback=stream_callback)


def _claude_batch(prompt: str, stream_callback=None) -> str:
    full = _batch_system_prompt() + "\n\n" + prompt
    return _claude_run(full, stream_callback=stream_callback)


def _claude_run(full_prompt: str, stream_callback=None) -> str:
    from myagent.config.auth import get_claude_model
    cmd = ["claude", "-p", full_prompt, "--model", get_claude_model()]

    if stream_callback:
        import time
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
            )
        except FileNotFoundError:
            raise RuntimeError("`claude` komutu bulunamadı.")
        parts: list[str] = []
        deadline = time.time() + 180
        try:
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ""):
                parts.append(line)
                stream_callback(line)
                if time.time() > deadline:
                    proc.kill()
                    raise RuntimeError("Claude worker CLI zaman aşımına uğradı.")
            proc.stdout.close()
            stderr = proc.stderr.read() if proc.stderr else ""
            proc.wait()
        except Exception:
            try:
                proc.kill()
            except OSError:
                pass
            raise
        if proc.returncode != 0:
            raise RuntimeError(
                f"Claude worker CLI hata (kod {proc.returncode}):\n{stderr.strip()}"
            )
        return "".join(parts)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        raise RuntimeError("`claude` komutu bulunamadı.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude worker CLI zaman aşımına uğradı.")
    if result.returncode != 0:
        raise RuntimeError(
            f"Claude worker CLI hata (kod {result.returncode}):\n"
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result.stdout
