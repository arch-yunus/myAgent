import locale
import os

SUPPORTED_LANGUAGES = {"tr", "en"}
DEFAULT_LANGUAGE = "tr"


def get_system_language() -> str:
    """Detect system language; default to Turkish."""
    # 1. Check LANG env var
    lang_env = os.environ.get("LANG", "")
    if lang_env.lower().startswith("tr"):
        return "tr"
    if lang_env.lower().startswith("en"):
        return "en"

    # 2. Check LC_ALL / LC_MESSAGES
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        val = os.environ.get(var, "")
        if val.lower().startswith("tr"):
            return "tr"
        if val.lower().startswith("en"):
            return "en"

    # 3. Try Python locale
    try:
        loc, _ = locale.getdefaultlocale()
        if loc and loc.lower().startswith("tr"):
            return "tr"
        if loc and loc.lower().startswith("en"):
            return "en"
    except Exception:
        pass

    return DEFAULT_LANGUAGE


# Module-level constant — resolved once at import
SYSTEM_LANGUAGE: str = get_system_language()
