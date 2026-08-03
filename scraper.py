#!/usr/bin/env python3
"""
Fantasy Ekstraklasa - Scraper danych zawodników
================================================
Pobiera dane ze strony https://fantasy.ekstraklasa.org/
w tym: punkty, popularność, ceny, statystyki per kolejka.

Automatycznie loguje się mailem i hasłem (z GitHub Secrets).

Użycie:
    python scraper.py

Autor: Wygenerowane przez Claude dla Piotra
"""

import requests
import json
import csv
import time
import threading
import os
import sys
import glob
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from predictor import predict_all_players
from accuracy import evaluate_predictions, find_latest_predictions_csv, load_accuracy_history
from tuner import run_tuning
from utils import normalize_team_name, _normalize_team, _normalize_name
from players import fetch_all_players
from external_stats import fetch_ekstraklasa_table, fetch_extra_player_stats
from conceptually_client import fetch_conceptually_stats
from karpinski_client import fetch_karpinski_data, build_id_bridge, get_karpinski_stats
from fdr import compute_fdr
from config import (
    TARGET_ROUND, MAX_PLAYER_ID,
    TEAMS_TO_SCRAPE, LEAGUE_SLUG, LEAGUE_ID,
    REQUEST_DELAY, WORKERS,
    OUTPUT_DIR, BASE_URL,
    RANKING_HEADERS,
    POS_MAP,
    AUTUMN_LAST_ROUND,
)

from auth import get_session
from export import (
    save_to_csv, save_full_json,
    save_rounds_csv, print_round_summary,
)
from squads import (
    fetch_ranking_teams, fetch_league_teams, scrape_team_squad,
    scrape_teams_captains, _compute_captain_stats,
    _compute_squad_stats, generate_captain_stats, generate_squad_stats,
)

from transfers import compute_league_transfers, compute_player_stats_per90
from schedule import parse_terminarz, cleanup_old_output_files


def get_player_ids_by_scanning(session: requests.Session, max_id: int = 3000) -> list[int]:
    """
    Skanuje ID zawodników próbując kolejne numery.
    Używane jako fallback gdy /stats nie zwróci wyników.
    """
    print(f"🔍 Skanuję ID zawodników (1-{max_id})...")
    valid_ids = []

    for pid in range(1, max_id + 1):
        try:
            resp = session.get(
                f"{BASE_URL}/stats-player/{pid}",
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("data", {}).get("message"):
                    valid_ids.append(pid)
                    if len(valid_ids) % 50 == 0:
                        print(f"   ... znaleziono {len(valid_ids)} zawodników (sprawdzono do ID {pid})")

            time.sleep(REQUEST_DELAY / 2)  # Krótsze opóźnienie przy skanowaniu

        except Exception as e:  # jawne logowanie błędu zamiast cichego maskowania
            print(f"⚠️ błąd skanowania ID {pid}: {e}")
            continue

        # Jeśli po 200 kolejnych ID nie znaleźliśmy nikogo, przerywamy
        if pid > 200 and not valid_ids:
            print("   Nie znaleziono zawodników w zakresie 1-200, przerywam skanowanie.")
            break
        if valid_ids and (pid - max(valid_ids)) > 300:
            print(f"   Brak nowych zawodników od ID {max(valid_ids)}, przerywam.")
            break

    print(f"   Znaleziono {len(valid_ids)} zawodników")
    return valid_ids





def get_player_ids_from_ranking_squads(
    session: requests.Session, n_teams: int = 150
) -> list[dict]:
    """
    Pobiera listę unikalnych zawodników poprzez scrapowanie składów drużyn z rankingu.

    Metoda:
    1. POST /ranking-list → n_teams drużyn z rankingu (1 request)
    2. scrape_team_squad() dla każdej drużyny → 15 zawodników per drużyna
    3. Deduplikacja po player_id

    150 drużyn daje ~400-500 unikalnych zawodników w ~45s (vs 10 min dla skanera).
    Zawiera tylko zawodników faktycznie wybranych przez użytkowników gry — brak
    nieaktywnych/usuniętych graczy.
    """
    print(f"🏆 Pobieram zawodników przez składy {n_teams} drużyn z rankingu...")

    # Pobierz slugi N drużyn
    slugs: list[str] = []
    try:
        resp = session.post(
            f"{BASE_URL}/ranking-list",
            data=f"start=0&length={n_teams}",
            headers=RANKING_HEADERS,
            timeout=30,
        )
        if resp.status_code == 200:
            for team in resp.json().get("data", []):
                slug = team.get("slug", "")
                if slug:
                    slugs.append(slug)
    except Exception as e:
        print(f"   ⚠️  Błąd pobierania rankingu: {e}")

    if not slugs:
        return []
    print(f"   Pobrano {len(slugs)} drużyn z rankingu")

    # Scrapuj składy równolegle i zbieraj unikalne player_id
    seen: set[str] = set()
    players: list[dict] = []
    lock = threading.Lock()
    completed_count = 0

    def _fetch_squad(slug: str) -> list[dict]:
        squad_data = scrape_team_squad(session, slug)
        time.sleep(REQUEST_DELAY)
        return squad_data.get("players", [])

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(_fetch_squad, slug): slug for slug in slugs}
        for future in as_completed(futures):
            slug = futures[future]
            try:
                squad_players = future.result()
                with lock:
                    completed_count += 1
                    done = completed_count
                    for p in squad_players:
                        pid = str(p.get("player_id") or "")
                        if pid and pid not in seen:
                            seen.add(pid)
                            players.append({
                                "player_id": pid,
                                "name": p.get("name", ""),
                                "price": str(p.get("price", "")),
                                "position_id": p.get("position_id", ""),
                                "team": "",
                                "status": p.get("status", ""),
                            })
                if done % 50 == 0:
                    print(f"   Postęp: {done}/{len(slugs)} drużyn, "
                          f"{len(players)} unikalnych zawodników...")
            except Exception as e:
                print(f"   ⚠️  Błąd scraping {slug}: {e}")

    print(f"   ✅ Znaleziono {len(players)} unikalnych zawodników "
          f"z {len(slugs)} drużyn rankingu")
    return players

from dashboard import generate_dashboard_html

# ============================================================
# GŁÓWNA LOGIKA
# ============================================================

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("⚽ Fantasy Ekstraklasa - Scraper")
    print("=" * 50)
    print(f"🕐 Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 1. Utwórz sesję
    session = get_session()

    # 2. Pobierz listę zawodników
    # Metoda 1 (preferowana): składy drużyn z rankingu — szybka (150 drużyn ≈ 45s)
    # Daje ~400-500 aktywnych zawodników wybranych przez graczy fantazji.
    player_ids = []  # domyślna wartość — nadpisana gdy ranking_players nie pusty
    ranking_players = get_player_ids_from_ranking_squads(session, n_teams=150)
    if ranking_players:
        player_ids = [
            int(p["player_id"])
            for p in ranking_players
            if str(p.get("player_id", "")).isdigit()
        ]
        print(f"   ✅ Lista ze składów rankingowych: {len(player_ids)} zawodników")

    # Metoda 2 (ostateczny fallback): skanowanie zakresu ID (wolne, ~10 min)
    if not player_ids:
        print("\n⚠️  Nie udało się pobrać listy ze składów rankingowych")
        print("   Przechodzę do skanowania ID...")
        player_ids = get_player_ids_by_scanning(session, MAX_PLAYER_ID)

    if not player_ids:
        print("\n❌ Nie znaleziono żadnych zawodników!")
        print("   Sprawdź czy cookies sesyjne są poprawne.")
        print("   Możesz też ręcznie dodać ID do listy player_ids w skrypcie.")
        sys.exit(1)

    # Dodaj znane ID z zakresu (na wypadek gdyby strona /stats nie pokazała wszystkich)
    # Zakres 1-MAX_PLAYER_ID
    unique_ids = sorted(set(player_ids))[:MAX_PLAYER_ID]
    print(f"\n📌 Liczba zawodników do pobrania: {len(unique_ids)} (limit: {MAX_PLAYER_ID})")

    # 3. Pobierz szczegóły każdego zawodnika
    players = fetch_all_players(session, unique_ids)

    if not players:
        print("\n❌ Nie udało się pobrać danych żadnego zawodnika!")
        sys.exit(1)

    # 4. Zapisz dane
    print(f"\n💾 Zapisuję dane...")

    # Pełne dane JSON (ze wszystkimi kolejkami)
    json_file = os.path.join(OUTPUT_DIR, f"fantasy_full_{timestamp}.json")
    save_full_json(players, json_file)

    # CSV - podsumowanie zawodników
    # Znajdź obecną kolejkę (najwyższa rozegrana)
    current_round = TARGET_ROUND or 0
    if not current_round:
        played = [r.get("round", 0) for p in players
                  for r in p.get("rounds", []) if r.get("played")]
        current_round = max(played) if played else 0
    print(f"  📅 Obecna kolejka: {current_round}")

    summary_data = []
    for p in players:
        pts = p.get("total_points", 0) or 0
        if pts == 0:
            continue
        price = p.get("price", 0) or 0
        ppp = round(pts / price, 2) if price > 0 else 0

        # Forma: ostatnie 5 kolejek uwzględnionych w formie
        # - tryb domyślny (TARGET_ROUND is None): do bieżącej kolejki włącznie
        # - tryb historyczny (TARGET_ROUND ustawiony): tylko kolejki przed analizowaną
        rounds = sorted(p.get("rounds", []), key=lambda r: r.get("round", 0))
        if TARGET_ROUND is None:
            eligible_rounds = [r for r in rounds if r.get("round", 0) <= current_round] if current_round else rounds
        else:
            eligible_rounds = [r for r in rounds if r.get("round", 0) < current_round] if current_round else rounds
        last5 = eligible_rounds[-5:] if eligible_rounds else []
        form = [{"r": r.get("round", 0), "pts": r.get("points", 0) if r.get("played") else 0, "p": bool(r.get("played"))} for r in last5]

        summary_data.append({
            "player_id": p.get("player_id"),
            "name": p.get("name", ""),
            "team": p.get("team", ""),
            "position": p.get("position", ""),
            "total_points": pts,
            "price": price,
            "points_per_price": ppp,
            "popularity_pct": p.get("popularity_pct", ""),
            "stats_url": p.get("stats_url", ""),
            "form": form,
            # Status dostępności: None = dostępny, inaczej tekst (np. "Kontuzjowany")
            "availability_status": p.get("availability_status"),
            # Nowe statystyki per 90
            "xg_per90": p.get("xg_per90"),
            "shots_per90": p.get("shots_per90"),
            "shots_on_target_per90": p.get("shots_on_target_per90"),
            "key_passes_per90": p.get("key_passes_per90"),
            "crosses_per90": p.get("crosses_per90"),
            "crosses_accurate_per90": p.get("crosses_accurate_per90"),
        })
    summary_data.sort(key=lambda x: x.get("total_points", 0) or 0, reverse=True)
    csv_file = os.path.join(OUTPUT_DIR, f"fantasy_players_{timestamp}.csv")
    save_to_csv(summary_data, csv_file)

    # CSV - statystyki per kolejka
    rounds_file = os.path.join(OUTPUT_DIR, f"fantasy_rounds_{timestamp}.csv")
    save_rounds_csv(players, rounds_file)

    # 5. Podsumowanie kolejki
    if current_round:
        print_round_summary(players, current_round)

    # 6. Scrapowanie drużyn (kapitanowie, ownership)
    captain_stats = []
    ownership_stats = []
    team_results = []
    if TEAMS_TO_SCRAPE > 0:
        ranking_teams = fetch_ranking_teams(session, TEAMS_TO_SCRAPE)

        if ranking_teams:
            checkpoint = os.path.join(OUTPUT_DIR, "checkpoint_global.json")
            team_results = scrape_teams_captains(session, ranking_teams, checkpoint_file=checkpoint)

            # Usuń checkpoint jeśli wszystko pobrane
            if len(team_results) >= len(ranking_teams) and os.path.exists(checkpoint):
                os.remove(checkpoint)
                print(f"   🗑️  Checkpoint globalny usunięty (kompletny)")

            # CSV - statystyki kapitanów (pełne)
            captains_file = os.path.join(OUTPUT_DIR, f"fantasy_captains_{timestamp}.csv")
            captain_stats = generate_captain_stats(team_results, captains_file)

            # CSV - ownership w drużynach (pełne)
            ownership_file = os.path.join(OUTPUT_DIR, f"fantasy_ownership_{timestamp}.csv")
            ownership_stats = generate_squad_stats(team_results, ownership_file)

    # Oblicz statystyki per tier (top10, top100, all)
    tiers = {}
    if team_results:
        sorted_results = sorted(
            team_results,
            key=lambda t: t.get("ranking_position") or 999999
        )
        for tier_key, tier_limit in [("top10", 10), ("top100", 100)]:
            tier_teams = sorted_results[:tier_limit]
            if tier_teams:
                tiers[tier_key] = {
                    "captains": _compute_captain_stats(tier_teams),
                    "ownership": _compute_squad_stats(tier_teams),
                    "count": len(tier_teams),
                }
        # Pełny tier (all)
        tiers["all"] = {
            "captains": captain_stats,
            "ownership": ownership_stats,
            "count": len(team_results),
        }

    # 7. Scrapowanie ligi prywatnej
    league_captain_stats = []
    league_ownership_stats = []
    league_teams = []
    league_results = []
    if LEAGUE_SLUG:
        league_teams = fetch_league_teams(session, LEAGUE_SLUG, LEAGUE_ID)

        if league_teams:
            league_checkpoint = os.path.join(OUTPUT_DIR, "checkpoint_league.json")
            league_results = scrape_teams_captains(session, league_teams, checkpoint_file=league_checkpoint)

            # Usuń checkpoint jeśli wszystko pobrane
            if len(league_results) >= len(league_teams) and os.path.exists(league_checkpoint):
                os.remove(league_checkpoint)

            # CSV - statystyki kapitanów ligi
            league_captains_file = os.path.join(OUTPUT_DIR, f"fantasy_league_captains_{timestamp}.csv")
            league_captain_stats = generate_captain_stats(league_results, league_captains_file)

            # CSV - ownership w lidze
            league_ownership_file = os.path.join(OUTPUT_DIR, f"fantasy_league_ownership_{timestamp}.csv")
            league_ownership_stats = generate_squad_stats(league_results, league_ownership_file)

    # 8. Dashboard HTML
    # Buduj mapę roster ligi: zawodnik → lista drużyn (z pozycją w lidze)
    league_rosters = {}  # keyed by player_id (string)
    # Buduj pełne dane drużyn ligi do nowej zakładki
    league_teams_detail = []
    # Lookup player_id → pełne dane gracza z API statystyk
    player_lookup = {str(p.get("player_id")): p for p in players} if players else {}

    for team in league_results:
        slug = team.get("team_slug", "")
        rank = team.get("ranking_position", "")
        team_pts = team.get("team_points", 0)

        team_players = []
        for p in team.get("squad", []):
            name = p.get("name", "")
            pid = str(p.get("player_id", ""))
            if not name or not pid:
                continue
            roster_entry = {
                "team": slug,
                "pos": rank,
                "C": p.get("is_captain", False),
                "VC": p.get("is_subcaptain", False),  # wicekapitan (subcaptain) — potrzebne do Discord captains summary
                "R": p.get("is_reserve", False),
            }
            if pid not in league_rosters:
                league_rosters[pid] = []
            league_rosters[pid].append(roster_entry)
            # Dane gracza z API statystyk (pełne punkty, pozycja tekstowa)
            full = player_lookup.get(pid, {})
            api_name = full.get("name", name)
            team_players.append({
                "pid": pid,
                "name": api_name,
                "pos": full.get("position", "") or p.get("position_id", ""),
                "pts": full.get("total_points", 0) or 0,
                "price": full.get("price", 0) or p.get("price", 0),
                "C": p.get("is_captain", False),
                "VC": p.get("is_subcaptain", False),  # wicekapitan (subcaptain) — potrzebne do Discord captains summary
                "R": p.get("is_reserve", False),
                "form": [],
            })
            # Dodaj formę — ostatnie 5 kolejek uwzględnionych w formie
            # - tryb domyślny (TARGET_ROUND is None): do bieżącej kolejki włącznie
            # - tryb historyczny (TARGET_ROUND ustawiony): tylko kolejki przed analizowaną
            pr = sorted(full.get("rounds", []), key=lambda r: r.get("round", 0))
            if TARGET_ROUND is None:
                eligible_rounds = [r for r in pr if r.get("round", 0) <= current_round] if current_round else pr
            else:
                eligible_rounds = [r for r in pr if r.get("round", 0) < current_round] if current_round else pr
            last5 = eligible_rounds[-5:] if eligible_rounds else []
            team_players[-1]["form"] = [{"r": r.get("round", 0), "pts": r.get("points", 0) if r.get("played") else 0, "p": bool(r.get("played"))} for r in last5]

        league_teams_detail.append({
            "slug": slug,
            "rank": rank,
            "pts": team_pts,
            "players": team_players,
        })
    # DEBUG: pokaż strukturę danych pierwszej drużyny (kapitan i wicekapitan)
    if league_teams_detail:
        first = league_teams_detail[0]
        cap_player = next((p for p in first["players"] if p.get("C")), None)
        vice_player = next((p for p in first["players"] if p.get("VC")), None)
        print(f"  🔍 DEBUG pierwsza drużyna: slug={first.get('slug', '?')}")
        print(f"     kapitan: {cap_player['name'] if cap_player else 'BRAK'} (pid={cap_player.get('pid','?') if cap_player else '?'})")
        print(f"     wicekapitan: {vice_player['name'] if vice_player else 'BRAK'} (pid={vice_player.get('pid','?') if vice_player else '?'})")
        print(f"     graczy z C=True: {sum(1 for p in first['players'] if p.get('C'))}")
        print(f"     graczy z VC=True: {sum(1 for p in first['players'] if p.get('VC'))}")

    # Sortuj po pozycji
    league_teams_detail.sort(key=lambda t: t.get("rank") or 999)

    # 8.4b Sezonowy tracker ligi — zapisz stan po bieżącej kolejce
    if league_teams and current_round:
        from league_tracker import save_round_standings
        save_round_standings(league_teams, current_round, os.path.join(OUTPUT_DIR, "league_history.json"))

    # 8.5 Parse terminarz for fixture ticker
    fixtures_data = parse_terminarz("terminarz.txt")
    if fixtures_data["rounds"]:
        print(f"  📅 Terminarz: {len(fixtures_data['rounds'])} kolejek, {len(fixtures_data['teams'])} drużyn")

    # 8.6 Scrapuj statystyki bramkowe z 90minut.pl (równolegle z 8.6b)
    # 8.6b Pobierz rozszerzone statystyki zawodników z ekstraklasa.org
    # (xG, strzały, podania kluczowe, dośrodkowania)
    with ThreadPoolExecutor(max_workers=3) as ex:
        fut_table = ex.submit(fetch_ekstraklasa_table)
        fut_extra = ex.submit(fetch_extra_player_stats)
        fut_karp = ex.submit(fetch_karpinski_data)  # Karpinski zamiast conceptually_client
        ekstra_stats = fut_table.result()
        extra_player_stats = fut_extra.result()
        karp_players, adv_table, karp_season = fut_karp.result()

    # Zaktualizuj most ID (dopisuje nowych graczy Fantasy do mostu z danymi Karpińskiego)
    build_id_bridge(players, karp_players)

    # Oblicz sumę minut dla każdego zawodnika (do przeliczania na per 90)
    player_minutes = {}
    for p in players:
        pid = str(p.get("player_id", ""))
        total_mins = sum(r.get("minutes", 0) for r in p.get("rounds", []))
        if total_mins > 0:
            player_minutes[pid] = total_mins

    # Wzbogać dane zawodników o statystyki per 90 (xG, strzały, podania)
    players = compute_player_stats_per90(extra_player_stats, players, player_minutes)

    # Wzbogać o statystyki z API Karpińskiego (xA, percentyle) — zastępuje conceptually_client
    # Dane są w adv_table.json, dostęp przez most ID (player_id_bridge.json)
    for p in players:
        stats = get_karpinski_stats(int(p["player_id"]))
        p["xa_per_90"] = stats.get("expected_assists") if stats else None
        p["percentile_xa"] = stats.get("percentile_xa") if stats else None
        p["percentile_xg"] = stats.get("percentile_xg") if stats else None
        p["karpinski_slug"] = stats.get("slug") if stats else None

    # TODO: usunąć po weryfikacji karpinski_client
    # # Wzbogać o statystyki z conceptuallyfootball.com (xA, percentyle)
    # if cf_stats:
    #     for p in players:
    #         norm = _normalize_name(p.get("name", ""))
    #         cf = cf_stats.get(norm, {})
    #         p["xa_per_90"] = cf.get("xa_per_90")
    #         p["percentile_xa"] = cf.get("percentile_xa")
    #         p["percentile_xg"] = cf.get("percentile_xg")
    #         p["goals_per_90"] = cf.get("goals_per_90")
    #         p["assists_per_90"] = cf.get("assists_per_90")

    # 8.7 Oblicz FDR (Fixture Difficulty Rating)
    remaining_rounds = sum(1 for r in fixtures_data.get("rounds", []) if r >= (current_round or 0))
    fdr_data = compute_fdr(
        ekstra_stats, fixtures_data,
        current_round=current_round,
        num_rounds=max(remaining_rounds, 6)
    )

    # 8.8 Prognoza punktów (predictor)
    predictions_data = []
    if fdr_data.get("teams") and fdr_data.get("gameweeks"):
        # Znajdź pierwszą naprawdę nierozpoczętą kolejkę — pomijamy bieżącą,
        # która może mieć przełożone mecze w przyszłości (np. K31 z meczami 13.05)
        next_gw = None
        for gw in fdr_data["gameweeks"]:
            if not current_round or gw > current_round:
                next_gw = gw
                break
        if not next_gw:
            next_gw = fdr_data["gameweeks"][0]  # fallback
        next_matches = fixtures_data.get("matches", {}).get(str(next_gw), [])

        # Zabezpieczenie: gdy brak meczów (np. koniec sezonu), pomiń prognozę z komunikatem
        if not next_matches:
            print(f"  ⚠️  Brak kolejki do prognozy (kolejka {next_gw} nie ma meczów w terminarzu)")
            # Dalej pomijamy predykcję — next_matches pusta, pred_fixtures będzie {}

        # Buduj fixtures w formacie predictora: {team: {opponent, is_home}}
        # Nazwy drużyn normalizowane (strip, NFKD, lower) dla zgodności z player["team"]
        pred_fixtures = {}
        for m in next_matches:
            pred_fixtures[_normalize_team(m["home"])] = {"opponent": m["away"], "is_home": True}
            pred_fixtures[_normalize_team(m["away"])] = {"opponent": m["home"], "is_home": False}

        # Buduj fdr_data w formacie predictora: {team: {atk, def}}
        # Użyj FDR z pierwszej kolejki w fdr_data (next_gw)
        pred_fdr = {}
        for team_fdr in fdr_data["teams"]:
            for fix in team_fdr.get("fixtures", []):
                if fix.get("gw") == next_gw and fix.get("opponent"):
                    # FDR rywala: atk i def rywala
                    pred_fdr[fix["opponent"]] = {
                        "atk": fix.get("atk", 3),
                        "def": fix.get("def", 3),
                    }

        # Mapuj pozycje z pełnych nazw na skróty dla predictora
        players_for_pred = []
        for p in players:
            pp = dict(p)
            raw_pos = pp.get("position", "")
            pp["position"] = POS_MAP.get(raw_pos, raw_pos)
            # Normalizuj nazwę drużyny tak samo jak klucze w pred_fixtures
            pp["team"] = _normalize_team(pp.get("team", ""))
            players_for_pred.append(pp)

        # DEBUG: sprawdź dane przed predykcją
        if players_for_pred:
            sample = players_for_pred[0]
            print(f"   DEBUG: pierwszy gracz do pred={sample.get('name')}, xg_per90={sample.get('xg_per90')}")
        # DEBUG: porównaj nazwy drużyn w fixtures vs players (diagnostyka niezgodności)
        print(f"   DEBUG pred_fixtures keys: {list(pred_fixtures.keys())[:5]}")
        print(f"   DEBUG player teams: {[p['team'] for p in players_for_pred[:5]]}")
        
        # Uruchom predykcję tylko gdy są fixtures; inaczej zwróć pustą listę (np. koniec sezonu)
        if pred_fixtures:
            predictions_data = predict_all_players(players_for_pred, pred_fdr, pred_fixtures)
        else:
            predictions_data = []
        print(f"   DEBUG: predykcje={len(predictions_data)}")
        if predictions_data:
            print(f"   DEBUG: top3 pred: {[(p.get('name'), p.get('predicted_points')) for p in predictions_data[:3]]}")

        # Dodaj informacje o rywalu z FDR dla dashboardu
        fdr_by_team = {}
        for team_fdr in fdr_data["teams"]:
            for fix in team_fdr.get("fixtures", []):
                if fix.get("gw") == next_gw:
                    fdr_by_team[_normalize_team(team_fdr["name"])] = {
                        "opponent": fix.get("opponent", ""),
                        "opponent_short": fix.get("opponent_short", ""),
                        "home": fix.get("home", True),
                        "atk": fix.get("atk", 3),
                        "def": fix.get("def", 3),
                    }
        for pred in predictions_data:
            team = pred.get("team", "")
            fi = fdr_by_team.get(team, {})
            pred["opponent_short"] = fi.get("opponent_short", "")
            pred["fdr_atk_team"] = fi.get("atk", 3)
            pred["fdr_def_team"] = fi.get("def", 3)
            pred["round_number"] = next_gw  # kolejka której dotyczy prognoza

        # Zapisz CSV z prognozami
        if predictions_data:
            pred_csv = os.path.join(OUTPUT_DIR, f"fantasy_predictions_{timestamp}.csv")
            pred_fields = [
                "player_id", "name", "team", "position", "next_opponent", "is_home",
                "predicted_points", "base_avg", "fdr_modifier",
                "minutes_factor", "home_away_factor", "avg_minutes",
                "confidence", "detail",
                "unavailable", "availability_reason",  # status dostępności
                "round_number",  # numer kolejki, której dotyczy prognoza (dla accuracy.py)
            ]
            with open(pred_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=pred_fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(predictions_data)
            print(f"  🔮 Prognoza: {len(predictions_data)} zawodników → {os.path.basename(pred_csv)}")

    # 8.8b Sprawdź trafność prognoz z poprzedniego uruchomienia
    accuracy_data = None
    if current_round:
        # Znajdź najnowszy plik prognoz PRZED tym uruchomieniem
        prev_pred_csv = find_latest_predictions_csv(OUTPUT_DIR)
        # Upewnij się, że to nie jest plik z tego uruchomienia
        current_pred_csv = os.path.join(OUTPUT_DIR, f"fantasy_predictions_{timestamp}.csv")
        if prev_pred_csv and os.path.abspath(prev_pred_csv) != os.path.abspath(current_pred_csv):
            accuracy_data = evaluate_predictions(prev_pred_csv, players, current_round)

    # Wczytaj historię trafności dla dashboardu
    accuracy_history = load_accuracy_history() or []

    # 8.8c Auto-tuning parametrów predictora (po zebraniu min. 4 kolejek)
    # Uruchamiamy PO ewaluacji trafności — dane są już aktualne
    run_tuning(
        accuracy_history_path=os.path.join(OUTPUT_DIR, "accuracy_history.json"),
        output_dir=OUTPUT_DIR,
        output_path=os.path.join(OUTPUT_DIR, "tuned_params.json"),
    )

    # 8.9 Oblicz transfery w lidze prywatnej
    transfers_data: dict = {}
    if league_results and current_round > 1:
        transfers_data = compute_league_transfers(
            session=session,
            league_results=league_results,
            current_round=current_round,
            player_lookup=player_lookup,
        )

    # 8.10 Liga Hokejowa — wzbogać league_teams_detail o dane jesienne i ranking łączny
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Automatyczny zapis punktów rundy jesiennej
    autumn_path = os.path.join(script_dir, "autumn_points.json")
    if (current_round == AUTUMN_LAST_ROUND
            and league_teams
            and not os.path.exists(autumn_path)):
        autumn_data = {}
        for t in league_teams:
            slug = t.get("slug", "")
            if slug:
                autumn_data[slug] = {
                    "points": t.get("total_points", 0) or 0,
                    "best_gameweek": t.get("max_points", 0) or 0,
                }
        with open(autumn_path, "w", encoding="utf-8") as f:
            json.dump(autumn_data, f, ensure_ascii=False, indent=2)
        print(f"🍂 Zapisano autumn_points.json ({len(autumn_data)} drużyn, kolejka {current_round})")
    autumn_points_file = os.path.join(script_dir, "autumn_points.json")
    hockey_prev_file = os.path.join(script_dir, "hockey_prev_ranking.json")
    if os.path.exists(autumn_points_file):
        try:
            with open(autumn_points_file, "r", encoding="utf-8") as f:
                autumn_raw = json.load(f)
            print(f"\n🏒 Liga Hokejowa: wczytano {len(autumn_raw)} drużyn z rundy jesiennej")

            # Buduj lookup po slugach (nowy format: klucze to slugi)
            autumn_lookup = {}
            for slug, data in autumn_raw.items():
                # Nowy format: klucze to slugi (np. "tokusatsu-soccer")
                if isinstance(data, dict):
                    autumn_lookup[slug] = {
                        "points": data.get("points", 0) or 0,
                        "best_gw": data.get("best_gameweek", 0) or 0,
                        "display_name": slug.replace("-", " ").title(),
                    }
                else:
                    autumn_lookup[slug] = {
                        "points": data,
                        "best_gw": 0,
                        "display_name": slug.replace("-", " ").title(),
                    }

            # Buduj lookup max_points z league_teams (fetch_league_teams → /ranking-list)
            max_pts_lookup = {}
            if league_teams:
                for t in league_teams:
                    max_pts_lookup[t["slug"]] = t.get("max_points", 0)

            # Wzbogać league_teams_detail o dane hokejowe
            # Wykrywamy, w której połowie sezonu jesteśmy:
            # - jesień (current_round <= AUTUMN_LAST_ROUND): bieżące punkty = jesienne
            # - wiosna (current_round > AUTUMN_LAST_ROUND): bieżące punkty = wiosenne
            in_autumn = current_round and current_round <= AUTUMN_LAST_ROUND
            spring_seen_slugs = set()
            matched_any = False
            for t in league_teams_detail:
                slug = t.get("slug", "")
                spring_seen_slugs.add(slug)
                autumn_info = autumn_lookup.get(slug)
                best_gw = max_pts_lookup.get(slug, 0)
                if in_autumn:
                    # Jesień — bieżące punkty z API to punkty jesienne
                    if autumn_info and autumn_info["points"] > 0:
                        # autumn_points.json ma rzeczywiste dane z zeszłego sezonu
                        t["autumn_pts"] = autumn_info["points"]
                        t["best_gw_autumn"] = autumn_info["best_gw"]
                    else:
                        # Świeży plik (zera) — używamy bieżących punktów jako jesiennych
                        t["autumn_pts"] = t["pts"]
                        t["best_gw_autumn"] = best_gw if best_gw else 0
                    t["spring_pts"] = 0
                    t["best_gw_spring"] = 0
                    t["display_name"] = slug.replace("-", " ").title()
                else:
                    # Wiosna — bieżące punkty z API to punkty wiosenne
                    if autumn_info:
                        matched_any = True
                        t["autumn_pts"] = autumn_info["points"]
                        t["best_gw_autumn"] = autumn_info["best_gw"]
                        t["display_name"] = autumn_info["display_name"] or slug.replace("-", " ").title()
                    else:
                        t["autumn_pts"] = 0
                        t["best_gw_autumn"] = 0
                        t["display_name"] = slug.replace("-", " ").title()
                    t["best_gw_spring"] = best_gw if best_gw else 0
                    t["spring_pts"] = t["pts"]
                t["total_pts"] = t["autumn_pts"] + t["spring_pts"]
                t["autumn_only"] = False
                t["spring_only"] = slug not in autumn_lookup

            # Fallback: stary format kluczy (nazwy) nie dopasuje się do slugów
            if not matched_any and autumn_lookup:
                print(f"⚠️ autumn_points.json używa starych kluczy (nazwy) — zostanie zastąpiony automatycznie po kolejce {AUTUMN_LAST_ROUND}")

            # Dodaj drużyny jesienne bez wiosny (autumn_only)
            for slug, info in autumn_lookup.items():
                if slug not in spring_seen_slugs:
                    league_teams_detail.append({
                        "slug": slug,
                        "rank": None,
                        "pts": 0,
                        "players": [],
                        "autumn_pts": info["points"],
                        "best_gw_autumn": info["best_gw"],
                        "best_gw_spring": 0,
                        "spring_pts": 0,
                        "total_pts": info["points"],
                        "display_name": info["display_name"],
                        "autumn_only": True,
                        "spring_only": False,
                    })

            # Sortuj po total_pts malejąco
            league_teams_detail.sort(key=lambda x: x["total_pts"], reverse=True)

            # Wczytaj ranking per-kolejka (format: {"round_N": {team: pos}})
            rankings_by_round = {}
            if os.path.exists(hockey_prev_file):
                try:
                    with open(hockey_prev_file, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    # Migracja ze starego formatu {team: pos} do nowego {round_N: {team: pos}}
                    if loaded and not any(k.startswith("round_") for k in loaded):
                        pass  # stary format — ignorujemy, zaczynamy od nowa
                    else:
                        rankings_by_round = loaded
                except Exception as e:  # jawne logowanie błędu parsowania hockey_prev_ranking.json
                    print(f"⚠️ błąd parsowania hockey_prev_ranking.json: {e}")

            # Pobierz ranking poprzedniej kolejki do porównania
            prev_round_key = f"round_{current_round - 1}" if current_round and current_round > 1 else None
            prev_ranking = rankings_by_round.get(prev_round_key, {}) if prev_round_key else {}

            # Oblicz rank_change vs. poprzednia kolejka
            current_ranking = {}
            for i, t in enumerate(league_teams_detail):
                combined_pos = i + 1
                norm_key = normalize_team_name(t.get("display_name", t["slug"].replace("-", " ")))
                current_ranking[norm_key] = combined_pos
                prev_pos = prev_ranking.get(norm_key)
                t["rank_change"] = (prev_pos - combined_pos) if prev_pos is not None else 0
                t["hockey_pos"] = combined_pos

            # Zbuduj słownik slug → pozycja sumaryczna (jesień+wiosna) dla league_rosters
            league_standings = {t["slug"]: t.get("hockey_pos", combined_pos) for t in league_teams_detail}

            # Zaktualizuj pozycje w league_rosters na sumaryczne (jesień+wiosna)
            for pid, teams in league_rosters.items():
                for t in teams:
                    team_slug = t.get("team", "")
                    t["pos"] = league_standings.get(team_slug, t.get("pos", 999))

            # Zapisz aktualny ranking dla bieżącej kolejki
            if current_round:
                rankings_by_round[f"round_{current_round}"] = current_ranking
            with open(hockey_prev_file, "w", encoding="utf-8") as f:
                json.dump(rankings_by_round, f, ensure_ascii=False, indent=2)

            print(f"   ✅ Przygotowano {len(league_teams_detail)} drużyn do klasyfikacji łącznej")
        except Exception as e:
            print(f"   ⚠️  Błąd ładowania danych jesiennych: {e}")

    # Duety — oblicz punkty z danych drużyn
    duets_data = []
    duets_file = os.path.join(script_dir, "duets.json")
    duets_prev_file = os.path.join(script_dir, "duets_prev_ranking.json")
    if os.path.exists(duets_file) and league_teams_detail:
        try:
            with open(duets_file, "r", encoding="utf-8") as f:
                duets_config = json.load(f)

            # Buduj lookup: normalize(display_name) → dane drużyny
            team_lookup = {}
            for t in league_teams_detail:
                key = normalize_team_name(t.get("display_name", t["slug"].replace("-", " ")))
                team_lookup[key] = t

            for d in duets_config:
                k1 = normalize_team_name(d["team1"])
                k2 = normalize_team_name(d["team2"])
                t1 = team_lookup.get(k1, {})
                t2 = team_lookup.get(k2, {})
                autumn_pts = (t1.get("autumn_pts", 0) or 0) + (t2.get("autumn_pts", 0) or 0)
                spring_pts = (t1.get("spring_pts", 0) or 0) + (t2.get("spring_pts", 0) or 0)
                total_pts = autumn_pts + spring_pts
                duets_data.append({
                    "duet_name": d["duet_name"],
                    "players": d["players"],
                    "team1_name": t1.get("display_name", d["team1"]),
                    "team1_autumn": t1.get("autumn_pts", 0) or 0,
                    "team1_spring": t1.get("spring_pts", 0) or 0,
                    "team2_name": t2.get("display_name", d["team2"]),
                    "team2_autumn": t2.get("autumn_pts", 0) or 0,
                    "team2_spring": t2.get("spring_pts", 0) or 0,
                    "autumn_pts": autumn_pts,
                    "spring_pts": spring_pts,
                    "total_pts": total_pts,
                    "rank_change": 0,
                })

            duets_data.sort(key=lambda x: x["total_pts"], reverse=True)

            # Wczytaj ranking duetów per-kolejka (format: {"round_N": {duet: pos}})
            duets_rankings_by_round = {}
            if os.path.exists(duets_prev_file):
                try:
                    with open(duets_prev_file, "r", encoding="utf-8") as f:
                        loaded_duets = json.load(f)
                    # Migracja ze starego formatu {duet: pos} do nowego {round_N: {duet: pos}}
                    if loaded_duets and not any(k.startswith("round_") for k in loaded_duets):
                        pass  # stary format — ignorujemy
                    else:
                        duets_rankings_by_round = loaded_duets
                except Exception as e:  # jawne logowanie błędu parsowania duets_prev_ranking.json
                    print(f"⚠️ błąd parsowania duets_prev_ranking.json: {e}")

            duets_prev_round_key = f"round_{current_round - 1}" if current_round and current_round > 1 else None
            duets_prev_ranking = duets_rankings_by_round.get(duets_prev_round_key, {}) if duets_prev_round_key else {}

            current_duets_ranking = {}
            for i, d in enumerate(duets_data):
                pos = i + 1
                key = normalize_team_name(d["duet_name"])
                current_duets_ranking[key] = pos
                prev_pos = duets_prev_ranking.get(key)
                d["rank_change"] = (prev_pos - pos) if prev_pos is not None else 0

            if current_round:
                duets_rankings_by_round[f"round_{current_round}"] = current_duets_ranking
            with open(duets_prev_file, "w", encoding="utf-8") as f:
                json.dump(duets_rankings_by_round, f, ensure_ascii=False, indent=2)

            print(f"   ✅ Przygotowano {len(duets_data)} duetów")
        except Exception as e:
            print(f"   ⚠️  Błąd ładowania duetów: {e}")

    # Wczytaj wytunowane parametry dla dashboardu (mogły zostać właśnie zaktualizowane)
    tuned_params_file = os.path.join(OUTPUT_DIR, "tuned_params.json")
    tuned_params = None
    if os.path.exists(tuned_params_file):
        try:
            with open(tuned_params_file, encoding="utf-8") as f:
                tuned_params = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Wczytaj historię ligi (league_history.json) dla zakładki Sezon
    league_history_file = os.path.join(OUTPUT_DIR, "league_history.json")
    league_history: dict = {"rounds": []}
    if os.path.exists(league_history_file):
        try:
            with open(league_history_file, "r", encoding="utf-8") as f:
                league_history = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # 📖 load_newsletter_history usunięte — newsletter_history.json write-only, zakładka Newsletter wyłączona

    dashboard_file = os.path.join(OUTPUT_DIR, "dashboard.html")
    
    # Zapisz dane drużyn ligi dla archiwizacji
    try:
        import json as _json
        with open("output/league_teams_detail.json", "w", encoding="utf-8") as f:
            _json.dump(league_teams_detail, f, ensure_ascii=False, indent=2)
        print("  💾 Zapisano dane drużyn ligi: output/league_teams_detail.json")
    except Exception as e:
        print(f"  ⚠️  Nie udało się zapisać danych drużyn ligi: {e}")

    if current_round and league_teams_detail:
        save_league_squads_history(league_teams_detail, current_round)

    generate_dashboard_html(
        summary_data=summary_data,
        tiers=tiers,
        teams_count=TEAMS_TO_SCRAPE,
        league_captain_stats=league_captain_stats,
        league_ownership_stats=league_ownership_stats,
        league_name=LEAGUE_SLUG or "",
        league_teams_count=len(league_teams) if LEAGUE_SLUG and league_teams else 0,
        league_rosters=league_rosters,
        league_teams_detail=league_teams_detail,
        duets_data=duets_data,
        fixtures_data=fixtures_data,
        ekstra_stats=ekstra_stats,
        fdr_data=fdr_data,
        transfers_data=transfers_data,
        predictions_data=predictions_data,
        accuracy_history=accuracy_history,
        tuned_params=tuned_params,
        league_history=league_history,
        # 📖 newsletter_data usunięte — zakładka Newsletter wyłączona, newsletter_history.json write-only
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        filename=dashboard_file,
        has_archive=len(glob.glob("docs/archive/sezon-*.html")) > 0,
    )

    # ============================================================
    # DISCORD NOTIFICATIONS
    # Wysyłamy powiadomienia PRZED kolejką (pre-round) i PO kolejce (post-round).
    # Logika timingowa jest w discord_notify.py — tutaj tylko sprawdzamy warunki
    # i przekazujemy odpowiednie dane.
    # Jeśli DISCORD_WEBHOOK_URL nie jest ustawiony → pomijamy bez błędu.
    # ============================================================
    from discord_notify import (
        send_pre_round,
        send_post_round,
        send_captains_summary,
        send_expert_predictions,
        should_send_pre_round,
        should_send_post_round,
        should_send_captains_summary,
    )

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        # Numer następnej (jeszcze nierozpoczętej) kolejki — pomijamy bieżącą,
        # która może mieć przełożone mecze w przyszłości (np. K31 z meczami 13.05)
        discord_next_gw = None
        if fdr_data.get("gameweeks"):
            for gw in fdr_data["gameweeks"]:
                if not current_round or gw > current_round:
                    discord_next_gw = gw
                    break
        # Numer bieżącej (ostatniej rozegranej) kolejki — use the one already computed from player data
        # not from fixtures_data which only contains future rounds
        if not current_round and fixtures_data.get("rounds"):
            all_rounds = sorted(fixtures_data.get("rounds", []), reverse=True)
            if all_rounds:
                current_round = all_rounds[0]

        # CAPTAINS: wyślij godzinę po pierwszym meczu kolejki
        if (
            current_round
            and league_teams_detail
            and should_send_captains_summary(current_round, fixtures_data)
        ):
            # Zmiana: używamy total_points (tabela sumaryczna jesień+wiosna) do sortowania
            # Zamiast pozycji z kolejki wiosennej (position/pos)
            cmf_standings = {}
            for t in league_teams:
                slug = t.get("slug", "")
                total_pts = t.get("total_points", 0) or 0
                cmf_standings[slug] = -total_pts  # ujemne żeby sortować rosnąco = najwięcej punktów = najwyżej
            send_captains_summary(
                league_teams_detail=league_teams_detail,
                cmf_standings=cmf_standings,
                webhook_url=webhook_url,
                round_number=current_round,
            )

        # PRE-ROUND: wyślij dzień przed pierwszym meczem kolejki
        # (lub w dzień meczu jako okno ratunkowe)
        if (
            discord_next_gw
            and predictions_data
            and should_send_pre_round(discord_next_gw, fixtures_data)
        ):
            send_pre_round(
                predictions=predictions_data,
                players_data=players,
                webhook_url=webhook_url,
                round_number=discord_next_gw,
                fixtures=fixtures_data,
                fdr_data=fdr_data,
            )

            # Prognozy eksperckie (Rabbti + Tlinf) — wysyłane TYLKO w dzień przed meczem
            # (nie w dzień meczu, bo wtedy wysyła się też captains summary)
            from datetime import date
            from discord_notify import _get_round_date_range
            first_date, _ = _get_round_date_range(fixtures_data, discord_next_gw)
            is_day_before = date.today() == (first_date - __import__('datetime').timedelta(days=1)) if first_date else False
            
            # Tylko dzień przed meczem (nie w dzień meczu!)
            deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
            gemini_key = os.environ.get("GEMINI_API_KEY", "")
            if (deepseek_key or gemini_key) and is_day_before:
                # Buduj mapę slug → display_name dla ładniejszych nazw drużyn
                display_name_map = {
                    t.get("slug", ""): t.get("display_name", "")
                    for t in league_teams_detail
                    if t.get("display_name")
                }
                # Wzbogać league_teams o display_name
                discord_league = []
                for t in (league_teams or []):
                    entry = dict(t)
                    slug = entry.get("slug", "")
                    if slug in display_name_map:
                        entry["display_name"] = display_name_map[slug]
                    discord_league.append(entry)

                # Przygotuj wszystkie dane dla ekspertów
                expert_data = {
                    "round_number": discord_next_gw,
                    "predictions_data": predictions_data,
                    "fixtures_data": fixtures_data,
                    "ekstra_stats": ekstra_stats,
                    "fdr_data": fdr_data,
                    "league_teams": discord_league,
                    "league_teams_detail": league_teams_detail,
                }
                send_expert_predictions(
                    all_data=expert_data,
                    webhook_url=webhook_url,
                    deepseek_key=deepseek_key,
                    gemini_key=gemini_key,
                    round_number=discord_next_gw,
                )
            else:
                # Rozróżnij przyczynę pominięcia: brak kluczy vs nie ten dzień
                if not deepseek_key and not gemini_key:
                    print("  ℹ️  Eksperci: brak kluczy API (DEEPSEEK_API_KEY ani GEMINI_API_KEY) — pomijam generowanie")
                elif not is_day_before:
                    print("  ℹ️  Eksperci: nie dzień przed meczem — pomijam generowanie")

        # POST-ROUND: wyślij dzień po ostatnim meczu kolejki.
        # Wzbogacamy league_teams o display_name z league_teams_detail jeśli dostępne,
        # żeby Discord pokazywał ładne nazwy drużyn zamiast slugów.
        if current_round and should_send_post_round(current_round, fixtures_data):
            # Buduj mapę slug → display_name z wzbogaconych danych (może być puste)
            display_name_map = {
                t.get("slug", ""): t.get("display_name", "")
                for t in league_teams_detail
                if t.get("display_name")
            }
            # Dodaj display_name do danych ligi (kopia, żeby nie modyfikować oryginału)
            discord_league = []
            for t in (league_teams or []):
                entry = dict(t)
                slug = entry.get("slug", "")
                if slug in display_name_map:
                    entry["display_name"] = display_name_map[slug]
                discord_league.append(entry)

            # Newsletter AI (DeepSeek + Gemini fallback) — generuj jeśli klucz API jest dostępny.
            # Błąd newslettera NIE przerywa wysyłki post-rounda.
            from newsletter import generate_newsletter
            deepseek_key2 = os.environ.get("DEEPSEEK_API_KEY", "")
            gemini_key2 = os.environ.get("GEMINI_API_KEY", "")
            newsletter_text = None
            if deepseek_key2 or gemini_key2:
                newsletter_round_data = {
                    "round_number": current_round,
                    "league_data": discord_league,
                    "players_data": players,
                    "accuracy_data": accuracy_data,
                    "league_teams_detail": league_teams_detail,
                    "predictions_data": predictions_data,
                }
                newsletter_text = generate_newsletter(newsletter_round_data, deepseek_key=deepseek_key2, gemini_key=gemini_key2)
            else:
                print("  ℹ️  Newsletter: brak kluczy API (DEEPSEEK_API_KEY ani GEMINI_API_KEY) — pomijam generowanie")

            send_post_round(
                league_data=discord_league,
                players_data=players,
                accuracy_data=accuracy_data,
                webhook_url=webhook_url,
                round_number=current_round,
                league_teams_detail=league_teams_detail,
                newsletter_text=newsletter_text,
            )
    else:
        print("  ℹ️  DISCORD_WEBHOOK_URL nie ustawiony — pomijam powiadomienia Discord")

    # Czyszczenie starych plików z timestampem w output/
    cleanup_old_output_files()

    print(f"\n{'='*50}")
    print(f"✅ Gotowe! Pliki zapisane w katalogu: {OUTPUT_DIR}/")
    print(f"   - {os.path.basename(json_file)} (pełne dane JSON)")
    print(f"   - {os.path.basename(csv_file)} (podsumowanie CSV)")
    print(f"   - {os.path.basename(rounds_file)} (statystyki per kolejka CSV)")
    if TEAMS_TO_SCRAPE > 0:
        print(f"   - {os.path.basename(captains_file)} (statystyki kapitanów CSV)")
        print(f"   - {os.path.basename(ownership_file)} (ownership w drużynach CSV)")
    if LEAGUE_SLUG and league_teams:
        print(f"   - {os.path.basename(league_captains_file)} (kapitanowie ligi)")
        print(f"   - {os.path.basename(league_ownership_file)} (ownership ligi)")
    if predictions_data:
        print(f"   - fantasy_predictions_{timestamp}.csv (prognoza punktów)")
    print(f"   - dashboard.html (interaktywny dashboard)")
    print(f"🕐 Koniec: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def save_league_squads_history(league_teams_detail, current_round):
    """
    Archiwizuje składy drużyn ligowych per kolejka.
    Dopisuje do output/league_squads_history.json bez nadpisywania
    poprzednich kolejek.
    Format: {
      "round": 5,
      "timestamp": "2026-07-25T20:30:00",
      "teams": [
        {
          "slug": "tokusatsu-soccer",
          "display_name": "Tokusatsu Soccer",
          "total_pts": 142,
          "players": [
            {"pid": 480, "name": "Bartosz Nowak", "pos": "NAP",
             "C": false, "VC": false}
          ]
        }
      ]
    }
    Jeden wpis per kolejka — jeśli wpis dla tej kolejki już istnieje,
    nadpisuje go (idempotentność przy wielokrotnych runach tej samej kolejki).
    """
    path = os.path.join(OUTPUT_DIR, "league_squads_history.json")

    # Wczytaj istniejącą historię
    history = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = []

    # Zbuduj wpis dla bieżącej kolejki
    teams_snapshot = []
    for team in league_teams_detail:
        players_snapshot = [
            {
                "pid": p.get("pid"),
                "name": p.get("name", ""),
                "pos": p.get("pos", ""),
                "C": p.get("C", False),
                "VC": p.get("VC", False),
            }
            for p in team.get("players", [])
        ]
        teams_snapshot.append({
            "slug": team.get("slug", ""),
            "display_name": team.get("display_name", ""),
            "total_pts": team.get("total_pts", 0),
            "players": players_snapshot,
        })

    entry = {
        "round": current_round,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "teams": teams_snapshot,
    }

    # Usuń poprzedni wpis dla tej kolejki jeśli istnieje
    history = [h for h in history if h.get("round") != current_round]
    history.append(entry)
    history.sort(key=lambda h: h["round"])

    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"📚 Zapisano składy kolejki {current_round} "
          f"({len(teams_snapshot)} drużyn) → league_squads_history.json")


if __name__ == "__main__":
    main()
