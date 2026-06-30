"""
transfers.py - obliczanie transferów w lidze prywatnej (K-1 → K)
i statystyki zawodników per 90 minut.
"""

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import WORKERS
from utils import _normalize_name
from squads import scrape_team_squad


def _fetch_prev_squad(args):
    """Worker do pobrania składu z poprzedniej kolejki (thread-safe).
    Zwraca (slug, set[pids], error_msg|None)."""
    session, slug, prev_round = args
    try:
        prev_squad_data = scrape_team_squad(session, slug, round_num=prev_round)
        return (slug, {
            str(p.get("player_id"))
            for p in prev_squad_data.get("players", [])
            if p.get("player_id")
        }, None)
    except Exception as e:
        return (slug, set(), str(e))


def compute_league_transfers(
    session: requests.Session,
    league_results: list[dict],
    current_round: int,
    player_lookup: dict,
) -> dict:
    """
    Oblicza popularne transfery w lidze prywatnej.
    Porównuje skład każdej drużyny w current_round vs current_round-1
    i zlicza, ile drużyn kupło / sprzedało każdego zawodnika.
    """
    empty = {
        "gameweek": current_round,
        "prev_gameweek": max(current_round - 1, 1),
        "league_teams_count": 0,
        "transfers_in": [],
        "transfers_out": [],
    }

    if not league_results or current_round <= 1:
        return empty

    prev_round = current_round - 1
    total_teams = len(league_results)

    transfers_in_count: dict[str, int] = {}
    transfers_out_count: dict[str, int] = {}

    print(f"\n🔄 Obliczam transfery ligi (K{prev_round} → K{current_round}, {total_teams} drużyn)...")

    # Zbuduj mapę slug → current_pids (składy z obecnej kolejki już pobrane)
    slug_to_current_pids: dict[str, set[str]] = {}
    for team in league_results:
        slug = team.get("team_slug", "")
        if not slug:
            continue
        current_pids = {
            str(p.get("player_id"))
            for p in team.get("squad", [])
            if p.get("player_id")
        }
        slug_to_current_pids[slug] = current_pids

    # Równoległe pobieranie składów K{prev_round} (ThreadPoolExecutor)
    # Wzorzec identyczny jak w scrape_teams_captains()
    print(f"   Równoległe pobieranie składów K{prev_round} ({WORKERS} workerów)...")
    args_list = [(session, slug, prev_round) for slug in slug_to_current_pids]
    total = len(slug_to_current_pids)
    completed = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(_fetch_prev_squad, args): args[1] for args in args_list}
        for future in as_completed(futures):
            slug = futures[future]
            try:
                result_slug, prev_pids, error = future.result(timeout=30)
            except Exception as e:
                prev_pids = set()
                error = str(e)

            if error:
                errors += 1
                if errors <= 3:  # Pokaż pierwsze 3 błędy (jak w oryginale)
                    print(f"   ⚠️  Błąd pobierania K{prev_round} dla {slug}: {error}")

            # Transfery IN = pojawili się w current, nie było ich w prev
            current_pids = slug_to_current_pids.get(slug, set())
            for pid in current_pids - prev_pids:
                transfers_in_count[pid] = transfers_in_count.get(pid, 0) + 1
            # Transfery OUT = byli w prev, nie ma ich w current
            for pid in prev_pids - current_pids:
                transfers_out_count[pid] = transfers_out_count.get(pid, 0) + 1

            completed += 1
            if completed % 5 == 0 or completed == total:
                print(f"   [{completed}/{total}] drużyn przetworzono")

    def _build_list(count_dict: dict, limit: int = 15) -> list[dict]:
        rows = []
        for pid, count in sorted(count_dict.items(), key=lambda x: x[1], reverse=True):
            full = player_lookup.get(str(pid), {})
            if not full:
                continue
            # Zmiana ceny z historii
            price_change = 0.0
            ph = full.get("price_history", [])
            if len(ph) >= 2:
                price_change = round((ph[-1].get("price") or 0) - (ph[-2].get("price") or 0), 2)
            rows.append({
                "player_id": pid,
                "name": full.get("name", ""),
                "position": full.get("position", ""),
                "team": full.get("team", ""),
                "price": full.get("price", 0),
                "price_change": price_change,
                "count": count,
                "pct": round(count / total_teams * 100, 1),
            })
            if len(rows) >= limit:
                break
        return rows

    result = {
        "gameweek": current_round,
        "prev_gameweek": prev_round,
        "league_teams_count": total_teams,
        "transfers_in": _build_list(transfers_in_count),
        "transfers_out": _build_list(transfers_out_count),
    }

    t_in = len(result["transfers_in"])
    t_out = len(result["transfers_out"])
    print(f"   ✅ Transfery: {t_in} kupno, {t_out} sprzedaż (top 15 każdy)")
    return result


def compute_player_stats_per90(
    extra_stats: dict,
    players_data: list[dict],
    player_minutes: dict
) -> list[dict]:
    """
    Przelicza statystyki na wartość per 90 minut i dopasowuje do danych zawodników.
    
    Parametry:
        extra_stats: dict ze statystykami {stat: {name: value}}
        players_data: lista zawodników z fantasy
        player_minutes: dict {player_id: total_minutes}
    
    Zwraca:
        Lista zawodników z nowymi polami: xg_per90, shots_per90, itp.
    """
    if not extra_stats or not players_data:
        return players_data
    
    # DEBUG: pokaż przykładowe nazwy z obu źródeł
    fantasy_names = [p.get("name", "") for p in players_data[:10] if p.get("name")]
    extra_names = list(extra_stats.get("xg", {}).keys())[:10] if extra_stats.get("xg") else []
    print(f"   DEBUG Fantasy (pierwsze 5): {fantasy_names[:5]}")
    print(f"   DEBUG Ekstraklasa (pierwsze 5): {extra_names[:5]}")
    
    # Normalizuj nazwy zawodników z fantasy (klucz: znormalizowana nazwa -> player_id)
    normalized_lookup = {}
    fantasy_names_normalized = []  # do fuzzy matching
    for p in players_data:
        name = p.get("name", "")
        if name:
            # Normalizuj: lowercase + usuń polskie znaki
            norm_name = _normalize_name(name)
            normalized_lookup[norm_name] = str(p.get("player_id", ""))
            # Zapisz też oryginalną nazwę (bez normalizacji)
            normalized_lookup[name.lower()] = str(p.get("player_id", ""))
            # Zapisz do fuzzy matching (tylko last name)
            last_name = norm_name.split()[-1] if norm_name else ""
            if last_name:
                fantasy_names_normalized.append((last_name, str(p.get("player_id", "")), name))
    
    # Build last name lookup dla fuzzy matching
    last_name_map = {}  # last_name -> [(player_id, full_name), ...]
    for ln, pid, full in fantasy_names_normalized:
        if ln not in last_name_map:
            last_name_map[ln] = []
        last_name_map[ln].append((pid, full))
    
    # scalono pętlę debug z pętlą produkcyjną - ta sama logika dopasowania, raz
    sample_matches = []  # dokładne dopasowania (debug)
    fuzzy_matches = []  # fuzzy po last name (debug)
    sample_misses = []  # niedopasowane (debug)
    
    # Przygotuj statystyki per 90 dla każdego zawodnika
    stats_per90 = {}  # player_id -> {stat: per90}
    
    for stat_name, stat_data in extra_stats.items():
        if not stat_data:
            continue
        
        for raw_name, raw_value in stat_data.items():
            # Normalizuj nazwę z ekstraklasa.org
            norm_name = _normalize_name(raw_name)
            player_id = normalized_lookup.get(norm_name) or normalized_lookup.get(raw_name.lower())
            
            # Zbieranie danych debug: dokładne dopasowanie
            if player_id:
                sample_matches.append((raw_name, player_id))
            
            # Fuzzy fallback: szukaj po last name
            if not player_id:
                api_last = norm_name.split()[-1] if norm_name else ""
                if api_last and api_last in last_name_map:
                    player_id = last_name_map[api_last][0][0]  # bierz pierwszy match
                    fuzzy_matches.append((raw_name, player_id, api_last))
            
            if not player_id:
                sample_misses.append(raw_name)
                continue
            
            # Pobierz minuty
            minutes = player_minutes.get(player_id, 0)
            if minutes <= 0:
                continue
            
            # Przelicz na 90 minut: (stat / minutes) * 90
            per90 = round((raw_value / minutes) * 90, 2)
            
            if player_id not in stats_per90:
                stats_per90[player_id] = {}
            stats_per90[player_id][f"{stat_name}_per90"] = per90
    
    print(f"   DEBUG: dokładne {len(sample_matches)}, fuzzy {len(fuzzy_matches)}")
    print(f"   DEBUG: przykłady dokładne: {sample_matches[:3]}")
    print(f"   DEBUG: przykłady fuzzy: {fuzzy_matches[:3]}")
    print(f"   DEBUG: niedopasowane (pierwsze 5): {sample_misses[:5]}")
    
    # Dodaj statystyki do danych zawodników
    enriched_players = []
    for p in players_data:
        pid = str(p.get("player_id", ""))
        extra = stats_per90.get(pid, {})
        
        # Dodaj nowe pola z wartościami domyślnymi (None jeśli brak danych)
        enriched = dict(p)
        enriched["xg_per90"] = extra.get("xg_per90")
        enriched["shots_per90"] = extra.get("shots_per90")
        enriched["shots_on_target_per90"] = extra.get("shots_on_target_per90")
        enriched["key_passes_per90"] = extra.get("key_passes_per90")
        enriched["crosses_per90"] = extra.get("crosses_per90")
        enriched["crosses_accurate_per90"] = extra.get("crosses_accurate_per90")
        
        enriched_players.append(enriched)
    
    return enriched_players
