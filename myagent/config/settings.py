import os
from pathlib import Path

# API Keys — set via environment variables
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

# Model identifiers
CLAUDE_MODEL: str = "claude-opus-4-6"
GEMINI_MODEL: str = "gemini-2.0-flash"

# Limits
MAX_STEPS: int = 10
BASH_TIMEOUT: int = 15

# Working directory for file/command execution (resolved at import time)
WORK_DIR: Path = Path(os.environ.get("MYAGENT_WORK_DIR", os.getcwd())).resolve()

# Prompts directory
PROMPTS_DIR: Path = Path(__file__).parent.parent / "prompts"


def validate() -> list[str]:
    """Return missing required config items.

    Only flags API keys as missing when the corresponding mode is 'api'.
    In CLI mode the key is not needed.
    """
    from myagent.config.auth import API, get_claude_mode, get_gemini_mode

    missing: list[str] = []
    if get_claude_mode() == API and not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if get_gemini_mode() == API and not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    return missing
