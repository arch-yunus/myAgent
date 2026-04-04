"""
Translation layer: Turkish ↔ English.

Strategy (two-pass):
  1. Dictionary substitution for known tech/command terms (fast, offline).
  2. Claude API call for full sentence-level translation (accurate, handles
     free-form Turkish input that the dictionary can't cover).

The dictionary entries are applied BEFORE the API call so that domain-specific
terminology is always rendered consistently regardless of what the model outputs.
"""

from __future__ import annotations

import re
from functools import lru_cache

# ---------------------------------------------------------------------------
# Turkish → English term dictionary
# Keys are lower-cased; longer phrases must come first so they match before
# their sub-phrases do.
# ---------------------------------------------------------------------------
TR_EN: dict[str, str] = {
    # intents / verbs
    "oluştur": "create",
    "yaz": "write",
    "yap": "make",
    "çalıştır": "run",
    "başlat": "start",
    "durdur": "stop",
    "sil": "delete",
    "listele": "list",
    "göster": "show",
    "test et": "test",
    "analiz et": "analyze",
    "optimize et": "optimize",
    "düzelt": "fix",
    "güncelle": "update",
    "ekle": "add",
    "kaldır": "remove",
    "kur": "install",
    "denetle": "audit",
    "tara": "scan",
    "keşfet": "discover",
    "bul": "find",
    # locations / prepositions
    "bulunduğum dizine": "in the current directory",
    "mevcut dizine": "in the current directory",
    "bu dizine": "in this directory",
    "dizine": "to directory",
    "dizinde": "in directory",
    "dosyaya": "to file",
    "dosyada": "in file",
    # common nouns (tech)
    "port tarayıcı": "port scanner",
    "port scanner": "port scanner",
    "ağ tarayıcı": "network scanner",
    "güvenlik açığı": "vulnerability",
    "açık port": "open port",
    "saldırı": "attack",
    "savunma": "defense",
    "şifre": "password",
    "şifreleme": "encryption",
    "anahtar": "key",
    "sertifika": "certificate",
    "web sunucu": "web server",
    "veritabanı": "database",
    "dosya": "file",
    "klasör": "folder",
    "dizin": "directory",
    "betik": "script",
    "program": "program",
    "uygulama": "application",
    "araç": "tool",
    "modül": "module",
    "kütüphane": "library",
    "paket": "package",
    "sunucu": "server",
    "istemci": "client",
    "ağ": "network",
    "bağlantı": "connection",
    "protokol": "protocol",
    "arayüz": "interface",
    "rapor": "report",
    "log": "log",
    "hata": "error",
    "uyarı": "warning",
    "bilgi": "information",
    # languages / frameworks
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "bash": "Bash",
    "go": "Go",
    "rust": "Rust",
    # articles / misc
    "bir": "a",
    "basit": "simple",
    "gelişmiş": "advanced",
    "hızlı": "fast",
    "güvenli": "secure",
    "otomatik": "automatic",
    "tam": "complete",
}

# English → Turkish (result translation)
EN_TR: dict[str, str] = {
    "Created file": "Dosya oluşturuldu",
    "created file": "dosya oluşturuldu",
    "Wrote file": "Dosya yazıldı",
    "wrote file": "dosya yazıldı",
    "Executed": "Yürütüldü",
    "executed": "yürütüldü",
    "Error in step": "Adımda hata",
    "Error": "Hata",
    "error": "hata",
    "completed": "tamamlandı",
    "Completed": "Tamamlandı",
    "skipped": "atlandı",
    "No steps generated": "Adım üretilemedi",
    "No output": "Çıktı yok",
    "Security": "Güvenlik",
    "Command not allowed": "Komut izin verilmiyor",
    "Command timed out": "Komut zaman aşımına uğradı",
    "Unrecognized output format": "Tanımlanamayan çıktı biçimi",
    "path traversal denied": "dizin geçişi reddedildi",
    "Task aborted": "Görev iptal edildi",
    "All steps completed": "Tüm adımlar tamamlandı",
    "step": "adım",
    "Step": "Adım",
    "file": "dosya",
    "File": "Dosya",
    "directory": "dizin",
    "created": "oluşturuldu",
    "written": "yazıldı",
    "deleted": "silindi",
    "running": "çalışıyor",
    "done": "bitti",
    "success": "başarılı",
    "failed": "başarısız",
}


def _apply_dict(text: str, mapping: dict[str, str]) -> str:
    """Apply all dictionary substitutions (longest-first, case-insensitive)."""
    result = text
    # Sort by length descending so longer phrases match before sub-phrases
    for src, dst in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        result = re.sub(re.escape(src), dst, result, flags=re.IGNORECASE)
    return result


# ---------------------------------------------------------------------------
# Claude-backed translation (imported lazily to avoid circular imports)
# ---------------------------------------------------------------------------

def _claude_translate(text: str, target_lang: str) -> str:
    """Use the Claude API for high-quality sentence translation."""
    try:
        import anthropic  # type: ignore
        from myagent.config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL

        if not ANTHROPIC_API_KEY:
            return text

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        lang_name = "English" if target_lang == "en" else "Turkish"
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=(
                f"You are a translator. Translate the user's text into {lang_name}. "
                "Output ONLY the translated text. No explanations. No quotes."
            ),
            messages=[{"role": "user", "content": text}],
        )
        return response.content[0].text.strip()
    except Exception:
        return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def tr_to_en(text: str) -> str:
    """Translate Turkish input to English (dictionary only, no API call)."""
    return _apply_dict(text, TR_EN)


def en_to_tr(text: str) -> str:
    """Translate English output to Turkish (dictionary only, no API call)."""
    return _apply_dict(text, EN_TR)


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

_TR_CHARS = set("şŞıİğĞüÜöÖçÇ")
_TR_WORDS = {
    "bir", "ve", "ile", "için", "bu", "oluştur", "yap", "yaz",
    "dizin", "dosya", "çalıştır", "tara", "bul",
}


def _contains_turkish(text: str) -> bool:
    if any(c in _TR_CHARS for c in text):
        return True
    words = set(re.findall(r"\b\w+\b", text.lower()))
    return bool(words & _TR_WORDS)


def _looks_english(text: str) -> bool:
    """Rough check: still has English words that weren't translated."""
    english_indicators = {
        "created", "wrote", "executed", "error", "file", "step",
        "completed", "failed", "success", "directory",
    }
    words = set(re.findall(r"\b\w+\b", text.lower()))
    return bool(words & english_indicators)
