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
import re
import os
import sys
import hashlib
from datetime import datetime
from typing import Optional
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from Crypto.Random import get_random_bytes


def cryptojs_aes_encrypt(plaintext: str, passphrase: str) -> str:
    """
    Szyfruje tekst kompatybilnie z CryptoJS.AES.encrypt(text, passphrase).
    Używa OpenSSL EVP_BytesToKey (MD5) do wyprowadzenia klucza i IV.
    Zwraca base64 string w formacie: "Salted__" + salt + ciphertext.
    """
    salt = get_random_bytes(8)

    # EVP_BytesToKey z MD5 — kompatybilne z CryptoJS
    key_iv = b""
    prev = b""
    while len(key_iv) < 48:  # 32 bytes key + 16 bytes IV
        prev = hashlib.md5(prev + passphrase.encode("utf-8") + salt).digest()
        key_iv += prev

    key = key_iv[:32]
    iv = key_iv[32:48]

    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))

    import base64
    result = base64.b64encode(b"Salted__" + salt + ciphertext).decode("utf-8")
    return result


# ============================================================
# KONFIGURACJA
# ============================================================

# Dane logowania (z GitHub Secrets lub zmiennych środowiskowych)
FANTASY_EMAIL = os.environ.get("FANTASY_EMAIL", "")
FANTASY_PASSWORD = os.environ.get("FANTASY_PASSWORD", "")

# Którą kolejkę analizować (None = ostatnia rozegrana)
TARGET_ROUND = int(os.environ["TARGET_ROUND"]) if os.environ.get("TARGET_ROUND") else None

# Maksymalne ID zawodnika do sprawdzenia
MAX_PLAYER_ID = int(os.environ.get("MAX_PLAYER_ID", "4000"))

# Ile drużyn z rankingu scrapować (dla statystyk kapitanów itp.)
TEAMS_TO_SCRAPE = int(os.environ.get("TEAMS_TO_SCRAPE", "1000"))

# Slug ligi prywatnej (puste = pomiń)
LEAGUE_SLUG = os.environ.get("LEAGUE_SLUG", "discord-fmforumcmf")
# ID ligi (z Network tab: POST /ranking-list → league: 304)
LEAGUE_ID = os.environ.get("LEAGUE_ID", "304")

# Opóźnienie między requestami (w sekundach) - bądź miły dla serwera
REQUEST_DELAY = 0.3

# Ile równoległych workerów do scrapowania drużyn
WORKERS = int(os.environ.get("WORKERS", "10"))

# Maksymalny czas pracy (minuty) — graceful stop przed limitem GitHub Actions (6h)
MAX_RUNTIME_MINUTES = int(os.environ.get("MAX_RUNTIME_MINUTES", "300"))

# Globalny czas startu
SCRIPT_START = time.time()

# Plik wyjściowy
OUTPUT_DIR = "output"
# ============================================================


BASE_URL = "https://fantasy.ekstraklasa.org"
LOGIN_API_URL = "https://wicket-api.ekstraklasa-prod.tisagroup.ch/p/user/login/"
TOKEN_CREATE_URL = "https://wicket-api.ekstraklasa-prod.tisagroup.ch/p/anonymous/token/create"
LOGIN_SSO_URL = f"{BASE_URL}/login-sso"
APPLICATION_ID = "sHCKWvfuCwRdu7s0vWwlPgBBjtHahTCvVgzTVZ8osyBGYKpikt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_URL}/",
}


def login(session: requests.Session) -> bool:
    """
    Automatycznie loguje się do Fantasy Ekstraklasa.
    
    Flow:
    1. POST email+hasło → wicket API → dostajemy tokeny
    2. POST tokeny → fantasy.ekstraklasa.org/login-sso → dostajemy sesję
    """
    if not FANTASY_EMAIL or not FANTASY_PASSWORD:
        print("❌ Brak danych logowania!")
        print("   Ustaw zmienne środowiskowe FANTASY_EMAIL i FANTASY_PASSWORD")
        print("   lub dodaj je jako GitHub Secrets.")
        return False

    print(f"🔐 Logowanie jako {FANTASY_EMAIL}...")

    # Krok 1: Pobranie tokenów z wicket API
    login_payload = {
        "email": FANTASY_EMAIL,
        "password": FANTASY_PASSWORD,
        "fan_application_sub": APPLICATION_ID,
        "fk_dict_device_type_id": 1,
    }

    try:
        resp = session.post(LOGIN_API_URL, json=login_payload, timeout=30)
        if resp.status_code != 201:
            print(f"   ❌ Błąd logowania (krok 1): HTTP {resp.status_code}")
            print(f"   Odpowiedź: {resp.text[:200]}")
            return False

        token_data = resp.json()
        access_token = token_data.get("token")

        if not access_token:
            print("   ❌ Brak tokenu w odpowiedzi!")
            return False

        print("   ✅ Tokeny pobrane")

    except Exception as e:
        print(f"   ❌ Błąd połączenia z API logowania: {e}")
        return False

    # Krok 2: Szyfrowanie tokenu (CryptoJS.AES.encrypt kompatybilne)
    id_token = token_data.get("id_token", "")
    encrypted = cryptojs_aes_encrypt(access_token, "secret")
    encrypted_urlencoded = quote(encrypted, safe="")
    print("   ✅ Token zaszyfrowany")

    # Krok 3: Tworzenie tokenu connect — POST /p/anonymous/token/create
    try:
        create_payload = {
            "token_text": encrypted_urlencoded,
            "fan_application_sub": APPLICATION_ID,
        }
        resp = session.post(
            TOKEN_CREATE_URL,
            json=create_payload,
            headers={
                "Authorization": id_token,
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://konto.ekstraklasa.org",
                "Referer": "https://konto.ekstraklasa.org/",
            },
            timeout=30,
        )
        print(f"   Token create status: {resp.status_code}")
        print(f"   Token create response: {resp.text[:300]}")

        if resp.status_code != 200:
            print(f"   ❌ Błąd tworzenia tokenu connect")
            return True  # kontynuuj bez cookies

        create_data = resp.json()
        connect_hash = create_data.get("token") or create_data.get("hash") or create_data.get("code")

        if not connect_hash:
            # Może cała odpowiedź to hash?
            print(f"   DEBUG create_data keys: {list(create_data.keys()) if isinstance(create_data, dict) else type(create_data)}")
            print(f"   DEBUG create_data: {json.dumps(create_data)[:500]}")
            return True

        print(f"   ✅ Connect hash: {str(connect_hash)[:50]}...")

    except Exception as e:
        print(f"   ❌ Błąd token/create: {e}")
        return True

    # Krok 4: GET /connect?g4t7hjq3rcyb0s2m={hash} — ustawia PHPSESSID
    try:
        # Tymczasowo użyj czystych headerów przeglądarki (bez X-Requested-With)
        saved_headers = dict(session.headers)
        session.headers.clear()
        browser_hdrs = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9",
        }
        session.headers.update(browser_hdrs)

        # Najpierw GET na stronę z fałszywym PHPSESSID — wymusza PHP backend
        session.cookies.set("PHPSESSID", "init_session_000", domain="fantasy.ekstraklasa.org")
        init_resp = session.get(BASE_URL, timeout=15)
        print(f"   Init GET / status: {init_resp.status_code}, cookies: {dict(session.cookies)}")
        print(f"   Init Set-Cookie: {init_resp.headers.get('Set-Cookie', 'brak')}")

        # Teraz GET /connect z hashem
        resp = session.get(
            f"{BASE_URL}/connect",
            params={"g4t7hjq3rcyb0s2m": connect_hash},
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=30,
            allow_redirects=True,
        )
        print(f"   Connect status: {resp.status_code}, cookies: {dict(session.cookies)}")
        print(f"   Connect Set-Cookie: {resp.headers.get('Set-Cookie', 'brak')}")
        print(f"   Connect all headers: {dict(resp.headers)}")
        print(f"   Connect history (redirects): {[r.status_code for r in resp.history]}")
        for i, r in enumerate(resp.history):
            print(f"   Redirect {i}: {r.status_code} → {r.headers.get('Location', '?')}, Set-Cookie: {r.headers.get('Set-Cookie', 'brak')}")

        if not dict(session.cookies).get("PHPSESSID"):
            print("   ⚠️  /connect nie ustawiło PHPSESSID")
            session.headers.clear()
            session.headers.update(saved_headers)
            return True

    except Exception as e:
        print(f"   ❌ Błąd /connect: {e}")
        session.headers.clear()
        session.headers.update(saved_headers)
        return True

    # Krok 5: POST /login-sso — autoryzuje sesję
    try:
        resp = session.post(
            LOGIN_SSO_URL,
            data={"id_token": id_token},
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/connect",
            },
            timeout=30,
            allow_redirects=True,
        )
        print(f"   Login SSO status: {resp.status_code}, resp: {resp.text[:150]}")

        # Przywróć oryginalne headers sesji
        session.headers.clear()
        session.headers.update(saved_headers)

        print(f"   ✅ Zalogowano! Cookies: {dict(session.cookies)}")
        return True

    except Exception as e:
        print(f"   ❌ Błąd SSO: {e}")
        session.headers.clear()
        session.headers.update(saved_headers)
        return False


def get_session() -> requests.Session:
    """Tworzy sesję HTTP i loguje się automatycznie."""
    session = requests.Session()
    session.headers.update(HEADERS)

    if not login(session):
        print("\n❌ Nie udało się zalogować. Sprawdź dane logowania.")
        sys.exit(1)

    return session


def get_player_ids_from_stats_page(session: requests.Session) -> list[dict]:
    """
    Pobiera listę ID zawodników ze strony /stats.
    Zwraca listę słowników z podstawowymi danymi.
    """
    print("📋 Pobieram listę zawodników ze strony /stats...")
    players = []

    try:
        resp = session.get(f"{BASE_URL}/stats", timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Szukamy elementów z data-player-id
        player_elements = soup.select("[data-player-id]")
        for el in player_elements:
            player_id = el.get("data-player-id")
            player_price = el.get("data-player-price", "")
            player_pos = el.get("data-player-pos", "")
            name_el = el.select_one(".name")
            name = name_el.text.strip() if name_el else ""
            points_el = el.select_one(".points")
            points = points_el.text.strip() if points_el else ""

            players.append({
                "player_id": player_id,
                "name": name,
                "price": player_price,
                "position_id": player_pos,
                "total_points": points,
            })

        # Szukamy też linków do /player/{id}
        player_links = soup.select("a[href*='/player/']")
        existing_ids = {p["player_id"] for p in players}
        for link in player_links:
            href = link.get("href", "")
            match = re.search(r"/player/(\d+)", href)
            if match:
                pid = match.group(1)
                if pid not in existing_ids:
                    players.append({
                        "player_id": pid,
                        "name": link.text.strip(),
                        "price": "",
                        "position_id": "",
                        "total_points": "",
                    })
                    existing_ids.add(pid)

        print(f"   Znaleziono {len(players)} zawodników na stronie /stats")

    except Exception as e:
        print(f"   ⚠️  Błąd pobierania /stats: {e}")

    return players


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

        except Exception:
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

    return player


def fetch_player_detail(session: requests.Session, player_id: int) -> Optional[dict]:
    """
    Pobiera szczegóły zawodnika z endpointu /stats-player/{id}.
    """
    try:
        resp = session.get(
            f"{BASE_URL}/stats-player/{player_id}",
            timeout=15,
        )
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
    """Pobiera dane wszystkich zawodników."""
    players = []
    total = len(player_ids)

    print(f"\n📊 Pobieram szczegóły {total} zawodników...")
    for i, pid in enumerate(player_ids, 1):
        player = fetch_player_detail(session, pid)
        if player and player.get("name"):
            players.append(player)
            name = player.get("name", "?")
            team = player.get("team", "?")
            pts = player.get("total_points", "?")
            pop = player.get("popularity_pct", "?")
            print(f"   [{i}/{total}] ✅ {name} ({team}) - {pts} pkt, popularność: {pop}")
        else:
            if i % 100 == 0:
                print(f"   [{i}/{total}] ... skanowanie")

        time.sleep(REQUEST_DELAY)

    print(f"\n   ✅ Pobrano dane {len(players)} zawodników")
    return players


def filter_by_round(players: list[dict], round_num: int) -> list[dict]:
    """Filtruje statystyki do konkretnej kolejki."""
    filtered = []
    for p in players:
        round_stats = None
        for r in p.get("rounds", []):
            if r.get("round") == round_num:
                round_stats = r
                break

        filtered.append({
            "player_id": p.get("player_id"),
            "name": p.get("name", ""),
            "team": p.get("team", ""),
            "position": p.get("position", ""),
            "total_points": p.get("total_points", 0),
            "price": p.get("price", 0),
            "popularity_pct": p.get("popularity_pct", ""),
            "round": round_num,
            "round_played": round_stats.get("played", False) if round_stats else None,
            "round_opponent": round_stats.get("opponent", "") if round_stats else "",
            "round_minutes": round_stats.get("minutes", 0) if round_stats else 0,
            "round_goals": round_stats.get("goals", 0) if round_stats else 0,
            "round_assists": round_stats.get("assists", 0) if round_stats else 0,
            "round_yellow_cards": round_stats.get("yellow_cards", 0) if round_stats else 0,
            "round_red_cards": round_stats.get("red_cards", 0) if round_stats else 0,
            "round_points": round_stats.get("points", 0) if round_stats else 0,
        })

    return filtered


def save_to_csv(data: list[dict], filename: str):
    """Zapisuje dane do pliku CSV."""
    if not data:
        print("⚠️  Brak danych do zapisania.")
        return

    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

    # Zbierz wszystkie klucze
    keys = []
    for row in data:
        for k in row:
            if k not in keys and k != "rounds" and k != "price_history":
                keys.append(k)

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

    print(f"💾 Zapisano do: {filename}")


def save_full_json(players: list[dict], filename: str):
    """Zapisuje pełne dane (ze statystykami per kolejka) do JSON."""
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(players, f, ensure_ascii=False, indent=2)

    print(f"💾 Zapisano pełne dane JSON do: {filename}")


def save_rounds_csv(players: list[dict], filename: str):
    """Zapisuje statystyki per kolejka (każdy wiersz = zawodnik + kolejka)."""
    rows = []
    for p in players:
        # Zbuduj mapę cen per kolejka z price_history
        price_by_round = {}
        for ph in p.get("price_history", []):
            r_num = ph.get("round")
            r_price = ph.get("price")
            if r_num is not None and r_price is not None:
                price_by_round[r_num] = r_price

        for r in p.get("rounds", []):
            round_num = r.get("round", 0)
            current_price = price_by_round.get(round_num)
            prev_price = price_by_round.get(round_num - 1)

            if current_price is not None and prev_price is not None:
                price_change = round(current_price - prev_price, 2)
            else:
                price_change = ""

            rows.append({
                "player_id": p.get("player_id"),
                "name": p.get("name", ""),
                "team": p.get("team", ""),
                "position": p.get("position", ""),
                "popularity_pct": p.get("popularity_pct", ""),
                "price": current_price if current_price is not None else p.get("price", 0),
                "price_change": price_change,
                **r,
            })

    save_to_csv(rows, filename)


def print_round_summary(players: list[dict], round_num: int):
    """Wyświetla podsumowanie kolejki."""
    round_data = filter_by_round(players, round_num)

    # Sortuj po punktach w kolejce
    played = [p for p in round_data if p.get("round_played")]
    played.sort(key=lambda x: x.get("round_points", 0), reverse=True)

    print(f"\n{'='*70}")
    print(f"  📊 PODSUMOWANIE KOLEJKI {round_num}")
    print(f"{'='*70}")

    if not played:
        print(f"  Brak danych dla kolejki {round_num}")
        return

    # Top 10 punktujących
    print(f"\n  🏆 TOP 10 - Najlepsi w kolejce {round_num}:")
    print(f"  {'Zawodnik':<25} {'Drużyna':<15} {'Pkt':>4} {'Pop.':>6} {'Min':>4} {'Br':>3} {'As':>3}")
    print(f"  {'-'*65}")
    for p in played[:10]:
        print(f"  {p['name']:<25} {p['team']:<15} {p['round_points']:>4} "
              f"{p['popularity_pct']:>6} {p['round_minutes']:>4} "
              f"{p['round_goals']:>3} {p['round_assists']:>3}")

    # Top 10 najpopularniejszych
    by_pop = sorted(round_data, key=lambda x: _safe_float(x.get("popularity_pct", "0").replace("%", "")), reverse=True)
    print(f"\n  👥 TOP 10 - Najpopularniejsi zawodnicy:")
    print(f"  {'Zawodnik':<25} {'Drużyna':<15} {'Pop.':>6} {'Pkt kol.':>8} {'Pkt total':>9}")
    print(f"  {'-'*65}")
    for p in by_pop[:10]:
        print(f"  {p['name']:<25} {p['team']:<15} {p['popularity_pct']:>6} "
              f"{p['round_points']:>8} {p['total_points']:>9}")

    # Najdrożsi
    by_price = sorted(round_data, key=lambda x: x.get("price", 0) or 0, reverse=True)
    print(f"\n  💰 TOP 10 - Najdrożsi:")
    print(f"  {'Zawodnik':<25} {'Drużyna':<15} {'Cena':>6} {'Pop.':>6} {'Pkt total':>9}")
    print(f"  {'-'*65}")
    for p in by_price[:10]:
        price = p.get('price', 0) or 0
        print(f"  {p['name']:<25} {p['team']:<15} {price:>6.2f} "
              f"{p['popularity_pct']:>6} {p['total_points']:>9}")


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


# ============================================================
# METODA 2: Scraping strony /stats (HTML) - jako alternatywa
# ============================================================

def scrape_stats_page(session: requests.Session) -> list[dict]:
    """
    Scrapuje stronę /stats żeby uzyskać listę wszystkich zawodników
    z ich data-player-id.
    """
    print("📋 Scrapuję stronę ze statystykami...")
    all_players = []

    # Strona /stats może mieć paginację lub filtrowanie
    # Spróbujmy pobrać dla każdej pozycji (1=GK, 2=DEF, 3=MID, 4=FWD)
    for pos in [1, 2, 3, 4]:
        pos_names = {1: "Bramkarze", 2: "Obrońcy", 3: "Pomocnicy", 4: "Napastnicy"}
        print(f"   Pozycja: {pos_names.get(pos, pos)}...")

        try:
            resp = session.get(f"{BASE_URL}/stats", params={"pos": pos}, timeout=30)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                players = soup.select("[data-player-id]")
                for el in players:
                    pid = el.get("data-player-id")
                    if pid and pid not in [p.get("data_player_id") for p in all_players]:
                        all_players.append({
                            "data_player_id": pid,
                            "name": el.select_one(".name").text.strip() if el.select_one(".name") else "",
                            "price": el.get("data-player-price", ""),
                            "position_id": el.get("data-player-pos", ""),
                        })
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"   ⚠️  Błąd: {e}")

    print(f"   Znaleziono {len(all_players)} zawodników")
    return all_players


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
                headers={
                    **HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
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
            headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": f"{BASE_URL}/league/{league_slug}",
            },
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
                    "position": team.get("pos"),
                })

        print(f"   ✅ Pobrano {len(teams)} drużyn z ligi")

    except Exception as e:
        print(f"   ⚠️  Błąd POST ranking-list (league): {e}")

    return teams


def scrape_team_squad(session: requests.Session, slug: str, debug: bool = False) -> dict:
    """
    Scrapuje skład drużyny ze strony /user-team/view/{slug}.
    Dane są osadzone w HTML jako wywołania app.Pitch.$squad.push({...}).
    Thread-safe — nie modyfikuje session.headers, używa requests.get() bezpośrednio.
    """
    try:
        # Czyste headery przeglądarki — bez X-Requested-With
        browser_headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
            "Referer": f"{BASE_URL}/",
        }

        # Thread-safe: użyj requests.get() z cookies z sesji
        resp = requests.get(
            f"{BASE_URL}/user-team/view/{slug}",
            headers=browser_headers,
            cookies=dict(session.cookies),
            timeout=15,
        )

        if resp.status_code != 200:
            if debug:
                print(f"      ⚠️  HTTP {resp.status_code} dla {slug}")
            return {"slug": slug, "players": [], "captain_id": None}

        html = resp.text
        players = []
        captain_id = None

        # Szukamy wzorca: $squad.push({ ... }); — startowi (11)
        pattern = r'squad\.push\(\{(.*?)\}\);'
        matches = re.findall(pattern, html, re.DOTALL)

        # Szukamy wzorca: $bench.push({ ... }); — ławka (4)
        bench_pattern = r'bench\.push\(\{(.*?)\}\);'
        bench_matches = re.findall(bench_pattern, html, re.DOTALL)

        if debug:
            print(f"      DEBUG {slug}: squad.push={len(matches)}, bench.push={len(bench_matches)}")
            # Pokaż WSZYSTKIE .push() wzorce w HTML
            all_pushes = re.findall(r'(\$?\w+(?:\.\$?\w+)*)\.push\(\{', html)
            print(f"      DEBUG wszystkie .push(): {all_pushes}")
            # Szukaj "bench" w jakimkolwiek kontekście
            bench_refs = [(m.start(), html[max(0,m.start()-30):m.start()+80]) for m in re.finditer(r'bench', html, re.IGNORECASE)]
            if bench_refs:
                for pos, ctx in bench_refs[:5]:
                    print(f"      DEBUG bench @{pos}: {ctx}")
            else:
                print(f"      DEBUG 'bench' NIE ZNALEZIONE w HTML")
            # Szukaj "reserve" / "rezerw" / "substitute" / "sub"
            for keyword in ["reserv", "rezerw", "substitut", "ławk", "lawka"]:
                refs = [(m.start(), html[max(0,m.start()-40):m.start()+80]) for m in re.finditer(keyword, html, re.IGNORECASE)]
                if refs:
                    for pos, ctx in refs[:3]:
                        print(f"      DEBUG '{keyword}' @{pos}: {ctx}")
            # Pokaż cały blok JS wokół squad.push (szukamy skryptu)
            sq_idx = html.find("squad.push")
            if sq_idx >= 0:
                # Znajdź koniec sekcji z push (następne 3000 znaków po ostatnim push)
                last_push_idx = html.rfind(".push(", 0, sq_idx + 5000)
                js_block = html[max(0, sq_idx - 100):min(len(html), last_push_idx + 500)]
                print(f"      DEBUG JS block ({len(js_block)} chars): ...{js_block[-800:]}...")
            # Zapisz pełny HTML pierwszej drużyny do pliku
            try:
                html_dump = os.path.join(OUTPUT_DIR, f"debug_team_{slug}.html")
                with open(html_dump, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"      DEBUG HTML zapisany do: {html_dump}")
            except Exception:
                pass
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
        for match in bench_matches:
            p, is_cap, pid = _parse_player(match, is_reserve=True)
            if is_cap and pid:
                captain_id = pid
            players.append(p)

        # Fallback: jeśli nie było bench.push, ale jest >11 graczy, użyj indeksu
        if not bench_matches and len(players) > 11:
            for i, p in enumerate(players):
                if i >= 11:
                    p["is_reserve"] = True

        if debug and players:
            cap_name = next((p["name"] for p in players if p["is_captain"]), "brak")
            reserves = sum(1 for p in players if p["is_reserve"])
            print(f"      DEBUG kapitan: {cap_name}, graczy: {len(players)}, "
                  f"rezerwa: {reserves}, bench.push: {len(bench_matches)}")

        return {
            "slug": slug,
            "players": players,
            "captain_id": captain_id,
        }

    except Exception as e:
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
                except Exception:
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
            except Exception:
                pass

        if timed_out:
            break

    # Finalny checkpoint
    if checkpoint_file:
        try:
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False)
        except Exception:
            pass

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


# ============================================================
# DASHBOARD HTML
# ============================================================

def generate_dashboard_html(
    summary_data: list[dict],
    tiers: dict,
    teams_count: int,
    league_captain_stats: list[dict],
    league_ownership_stats: list[dict],
    league_name: str,
    league_teams_count: int,
    league_rosters: dict,
    league_teams_detail: list[dict],
    timestamp: str,
    filename: str,
):
    """Generuje interaktywny dashboard HTML z danymi Fantasy Ekstraklasa."""

    # Build DATA object for JS: { scope_key: { captains, ownership, label, count } }
    scopes_data = {}
    scope_buttons = []

    # Tier scopes (top10, top100, all)
    for key in ["top10", "top100", "all"]:
        tier = tiers.get(key)
        if not tier:
            continue
        count = tier["count"]
        label = f"Top {count}" if key != "all" else f"Wszystkie ({count})"
        scopes_data[key] = {
            "captains": tier["captains"][:50],
            "ownership": tier["ownership"],
            "label": label,
            "count": count,
        }
        emoji = "🏆" if key == "top10" else "🥈" if key == "top100" else "📊"
        scope_buttons.append((key, f"{emoji} Top {count}" if key != "all" else f"{emoji} Wszystkie ({count})"))

    # League scope
    has_league = league_teams_count > 0
    league_label = league_name.replace("-", " ").title() if league_name else ""
    if has_league:
        scopes_data["league"] = {
            "captains": league_captain_stats[:50],
            "ownership": league_ownership_stats,
            "label": league_label,
            "count": league_teams_count,
        }
        scope_buttons.append(("league", f"🏅 {league_label}"))

    data_json = json.dumps(scopes_data, ensure_ascii=False)
    players_json = json.dumps(summary_data, ensure_ascii=False)
    rosters_json = json.dumps(league_rosters, ensure_ascii=False)
    teams_detail_json = json.dumps(league_teams_detail, ensure_ascii=False)

    # For stat cards
    all_tier = tiers.get("all", tiers.get("top100", tiers.get("top10", {})))
    all_caps = all_tier.get("captains", []) if all_tier else []
    all_owns = all_tier.get("ownership", []) if all_tier else []
    top_captain = all_caps[0] if all_caps else {}
    top_owned = all_owns[0] if all_owns else {}
    best_ppp = max(summary_data, key=lambda x: x.get("points_per_price", 0)) if summary_data else {}

    # Default scope
    default_scope = "top10" if "top10" in scopes_data else ("top100" if "top100" in scopes_data else "league")

    # Build scope toggle HTML
    scope_toggle_html = ""
    if len(scope_buttons) > 1:
        btns = ""
        for key, label in scope_buttons:
            btns += f"<button class='scope-btn' data-scope='{key}'>{label}</button>"
        scope_toggle_html = f"<div class='scope-toggle'>{btns}</div>"

    html = f'''<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fantasy Ekstraklasa Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  min-height: 100vh;
  background: linear-gradient(180deg, #0b1120 0%, #0f172a 100%);
  color: #e2e8f0;
  font-family: 'DM Sans', -apple-system, sans-serif;
  padding: 24px 16px;
}}
.container {{ max-width: 1060px; margin: 0 auto; }}
.header {{ display: flex; align-items: center; gap: 14px; margin-bottom: 6px; }}
.logo {{
  width: 40px; height: 40px; border-radius: 10px;
  background: linear-gradient(135deg, #006847, #d92231);
  display: flex; align-items: center; justify-content: center; font-size: 20px;
}}
.header h1 {{ font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }}
.header .sub {{ font-size: 12px; color: #64748b; margin: 0; }}
.stats-row {{ display: flex; gap: 12px; margin-top: 16px; overflow-x: auto; padding-bottom: 4px; flex-wrap: wrap; }}
.stat-card {{
  background: #1e293b; border-radius: 10px; padding: 16px 20px;
  min-width: 140px; flex-shrink: 0;
}}
.stat-card .val {{ font-size: 24px; font-weight: 800; }}
.stat-card .label {{ font-size: 11px; color: #94a3b8; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.8px; }}
.stat-card .sub {{ font-size: 11px; color: #64748b; margin-top: 4px; }}
.accent-cyan {{ border-left: 3px solid #22d3ee; }}
.accent-cyan .val {{ color: #22d3ee; }}
.accent-gold {{ border-left: 3px solid #fbbf24; }}
.accent-gold .val {{ color: #fbbf24; }}
.accent-green {{ border-left: 3px solid #10b981; }}
.accent-green .val {{ color: #10b981; }}
.accent-purple {{ border-left: 3px solid #a78bfa; }}
.accent-purple .val {{ color: #a78bfa; }}
.tabs {{ display: flex; gap: 4px; border-bottom: 1px solid #1e293b; flex-wrap: wrap; }}
.tab {{
  background: transparent; border: none; border-bottom: 2px solid transparent;
  color: #64748b; padding: 10px 18px; font-size: 13px; font-weight: 600;
  cursor: pointer; border-radius: 8px 8px 0 0; transition: all 0.2s;
  font-family: inherit;
}}
.tab.active {{ background: #1e293b; border-bottom-color: #22d3ee; color: #e2e8f0; }}
.tab:hover {{ color: #e2e8f0; }}
.filters-row {{ display: flex; gap: 8px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
.pos-filters {{ display: flex; gap: 4px; align-items: center; }}
.pos-btn {{
  background: transparent; border: 1px solid #334155; color: #64748b;
  padding: 4px 10px; font-size: 11px; font-weight: 700; cursor: pointer;
  border-radius: 6px; font-family: inherit; transition: all 0.15s;
}}
.pos-btn.active {{ border-color: transparent; color: #0f172a; }}
.pos-btn.active[data-pos="ALL"] {{ background: #22d3ee; }}
.pos-btn.active[data-pos="BR"] {{ background: #f59e0b; }}
.pos-btn.active[data-pos="OBR"] {{ background: #3b82f6; }}
.pos-btn.active[data-pos="POM"] {{ background: #10b981; }}
.pos-btn.active[data-pos="NAP"] {{ background: #ef4444; }}
.scope-toggle {{ display: flex; gap: 0; border-radius: 8px; overflow: hidden; border: 1px solid #334155; }}
.scope-btn {{
  background: transparent; border: none; color: #64748b;
  padding: 6px 14px; font-size: 12px; font-weight: 600; cursor: pointer;
  font-family: inherit; transition: all 0.15s;
}}
.scope-btn.active {{ background: #22d3ee; color: #0f172a; }}
.section-title {{ display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }}
.section-title h2 {{ font-size: 16px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: #e2e8f0; }}
.section-title .line {{ flex: 1; height: 1px; background: linear-gradient(90deg, #334155, transparent); }}
.data-table {{ background: #1e293b; border-radius: 12px; overflow: hidden; width: 100%; overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
thead tr {{ background: #0f172a; }}
th {{
  padding: 10px 14px; color: #64748b; font-weight: 600; font-size: 11px;
  text-transform: uppercase; white-space: nowrap;
}}
th.sortable {{ cursor: pointer; user-select: none; }}
th.sortable:hover {{ color: #94a3b8; }}
td {{ padding: 10px 14px; border-top: 1px solid #0f172a; white-space: nowrap; }}
tr.highlight {{ background: rgba(251,191,36,0.06); }}
.pos-badge {{
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 700; letter-spacing: 0.5px; color: #0f172a;
}}
.pos-BR, .pos-1 {{ background: #f59e0b; }}
.pos-OBR, .pos-2 {{ background: #3b82f6; }}
.pos-POM, .pos-3 {{ background: #10b981; }}
.pos-NAP, .pos-4 {{ background: #ef4444; }}
.captain-badge {{
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%;
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
  color: #0f172a; font-size: 11px; font-weight: 800;
}}
.bar-wrap {{ display: flex; align-items: center; gap: 8px; }}
.bar-bg {{ width: 80px; height: 6px; background: #0f172a; border-radius: 3px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.6s ease; }}
.bar-val {{ font-size: 13px; color: #94a3b8; min-width: 38px; text-align: right; }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.footer {{ text-align: center; margin-top: 32px; color: #334155; font-size: 12px; }}
.text-right {{ text-align: right; }}
.text-center {{ text-align: center; }}
.text-left {{ text-align: left; }}
.fw-700 {{ font-weight: 700; }}
.fw-600 {{ font-weight: 600; }}
.c-muted {{ color: #94a3b8; }}
.c-dim {{ color: #64748b; }}
.empty-msg {{ padding: 40px; text-align: center; color: #64748b; }}
.clickable {{ cursor: pointer; }}
.clickable:hover {{ color: #22d3ee; }}
.roster-row td {{ padding: 0 !important; border-top: none !important; }}
.roster-panel {{
  background: #162032; padding: 10px 16px 10px 48px;
  border-left: 3px solid #22d3ee; margin: 0;
  display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center;
  font-size: 12px;
}}
.roster-panel .rp-label {{ color: #64748b; font-weight: 600; text-transform: uppercase; font-size: 10px; letter-spacing: 0.5px; margin-right: 4px; }}
.roster-chip {{
  display: inline-flex; align-items: center; gap: 4px;
  background: #1e293b; border: 1px solid #334155; border-radius: 6px;
  padding: 3px 10px; font-size: 12px; color: #e2e8f0;
}}
.roster-chip .rc-badge {{
  font-size: 9px; font-weight: 800; border-radius: 3px; padding: 1px 4px;
}}
.rc-cap {{ background: #fbbf24; color: #0f172a; }}
.rc-res {{ background: #475569; color: #e2e8f0; }}
.rc-xi {{ background: #22d3ee; color: #0f172a; }}
.form-chart {{
  display: inline-flex; align-items: flex-end; gap: 2px; height: 28px; vertical-align: middle;
}}
.form-bar {{
  width: 8px; border-radius: 2px 2px 0 0; min-height: 2px; position: relative;
  display: inline-flex; align-items: flex-start; justify-content: center;
}}
.form-bar .form-val {{
  position: absolute; top: -14px; font-size: 8px; color: #94a3b8; white-space: nowrap;
}}
.team-select {{
  background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px;
  padding: 8px 14px; font-size: 14px; font-family: inherit; cursor: pointer;
  min-width: 280px; margin-bottom: 16px;
}}
.team-select:focus {{ outline: none; border-color: #22d3ee; }}
.diff-badge {{
  display: inline-block; font-size: 12px; font-weight: 700; border-radius: 4px;
  padding: 2px 8px; min-width: 48px; text-align: center;
}}
.diff-pos {{ background: rgba(16,185,129,0.15); color: #10b981; }}
.diff-neg {{ background: rgba(239,68,68,0.15); color: #ef4444; }}
.diff-zero {{ background: rgba(100,116,139,0.15); color: #94a3b8; }}
.team-header {{
  display: flex; align-items: center; gap: 16px; margin-bottom: 16px; flex-wrap: wrap;
}}
.team-stat {{ font-size: 13px; color: #94a3b8; }}
.team-stat b {{ color: #e2e8f0; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="logo">⚽</div>
    <div>
      <h1>Fantasy Ekstraklasa</h1>
      <p class="sub">Dashboard · {timestamp}</p>
    </div>
  </div>
  <div class="stats-row">
    <div class="stat-card accent-cyan">
      <div class="val">{teams_count}</div>
      <div class="label">Top drużyn</div>
    </div>
    <div class="stat-card accent-gold">
      <div class="val">{top_captain.get('name', '—')}</div>
      <div class="label">Top kapitan</div>
      <div class="sub">{top_captain.get('captain_pct', '—')} drużyn</div>
    </div>
    <div class="stat-card accent-green">
      <div class="val">{top_owned.get('squad_pct', '—')}</div>
      <div class="label">Top owned</div>
      <div class="sub">{top_owned.get('name', '—')}</div>
    </div>
    <div class="stat-card accent-purple">
      <div class="val">{best_ppp.get('points_per_price', 0):.1f}</div>
      <div class="label">Najlepszy PPP</div>
      <div class="sub">{best_ppp.get('name', '—')} · {best_ppp.get('price', 0):.1f}M</div>
    </div>
    {"<div class='stat-card accent-cyan'><div class='val'>" + str(league_teams_count) + "</div><div class='label'>Liga</div><div class='sub'>" + league_label + "</div></div>" if has_league else ""}
  </div>

  <div style="margin-top: 24px;">
    <div class="tabs">
      <button class="tab active" data-tab="captains">👑 Kapitanowie</button>
      <button class="tab" data-tab="players">⚽ Zawodnicy</button>
      {"<button class='tab' data-tab='teams'>📋 Drużyny ligi</button>" if has_league else ""}
    </div>
    <div class="filters-row" style="margin-top: 12px;">
      {scope_toggle_html}
      <div class="pos-filters" style="margin-left:auto;">
        <button class="pos-btn active" data-pos="ALL">ALL</button>
        <button class="pos-btn" data-pos="BR">GK</button>
        <button class="pos-btn" data-pos="OBR">DEF</button>
        <button class="pos-btn" data-pos="POM">MID</button>
        <button class="pos-btn" data-pos="NAP">FWD</button>
      </div>
    </div>
    <div id="tab-captains" class="tab-content active"></div>
    <div id="tab-players" class="tab-content"></div>
    <div id="tab-teams" class="tab-content"></div>
  </div>
  <div class="footer">Fantasy Ekstraklasa Dashboard · {timestamp}</div>
</div>

<script>
const DATA = {data_json};
const PLAYERS = {players_json};
const ROSTERS = {rosters_json};
const LEAGUE_TEAMS = {teams_detail_json};

const POS_MAP = {{BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD','1':'GK','2':'DEF','3':'MID','4':'FWD'}};
const POS_ID = {{'1':'BR','2':'OBR','3':'POM','4':'NAP',BR:'BR',OBR:'OBR',POM:'POM',NAP:'NAP',
  Bramkarz:'BR','Obrońca':'OBR',Pomocnik:'POM',Napastnik:'NAP'}};

let tab = 'captains', pos = 'ALL', scope = '{default_scope}';
let selectedTeam = '';
let sorts = {{
  captains: {{col:'captain_count', dir:'desc'}},
  players: {{col:'total_points', dir:'desc'}},
}};

function num(v) {{ return typeof v === 'string' ? parseFloat(v) || 0 : v || 0; }}
function bar(val, max, color) {{
  const w = Math.min(val / max * 100, 100);
  return '<div class="bar-wrap"><div class="bar-bg"><div class="bar-fill" style="width:'+w+'%;background:'+color+'"></div></div><span class="bar-val">'+val.toFixed(1)+'%</span></div>';
}}
function posBadge(p) {{
  const k = POS_ID[p] || p;
  return '<span class="pos-badge pos-'+k+'">'+(POS_MAP[k]||POS_MAP[p]||p)+'</span>';
}}
function arrow(tab, col) {{
  const s = sorts[tab];
  return s.col === col ? (s.dir === 'desc' ? ' ▼' : ' ▲') : '';
}}
function filterPos(data) {{
  if (pos === 'ALL') return data;
  return data.filter(p => {{
    const pk = POS_ID[p.position] || POS_ID[p.position_id] || p.position;
    return pk === pos;
  }});
}}
function sortData(data, tab) {{
  const s = sorts[tab];
  return [...data].sort((a, b) => {{
    let av = a[s.col], bv = b[s.col];
    if (s.col === 'position' || s.col === 'position_id') {{
      const order = {{BR:1,OBR:2,POM:3,NAP:4,'1':1,'2':2,'3':3,'4':4,Bramkarz:1,'Obrońca':2,Pomocnik:3,Napastnik:4}};
      av = order[av] || 5; bv = order[bv] || 5;
    }} else if (s.col === 'name' || s.col === 'team') {{
      av = (av || '').toLowerCase(); bv = (bv || '').toLowerCase();
      if (av < bv) return s.dir === 'desc' ? 1 : -1;
      if (av > bv) return s.dir === 'desc' ? -1 : 1;
      return 0;
    }} else {{
      av = num(av); bv = num(bv);
    }}
    return s.dir === 'desc' ? bv - av : av - bv;
  }});
}}

// Roster detail — kliknięcie na zawodnika pokazuje drużyny z ligi
function nameCell(name, style, prefix) {{
  const r = ROSTERS[name];
  const hasRoster = r && r.length > 0;
  const cls = hasRoster ? 'clickable roster-trigger' : '';
  const icon = hasRoster ? ' <span style="font-size:10px;color:#64748b">▸</span>' : '';
  // Użyj data-name z base64 żeby uniknąć problemów z cudzysłowami
  const attr = hasRoster ? ' data-pname="'+btoa(unescape(encodeURIComponent(name)))+'"' : '';
  return '<td class="'+cls+'"'+attr+' style="'+(style||'')+'">'+( prefix||'')+name+icon+'</td>';
}}
function rosterRow(name, colspan) {{
  const r = ROSTERS[name];
  if (!r || !r.length) return '';
  // Sortuj po pozycji w lidze
  const sorted = [...r].sort((a,b) => (a.pos||999) - (b.pos||999));
  let chips = '';
  sorted.forEach(t => {{
    let badge = '';
    if (t.C) badge = '<span class="rc-badge rc-cap">C</span>';
    else if (t.R) badge = '<span class="rc-badge rc-res">RES</span>';
    else badge = '<span class="rc-badge rc-xi">XI</span>';
    const slug = t.team.replace(/-/g,' ');
    const posLabel = t.pos ? '<span style="color:#64748b;font-size:10px;margin-right:2px">#'+t.pos+'</span>' : '';
    chips += '<span class="roster-chip">'+posLabel+slug+' '+badge+'</span>';
  }});
  return '<tr class="roster-row"><td colspan="'+colspan+'"><div class="roster-panel"><span class="rp-label">Liga ('+r.length+'):</span>'+chips+'</div></td></tr>';
}}
function attachRosterClicks() {{
  document.querySelectorAll('.roster-trigger').forEach(td => {{
    td.onclick = function() {{
      const encoded = this.dataset.pname;
      const name = decodeURIComponent(escape(atob(encoded)));
      const row = this.closest('tr');
      const next = row.nextElementSibling;
      // Toggle — zamknij jeśli już otwarty
      if (next && next.classList.contains('roster-row')) {{
        next.remove();
        return;
      }}
      // Zamknij inne otwarte
      document.querySelectorAll('.roster-row').forEach(r => r.remove());
      const cols = row.querySelectorAll('td').length;
      row.insertAdjacentHTML('afterend', rosterRow(name, cols));
    }};
  }});
}}

function formChart(form) {{
  if (!form || !form.length) return '<span class="c-dim" style="font-size:11px">—</span>';
  const maxPts = Math.max(...form.map(f => Math.abs(f.pts)), 1);
  let h = '<div class="form-chart" title="Ostatnie '+form.length+' kolejek">';
  form.forEach(f => {{
    const pts = f.pts || 0;
    const ht = Math.max(Math.abs(pts) / maxPts * 24, 2);
    const c = pts >= 8 ? '#22d3ee' : pts >= 4 ? '#10b981' : pts >= 0 ? '#64748b' : '#ef4444';
    h += '<div class="form-bar" style="height:'+ht+'px;background:'+c+'"><span class="form-val">'+pts+'</span></div>';
  }});
  h += '</div>';
  return h;
}}

function renderCaptains() {{
  if (!DATA[scope]) return '<div class="empty-msg">Brak danych dla tego zakresu</div>';
  let data = DATA[scope].captains;
  data = sortData(data, 'captains');
  if (!data.length) return '<div class="empty-msg">Brak danych o kapitanach</div>';
  const maxPct = Math.max(...data.map(c => c.captain_count));
  let h = '<div class="section-title"><span style="font-size:22px">👑</span><h2>Popularność kapitanów — '+(DATA[scope].label||scope)+'</h2><div class="line"></div></div>';
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-left sortable" data-tab="captains" data-col="index">#'+arrow('captains','index')+'</th>';
  h += '<th class="text-left sortable" data-tab="captains" data-col="name">Zawodnik'+arrow('captains','name')+'</th>';
  h += '<th class="text-right sortable" data-tab="captains" data-col="captain_count">Wyborów'+arrow('captains','captain_count')+'</th>';
  h += '<th class="text-left" style="min-width:160px">Popularność</th>';
  h += '</tr></thead><tbody>';
  data.forEach((c, i) => {{
    const hl = i === 0 ? ' class="highlight"' : '';
    const ns = i === 0 ? 'color:#fbbf24;font-weight:700' : i < 3 ? 'font-weight:700' : 'font-weight:500';
    const badge = i === 0 ? '<span class="captain-badge">C</span> ' : '';
    const bc = i === 0 ? '#fbbf24' : '#22d3ee';
    h += '<tr'+hl+'><td class="c-muted fw-600">'+(i+1)+'</td>'+nameCell(c.name, ns, badge);
    h += '<td class="text-right fw-700">'+c.captain_count+'</td>';
    h += '<td>'+bar(parseFloat(c.captain_pct), maxPct*1.2, bc)+'</td></tr>';
  }});
  h += '</tbody></table></div>';
  return h;
}}

function renderPlayers() {{
  let data = [...PLAYERS];
  if (pos !== 'ALL') data = data.filter(p => (POS_ID[p.position] || p.position) === pos);
  if (!data.length) return '<div class="empty-msg">Brak danych</div>';

  // Buduj lookup ownership z aktualnego scope — dopasowanie po player_id
  const scopeData = DATA[scope] || {{}};
  const ownData = scopeData.ownership || [];
  const ownMap = {{}};
  ownData.forEach(o => {{ ownMap[o.player_id] = o; }});
  const hasOwn = ownData.length > 0;
  const hasLeague = LEAGUE_TEAMS.length > 0 && Object.keys(LEAGUE_POS_AVGS).length > 0;
  const scopeLabel = scopeData.label || scope;

  let h = '<div class="section-title"><span style="font-size:22px">⚽</span><h2>Zawodnicy'+(hasOwn ? ' — ownership: '+scopeLabel : '')+'</h2><div class="line"></div></div>';
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-left">#</th>';
  h += '<th class="text-left sortable" data-tab="players" data-col="name">Zawodnik'+arrow('players','name')+'</th>';
  h += '<th class="text-left sortable" data-tab="players" data-col="team">Drużyna'+arrow('players','team')+'</th>';
  h += '<th class="text-center sortable" data-tab="players" data-col="position">Poz'+arrow('players','position')+'</th>';
  h += '<th class="text-right sortable" data-tab="players" data-col="price">Cena'+arrow('players','price')+'</th>';
  h += '<th class="text-right sortable" data-tab="players" data-col="total_points">Punkty'+arrow('players','total_points')+'</th>';
  h += '<th class="text-center sortable" data-tab="players" data-col="_diff_global" title="Różnica vs średnia pozycji (wszyscy grający)">±Avg'+arrow('players','_diff_global')+'</th>';
  if (hasLeague) {{
    h += '<th class="text-center sortable" data-tab="players" data-col="_diff_league" title="Różnica vs średnia pozycji (gracze w lidze)">±Liga'+arrow('players','_diff_league')+'</th>';
  }}
  h += '<th class="text-right sortable" data-tab="players" data-col="points_per_price">Pkt/Cena'+arrow('players','points_per_price')+'</th>';
  h += '<th class="text-center sortable" data-tab="players" data-col="_form_avg" style="min-width:80px">Forma'+arrow('players','_form_avg')+'</th>';
  h += '<th class="text-right sortable" data-tab="players" data-col="popularity_pct">Pop.'+arrow('players','popularity_pct')+'</th>';
  if (hasOwn) {{
    h += '<th class="text-right sortable" data-tab="players" data-col="_own_squad" style="min-width:100px">W składzie'+arrow('players','_own_squad')+'</th>';
    h += '<th class="text-right sortable" data-tab="players" data-col="_own_starting" style="min-width:100px">Start XI'+arrow('players','_own_starting')+'</th>';
    h += '<th class="text-right sortable" data-tab="players" data-col="_own_captain" style="min-width:100px">Kapitan'+arrow('players','_own_captain')+'</th>';
  }}
  h += '</tr></thead><tbody>';

  // Dodaj dane ownership, formę i diff do sortowania
  data.forEach(p => {{
    const o = ownMap[p.player_id];
    p._own_squad = o ? num(o.squad_pct) : 0;
    p._own_starting = o ? num(o.starting_pct) : 0;
    p._own_captain = o ? num(o.captain_pct) : 0;
    const f = p.form || [];
    p._form_avg = f.length ? f.reduce((s,x) => s + (x.pts||0), 0) / f.length : 0;
    const pk = POS_ID[p.position] || p.position || '';
    const pts = p.total_points || 0;
    p._diff_global = (POS_AVGS[pk] && pts > 0) ? pts - POS_AVGS[pk] : 0;
    p._diff_league = (LEAGUE_POS_AVGS[pk] && pts > 0) ? pts - LEAGUE_POS_AVGS[pk] : 0;
  }});
  data = sortData(data, 'players');

  data.forEach((p, i) => {{
    const pts = p.total_points || 0, price = p.price || 0, ppp = p.points_per_price || 0;
    const ptsC = pts >= 35 ? '#22d3ee' : pts >= 25 ? '#e2e8f0' : '#94a3b8';
    const pppC = ppp >= 15 ? '#10b981' : ppp >= 10 ? '#e2e8f0' : '#94a3b8';
    const pk = POS_ID[p.position] || p.position || '';
    h += '<tr><td class="c-muted fw-600">'+(i+1)+'</td>';
    h += nameCell(p.name, 'font-weight:600');
    h += '<td class="c-muted" style="font-size:13px">'+p.team+'</td>';
    h += '<td class="text-center">'+posBadge(pk)+'</td>';
    h += '<td class="text-right c-muted">'+price.toFixed(1)+'M</td>';
    h += '<td class="text-right fw-700" style="color:'+ptsC+'">'+pts+'</td>';
    h += '<td class="text-center">'+diffBadge(pts, POS_AVGS[pk])+'</td>';
    if (hasLeague) {{
      h += '<td class="text-center">'+diffBadge(pts, LEAGUE_POS_AVGS[pk])+'</td>';
    }}
    h += '<td class="text-right fw-600" style="color:'+pppC+'">'+ppp.toFixed(1)+'</td>';
    h += '<td class="text-center">'+formChart(p.form)+'</td>';
    h += '<td class="text-right c-dim" style="font-size:13px">'+p.popularity_pct+'</td>';
    if (hasOwn) {{
      const sq = p._own_squad, st = p._own_starting, cp = p._own_captain;
      h += '<td>'+(sq > 0 ? bar(sq, 100, '#10b981') : '<span class="c-dim" style="font-size:12px">—</span>')+'</td>';
      h += '<td>'+(st > 0 ? bar(st, 100, '#3b82f6') : '<span class="c-dim" style="font-size:12px">—</span>')+'</td>';
      h += '<td>'+(cp > 0 ? bar(cp, 40, '#fbbf24') : '<span class="c-dim" style="font-size:12px">—</span>')+'</td>';
    }}
    h += '</tr>';
  }});
  h += '</tbody></table></div>';
  return h;
}}

// Oblicz średnie punkty per pozycja — globalne (wykluczając <=0)
const POS_AVGS = {{}};
(function() {{
  const sums = {{}}, counts = {{}};
  PLAYERS.forEach(p => {{
    const pk = POS_ID[p.position] || p.position || '';
    const pts = p.total_points || 0;
    if (pts > 0 && pk) {{
      sums[pk] = (sums[pk] || 0) + pts;
      counts[pk] = (counts[pk] || 0) + 1;
    }}
  }});
  for (const k in sums) POS_AVGS[k] = sums[k] / counts[k];
}})();

// Oblicz średnie punkty per pozycja — liga (z drużyn ligowych, wykluczając <=0)
const LEAGUE_POS_AVGS = {{}};
(function() {{
  const seen = {{}}, sums = {{}}, counts = {{}};
  LEAGUE_TEAMS.forEach(t => {{
    t.players.forEach(p => {{
      const pid = p.pid;
      if (seen[pid]) return;
      seen[pid] = true;
      const pk = POS_ID[p.pos] || p.pos || '';
      const pts = p.pts || 0;
      if (pts > 0 && pk) {{
        sums[pk] = (sums[pk] || 0) + pts;
        counts[pk] = (counts[pk] || 0) + 1;
      }}
    }});
  }});
  for (const k in sums) LEAGUE_POS_AVGS[k] = sums[k] / counts[k];
}})();

function diffBadge(pts, avg) {{
  if (!avg) return '<span class="diff-badge diff-zero">—</span>';
  const d = pts - avg;
  const cls = d > 0 ? 'diff-pos' : d < 0 ? 'diff-neg' : 'diff-zero';
  return '<span class="diff-badge '+cls+'">'+(d>0?'+':'')+d.toFixed(0)+'</span>';
}}

function renderTeams() {{
  if (!LEAGUE_TEAMS.length) return '<div class="empty-msg">Brak danych o drużynach ligi</div>';

  let h = '<div class="section-title"><span style="font-size:22px">📋</span><h2>Drużyny ligi</h2><div class="line"></div></div>';

  // Dropdown
  h += '<select class="team-select" id="teamSelect">';
  h += '<option value="">— Wybierz drużynę —</option>';
  LEAGUE_TEAMS.forEach(t => {{
    const sel = t.slug === selectedTeam ? ' selected' : '';
    h += '<option value="'+t.slug+'"'+sel+'>#'+t.rank+' '+t.slug.replace(/-/g,' ')+' ('+t.pts+' pkt)</option>';
  }});
  h += '</select>';

  const team = LEAGUE_TEAMS.find(t => t.slug === selectedTeam);
  if (!team) return h + '<div class="empty-msg" style="padding:20px;color:#64748b">Wybierz drużynę z listy powyżej</div>';

  // Team header
  h += '<div class="team-header">';
  h += '<div class="team-stat">Pozycja: <b>#'+team.rank+'</b></div>';
  h += '<div class="team-stat">Punkty: <b>'+team.pts+'</b></div>';
  h += '<div class="team-stat">Zawodników: <b>'+team.players.length+'</b></div>';
  h += '</div>';

  // Tabela zawodników
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-left">#</th>';
  h += '<th class="text-left">Zawodnik</th>';
  h += '<th class="text-center">Poz</th>';
  h += '<th class="text-right">Cena</th>';
  h += '<th class="text-right">Punkty</th>';
  h += '<th class="text-center">±Avg</th>';
  h += '<th class="text-center">±Liga</th>';
  h += '<th class="text-center" style="min-width:80px">Forma</th>';
  h += '<th class="text-center">Rola</th>';
  h += '</tr></thead><tbody>';

  // Startowi, potem rezerwowi
  const starters = team.players.filter(p => !p.R);
  const reserves = team.players.filter(p => p.R);

  function renderRow(p, idx) {{
    const pk = POS_ID[p.pos] || p.pos || '';
    const pts = p.pts || 0;
    const price = p.price || 0;
    let role = '';
    if (p.C) role = '<span class="rc-badge rc-cap" style="font-size:11px;padding:2px 6px">C</span>';
    else if (p.R) role = '<span class="rc-badge rc-res" style="font-size:11px;padding:2px 6px">RES</span>';
    else role = '<span class="rc-badge rc-xi" style="font-size:11px;padding:2px 6px">XI</span>';

    h += '<tr><td class="c-muted fw-600">'+(idx+1)+'</td>';
    h += nameCell(p.name, 'font-weight:600');
    h += '<td class="text-center">'+posBadge(pk)+'</td>';
    h += '<td class="text-right c-muted">'+price.toFixed(1)+'M</td>';
    h += '<td class="text-right fw-700">'+pts+'</td>';
    h += '<td class="text-center">'+diffBadge(pts, POS_AVGS[pk])+'</td>';
    h += '<td class="text-center">'+diffBadge(pts, LEAGUE_POS_AVGS[pk])+'</td>';
    h += '<td class="text-center">'+formChart(p.form)+'</td>';
    h += '<td class="text-center">'+role+'</td>';
    h += '</tr>';
  }}

  starters.forEach((p, i) => renderRow(p, i));
  if (reserves.length) {{
    h += '<tr><td colspan="9" style="padding:6px 0;border-top:1px dashed #334155"><span class="c-dim" style="font-size:11px;text-transform:uppercase;letter-spacing:1px">Ławka rezerwowych</span></td></tr>';
    reserves.forEach((p, i) => renderRow(p, starters.length + i));
  }}

  // Podsumowanie
  const totalPts = team.players.filter(p => !p.R).reduce((s,p) => s + (p.pts||0), 0);
  const totalDiffG = team.players.reduce((s,p) => {{
    const pk = POS_ID[p.pos] || p.pos || '';
    return s + ((p.pts||0) - (POS_AVGS[pk] || 0));
  }}, 0);
  const totalDiffL = team.players.reduce((s,p) => {{
    const pk = POS_ID[p.pos] || p.pos || '';
    return s + ((p.pts||0) - (LEAGUE_POS_AVGS[pk] || 0));
  }}, 0);
  h += '<tr style="border-top:2px solid #334155"><td colspan="4" class="fw-700" style="text-align:right;padding-top:10px">Razem (startowi):</td>';
  h += '<td class="text-right fw-700" style="padding-top:10px">'+totalPts+'</td>';
  const gCls = totalDiffG > 0 ? 'diff-pos' : totalDiffG < 0 ? 'diff-neg' : 'diff-zero';
  const lCls = totalDiffL > 0 ? 'diff-pos' : totalDiffL < 0 ? 'diff-neg' : 'diff-zero';
  h += '<td class="text-center" style="padding-top:10px"><span class="diff-badge '+gCls+'">'+(totalDiffG>0?'+':'')+totalDiffG.toFixed(0)+'</span></td>';
  h += '<td class="text-center" style="padding-top:10px"><span class="diff-badge '+lCls+'">'+(totalDiffL>0?'+':'')+totalDiffL.toFixed(0)+'</span></td>';
  h += '<td colspan="2"></td></tr>';

  h += '</tbody></table></div>';
  return h;
}}

function render() {{
  document.getElementById('tab-captains').innerHTML = tab === 'captains' ? renderCaptains() : '';
  document.getElementById('tab-players').innerHTML = tab === 'players' ? renderPlayers() : '';
  document.getElementById('tab-teams').innerHTML = tab === 'teams' ? renderTeams() : '';
  document.querySelectorAll('.tab-content').forEach(el => el.classList.toggle('active', el.id === 'tab-'+tab));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.pos-btn').forEach(b => b.classList.toggle('active', b.dataset.pos === pos));
  document.querySelectorAll('.scope-btn').forEach(b => b.classList.toggle('active', b.dataset.scope === scope));
  // Sortable click handlers
  document.querySelectorAll('.sortable').forEach(th => {{
    th.onclick = () => {{
      const t = th.dataset.tab, col = th.dataset.col;
      if (sorts[t].col === col) sorts[t].dir = sorts[t].dir === 'desc' ? 'asc' : 'desc';
      else {{ sorts[t].col = col; sorts[t].dir = 'desc'; }}
      render();
    }};
  }});
  // Attach roster click handlers
  attachRosterClicks();
  // Team select handler
  const sel = document.getElementById('teamSelect');
  if (sel) sel.onchange = () => {{ selectedTeam = sel.value; render(); }};
}}

document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => {{ tab = t.dataset.tab; render(); }}));
document.querySelectorAll('.pos-btn').forEach(b => b.addEventListener('click', () => {{ pos = b.dataset.pos; render(); }}));
document.querySelectorAll('.scope-btn').forEach(b => b.addEventListener('click', () => {{ scope = b.dataset.scope; render(); }}));
render();
</script>
</body>
</html>'''

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📊 Dashboard: {filename}")


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
    stats_players = scrape_stats_page(session)

    if stats_players:
        # Mamy listę z data-player-id, ale potrzebujemy stats-player ID
        # Spróbujmy najpierw data-player-id jako stats-player ID
        player_ids = [int(p["data_player_id"]) for p in stats_players if p["data_player_id"].isdigit()]
    else:
        # Fallback: skanuj zakres ID
        print("\n⚠️  Nie udało się pobrać listy ze strony /stats")
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
    summary_data = []
    for p in players:
        pts = p.get("total_points", 0) or 0
        price = p.get("price", 0) or 0
        ppp = round(pts / price, 2) if price > 0 else 0

        # Ostatnie 5 rozegranych kolejek (forma)
        rounds = p.get("rounds", [])
        played_rounds = [r for r in rounds if r.get("played")]
        last5 = played_rounds[-5:] if played_rounds else []
        form = [{"r": r.get("round", 0), "pts": r.get("points", 0)} for r in last5]

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
        })
    summary_data.sort(key=lambda x: x.get("total_points", 0) or 0, reverse=True)
    csv_file = os.path.join(OUTPUT_DIR, f"fantasy_players_{timestamp}.csv")
    save_to_csv(summary_data, csv_file)

    # CSV - statystyki per kolejka
    rounds_file = os.path.join(OUTPUT_DIR, f"fantasy_rounds_{timestamp}.csv")
    save_rounds_csv(players, rounds_file)

    # 5. Podsumowanie kolejki
    if TARGET_ROUND:
        print_round_summary(players, TARGET_ROUND)
    else:
        # Znajdź ostatnią rozegraną kolejkę
        max_round = 0
        for p in players:
            for r in p.get("rounds", []):
                if r.get("played") and r.get("round", 0) > max_round:
                    max_round = r["round"]
        if max_round:
            print_round_summary(players, max_round)

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
    league_rosters = {}
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
            pid = p.get("player_id", "")
            if not name:
                continue
            # Roster map
            if name not in league_rosters:
                league_rosters[name] = []
            league_rosters[name].append({
                "team": slug,
                "pos": rank,
                "C": p.get("is_captain", False),
                "R": p.get("is_reserve", False),
            })
            # Dane gracza z API statystyk (pełne punkty, pozycja tekstowa)
            full = player_lookup.get(str(pid), {})
            team_players.append({
                "pid": pid,
                "name": name,
                "pos": full.get("position", "") or p.get("position_id", ""),
                "pts": full.get("total_points", 0) or 0,
                "price": full.get("price", 0) or p.get("price", 0),
                "C": p.get("is_captain", False),
                "R": p.get("is_reserve", False),
                "form": [],
            })
            # Dodaj formę
            pr = full.get("rounds", [])
            played = [r for r in pr if r.get("played")]
            last5 = played[-5:] if played else []
            team_players[-1]["form"] = [{"r": r.get("round", 0), "pts": r.get("points", 0)} for r in last5]

        league_teams_detail.append({
            "slug": slug,
            "rank": rank,
            "pts": team_pts,
            "players": team_players,
        })
    # Sortuj po pozycji
    league_teams_detail.sort(key=lambda t: t.get("rank") or 999)

    dashboard_file = os.path.join(OUTPUT_DIR, "dashboard.html")
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
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        filename=dashboard_file,
    )

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
    print(f"   - dashboard.html (interaktywny dashboard)")
    print(f"🕐 Koniec: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
