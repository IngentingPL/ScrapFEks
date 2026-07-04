"""
conceptually_client.py - pobieranie statystyk zawodników z
conceptuallyfootball.com (xA, percentyle). Cache 24h.
Źródło: Sofascore. robots.txt pozwala na scraping.
"""

import requests

from network import _get_cached_external, _save_external_cache
from utils import _normalize_name


def fetch_conceptually_stats(competition="POL1", season="2025-26"):
    """
    Pobiera statystyki zawodników z conceptuallyfootball.com (Sofascore).
    
    API endpoint: /api/v1/player-seasons/derived-stats
    Zwraca dane xA, xG, goals, assists per 90 oraz percentyle.
    
    Returns:
        dict: {normalized_name: {"xa_per_90": float, "percentile_xa": float, ...}}
    """
    # Cache 24h — unikamy ponownego odpytywania API przy każdym runie
    cached = _get_cached_external("conceptually_stats")
    if cached is not None:
        return cached

    url = "https://conceptuallyfootball.com/api/v1/player-seasons/derived-stats"
    headers = {
        "User-Agent": "ScrapFEks/1.0 (github.com/IngentingPL/ScrapFEks)",
    }
    params = {"competition": competition, "season": season, "include": "meta"}

    result = {}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        players = data.get("results", [])
        if not players:
            print("  ⚠️  CF API: brak wyników")
            return result

        with_xa = 0
        for p in players:
            name = p.get("canonical_player_name", "")
            if not name:
                continue

            norm = _normalize_name(name)
            metrics = p.get("metrics", {}) or {}
            percentiles = p.get("percentiles", {}) or {}

            # Dodaj statystyki — używamy .get() z None jako domyślnym,
            # żeby odróżnić brak danych od wartości 0
            entry = {
                "xa_per_90": _safe_float_or_none(metrics.get("xa_per_90")),
                "goals_per_90": _safe_float_or_none(metrics.get("goals_per_90")),
                "assists_per_90": _safe_float_or_none(metrics.get("assists_per_90")),
                "percentile_xa": _safe_float_or_none(percentiles.get("xa_per_90")),
                "percentile_xg": _safe_float_or_none(percentiles.get("xg_per_90")),
            }

            result[norm] = entry
            if entry["xa_per_90"] is not None:
                with_xa += 1

        print(f"  ✓ CF: {len(result)} graczy, {with_xa} z xA")

    except Exception as e:
        print(f"  ⚠️  Błąd pobierania z conceptuallyfootball.com: {e}")

    # Zapisz do cache tylko jeśli pobrano niepuste dane
    if result:
        _save_external_cache("conceptually_stats", result)
    return result


def _safe_float_or_none(val):
    """Bezpiecznie konwertuje wartość na float. Zwraca None jeśli konwersja niemożliwa."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
