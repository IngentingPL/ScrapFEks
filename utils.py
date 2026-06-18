"""
utils.py - funkcje normalizujące i bezpieczne konwersje typów,
używane w wielu miejscach scraper.py. Zero zależności od reszty
projektu - czyste funkcje bezstanowe.
"""

import re
import unicodedata


def normalize_team_name(name: str) -> str:
    """Normalizuj nazwę drużyny: lowercase + usuń polskie diakrytyki."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_name = ascii_name.replace("ł", "l").replace("Ł", "L")
    return ascii_name.lower().strip()

def _normalize_name(name: str) -> str:
    """Normalizuj imię i nazwisko: lowercase + usuń polskie diakrytyki, zachowaj spację."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_name = ascii_name.replace("ł", "l").replace("Ł", "L")
    return ascii_name.lower().strip()


def _safe_int(val: str) -> int:
    """Bezpiecznie konwertuje string na int."""
    try:
        return int(re.sub(r"[^\d-]", "", val or "0") or "0")
    except (ValueError, TypeError):
        return 0


def _safe_float(val: str) -> float:
    """Bezpiecznie konwertuje string na float."""
    try:
        return float(re.sub(r"[^\d.,\-]", "", val or "0").replace(",", ".") or "0")
    except (ValueError, TypeError):
        return 0.0


def _normalize_team(name: str) -> str:
    """Normalizuje nazwę drużyny dla porównań (strip, NFKD, lower)."""
    return unicodedata.normalize("NFKD", name.strip()).lower()
