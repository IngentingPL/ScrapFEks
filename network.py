"""
network.py - transport HTTP: retry logic i cache zewnętrznych
statystyk (90minut.pl i API ekstraklasy). Izolowana warstwa sieciowa
bez logiki biznesowej.
"""

import os
import json
import time
from datetime import datetime

import requests

from config import OUTPUT_DIR


def _request_with_retry(method, url, max_retries=3, **kwargs):
    """
    Wykonuje request HTTP z retry (exponential backoff: 1s, 2s, 4s).
    method: requests.get lub requests.post
    Zwraca response albo None jeśli wszystkie próby zawiodły.
    """
    for attempt in range(max_retries):
        try:
            return method(url, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"   ⚠️  Błąd sieci ({e.__class__.__name__}), próba {attempt+1}/{max_retries}, czekam {wait}s...")
                time.sleep(wait)
            else:
                print(f"   ❌ Wszystkie {max_retries} próby nieudane: {url}")
                return None
    return None


# ============================================================
# CACHE ZEWNĘTRZNYCH ŹRÓDEŁ (90minut.pl, ekstraklasa.org API)
# ============================================================

def _load_external_cache():
    """Wczytuje cache zewnętrznych statystyk z external_cache.json."""
    try:
        with open(os.path.join(OUTPUT_DIR, "external_cache.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get_cached_external(key, ttl_hours=24):
    """Zwraca dane z cache jeśli są świeższe niż ttl_hours, inaczej None."""
    entry = _load_external_cache().get(key)
    if not entry:
        return None
    try:
        ts = datetime.fromisoformat(entry["timestamp"])
    except (KeyError, ValueError):
        return None
    age_h = (datetime.now() - ts).total_seconds() / 3600
    if age_h < entry.get("ttl_hours", ttl_hours):
        print(f"📦 Cache hit dla '{key}' (wiek: {age_h:.1f}h)")
        return entry["data"]
    return None


def _save_external_cache(key, data, ttl_hours=24):
    """Zapisuje dane do cache, zachowując inne klucze w pliku."""
    cache = _load_external_cache()
    cache[key] = {
        "timestamp": datetime.now().isoformat(),
        "ttl_hours": ttl_hours,
        "data": data,
    }
    with open(os.path.join(OUTPUT_DIR, "external_cache.json"), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
