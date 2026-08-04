"""
karpinski_client.py – klient do API Artura Karpińskiego
(ekstraklasa-scouting). Most ID między Fantasy Ekstraklasa
a danymi Sofascore (xA, xG, percentyle z adv_table.json).

Cache oparty na polu 'generated' z meta.json – różni się od
24h-TTL w network.py, dlatego używa własnych plików.

Struktura adv_table.json:
{
  "seasons": ["Ekstraklasa|25/26", "Betclic 1. Liga|25/26", ...],
  "players_by_season": {
    "Ekstraklasa|25/26": {
      "slug": {
        "expected_assists": [per90, total, percentile_per90, percentile_total],
        "expected_goals":   [per90, total, percentile_per90, percentile_total],
        ...
      }
    }
  }
}
"""

import csv
import json
import os
from datetime import datetime

import requests

from config import OUTPUT_DIR
from utils import _normalize_name

# ============================================================
# URL-e API Karpińskiego
# ============================================================

KARPINSKI_BASE = "https://arturkarpinski.com/ekstraklasa-scouting/data"
META_URL = f"{KARPINSKI_BASE}/meta.json"
PLAYERS_URL = f"{KARPINSKI_BASE}/players.json"
ADV_TABLE_URL = f"{KARPINSKI_BASE}/adv_table.json"

# ============================================================
# Ścieżki plików cache / mostu
# ============================================================

SYNC_FILE = os.path.join(OUTPUT_DIR, "karpinski_last_sync.json")
KARP_PLAYERS_CACHE = os.path.join(OUTPUT_DIR, "karpinski_players.json")
KARP_ADV_TABLE_CACHE = os.path.join(OUTPUT_DIR, "karpinski_adv_table.json")
BRIDGE_FILE = os.path.join(OUTPUT_DIR, "player_id_bridge.json")
COLLISIONS_FILE = os.path.join(OUTPUT_DIR, "bridge_collisions.json")

HEADERS = {
    "User-Agent": "ScrapFEks/1.0 (github.com/IngentingPL/ScrapFEks)",
}

# ============================================================
# WYKRYWANIE BIEŻĄCEGO SEZONU
# ============================================================

def _detect_current_ek_season(available_seasons):
    """
    Wybiera bieżący sezon Ekstraklasy z listy dostępnych sezonów
    na podstawie aktualnej daty.

    Sezon Ekstraklasy trwa od lipca do maja:
    - styczeń–czerwiec 2026 → druga połowa, sezon 2025/2026 → "Ekstraklasa|25/26"
    - lipiec–grudzień 2026 → pierwsza połowa, sezon 2026/2027 → "Ekstraklasa|26/27"

    Format sezonu w API: "Ekstraklasa|YY/YY" (dwucyfrowe lata).

    Args:
        available_seasons: lista stringów, np. ["Ekstraklasa|25/26", "Betclic 1. Liga|25/26", ...]

    Returns:
        str lub None: nazwa sezonu w formacie "Ekstraklasa|YY/YY", albo None jeśli brak.
    """
    today = datetime.now()
    year = today.year
    month = today.month
    # Wyznacz lata startowe sezonu
    start_yy = (year - 1 if month <= 6 else year) % 100
    end_yy = (start_yy + 1) % 100
    expected = f"Ekstraklasa|{start_yy:02d}/{end_yy:02d}"

    # Filtruj tylko sezony Ekstraklasy, sortuj
    ek_seasons = sorted([s for s in available_seasons if s.startswith("Ekstraklasa|")])

    if expected in ek_seasons:
        print(f"  🗓️  Wykryto bieżący sezon: {expected}")
        return expected

    # Fallback: jeśli oczekiwany sezon nie istnieje, weź ostatni dostępny
    if ek_seasons:
        fallback = ek_seasons[-1]
        print(f"  🗓️  Sezon {expected} niedostępny — fallback do {fallback}")
        return fallback

    return None

# ============================================================
# POMOCNICZE: JSON I/O
# ============================================================

def _load_json(path):
    """Wczytuje plik JSON. Zwraca {} jeśli nie istnieje lub jest uszkodzony."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_json(path, data):
    """Zapisuje dane do pliku JSON (tworzy katalog output jeśli trzeba)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ============================================================
# 1) fetch_karpinski_meta()
# ============================================================

def fetch_karpinski_meta():
    """
    Pobiera meta.json z API Karpińskiego. Porównuje pole 'generated'
    z lokalnie zapisaną wartością w output/karpinski_last_sync.json.

    Returns:
        True  — dane się zmieniły (lub pierwsze uruchomienie), trzeba pobrać
        False — generated bez zmian, można użyć zapisanych plików cache
    """
    sync_data = _load_json(SYNC_FILE)
    last_generated = sync_data.get("generated")

    try:
        resp = requests.get(META_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        meta = resp.json()
    except Exception as e:
        print(f"  ⚠️  Błąd pobierania meta.json: {e}")
        # Jeśli nie udało się pobrać, NIE pobieramy reszty
        return False

    current_generated = meta.get("generated")
    if not current_generated:
        print("  ⚠️  meta.json nie zawiera pola 'generated' — pobieram dane")
        return True

    if last_generated and last_generated == current_generated:
        print(f"📦 Karpinski: dane bez zmian od {current_generated} — pomijam pobieranie")
        return False

    print(f"🔄 Karpinski: nowe dane (generated: {current_generated}, "
          f"poprzednio: {last_generated or 'brak'}) — pobieram")
    sync_data["generated"] = current_generated
    _save_json(SYNC_FILE, sync_data)
    return True

# ============================================================
# 2) fetch_karpinski_data()
# ============================================================

def fetch_karpinski_data():
    """
    Pobiera players.json i adv_table.json z API Karpińskiego.
    Filtruje zawodników z players.json: tylko league == "Ekstraklasa"
    (API nie udostępnia pola 'season' — zawsze null).

    Dla adv_table.json: automatycznie wykrywa bieżący sezon Ekstraklasy
    z listy dostępnych sezonów i zwraca tylko tę część danych.
    Pełna struktura adv_table.json jest cache'owana do pliku.

    Zapisuje do plików cache: output/karpinski_players.json,
    output/karpinski_adv_table.json (pełna struktura).

    Jeśli dane nie zmieniły się od ostatniego uruchomienia
    (fetch_karpinski_meta() → False), wczytuje z cache z dysku.

    Returns:
        tuple: (karpinski_players, adv_table, detected_season)
            - karpinski_players: lista dictów z players.json (przefiltrowana)
            - adv_table: dict {slug: {expected_assists: [...], ...}} dla bieżącego sezonu
            - detected_season: string, np. "Ekstraklasa|25/26" lub None
    """

    # Sprawdź czy dane się zmieniły – jeśli nie, wczytaj z cache
    if not fetch_karpinski_meta():
        players = _load_json(KARP_PLAYERS_CACHE)
        full_adv = _load_json(KARP_ADV_TABLE_CACHE)
        if players and full_adv:
            # Wykryj sezon z cache'owanego adv_table
            available = full_adv.get("seasons", [])
            season = _detect_current_ek_season(available)
            adv_slice = _get_adv_slice(full_adv, season)
            print(f"  📦 Wczytano z cache: {len(players)} graczy, "
                  f"{len(adv_slice)} wpisów adv_table (sezon {season})")
            return players, adv_slice, season
        # Cache pusty/uszkodzony mimo że meta się nie zmienił?
        print("  ⚠️  Cache pusty mimo niezmienionego meta — pobieram dane")

    # Pobierz players.json
    karpinski_players = []
    try:
        resp = requests.get(PLAYERS_URL, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        raw = resp.json()

        # players.json może być listą lub dictem z kluczem "players" / "data"
        all_players = raw
        if isinstance(raw, dict):
            all_players = raw.get("players") or raw.get("data") or []

        if not isinstance(all_players, list):
            print(f"  ⚠️  players.json: nieoczekiwany format ({type(all_players).__name__})")
            all_players = []

        for p in all_players:
            if not isinstance(p, dict):
                continue
            p_league = str(p.get("league", ""))
            if p_league == "Ekstraklasa":
                karpinski_players.append(p)

        print(f"  ✓ Karpinski players.json: {len(karpinski_players)} graczy Ekstraklasy "
              f"(z {len(all_players)} ogółem)")
    except Exception as e:
        print(f"  ⚠️  Błąd pobierania players.json: {e}")
        # Próbuj wczytać z cache jako fallback
        cached = _load_json(KARP_PLAYERS_CACHE)
        if cached:
            print(f"  📦 Fallback: wczytano {len(cached)} graczy z cache")
            karpinski_players = cached

    # Zapisz do cache
    if karpinski_players:
        _save_json(KARP_PLAYERS_CACHE, karpinski_players)

    # Pobierz adv_table.json
    full_adv = {}
    try:
        resp = requests.get(ADV_TABLE_URL, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        raw_adv = resp.json()

        if isinstance(raw_adv, dict) and "players_by_season" in raw_adv:
            full_adv = raw_adv
        else:
            print(f"  ⚠️  adv_table.json: nieoczekiwany format — oczekiwano dict z 'players_by_season'")
            # Fallback: spróbuj zapisać cokolwiek
            full_adv = raw_adv if isinstance(raw_adv, dict) else {}

        num_players = sum(
            len(v) for v in full_adv.get("players_by_season", {}).values()
            if isinstance(v, dict)
        )
        num_seasons = len(full_adv.get("seasons", []))
        print(f"  ✓ Karpinski adv_table.json: {num_players} wpisów w {num_seasons} sezonach")
    except Exception as e:
        print(f"  ⚠️  Błąd pobierania adv_table.json: {e}")
        # Fallback z cache
        cached = _load_json(KARP_ADV_TABLE_CACHE)
        if cached:
            print(f"  📦 Fallback: wczytano adv_table z cache")
            full_adv = cached

    # Zapisz pełną strukturę do cache
    if full_adv:
        _save_json(KARP_ADV_TABLE_CACHE, full_adv)

    # Wykryj bieżący sezon i zwróć tylko jego część
    available = full_adv.get("seasons", [])
    season = _detect_current_ek_season(available)
    adv_slice = _get_adv_slice(full_adv, season)
    print(f"  📊 Adv slice dla sezonu {season}: {len(adv_slice)} graczy")

    return karpinski_players, adv_slice, season


def _get_adv_slice(full_adv, season):
    """
    Wyciąga część adv_table dla konkretnego sezonu.

    Args:
        full_adv: pełna struktura adv_table.json (dict z 'players_by_season')
        season: string, np. "Ekstraklasa|25/26"

    Returns:
        dict: {slug: {expected_assists: [...], ...}} lub {} jeśli brak
    """
    if not season or not full_adv:
        return {}

    players_by_season = full_adv.get("players_by_season", {})
    if not isinstance(players_by_season, dict):
        return {}

    return players_by_season.get(season, {})


# ============================================================
# 3) build_id_bridge()
# ============================================================

def build_id_bridge(fantasy_players, karpinski_players):
    """
    Buduje most ID między Fantasy Ekstraklasa a danymi Karpińskiego.
    Dopasowuje graczy po znormalizowanym imieniu+nazwisku (używa _normalize_name
    z utils.py — lowercase, bez polskich znaków).

    Zasady:
    - Gracze już obecni w player_id_bridge.json — pomijani (cache, nie dopasowujemy
      przy każdym uruchomieniu)
    - Jeśli dla jednego znormalizowanego nazwiska jest więcej niż jedno dopasowanie
      u Karpińskiego (kolizja) — NIE zgadujemy, zapisujemy osobno do
      bridge_collisions.json
    - Jeśli brak dopasowania — pomijamy, logujemy imię gracza

    Args:
        fantasy_players: lista dictów {"player_id": int, "name": str} z Fantasy
        karpinski_players: lista dictów z API Karpińskiego (muszą mieć co najmniej
                           "name", "sofascore_id", "slug", "tm_id")

    Returns:
        dict: zaktualizowany bridge {fantasy_player_id: {sofascore_id, slug, tm_id}}
    """
    # Wczytaj istniejący most
    bridge = _load_json(BRIDGE_FILE)
    # Konwertuj klucze na int (JSON zapisuje jako string)
    bridge = {int(k): v for k, v in bridge.items() if isinstance(v, dict)}

    # Wczytaj istniejące kolizje
    collisions = _load_json(COLLISIONS_FILE)
    if not isinstance(collisions, list):
        collisions = []

    # Zbuduj indeks Karpińskiego: normalized_name → lista pasujących wpisów
    karpinski_index = {}  # {norm_name: [entry, ...]}
    for kp in karpinski_players:
        name = kp.get("name", "")
        if not name:
            continue
        norm = _normalize_name(name)
        if not norm:
            continue
        if norm not in karpinski_index:
            karpinski_index[norm] = []
        karpinski_index[norm].append(kp)

    # Statystyki do logowania
    already_bridged = 0
    new_matches = 0
    collisions_new = 0
    no_match = 0

    for fp in fantasy_players:
        fp_id = fp.get("player_id")
        if not fp_id:
            continue
        fp_id = int(fp_id)

        # Gracz już w moście — pomiń
        if fp_id in bridge:
            already_bridged += 1
            continue

        fp_name = fp.get("name", "")
        norm = _normalize_name(fp_name)
        if not norm:
            no_match += 1
            continue

        matches = karpinski_index.get(norm, [])

        if len(matches) == 0:
            no_match += 1
            print(f"  ❌ Brak dopasowania: {fp_name} (ID {fp_id})")
            continue

        if len(matches) > 1:
            # Kolizja — kilka graczy Karpińskiego z tym samym znormalizowanym imieniem
            collisions_new += 1
            options = []
            for m in matches:
                options.append({
                    "name": m.get("name", "?"),
                    "sofascore_id": m.get("sofascore_id"),
                    "slug": m.get("slug"),
                    "tm_id": m.get("tm_id"),
                    "team": m.get("team", ""),
                })
            collision_entry = {
                "fantasy_id": fp_id,
                "fantasy_name": fp_name,
                "normalized": norm,
                "karpinski_options": options,
            }
            collisions.append(collision_entry)
            print(f"  ⚠️  KOLIZJA dla '{fp_name}' (ID {fp_id}): "
                  f"{len(matches)} opcji — zapisano do bridge_collisions.json")
            # Lista opcji do ręcznego rozstrzygnięcia
            for m in matches:
                m_name = m.get("name", "?")
                m_slug = m.get("slug", "?")
                m_team = m.get("team", "")
                print(f"      → {m_name} (slug: {m_slug}, team: {m_team})")
            continue

        # Dokładnie jedno dopasowanie — dodaj do mostu
        match = matches[0]
        bridge[fp_id] = {
            "sofascore_id": match.get("sofascore_id"),
            "slug": match.get("slug"),
            "tm_id": match.get("tm_id"),
        }
        new_matches += 1
        print(f"  ✅ Dopasowano: {fp_name} (ID {fp_id}) → {match.get('name')} "
              f"(slug: {match.get('slug')})")

    # Zapisz zaktualizowany most i kolizje
    if new_matches > 0:
        _save_json(BRIDGE_FILE, bridge)
        print(f"\n  💾 Zapisano most: +{new_matches} nowych wpisów "
              f"(łącznie {len(bridge)} w player_id_bridge.json)")

    if collisions_new > 0:
        _save_json(COLLISIONS_FILE, collisions)
        print(f"  💾 Zapisano {collisions_new} nowych kolizji "
              f"(łącznie {len(collisions)} w bridge_collisions.json)")

    # Podsumowanie
    total_fantasy = already_bridged + new_matches + collisions_new + no_match
    print(f"\n  📊 Podsumowanie mostu:")
    print(f"     Łącznie graczy Fantasy: {total_fantasy}")
    print(f"     Już w moście:          {already_bridged}")
    print(f"     Nowe dopasowania:      {new_matches}")
    print(f"     Kolizje (ręczne):      {collisions_new}")
    print(f"     Bez dopasowania:       {no_match}")

    return bridge

# ============================================================
# 4) get_karpinski_stats()
# ============================================================

def get_karpinski_stats(fantasy_player_id):
    """
    Zwraca statystyki z adv_table.json dla danego gracza Fantasy (przez most ID).
    Automatycznie wykrywa bieżący sezon Ekstraklasy z cache'owanego adv_table.

    Args:
        fantasy_player_id: int – ID gracza z Fantasy Ekstraklasy

    Returns:
        dict lub None:
        {
            "slug": "kamil-grosicki",
            "expected_assists": 0.23,       # expected_assists[0] — per 90
            "expected_goals": 1.05,          # expected_goals[0] — per 90
            "percentile_xa": 92.4,           # expected_assists[2] — percentyl per 90
            "percentile_xg": 88.7,           # expected_goals[2] — percentyl per 90
            "shots_per_90": 3.0,             # adv_table["shots"][0] — per 90
            "chances_created_per_90": 1.5,   # adv_table["chances_created"][0] — per 90
            "clean_sheet_rate": 0.33,        # adv_table["clean_sheet_team_title"][0] — per 90
            "goals_conceded_per_90": 1.2,    # adv_table["goals_conceded"][0] — per 90
            "rating": 7.15,                  # players.json — ocena (float lub None)
        }
        None jeśli gracza nie ma w moście lub nie ma go w adv_table.
    """
    # Wczytaj most
    bridge = _load_json(BRIDGE_FILE)
    bridge = {int(k): v for k, v in bridge.items() if isinstance(v, dict)}

    entry = bridge.get(fantasy_player_id)
    if not entry:
        return None

    slug = entry.get("slug")
    if not slug:
        return None

    # Wczytaj adv_table i wykryj sezon
    full_adv = _load_json(KARP_ADV_TABLE_CACHE)
    if not full_adv:
        return None

    available = full_adv.get("seasons", [])
    season = _detect_current_ek_season(available)
    adv_slice = _get_adv_slice(full_adv, season)

    adv = adv_slice.get(slug)
    if not adv:
        return None

    # Bezpieczne wyciąganie wartości z tablic
    def _safe_idx(arr, idx, default=None):
        """Bezpiecznie pobiera element z listy po indeksie."""
        if isinstance(arr, list) and len(arr) > idx:
            try:
                return float(arr[idx])
            except (ValueError, TypeError):
                return default
        return default

    xa_raw = adv.get("expected_assists")
    xg_raw = adv.get("expected_goals")

    # Nowe pola z adv_table (indeks 0 = per 90)
    shots_raw = adv.get("shots")
    chances_raw = adv.get("chances_created")
    cs_raw = adv.get("clean_sheet_team_title")
    gc_raw = adv.get("goals_conceded")

    # Ocena gracza z players.json (Karpińskiego) — wyszukaj po slugu
    rating = None
    karp_players = _load_json(KARP_PLAYERS_CACHE)
    if karp_players:
        for kp in karp_players:
            if isinstance(kp, dict) and kp.get("slug") == slug:
                raw_rating = kp.get("rating")
                if raw_rating not in (None, ""):
                    try:
                        rating = float(raw_rating)
                    except (ValueError, TypeError):
                        rating = None
                break

    result = {
        "slug": slug,
        "expected_assists": _safe_idx(xa_raw, 0),
        "expected_goals": _safe_idx(xg_raw, 0),
        "percentile_xa": _safe_idx(xa_raw, 2),
        "percentile_xg": _safe_idx(xg_raw, 2),
        # Nowe pola z adv_table, per 90
        "shots_per_90": _safe_idx(shots_raw, 0),
        "chances_created_per_90": _safe_idx(chances_raw, 0),
        "clean_sheet_rate": _safe_idx(cs_raw, 0),
        "goals_conceded_per_90": _safe_idx(gc_raw, 0),
        # Ocena z players.json
        "rating": rating,
    }

    return result

# ============================================================
# FUNKCJA TESTOWA main()
# ============================================================

def main():
    """
    Funkcja testowa: ładuje graczy Fantasy z najnowszego CSV w output/,
    pobiera dane Karpińskiego, buduje most, zapisuje raport do /tmp.
    """
    print("=" * 60)
    print("  karpinski_client.py – testowe uruchomienie")
    print("=" * 60)

    # --- Krok 1: Wczytaj graczy Fantasy z najnowszego CSV ---
    print("\n🔍 Szukam najnowszego fantasy_players_*.csv...")
    output_files = sorted(
        [f for f in os.listdir(OUTPUT_DIR) if f.startswith("fantasy_players_") and f.endswith(".csv")],
        reverse=True,
    )
    if not output_files:
        print("  ❌ Nie znaleziono pliku fantasy_players_*.csv w output/")
        return

    latest_csv = os.path.join(OUTPUT_DIR, output_files[0])
    print(f"  📄 Wczytuję: {latest_csv}")

    fantasy_players = []
    try:
        with open(latest_csv, "r", encoding="utf-8-sig") as f:  # utf-8-sig usuwa BOM
            reader = csv.DictReader(f)
            for row in reader:
                pid = row.get("player_id", "").strip()
                name = row.get("name", "").strip()
                if pid and name:
                    fantasy_players.append({
                        "player_id": int(pid),
                        "name": name,
                        "team": row.get("team", "").strip(),
                        "position": row.get("position", "").strip(),
                    })
    except Exception as e:
        print(f"  ❌ Błąd wczytywania CSV: {e}")
        return

    print(f"  ✓ Wczytano {len(fantasy_players)} graczy Fantasy")

    # --- Krok 2: Pobierz dane Karpińskiego ---
    print("\n🌐 Pobieram dane Karpińskiego...")
    karp_players, adv_table, detected_season = fetch_karpinski_data()

    if not karp_players:
        print("  ❌ Brak danych Karpińskiego – nie można zbudować mostu")
        return

    # --- Krok 3: Zbuduj most ---
    print(f"\n🔗 Buduję most ID ({len(fantasy_players)} Fantasy ↔ {len(karp_players)} Karpinski)...")
    bridge = build_id_bridge(fantasy_players, karp_players)

    # --- Krok 4: Raport do /tmp ---
    bridge = _load_json(BRIDGE_FILE)
    bridge = {int(k): v for k, v in bridge.items() if isinstance(v, dict)}
    collisions = _load_json(COLLISIONS_FILE)
    if not isinstance(collisions, list):
        collisions = []

    matched = len(bridge)
    unmatched = sum(
        1 for fp in fantasy_players
        if int(fp.get("player_id", 0)) not in bridge
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"/tmp/karpinski_bridge_report_{timestamp}.txt"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"Raport mostu Karpiński – {datetime.now().isoformat()}\n")
            f.write(f"{'=' * 60}\n")
            f.write(f"Źródło Fantasy:  {latest_csv}\n")
            f.write(f"Sezon adv_table: {detected_season or 'nie wykryto'}\n")
            f.write(f"\nStatystyki dopasowania:\n")
            f.write(f"  Graczy Fantasy ogółem:  {len(fantasy_players)}\n")
            f.write(f"  Graczy Karpińskiego:    {len(karp_players)}\n")
            f.write(f"  Dopasowanych w moście:  {matched}\n")
            f.write(f"  Bez dopasowania:        {unmatched}\n")
            f.write(f"  Kolizje do ręcznego:    {len(collisions)}\n")
            f.write(f"\n  Pokrycie: {matched}/{len(fantasy_players)} "
                    f"({100 * matched / max(len(fantasy_players), 1):.1f}%)\n")

            if unmatched > 0:
                f.write(f"\nGracze bez dopasowania:\n")
                for fp in fantasy_players:
                    pid = int(fp.get("player_id", 0))
                    if pid not in bridge:
                        f.write(f"  - {fp['name']} (ID {pid}, {fp.get('team', '?')})\n")

            if collisions:
                f.write(f"\nKolizje ({len(collisions)}):\n")
                for c in collisions:
                    f.write(f"  - {c['fantasy_name']} (ID {c['fantasy_id']})\n")
                    for opt in c.get("karpinski_options", []):
                        f.write(f"      → {opt.get('name')} (slug: {opt.get('slug')}, "
                                f"team: {opt.get('team', '?')})\n")

        print(f"\n📝 Raport zapisany: {report_path}")
    except OSError as e:
        print(f"  ⚠️  Nie można zapisać raportu do {report_path}: {e}")

    # --- Krok 5: Test get_karpinski_stats() dla pierwszego gracza ---
    if bridge:
        first_id = next(iter(bridge))
        stats = get_karpinski_stats(first_id)
        print(f"\n🧪 Test get_karpinski_stats(ID {first_id}):")
        if stats:
            print(f"   slug:            {stats.get('slug')}")
            print(f"   expected_assists: {stats.get('expected_assists')}")
            print(f"   expected_goals:   {stats.get('expected_goals')}")
            print(f"   percentile_xa:    {stats.get('percentile_xa')}")
            print(f"   percentile_xg:    {stats.get('percentile_xg')}")
        else:
            print(f"   Brak wpisu w adv_table dla tego gracza")

    print(f"\n✅ Koniec testowego uruchomienia.")


if __name__ == "__main__":
    main()
