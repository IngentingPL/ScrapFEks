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


def _request_with_retry(method, url, max_retries=3, session=None, **kwargs):
    """
    Wykonuje request HTTP z retry (max 3 próby, komunikaty "próba X/3"):
    - wyjątki sieciowe (Timeout, ConnectionError) — rosnący odstęp 1s, 2s,
    - HTTP 429 — ponowienia, czeka wg nagłówka Retry-After (max 10s),
      bez Retry-After: rosnący odstęp 1s, 2s,
    - HTTP 5xx — ponowienia z rosnącym odstępem 1s, 2s,
    - 404 i inne 4xx — bez ponowienia (odpowiedź wraca od razu).
    method: requests.get lub requests.post
    Jeśli session podana — używa session.get() / session.post(),
    co zapewnia poprawne zarządzanie cookies (CookieJar).
    Domyślny timeout 30s (można nadpisać przez kwargs["timeout"]).
    Zwraca response — także gdy wszystkie próby dostawały 429/5xx
    (wywołujący może zalogować status i treść) — albo None, gdy
    wszystkie próby zawiodły na wyjątku sieciowym.
    """
    kwargs.setdefault("timeout", 30)  # ochrona przed "wiszącymi" requestami

    response = None
    for attempt in range(max_retries):
        try:
            if session is not None:
                # Użyj metody z sesji zamiast modułowej — cookies z CookieJar
                if method == requests.get:
                    response = session.get(url, **kwargs)
                elif method == requests.post:
                    response = session.post(url, **kwargs)
                else:
                    response = method(url, **kwargs)
            else:
                response = method(url, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"   ⚠️  Błąd sieci ({e.__class__.__name__}), próba {attempt+1}/{max_retries}, czekam {wait}s...")
                time.sleep(wait)
                continue
            print(f"   ❌ Wszystkie {max_retries} próby nieudane: {url}")
            return None

        status = response.status_code
        if status == 429 or 500 <= status < 600:
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s
                if status == 429:
                    # Retry-After: sekundy (fallback: rosnący odstęp), max 10s
                    try:
                        retry_after = int(float(response.headers.get("Retry-After", "")))
                        wait = min(max(retry_after, 0), 10)
                    except (TypeError, ValueError):
                        pass
                print(f"   ⚠️  HTTP {status}, próba {attempt+1}/{max_retries}, czekam {wait}s...")
                time.sleep(wait)
                continue
            print(f"   ❌ HTTP {status} po {max_retries} próbach: {url}")
            return response

        return response  # 2xx oraz 4xx (bez ponowień)
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
