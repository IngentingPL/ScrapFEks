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

# Maksymalne ID zawodnika do sprawdzenia (zmień na ~3000 dla pełnego scrapingu)
MAX_PLAYER_ID = int(os.environ.get("MAX_PLAYER_ID", "100"))

# Ile drużyn z rankingu scrapować (dla statystyk kapitanów itp.)
TEAMS_TO_SCRAPE = int(os.environ.get("TEAMS_TO_SCRAPE", "100"))

# Slug ligi prywatnej (puste = pomiń)
LEAGUE_SLUG = os.environ.get("LEAGUE_SLUG", "discord-fmforumcmf")
# ID ligi (z Network tab: POST /ranking-list → league: 304)
LEAGUE_ID = os.environ.get("LEAGUE_ID", "304")

# Opóźnienie między requestami (w sekundach) - bądź miły dla serwera
REQUEST_DELAY = 0.3

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
    """
    try:
        # Użyj czystych headerów przeglądarki — bez X-Requested-With
        # (ten header powoduje że serwer zwraca Angular shell zamiast PHP)
        browser_headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
            "Referer": f"{BASE_URL}/",
        }
        # Tymczasowo nadpisz session headers
        old_headers = dict(session.headers)
        session.headers.clear()
        session.headers.update(browser_headers)

        resp = session.get(
            f"{BASE_URL}/user-team/view/{slug}",
            timeout=15,
        )

        # Przywróć oryginalne headers
        session.headers.clear()
        session.headers.update(old_headers)
        if resp.status_code != 200:
            if debug:
                print(f"      ⚠️  HTTP {resp.status_code} dla {slug}")
            return {"slug": slug, "players": [], "captain_id": None}

        html = resp.text
        players = []
        captain_id = None

        # Szukamy wzorca: app.Pitch.$squad.push({ ... });
        pattern = r'squad\.push\(\{(.*?)\}\);'
        matches = re.findall(pattern, html, re.DOTALL)

        if debug:
            print(f"      DEBUG {slug}: znaleziono {len(matches)} zawodników w $squad.push")
            if not matches:
                has_squad = "squad" in html
                has_player = "player" in html.lower()
                print(f"      DEBUG 'squad' w HTML: {has_squad}, 'player' w HTML: {has_player}")
                print(f"      DEBUG HTML length: {len(html)}")
                # Pokaż fragment wokół "squad" jeśli istnieje
                idx = html.find("squad")
                if idx >= 0:
                    print(f"      DEBUG kontekst squad: ...{html[max(0,idx-50):idx+200]}...")
                else:
                    print(f"      DEBUG HTML (500 znaków): {html[:500]}")
            if not matches:
                # Sprawdź czy HTML zawiera cokolwiek o squad
                squad_refs = re.findall(r'squad|Pitch|player', html, re.IGNORECASE)
                print(f"      DEBUG słowa kluczowe w HTML: {squad_refs[:10]}")
                print(f"      DEBUG długość HTML: {len(html)}")
                print(f"      DEBUG cookies: {dict(session.cookies)}")
                # Szukaj fragmentu z app.Pitch
                pitch_match = re.search(r'app\.Pitch.*', html)
                if pitch_match:
                    print(f"      DEBUG app.Pitch fragment: {pitch_match.group()[:300]}")
                # Szukaj jakichkolwiek push()
                push_matches = re.findall(r'\.push\(\{.*?\}\)', html[:5000], re.DOTALL)
                print(f"      DEBUG push() w HTML: {len(push_matches)}")

        for match in matches:
            # Parsuj pola z JS obiektu
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

            if is_captain and player_id:
                captain_id = player_id

            points_text = points_match.group(1).strip() if points_match else ""

            players.append({
                "player_id": player_id,
                "name": name.group(1) if name else "",
                "position_id": pos.group(1) if pos else "",
                "price": float(price.group(1)) if price else 0,
                "points": _safe_int(points_text) if points_text and points_text != "-" else 0,
                "is_captain": is_captain,
                "is_subcaptain": is_subcaptain,
                "is_reserve": False,  # Zostanie ustawione poniżej
                "status": status.group(1) if status else "",
            })

        # Pierwsi 11 zawodników to skład startowy, reszta to rezerwa
        # (serwer zwraca w kolejności: 11 startowych + rezerwowi)
        starting_count = 11
        for i, p in enumerate(players):
            if i >= starting_count:
                p["is_reserve"] = True

        if debug and players:
            cap_name = next((p["name"] for p in players if p["is_captain"]), "brak")
            print(f"      DEBUG kapitan: {cap_name}")

        return {
            "slug": slug,
            "players": players,
            "captain_id": captain_id,
        }

    except Exception as e:
        if debug:
            print(f"      ⚠️  Błąd: {e}")
        return {"slug": slug, "players": [], "captain_id": None, "error": str(e)}


def scrape_teams_captains(session: requests.Session, teams: list[dict]) -> list[dict]:
    """Scrapuje składy drużyn i zbiera dane o kapitanach."""
    total = len(teams)
    results = []

    print(f"\n👑 Scrapuję składy {total} drużyn (kapitanowie, składy)...")

    for i, team in enumerate(teams, 1):
        slug = team["slug"]
        squad = scrape_team_squad(session, slug, debug=(i <= 2))

        captain_id = squad.get("captain_id")
        captain_name = ""
        for p in squad.get("players", []):
            if p["player_id"] == captain_id:
                captain_name = p["name"]
                break

        results.append({
            "ranking_position": team.get("position"),
            "team_slug": slug,
            "team_points": team.get("total_points"),
            "captain_id": captain_id,
            "captain_name": captain_name,
            "squad": squad.get("players", []),
        })

        if i % 20 == 0 or i == total:
            print(f"   [{i}/{total}] Scrapowanie drużyn...")

        time.sleep(REQUEST_DELAY)

    print(f"   ✅ Pobrano składy {len(results)} drużyn")
    return results


def generate_captain_stats(team_results: list[dict], filename: str):
    """
    Generuje statystyki kapitanów — ile razy dany zawodnik został wybrany kapitanem.
    Zapisuje do CSV.
    """
    captain_counts = {}
    total_teams = len(team_results)

    for team in team_results:
        cid = team.get("captain_id")
        cname = team.get("captain_name", "")
        if cid:
            if cid not in captain_counts:
                captain_counts[cid] = {"player_id": cid, "name": cname, "captain_count": 0}
            captain_counts[cid]["captain_count"] += 1

    # Sortuj po liczbie wyborów
    stats = sorted(captain_counts.values(), key=lambda x: x["captain_count"], reverse=True)

    # Dodaj procent
    for s in stats:
        s["captain_pct"] = f"{round(s['captain_count'] / total_teams * 100, 1)}%"

    save_to_csv(stats, filename)

    # Wydrukuj podsumowanie
    print(f"\n{'='*60}")
    print(f"  👑 STATYSTYKI KAPITANÓW (z {total_teams} drużyn)")
    print(f"{'='*60}")
    print(f"  {'Zawodnik':<25} {'Wyborów':>8} {'%':>8}")
    print(f"  {'-'*45}")
    for s in stats[:15]:
        print(f"  {s['name']:<25} {s['captain_count']:>8} {s['captain_pct']:>8}")

    return stats


def generate_squad_stats(team_results: list[dict], filename: str):
    """
    Generuje statystyki ownership — ile drużyn ma danego zawodnika w składzie.
    Zapisuje do CSV.
    """
    player_counts = {}
    total_teams = len(team_results)

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
    captain_stats: list[dict],
    ownership_stats: list[dict],
    teams_count: int,
    league_captain_stats: list[dict],
    league_ownership_stats: list[dict],
    league_name: str,
    league_teams_count: int,
    timestamp: str,
    filename: str,
):
    """Generuje interaktywny dashboard HTML z danymi Fantasy Ekstraklasa."""

    captains_json = json.dumps(captain_stats[:50], ensure_ascii=False)
    ownership_json = json.dumps(ownership_stats[:80], ensure_ascii=False)
    players_json = json.dumps(summary_data[:200], ensure_ascii=False)
    league_captains_json = json.dumps(league_captain_stats[:50], ensure_ascii=False)
    league_ownership_json = json.dumps(league_ownership_stats[:80], ensure_ascii=False)

    top_captain = captain_stats[0] if captain_stats else {}
    top_owned = ownership_stats[0] if ownership_stats else {}
    best_ppp = max(summary_data, key=lambda x: x.get("points_per_price", 0)) if summary_data else {}

    has_league = league_teams_count > 0
    league_label = league_name.replace("-", " ").title() if league_name else ""

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
      <button class="tab" data-tab="ownership">👥 Ownership</button>
      <button class="tab" data-tab="players">⚽ Zawodnicy</button>
    </div>
    <div class="filters-row" style="margin-top: 12px;">
      {"<div class='scope-toggle'><button class='scope-btn active' data-scope='global'>🏆 Top " + str(teams_count) + "</button><button class='scope-btn' data-scope='league'>🏅 " + league_label + "</button></div>" if has_league else ""}
      <div class="pos-filters" style="margin-left:auto;">
        <button class="pos-btn active" data-pos="ALL">ALL</button>
        <button class="pos-btn" data-pos="BR">GK</button>
        <button class="pos-btn" data-pos="OBR">DEF</button>
        <button class="pos-btn" data-pos="POM">MID</button>
        <button class="pos-btn" data-pos="NAP">FWD</button>
      </div>
    </div>
    <div id="tab-captains" class="tab-content active"></div>
    <div id="tab-ownership" class="tab-content"></div>
    <div id="tab-players" class="tab-content"></div>
  </div>
  <div class="footer">Fantasy Ekstraklasa Dashboard · {timestamp}</div>
</div>

<script>
const DATA = {{
  global: {{
    captains: {captains_json},
    ownership: {ownership_json},
  }},
  league: {{
    captains: {league_captains_json},
    ownership: {league_ownership_json},
  }},
}};
const PLAYERS = {players_json};

const POS_MAP = {{BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD','1':'GK','2':'DEF','3':'MID','4':'FWD'}};
const POS_ID = {{'1':'BR','2':'OBR','3':'POM','4':'NAP',BR:'BR',OBR:'OBR',POM:'POM',NAP:'NAP',
  Bramkarz:'BR','Obrońca':'OBR',Pomocnik:'POM',Napastnik:'NAP'}};

let tab = 'captains', pos = 'ALL', scope = 'global';
let sorts = {{
  captains: {{col:'captain_count', dir:'desc'}},
  ownership: {{col:'in_squad_count', dir:'desc'}},
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

function renderCaptains() {{
  let data = DATA[scope].captains;
  data = sortData(data, 'captains');
  if (!data.length) return '<div class="empty-msg">Brak danych o kapitanach</div>';
  const maxPct = Math.max(...data.map(c => c.captain_count));
  let h = '<div class="section-title"><span style="font-size:22px">👑</span><h2>Popularność kapitanów — '+(scope==='league'?'Liga':'Top {teams_count}')+'</h2><div class="line"></div></div>';
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
    h += '<tr'+hl+'><td class="c-muted fw-600">'+(i+1)+'</td><td><span style="'+ns+'">'+badge+c.name+'</span></td>';
    h += '<td class="text-right fw-700">'+c.captain_count+'</td>';
    h += '<td>'+bar(parseFloat(c.captain_pct), maxPct*1.2, bc)+'</td></tr>';
  }});
  h += '</tbody></table></div>';
  return h;
}}

function renderOwnership() {{
  let data = filterPos(DATA[scope].ownership);
  data = sortData(data, 'ownership');
  if (!data.length) return '<div class="empty-msg">Brak danych ownership</div>';
  let h = '<div class="section-title"><span style="font-size:22px">👥</span><h2>Ownership — '+(scope==='league'?'Liga':'Top {teams_count}')+'</h2><div class="line"></div></div>';
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-left">#</th>';
  h += '<th class="text-left sortable" data-tab="ownership" data-col="name">Zawodnik'+arrow('ownership','name')+'</th>';
  h += '<th class="text-center sortable" data-tab="ownership" data-col="position">Poz'+arrow('ownership','position')+'</th>';
  h += '<th class="text-left sortable" data-tab="ownership" data-col="in_squad_count" style="min-width:130px">W składzie'+arrow('ownership','in_squad_count')+'</th>';
  h += '<th class="text-left sortable" data-tab="ownership" data-col="in_starting_count" style="min-width:130px">Start XI'+arrow('ownership','in_starting_count')+'</th>';
  h += '<th class="text-left sortable" data-tab="ownership" data-col="captain_count" style="min-width:130px">Kapitan'+arrow('ownership','captain_count')+'</th>';
  h += '</tr></thead><tbody>';
  data.forEach((p, i) => {{
    const sq = num(p.squad_pct), st = num(p.starting_pct), cp = num(p.captain_pct);
    const pk = POS_ID[p.position] || p.position || '';
    h += '<tr><td class="c-muted fw-600">'+(i+1)+'</td><td class="fw-600">'+p.name+'</td>';
    h += '<td class="text-center">'+posBadge(pk)+'</td>';
    h += '<td>'+bar(sq, 100, '#10b981')+'</td>';
    h += '<td>'+bar(st, 100, '#3b82f6')+'</td>';
    h += '<td>'+bar(cp, 40, '#fbbf24')+'</td></tr>';
  }});
  h += '</tbody></table></div>';
  return h;
}}

function renderPlayers() {{
  let data = [...PLAYERS];
  if (pos !== 'ALL') data = data.filter(p => (POS_ID[p.position] || p.position) === pos);
  data = sortData(data, 'players');
  if (!data.length) return '<div class="empty-msg">Brak danych</div>';
  let h = '<div class="section-title"><span style="font-size:22px">⚽</span><h2>Statystyki zawodników</h2><div class="line"></div></div>';
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-left">#</th>';
  h += '<th class="text-left sortable" data-tab="players" data-col="name">Zawodnik'+arrow('players','name')+'</th>';
  h += '<th class="text-left sortable" data-tab="players" data-col="team">Drużyna'+arrow('players','team')+'</th>';
  h += '<th class="text-center sortable" data-tab="players" data-col="position">Poz'+arrow('players','position')+'</th>';
  h += '<th class="text-right sortable" data-tab="players" data-col="price">Cena'+arrow('players','price')+'</th>';
  h += '<th class="text-right sortable" data-tab="players" data-col="total_points">Punkty'+arrow('players','total_points')+'</th>';
  h += '<th class="text-right sortable" data-tab="players" data-col="points_per_price">Pkt/Cena'+arrow('players','points_per_price')+'</th>';
  h += '<th class="text-right sortable" data-tab="players" data-col="popularity_pct">Pop.'+arrow('players','popularity_pct')+'</th>';
  h += '</tr></thead><tbody>';
  data.forEach((p, i) => {{
    const pts = p.total_points || 0, price = p.price || 0, ppp = p.points_per_price || 0;
    const ptsC = pts >= 35 ? '#22d3ee' : pts >= 25 ? '#e2e8f0' : '#94a3b8';
    const pppC = ppp >= 15 ? '#10b981' : ppp >= 10 ? '#e2e8f0' : '#94a3b8';
    const pk = POS_ID[p.position] || p.position || '';
    h += '<tr><td class="c-muted fw-600">'+(i+1)+'</td>';
    h += '<td class="fw-600">'+p.name+'</td>';
    h += '<td class="c-muted" style="font-size:13px">'+p.team+'</td>';
    h += '<td class="text-center">'+posBadge(pk)+'</td>';
    h += '<td class="text-right c-muted">'+price.toFixed(1)+'M</td>';
    h += '<td class="text-right fw-700" style="color:'+ptsC+'">'+pts+'</td>';
    h += '<td class="text-right fw-600" style="color:'+pppC+'">'+ppp.toFixed(1)+'</td>';
    h += '<td class="text-right c-dim" style="font-size:13px">'+p.popularity_pct+'</td></tr>';
  }});
  h += '</tbody></table></div>';
  return h;
}}

function render() {{
  document.getElementById('tab-captains').innerHTML = tab === 'captains' ? renderCaptains() : '';
  document.getElementById('tab-ownership').innerHTML = tab === 'ownership' ? renderOwnership() : '';
  document.getElementById('tab-players').innerHTML = tab === 'players' ? renderPlayers() : '';
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
    if TEAMS_TO_SCRAPE > 0:
        ranking_teams = fetch_ranking_teams(session, TEAMS_TO_SCRAPE)

        if ranking_teams:
            team_results = scrape_teams_captains(session, ranking_teams)

            # CSV - statystyki kapitanów
            captains_file = os.path.join(OUTPUT_DIR, f"fantasy_captains_{timestamp}.csv")
            captain_stats = generate_captain_stats(team_results, captains_file)

            # CSV - ownership w drużynach
            ownership_file = os.path.join(OUTPUT_DIR, f"fantasy_ownership_{timestamp}.csv")
            ownership_stats = generate_squad_stats(team_results, ownership_file)

    # 7. Scrapowanie ligi prywatnej
    league_captain_stats = []
    league_ownership_stats = []
    league_teams = []
    if LEAGUE_SLUG:
        league_teams = fetch_league_teams(session, LEAGUE_SLUG, LEAGUE_ID)

        if league_teams:
            league_results = scrape_teams_captains(session, league_teams)

            # CSV - statystyki kapitanów ligi
            league_captains_file = os.path.join(OUTPUT_DIR, f"fantasy_league_captains_{timestamp}.csv")
            league_captain_stats = generate_captain_stats(league_results, league_captains_file)

            # CSV - ownership w lidze
            league_ownership_file = os.path.join(OUTPUT_DIR, f"fantasy_league_ownership_{timestamp}.csv")
            league_ownership_stats = generate_squad_stats(league_results, league_ownership_file)

    # 8. Dashboard HTML
    dashboard_file = os.path.join(OUTPUT_DIR, "dashboard.html")
    generate_dashboard_html(
        summary_data=summary_data,
        captain_stats=captain_stats,
        ownership_stats=ownership_stats,
        teams_count=TEAMS_TO_SCRAPE,
        league_captain_stats=league_captain_stats,
        league_ownership_stats=league_ownership_stats,
        league_name=LEAGUE_SLUG or "",
        league_teams_count=len(league_teams) if LEAGUE_SLUG and league_teams else 0,
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
