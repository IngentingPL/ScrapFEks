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
from bs4 import BeautifulSoup
import json
import csv
import time
import threading
import re
import glob
import os
import sys
import unicodedata
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from predictor import predict_all_players
from accuracy import evaluate_predictions, find_latest_predictions_csv, load_accuracy_history
from tuner import run_tuning
from utils import normalize_team_name, _normalize_name, _safe_int, _safe_float, _normalize_team
from network import _request_with_retry, _load_external_cache, _get_cached_external, _save_external_cache
from external_stats import fetch_ekstraklasa_table, fetch_extra_player_stats
from fdr import compute_fdr
from config import (
    FANTASY_EMAIL, FANTASY_PASSWORD, TARGET_ROUND, MAX_PLAYER_ID,
    TEAMS_TO_SCRAPE, LEAGUE_SLUG, LEAGUE_ID,
    REQUEST_DELAY, WORKERS, MAX_RUNTIME_MINUTES,
    OUTPUT_DIR, SCRIPT_START, BASE_URL, LOGIN_API_URL,
    TOKEN_CREATE_URL, LOGIN_SSO_URL, APPLICATION_ID,
    HEADERS, BROWSER_HEADERS, RANKING_HEADERS,
    EXTRA_API_TOKEN, TEAM_ABBREVS, NINETYM_TEAM_MAP,
    NINETYM_LIGA_ID, EXTRA_STATS_API, EXTRA_STATS_PARAMS, MONTHS_PL,
)

from auth import cryptojs_aes_encrypt, login, get_session
from export import (
    filter_by_round, save_to_csv, save_full_json,
    save_rounds_csv, print_round_summary,
)



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


def parse_player_detail(html_content: str) -> dict:
    """
    Parsuje HTML z odpowiedzi /stats-player/{id} i wyciąga dane zawodnika.
    """
    soup = BeautifulSoup(html_content, "lxml")
    player = {}

    # --- Dane podstawowe ---
    name_el = soup.select_one(".player-name")
    if name_el:
        # Imię i nazwisko to pierwszy tekst, reszta w <span>
        full_text = name_el.get_text(separator="|", strip=True)
        parts = full_text.split("|")
        player["name"] = parts[0].strip() if parts else ""
        if len(parts) > 1:
            team_pos = parts[1].strip()
            # Format: "Lech Poznań, Obrońca"
            if "," in team_pos:
                team, position = team_pos.rsplit(",", 1)
                player["team"] = team.strip()
                player["position"] = position.strip()
            else:
                player["team"] = team_pos
                player["position"] = ""

    # --- Tabela z danymi ogólnymi (Punkty, Cena, Popularność, Kraj) ---
    info_table = soup.select_one(".player-inf table")
    if info_table:
        for row in info_table.select("tr"):
            cells = row.select("td")
            if len(cells) >= 2:
                label = cells[0].text.strip().rstrip(":")
                value = cells[1].text.strip()

                if "Punkty" in label:
                    player["total_points"] = _safe_int(value)
                elif "Cena" in label:
                    player["price"] = _safe_float(value)
                elif "Popularno" in label:  # Popularność
                    player["popularity_pct"] = value  # np. "13%"
                    player["popularity"] = _safe_float(value.replace("%", ""))
                elif "Kraj" in label:
                    player["country"] = value
                elif "Poprzedni" in label:
                    player["previous_club"] = value

    # --- Zdjęcie zawodnika ---
    img = soup.select_one(".player-image")
    if img:
        player["image_url"] = img.get("src", "")

    # --- Statystyki per kolejka ---
    player["rounds"] = []
    stats_table = soup.select_one("#statsTab table")
    if stats_table:
        for row in stats_table.select("tbody tr"):
            cells = row.select("td")
            if not cells:
                continue

            round_data = {}

            # Sprawdź czy zawodnik nie grał
            colspan_cell = row.select_one("td[colspan]")
            if colspan_cell and "nie grał" in colspan_cell.text.lower():
                round_num = cells[0].text.strip()
                opponent = cells[1].text.strip() if len(cells) > 1 else ""
                # Wyczyść opponent z tagów img
                opp_el = cells[1] if len(cells) > 1 else None
                if opp_el:
                    opponent = opp_el.get_text(strip=True)

                round_data = {
                    "round": _safe_int(round_num),
                    "opponent": opponent,
                    "minutes": 0,
                    "goals": 0,
                    "assists": 0,
                    "assist_lotto": 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "points": 0,
                    "played": False,
                }
            elif len(cells) >= 9:
                round_data = {
                    "round": _safe_int(cells[0].text.strip()),
                    "opponent": cells[1].get_text(strip=True),
                    "minutes": _safe_int(cells[2].text.strip()),
                    "goals": _safe_int(cells[3].text.strip()),
                    "assists": _safe_int(cells[4].text.strip()),
                    "assist_lotto": _safe_int(cells[5].text.strip()),
                    "yellow_cards": _safe_int(cells[6].text.strip()),
                    "red_cards": _safe_int(cells[7].text.strip()),
                    "points": _safe_int(cells[8].text.strip()),
                    "played": True,
                }
            elif len(cells) >= 3:
                # Mniej kolumn - wyciągnij co się da
                round_data = {
                    "round": _safe_int(cells[0].text.strip()),
                    "opponent": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                    "played": False,
                }

            if round_data:
                player["rounds"].append(round_data)

    # --- Historia cen ---
    player["price_history"] = []
    price_table = soup.select_one("#priceTab table")
    if price_table:
        for row in price_table.select("tbody tr"):
            cells = row.select("td")
            if len(cells) >= 3:
                player["price_history"].append({
                    "round": _safe_int(cells[0].text.strip()),
                    "opponent": cells[1].get_text(strip=True),
                    "price": _safe_float(cells[2].text.strip()),
                })

    # --- Link do pełnych statystyk ---
    full_stats_link = soup.select_one("a[href*='/player/']")
    if full_stats_link:
        href = full_stats_link.get("href", "")
        match = re.search(r"/player/(\d+)", href)
        if match:
            player["stats_page_id"] = match.group(1)
            player["stats_url"] = f"{BASE_URL}{href}"

    # --- Status dostępności (kontuzje, zawieszenia, "nie zagra") ---
    # Szukamy <div class="info-NO_PLAY">Kontuzjowany</div>
    # Jeśli div istnieje → zawodnik niedostępny, zapisujemy tekst statusu
    # Jeśli div nie istnieje → zawodnik dostępny (ACTIVE, None)
    no_play_el = soup.select_one(".info-NO_PLAY")
    if no_play_el:
        player["availability_status"] = no_play_el.get_text(strip=True)
    # brak diva = brak statusu → domyślnie dostępny

    return player


def fetch_player_detail(session: requests.Session, player_id: int) -> Optional[dict]:
    """
    Pobiera szczegóły zawodnika z endpointu /stats-player/{id}.
    Thread-safe — używa requests.get() z cookies z sesji.
    """
    try:
        # Retry logic na wypadek problemów sieciowych
        resp = _request_with_retry(requests.get, f"{BASE_URL}/stats-player/{player_id}",
            headers=HEADERS, cookies=dict(session.cookies), timeout=15)
        if resp is None:
            return None
        if resp.status_code != 200:
            return None

        data = resp.json()
        html_content = data.get("data", {}).get("message", "")

        if not html_content:
            return None

        player = parse_player_detail(html_content)
        player["player_id"] = player_id
        player["source_url"] = f"{BASE_URL}/stats-player/{player_id}"
        return player

    except (json.JSONDecodeError, requests.RequestException):
        return None


def fetch_all_players(session: requests.Session, player_ids: list[int]) -> list[dict]:
    """Pobiera dane wszystkich zawodników równolegle (ThreadPoolExecutor)."""
    total = len(player_ids)
    print(f"\n📊 Pobieram szczegóły {total} zawodników ({WORKERS} workerów)...")

    results: list[Optional[dict]] = [None] * total
    completed_count = 0
    lock = threading.Lock()

    def _fetch(idx: int, pid: int) -> tuple[int, Optional[dict]]:
        player = fetch_player_detail(session, pid)
        time.sleep(REQUEST_DELAY)
        return idx, player

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(_fetch, i, pid): i for i, pid in enumerate(player_ids)}
        for future in as_completed(futures):
            idx, player = future.result()
            results[idx] = player
            with lock:
                completed_count += 1
                done = completed_count
            if player and player.get("name"):
                name = player.get("name", "?")
                team = player.get("team", "?")
                pts = player.get("total_points", "?")
                pop = player.get("popularity_pct", "?")
                print(f"   [{done}/{total}] ✅ {name} ({team}) - {pts} pkt, popularność: {pop}")
            elif done % 100 == 0:
                print(f"   [{done}/{total}] ... skanowanie")

    players = [p for p in results if p and p.get("name")]
    print(f"\n   ✅ Pobrano dane {len(players)} zawodników")
    return players




# ============================================================
# SCRAPOWANIE DRUŻYN - KAPITANOWIE I SKŁADY
# ============================================================

def fetch_ranking_teams(session: requests.Session, count: int) -> list[dict]:
    """
    Pobiera listę drużyn z rankingu generalnego.
    Używa endpointu DataTables POST /ranking-list.
    """
    print(f"\n🏆 Pobieram ranking ({count} najlepszych drużyn)...")
    teams = []
    batch_size = 100  # max per request

    for start in range(0, count, batch_size):
        length = min(batch_size, count - start)
        try:
            resp = session.post(
                f"{BASE_URL}/ranking-list",
                data=f"start={start}&length={length}",
                headers=RANKING_HEADERS,
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"   ⚠️  Błąd HTTP {resp.status_code} przy start={start}")
                continue

            data = resp.json()
            for team in data.get("data", []):
                slug = team.get("slug", "")
                if slug:
                    teams.append({
                        "team_id": team.get("id"),
                        "slug": slug,
                        "total_points": _safe_int(str(team.get("total_points", "0"))),
                        "last_points": _safe_int(str(team.get("last_points", "0"))),
                        "position": team.get("pos"),
                    })

            print(f"   Pobrano {len(teams)}/{count} drużyn...")
            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"   ⚠️  Błąd: {e}")

    print(f"   ✅ Pobrano {len(teams)} drużyn z rankingu")
    return teams


def fetch_league_teams(session: requests.Session, league_slug: str, league_id: str) -> list[dict]:
    """
    Pobiera listę drużyn z ligi prywatnej.
    POST /ranking-list z parametrem league={id}.
    """
    print(f"\n🏅 Pobieram drużyny z ligi: {league_slug} (ID: {league_id})...")
    teams = []

    try:
        payload = f"start=0&length=100&league={league_id}&round=0"
        resp = session.post(
            f"{BASE_URL}/ranking-list",
            data=payload,
            headers={**RANKING_HEADERS, "Referer": f"{BASE_URL}/league/{league_slug}"},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"   ⚠️  POST /ranking-list (league): HTTP {resp.status_code}")
            return teams

        data = resp.json()
        for team in data.get("data", []):
            slug = team.get("slug", "")
            if slug:
                teams.append({
                    "team_id": team.get("id"),
                    "slug": slug,
                    "total_points": _safe_int(str(team.get("total_points", "0"))),
                    "last_points": _safe_int(str(team.get("last_points", "0"))),
                    "max_points": _safe_int(str(team.get("max_points", "0"))),
                    "position": team.get("pos"),
                })

        print(f"   ✅ Pobrano {len(teams)} drużyn z ligi")

    except Exception as e:
        print(f"   ⚠️  Błąd POST ranking-list (league): {e}")

    return teams


def scrape_team_squad(session: requests.Session, slug: str, debug: bool = False,
                      round_num: int = None) -> dict:
    """
    Scrapuje skład drużyny ze strony /user-team/view/{slug}[/{round_num}].
    Dane są osadzone w HTML jako wywołania app.Pitch.$squad.push({...}).
    Thread-safe — nie modyfikuje session.headers, używa requests.get() bezpośrednio.
    """
    try:
        # Czyste headery przeglądarki — bez X-Requested-With
        browser_headers = {
            **BROWSER_HEADERS,
            "Referer": f"{BASE_URL}/",
        }

        url = (f"{BASE_URL}/user-team/view/{slug}/{round_num}"
               if round_num is not None
               else f"{BASE_URL}/user-team/view/{slug}")

        # Thread-safe: użyj requests.get() z cookies z sesji (z retry)
        resp = _request_with_retry(requests.get, url,
            headers=browser_headers, cookies=dict(session.cookies), timeout=15)
        if resp is None:
            return {"slug": slug, "players": [], "captain_id": None}

        if resp.status_code != 200:
            if debug:
                print(f"      ⚠️  HTTP {resp.status_code} dla {slug}")
            return {"slug": slug, "players": [], "captain_id": None}

        html = resp.text
        players = []
        captain_id = None

        # Szukamy wzorca: $squad.push({ ... }); — startowi (11)
        pattern = r'\$squad\.push\(\{(.*?)\}\);'
        matches = re.findall(pattern, html, re.DOTALL)

        # Szukamy wzorca: $subs.push({ ... }); — ławka (4)
        subs_pattern = r'\$subs\.push\(\{(.*?)\}\);'
        subs_matches = re.findall(subs_pattern, html, re.DOTALL)

        if debug:
            print(f"      DEBUG {slug}: squad.push={len(matches)}, subs.push={len(subs_matches)}")
            if not matches and not subs_matches:
                all_pushes = re.findall(r'(\$?\w+(?:\.\$?\w+)*)\.push\(\{', html)
                print(f"      DEBUG wszystkie .push(): {all_pushes}")
                print(f"      DEBUG HTML length: {len(html)}")

        def _parse_player(match, is_reserve=False):
            pid = re.search(r'"id"\s*:\s*(\d+)', match)
            name = re.search(r'"name"\s*:\s*"([^"]*)"', match)
            pos = re.search(r'"pos"\s*:\s*(\d+)', match)
            price = re.search(r'"price"\s*:\s*([\d.]+)', match)
            captain = re.search(r'"captain"\s*:\s*(true|false)', match)
            subcaptain = re.search(r'"subcaptain"\s*:\s*(true|false)', match)
            points_match = re.search(r'"points"\s*:\s*"([^"]*)"', match)
            status = re.search(r'"status"\s*:\s*"([^"]*)"', match)

            player_id = pid.group(1) if pid else None
            is_captain = captain.group(1) == "true" if captain else False
            is_subcaptain = subcaptain.group(1) == "true" if subcaptain else False
            points_text = points_match.group(1).strip() if points_match else ""

            return {
                "player_id": player_id,
                "name": name.group(1) if name else "",
                "position_id": pos.group(1) if pos else "",
                "price": float(price.group(1)) if price else 0,
                "points": _safe_int(points_text) if points_text and points_text != "-" else 0,
                "is_captain": is_captain,
                "is_subcaptain": is_subcaptain,
                "is_reserve": is_reserve,
                "status": status.group(1) if status else "",
            }, is_captain, player_id

        # Parsuj startowych
        for match in matches:
            p, is_cap, pid = _parse_player(match, is_reserve=False)
            if is_cap and pid:
                captain_id = pid
            players.append(p)

        # Parsuj ławkę
        for match in subs_matches:
            p, is_cap, pid = _parse_player(match, is_reserve=True)
            if is_cap and pid:
                captain_id = pid
            players.append(p)

        # Fallback: jeśli nie było subs.push, ale jest >11 graczy, użyj indeksu
        if not subs_matches and len(players) > 11:
            for i, p in enumerate(players):
                if i >= 11:
                    p["is_reserve"] = True

        if debug and players:
            cap_name = next((p["name"] for p in players if p["is_captain"]), "brak")
            reserves = sum(1 for p in players if p["is_reserve"])
            print(f"      DEBUG kapitan: {cap_name}, graczy: {len(players)}, "
                  f"rezerwa: {reserves}, subs.push: {len(subs_matches)}")

        return {
            "slug": slug,
            "players": players,
            "captain_id": captain_id,
        }

    except Exception as e:
        print(f"⚠️ błąd scrape_team_squad({slug}): {e}")
        if debug:
            print(f"      ⚠️  Błąd: {e}")
        return {"slug": slug, "players": [], "captain_id": None, "error": str(e)}


def _process_team(args):
    """Worker do przetworzenia jednej drużyny (thread-safe)."""
    session, team, debug = args
    slug = team["slug"]
    squad = scrape_team_squad(session, slug, debug=debug)

    captain_id = squad.get("captain_id")
    captain_name = ""
    for p in squad.get("players", []):
        if p["player_id"] == captain_id:
            captain_name = p["name"]
            break

    return {
        "ranking_position": team.get("position"),
        "team_slug": slug,
        "team_points": team.get("total_points"),
        "captain_id": captain_id,
        "captain_name": captain_name,
        "squad": squad.get("players", []),
    }


def scrape_teams_captains(session: requests.Session, teams: list[dict],
                          checkpoint_file: str = None) -> list[dict]:
    """
    Scrapuje składy drużyn równolegle (ThreadPoolExecutor).
    Zapisuje postęp co 500 drużyn do checkpoint_file.
    Zatrzymuje się gracefully gdy zbliża się MAX_RUNTIME.
    """
    total = len(teams)
    results = []
    done_slugs = set()

    # Wczytaj checkpoint jeśli istnieje
    if checkpoint_file and os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                results = json.load(f)
            done_slugs = {r["team_slug"] for r in results}
            print(f"   📂 Wczytano checkpoint: {len(results)} drużyn")
        except Exception as e:
            print(f"   ⚠️  Błąd checkpointu: {e}")

    remaining = [t for t in teams if t["slug"] not in done_slugs]
    if not remaining:
        print(f"\n👑 Wszystkie {total} drużyn już pobrane (checkpoint)")
        return results

    print(f"\n👑 Scrapuję składy {len(remaining)} drużyn ({WORKERS} workerów, "
          f"limit: {MAX_RUNTIME_MINUTES} min)...")
    if done_slugs:
        print(f"   Kontynuacja — już pobrano: {len(done_slugs)}")

    start_time = time.time()
    max_seconds = MAX_RUNTIME_MINUTES * 60
    completed = 0
    errors = 0
    timed_out = False

    # Przetwarzaj w batchach po 500 — pozwala sprawdzać czas
    BATCH_SIZE = 500
    for batch_start in range(0, len(remaining), BATCH_SIZE):
        # Sprawdź czas PRZED następnym batchem
        elapsed_total = time.time() - SCRIPT_START
        if elapsed_total > max_seconds:
            timed_out = True
            print(f"\n   ⏰ Limit czasu ({MAX_RUNTIME_MINUTES} min) — zatrzymuję po {completed} drużynach")
            break

        batch = remaining[batch_start:batch_start + BATCH_SIZE]
        args_list = [(session, team, batch_start + i < 2) for i, team in enumerate(batch)]

        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(_process_team, args): args[1]["slug"]
                       for args in args_list}

            for future in as_completed(futures):
                # Sprawdź czas w trakcie batcha
                elapsed_total = time.time() - SCRIPT_START
                if elapsed_total > max_seconds:
                    timed_out = True
                    # Poczekaj na bieżące futures ale nie startuj nowych
                    executor._threads.clear()  # type: ignore
                    break

                slug = futures[future]
                try:
                    result = future.result(timeout=30)
                    results.append(result)
                    completed += 1

                    if not result.get("squad"):
                        errors += 1
                except Exception as e:  # jawne logowanie błędu workera
                    print(f"⚠️ błąd workera ({slug}): {e}")
                    completed += 1
                    errors += 1

                # Progress co 500 drużyn
                total_done = len(done_slugs) + completed
                if completed % 500 == 0:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    remaining_count = len(remaining) - completed
                    eta = remaining_count / rate / 60 if rate > 0 else 0
                    time_left = (max_seconds - (time.time() - SCRIPT_START)) / 60
                    print(f"   [{total_done}/{total}] {rate:.1f}/s, "
                          f"ETA: {eta:.0f} min, pozostało czasu: {time_left:.0f} min, błędy: {errors}")

        # Checkpoint po każdym batchu
        if checkpoint_file:
            try:
                with open(checkpoint_file, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False)
                print(f"   💾 Checkpoint: {len(results)} drużyn")
            except Exception as e:  # jawne logowanie błędu checkpointu
                print(f"⚠️ nie udało się zapisać checkpointu: {e}")

        if timed_out:
            break

    # Finalny checkpoint
    if checkpoint_file:
        try:
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False)
        except Exception as e:  # jawne logowanie błędu finalnego checkpointu
            print(f"⚠️ nie udało się zapisać finalnego checkpointu: {e}")

    elapsed = time.time() - start_time
    status = "⏰ PRZERWANO (limit czasu)" if timed_out else "✅ Zakończono"
    print(f"   {status} — {len(results)}/{total} drużyn w {elapsed/60:.1f} min "
          f"({completed/(elapsed or 1):.1f}/s, błędy: {errors})")
    return results


def _compute_captain_stats(team_results: list[dict]) -> list[dict]:
    """Oblicza statystyki kapitanów (bez zapisu do CSV)."""
    captain_counts = {}
    total_teams = len(team_results)
    if total_teams == 0:
        return []

    for team in team_results:
        cid = team.get("captain_id")
        cname = team.get("captain_name", "")
        if cid:
            if cid not in captain_counts:
                captain_counts[cid] = {"player_id": cid, "name": cname, "captain_count": 0}
            captain_counts[cid]["captain_count"] += 1

    stats = sorted(captain_counts.values(), key=lambda x: x["captain_count"], reverse=True)
    for s in stats:
        s["captain_pct"] = f"{round(s['captain_count'] / total_teams * 100, 1)}%"
    return stats


def _compute_squad_stats(team_results: list[dict]) -> list[dict]:
    """Oblicza statystyki ownership (bez zapisu do CSV)."""
    player_counts = {}
    total_teams = len(team_results)
    if total_teams == 0:
        return []

    for team in team_results:
        for p in team.get("squad", []):
            pid = p["player_id"]
            if pid not in player_counts:
                player_counts[pid] = {
                    "player_id": pid,
                    "name": p["name"],
                    "position": p.get("position_id", ""),
                    "in_squad_count": 0,
                    "in_starting_count": 0,
                    "captain_count": 0,
                }
            player_counts[pid]["in_squad_count"] += 1
            if not p.get("is_reserve"):
                player_counts[pid]["in_starting_count"] += 1
            if p.get("is_captain"):
                player_counts[pid]["captain_count"] += 1

    stats = sorted(player_counts.values(), key=lambda x: x["in_squad_count"], reverse=True)
    for s in stats:
        s["squad_pct"] = f"{round(s['in_squad_count'] / total_teams * 100, 1)}%"
        s["starting_pct"] = f"{round(s['in_starting_count'] / total_teams * 100, 1)}%"
        s["captain_pct"] = f"{round(s['captain_count'] / total_teams * 100, 1)}%"
    return stats


def generate_captain_stats(team_results: list[dict], filename: str):
    """Generuje statystyki kapitanów i zapisuje do CSV."""
    stats = _compute_captain_stats(team_results)
    total_teams = len(team_results)

    save_to_csv(stats, filename)

    print(f"\n{'='*60}")
    print(f"  👑 STATYSTYKI KAPITANÓW (z {total_teams} drużyn)")
    print(f"{'='*60}")
    print(f"  {'Zawodnik':<25} {'Wyborów':>8} {'%':>8}")
    print(f"  {'-'*45}")
    for s in stats[:15]:
        print(f"  {s['name']:<25} {s['captain_count']:>8} {s['captain_pct']:>8}")

    return stats


def generate_squad_stats(team_results: list[dict], filename: str):
    """Generuje statystyki ownership i zapisuje do CSV."""
    stats = _compute_squad_stats(team_results)
    total_teams = len(team_results)

    save_to_csv(stats, filename)

    print(f"\n{'='*70}")
    print(f"  👥 OWNERSHIP W DRUŻYNACH (z {total_teams} drużyn)")
    print(f"{'='*70}")
    print(f"  {'Zawodnik':<25} {'W składzie':>10} {'Start XI':>10} {'Kapitan':>10}")
    print(f"  {'-'*60}")
    for s in stats[:15]:
        print(f"  {s['name']:<25} {s['squad_pct']:>10} {s['starting_pct']:>10} {s['captain_pct']:>10}")

    return stats


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


def parse_terminarz(filepath: str = "terminarz.txt") -> dict:
    """Parsuje terminarz.txt i zwraca dane do fixture ticker."""
    if not os.path.exists(filepath):
        print(f"  ⚠️  Brak pliku {filepath} — pomijam fixture ticker")
        return {"rounds": [], "matches": {}, "teams": [], "abbrevs": {}}

    matches_by_round = {}
    teams_set = set()
    current_round = None
    current_round_date = ""

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            round_match = re.match(r"Kolejka\s+(\d+)", line)
            if round_match:
                current_round = int(round_match.group(1))
                if current_round not in matches_by_round:
                    matches_by_round[current_round] = []
                header_date = re.search(r"(\d{1,2})[–\-]\d*\s+(\w+)", line[len(round_match.group(0)):])
                if header_date:
                    month = MONTHS_PL.get(header_date.group(2))
                    if month:
                        current_round_date = f"{int(header_date.group(1)):02d}.{month:02d}"
                continue
            # Opcjonalnie ignoruj frekwencję w nawiasie na końcu linii, np. "(14 569)"
            date_match = re.search(r"(\d{1,2})\s+(\w+),\s*(\d{1,2}):(\d{2})\s*(?:\(\d[\d\s]*\))?\s*$", line)
            if date_match and current_round:
                day = int(date_match.group(1))
                month_name = date_match.group(2)
                month = MONTHS_PL.get(month_name)
                if not month:
                    continue
                teams_part = line[:date_match.start()].strip()
                parts = re.split(r'	+-	+', teams_part)
                if len(parts) != 2:
                    parts = re.split(r'\s+-\s+', teams_part)
                if len(parts) == 2:
                    home = parts[0].strip()
                    away = parts[1].strip()
                    teams_set.add(home)
                    teams_set.add(away)
                    matches_by_round[current_round].append({
                        "home": home,
                        "away": away,
                        "date": f"{day:02d}.{month:02d}",
                    })
            elif current_round and ("–" in line or " - " in line or "\t-\t" in line):
                # Użyj tabulatora jako separatora jeśli dostępny — unikamy cięcia na myślnikach w nazwach (np. Bruk-Bet)
                if "\t-\t" in line:
                    parts = line.split("\t-\t", 1)
                elif "–" in line:
                    parts = line.split("–", 1)
                else:
                    parts = line.split(" - ", 1)
                if len(parts) == 2:
                    home = parts[0].strip()
                    away = parts[1].strip()
                    # Pomijamy linie z cyframi — to listy strzelców (np. "Luis Palma 57 - Kike Hermoso 52"),
                    # a nie mecze. Nazwy drużyn Ekstraklasy nigdy nie zawierają cyfr.
                    if home and away and len(home) > 2 and not re.match(r'^\d', home) \
                            and not re.search(r'\d', home) and not re.search(r'\d', away):
                        teams_set.add(home)
                        teams_set.add(away)
                        matches_by_round[current_round].append({
                            "home": home,
                            "away": away,
                            "date": current_round_date,
                        })

    teams = sorted(teams_set)
    abbrevs = {}
    for t in teams:
        abbrevs[t] = TEAM_ABBREVS.get(t, t[:3].upper())

    rounds = sorted(matches_by_round.keys())
    matches_json = {str(r): matches_by_round[r] for r in rounds}

    return {
        "rounds": rounds,
        "matches": matches_json,
        "teams": teams,
        "abbrevs": abbrevs,
    }
from dashboard import generate_dashboard_html

# ============================================================
# CZYSZCZENIE STARYCH PLIKÓW W OUTPUT/
# ============================================================

def cleanup_old_output_files():
    """
    Usuwa stare pliki z output/ z timestampem w nazwie, zachowując N najnowszych.
    NIGDY nie rusza plików stanu (dashboard.html, league_teams_detail.json,
    external_cache.json, itp.).
    Wzorce i liczba do zachowania są ustalone na stałe — tylko te pliki są czyszczone.
    """
    # Wzorzec → ile najnowszych plików zachować
    keep_rules = {
        "output/fantasy_full_*.json": 1,
        "output/fantasy_predictions_*.csv": 2,
        "output/fantasy_players_*.csv": 1,
        "output/fantasy_rounds_*.csv": 1,
        "output/fantasy_captains_*.csv": 1,
        "output/fantasy_ownership_*.csv": 1,
        "output/fantasy_league_captains_*.csv": 1,
        "output/fantasy_league_ownership_*.csv": 1,
    }

    for pattern, keep_count in keep_rules.items():
        try:
            files = sorted(glob.glob(pattern))
            if len(files) <= keep_count:
                continue  # nic do usunięcia

            to_remove = files[:-keep_count]  # najstarsze pliki
            for f in to_remove:
                try:
                    os.remove(f)
                except OSError as e:
                    print(f"  ⚠️  Nie udało się usunąć {f}: {e}")
            print(f"  🧹 {pattern}: usunięto {len(to_remove)} starych plików (zachowano {len(files) - len(to_remove)})")
        except Exception as e:
            print(f"  ⚠️  Błąd czyszczenia {pattern}: {e}")

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
        for p in players:
            for r in p.get("rounds", []):
                if r.get("played") and r.get("round", 0) > current_round:
                    current_round = r["round"]
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
        for tier_key, tier_limit in [("top10", 10), ("top100", 100)]:
            tier_teams = [t for t in team_results
                          if (t.get("ranking_position") or 999999) <= tier_limit]
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

    # 8.6 Scrapuj statystyki bramkowe z 90minut.pl
    ekstra_stats = fetch_ekstraklasa_table()

    # 8.6b Pobierz rozszerzone statystyki zawodników z ekstraklasa.org
    # (xG, strzały, podania kluczowe, dośrodkowania)
    extra_player_stats = fetch_extra_player_stats()

    # Oblicz sumę minut dla każdego zawodnika (do przeliczania na per 90)
    player_minutes = {}
    for p in players:
        pid = str(p.get("player_id", ""))
        total_mins = sum(r.get("minutes", 0) for r in p.get("rounds", []))
        if total_mins > 0:
            player_minutes[pid] = total_mins

    # Wzbogać dane zawodników o statystyki per 90
    players = compute_player_stats_per90(extra_player_stats, players, player_minutes)

    # 8.7 Oblicz FDR (Fixture Difficulty Rating)
    remaining_rounds = len([r for r in fixtures_data.get("rounds", []) if r >= (current_round or 0)])
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
        pos_map = {"Bramkarz": "BR", "Obrońca": "OBR", "Pomocnik": "POM", "Napastnik": "NAP"}
        players_for_pred = []
        for p in players:
            pp = dict(p)
            raw_pos = pp.get("position", "")
            pp["position"] = pos_map.get(raw_pos, raw_pos)
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
                    fdr_by_team[team_fdr["name"]] = {
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
            pred["round_number"] = current_round  # kolejka której dotyczy prognoza

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
    accuracy_history = load_accuracy_history()

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
    autumn_points_file = os.path.join(script_dir, "autumn_points.json")
    hockey_prev_file = os.path.join(script_dir, "hockey_prev_ranking.json")
    if os.path.exists(autumn_points_file):
        try:
            with open(autumn_points_file, "r", encoding="utf-8") as f:
                autumn_raw = json.load(f)
            print(f"\n🏒 Liga Hokejowa: wczytano {len(autumn_raw)} drużyn z rundy jesiennej")

            # Buduj lookup: normalize(name) → {points, best_gw, display_name}
            autumn_lookup = {}
            for name, val in autumn_raw.items():
                key = normalize_team_name(name)
                if isinstance(val, dict):
                    autumn_lookup[key] = {"points": val.get("points", 0), "best_gw": val.get("best_gameweek", 0), "display_name": name}
                else:
                    autumn_lookup[key] = {"points": val, "best_gw": 0, "display_name": name}

            # Buduj lookup max_points z league_teams (fetch_league_teams → /ranking-list)
            max_pts_lookup = {}
            if league_teams:
                for t in league_teams:
                    slug_name = t["slug"].replace("-", " ")
                    key = normalize_team_name(slug_name)
                    max_pts_lookup[key] = t.get("max_points", 0)

            # Wzbogać league_teams_detail o dane hokejowe
            spring_seen_keys = set()
            for t in league_teams_detail:
                slug_name = t["slug"].replace("-", " ")
                key = normalize_team_name(slug_name)
                spring_seen_keys.add(key)
                autumn_info = autumn_lookup.get(key, {"points": 0, "best_gw": 0, "display_name": ""})
                t["autumn_pts"] = autumn_info["points"]
                t["best_gw_autumn"] = autumn_info["best_gw"]
                best_gw_spring = max_pts_lookup.get(key, 0)
                t["best_gw_spring"] = best_gw_spring if best_gw_spring else 0
                t["spring_pts"] = t["pts"]
                t["total_pts"] = t["autumn_pts"] + t["spring_pts"]
                t["display_name"] = autumn_info["display_name"] or slug_name
                t["autumn_only"] = False
                t["spring_only"] = key not in autumn_lookup

            # Dodaj drużyny jesienne bez wiosny (autumn_only)
            for key, info in autumn_lookup.items():
                if key not in spring_seen_keys:
                    league_teams_detail.append({
                        "slug": info["display_name"].lower().replace(" ", "-"),
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


if __name__ == "__main__":
    main()
