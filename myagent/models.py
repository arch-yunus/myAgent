"""
Model registry: curated model lists, alias resolution, live API discovery.

Each model has a canonical ID, a list of short aliases, a description,
and a provider tag ("claude" | "gemini").

Resolution order when the user provides a name:
  1. Exact match on model ID
  2. Alias match
  3. Substring match on ID (e.g. "opus" matches "claude-opus-4-6")
  4. Treat as a raw model ID (user typed a model not in the curated list)
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ModelInfo:
    id: str
    aliases: list[str]
    description: str
    provider: str           # "claude" | "gemini"
    is_recommended: bool = False


# ---------------------------------------------------------------------------
# Curated Claude models
# ---------------------------------------------------------------------------

CLAUDE_CURATED: list[ModelInfo] = [
    ModelInfo(
        id="claude-opus-4-6",
        aliases=["opus", "opus4", "opus-4"],
        description="Most capable — best for complex multi-step planning (recommended)",
        provider="claude",
        is_recommended=True,
    ),
    ModelInfo(
        id="claude-sonnet-4-6",
        aliases=["sonnet", "sonnet4", "sonnet-4"],
        description="Balanced speed and quality — good for most planning tasks",
        provider="claude",
    ),
    ModelInfo(
        id="claude-haiku-4-5-20251001",
        aliases=["haiku", "haiku4", "haiku-4"],
        description="Fast and lightweight — simple or low-latency tasks",
        provider="claude",
    ),
]

# Default Claude model ID
CLAUDE_DEFAULT = "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Curated Gemini models
# ---------------------------------------------------------------------------

GEMINI_CURATED: list[ModelInfo] = [
    ModelInfo(
        id="gemini-2.5-flash",
        aliases=["2.5-flash", "2.5flash", "2.5", "flash"],
        description="Fast with built-in reasoning — recommended for code generation",
        provider="gemini",
        is_recommended=True,
    ),
    ModelInfo(
        id="gemini-2.5-pro",
        aliases=["2.5-pro", "2.5pro", "pro"],
        description="Most capable — complex reasoning, best for difficult tasks",
        provider="gemini",
    ),
    ModelInfo(
        id="gemini-2.0-flash",
        aliases=["2.0-flash", "2.0", "2flash"],
        description="Stable and fast — previous generation, reliable fallback",
        provider="gemini",
    ),
    ModelInfo(
        id="gemini-3-flash",
        aliases=["3-flash", "3flash"],
        description="Gemini 3 Flash — not yet GA, may return 404",
        provider="gemini",
    ),
    ModelInfo(
        id="gemini-3.1-pro",
        aliases=["3-pro", "3pro", "3.1-pro"],
        description="Gemini 3.1 Pro — not yet GA, may return 404",
        provider="gemini",
    ),
]

# Default Gemini model ID
GEMINI_DEFAULT = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------

def resolve_model(name: str, provider: str) -> str:
    """Resolve *name* to a full model ID for *provider*.

    Returns the resolved canonical ID, or *name* unchanged if it doesn't match
    anything in the curated list (treated as a raw model ID).
    """
    curated = CLAUDE_CURATED if provider == "claude" else GEMINI_CURATED
    lower = name.lower().strip()

    # 1. Exact ID match
    for m in curated:
        if m.id.lower() == lower:
            return m.id

    # 2. Alias match
    for m in curated:
        if lower in [a.lower() for a in m.aliases]:
            return m.id

    # 3. Substring match in ID
    for m in curated:
        if lower in m.id.lower():
            return m.id

    # 4. Unknown — pass through as-is (user might know a new model ID)
    return name


# ---------------------------------------------------------------------------
# Live model discovery
# ---------------------------------------------------------------------------

def fetch_claude_models(api_key: str) -> list[ModelInfo]:
    """Fetch live Claude models from Anthropic API.

    Falls back to the curated list on any error.
    """
    try:
        import anthropic  # type: ignore
        client = anthropic.Anthropic(api_key=api_key)
        response = client.models.list()

        live_ids: set[str] = {m.id for m in response.data}

        result: list[ModelInfo] = []
        seen: set[str] = set()

        # Keep curated entries that are actually live
        for curated in CLAUDE_CURATED:
            if curated.id in live_ids:
                result.append(curated)
                seen.add(curated.id)

        # Append newly discovered models not in the curated list
        for live_model in response.data:
            if live_model.id not in seen:
                result.append(ModelInfo(
                    id=live_model.id,
                    aliases=[],
                    description="(discovered via API)",
                    provider="claude",
                ))

        return result or CLAUDE_CURATED

    except Exception:
        return CLAUDE_CURATED


def fetch_gemini_models(api_key: str) -> list[ModelInfo]:
    """Fetch live Gemini text-generation models from the Google AI API.

    Falls back to the curated list on any error.
    """
    try:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=api_key)

        live_ids: set[str] = set()
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", [])
            if "generateContent" in methods:
                mid = m.name.replace("models/", "")
                live_ids.add(mid)

        result: list[ModelInfo] = []
        seen: set[str] = set()

        for curated in GEMINI_CURATED:
            if curated.id in live_ids:
                result.append(curated)
                seen.add(curated.id)

        for mid in sorted(live_ids):
            if mid not in seen and "gemini" in mid.lower():
                result.append(ModelInfo(
                    id=mid,
                    aliases=[],
                    description="(discovered via API)",
                    provider="gemini",
                ))

        return result or GEMINI_CURATED

    except Exception:
        return GEMINI_CURATED


# ---------------------------------------------------------------------------
# Formatting helpers (used by --list-models and setup wizard)
# ---------------------------------------------------------------------------

def format_model_table(models: list[ModelInfo], current_id: str = "") -> str:
    """Return a human-readable table of models."""
    lines: list[str] = []
    for m in models:
        alias_str = ", ".join(m.aliases) if m.aliases else "—"
        tag = " [current]" if m.id == current_id else ""
        rec = " *" if m.is_recommended else "  "
        lines.append(f"  {rec} {m.id:<35}  aliases: {alias_str:<18}  {m.description}{tag}")
    return "\n".join(lines)
