"""
players.py - pobieranie i parsowanie szczegółów zawodnika z
/stats-player/{id}: dane podstawowe + statystyki per kolejka.
"""

import json
import re
import time
import threading
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from config import BASE_URL, HEADERS, WORKERS, REQUEST_DELAY
from utils import _safe_int, _safe_float
from network import _request_with_retry


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
