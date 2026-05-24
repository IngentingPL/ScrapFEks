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

import base64
import requests
from bs4 import BeautifulSoup
import json
import csv
import time
import threading
import re
import os
import sys
import hashlib
import unicodedata
from datetime import datetime
from typing import Optional
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from predictor import predict_all_players
from accuracy import evaluate_predictions, find_latest_predictions_csv, load_accuracy_history
from tuner import run_tuning
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from Crypto.Random import get_random_bytes


def normalize_team_name(name: str) -> str:
    """Normalizuj nazwę drużyny: lowercase + usuń polskie diakrytyki."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_name = ascii_name.replace("ł", "l").replace("Ł", "L")
    return ascii_name.lower().strip()

def _normalize_name(name: str) -> str:
    """Normalizuj imię i nazwisko: lowercase + usuń polskie diakrytyki, zachowaj spację."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_name = ascii_name.replace("ł", "l").replace("Ł", "L")
    return ascii_name.lower().strip()


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

# Slug drużyny użytkownika (do zakładki transferów; puste = wykryj automatycznie)
USER_TEAM_SLUG = os.environ.get("USER_TEAM_SLUG", "")

# Opóźnienie między requestami (w sekundach) - bądź miły dla serwera
REQUEST_DELAY = 0.3

# Ile równoległych workerów do scrapowania drużyn
WORKERS = int(os.environ.get("WORKERS", "10"))

# Maksymalny czas pracy (minuty) — graceful stop przed limitem GitHub Actions (6h)
MAX_RUNTIME_MINUTES = int(os.environ.get("MAX_RUNTIME_MINUTES", "300"))

# Archiwizacja sezonu
ARCHIVE_SEASON = os.environ.get("ARCHIVE_SEASON", "false").lower() == "true"
SEASON_NAME = os.environ.get("SEASON_NAME", "")

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
        if resp.status_code != 200:
            print(f"   ❌ Błąd tworzenia tokenu connect")
            return True  # kontynuuj bez cookies

        create_data = resp.json()
        connect_hash = create_data.get("token") or create_data.get("hash") or create_data.get("code")

        if not connect_hash:
            print("   ⚠️  Brak connect_hash w odpowiedzi token/create")
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
        session.get(BASE_URL, timeout=15)

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


def get_user_team_slug(session: requests.Session) -> str:
    """
    Zwraca slug drużyny do użycia z transfer-info.

    Kolejność prób:
    1. Zmienna środowiskowa USER_TEAM_SLUG (własna drużyna użytkownika — preferowane)
    2. Pierwszy slug z ranking-list (działa, bo ranking-list AJAX już działał)
       — transfer-info może być dostępne z dowolnym autentykowanym slugiem
    """
    if USER_TEAM_SLUG:
        return USER_TEAM_SLUG

    print("🔍 Szukam slug drużyny przez ranking-list...")
    try:
        resp = session.post(
            f"{BASE_URL}/ranking-list",
            data="start=0&length=1",
            headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            for team in data.get("data", []):
                slug = team.get("slug", "")
                if slug:
                    print(f"   Znaleziono slug z rankingu: {slug}")
                    print(f"   💡 Dla pewności ustaw USER_TEAM_SLUG na własny slug drużyny")
                    return slug
    except Exception as e:
        print(f"   ⚠️  Błąd ranking-list: {e}")

    print("   ⚠️  Nie udało się pobrać żadnego slug")
    print("   💡 Ustaw zmienną środowiskową USER_TEAM_SLUG lub GitHub Secret")
    return ""


def get_player_ids_from_transfers(session: requests.Session, slug: str) -> list[dict]:
    """
    Pobiera listę wszystkich aktywnych zawodników z zakładki transferów.

    Próbuje endpointy w kolejności:
      1. GET /user-team/transfer-info/{slug}  — AJAX/JSON
      2. GET /user-team/view/{slug}           — HTML ze skryptami JS

    Parsuje trzy formaty: JSON, HTML data-player-id, JS push() bloki.
    Używa czystych headerów przeglądarki (bez X-Requested-With) dla HTML,
    tak jak scrape_team_squad().

    Zwraca listę słowników: player_id, name, price, position_id, team, status.
    """
    print(f"🔄 Pobieram listę zawodników z zakładki transferów (slug: {slug})...")
    players = []
    cookies = dict(session.cookies)

    # Headery dla endpointów AJAX (JSON)
    ajax_headers = {
        **HEADERS,
        "Accept": "application/json, text/javascript, */*",
        "Referer": f"{BASE_URL}/user-team/view/{slug}",
    }
    # Czyste headery przeglądarki dla stron HTML (bez X-Requested-With)
    browser_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": HEADERS["Accept-Language"],
        "Referer": f"{BASE_URL}/user-team/view/{slug}",
    }

    def _parse_js_blocks(html: str) -> list[dict]:
        """Parsuje bloki push() z JS osadzonego w HTML (jak scrape_team_squad)."""
        result = []
        # Wzorce podobne do $squad.push / $subs.push ale dla dostępnych graczy
        js_patterns = [
            r'\$available\.push\(\{(.*?)\}\)',
            r'app\.\w+\.\$available\.push\(\{(.*?)\}\)',
            r'\$players\.push\(\{(.*?)\}\)',
            r'availablePlayers\.push\(\{(.*?)\}\)',
            r'allPlayers\.push\(\{(.*?)\}\)',
            r'\$all\.push\(\{(.*?)\}\)',
        ]
        for pat in js_patterns:
            matches = re.findall(pat, html, re.DOTALL)
            if not matches:
                continue
            for match in matches:
                pid = re.search(r'"id"\s*:\s*(\d+)', match)
                if not pid:
                    continue
                name = re.search(r'"name"\s*:\s*"([^"]*)"', match)
                pos = re.search(r'"pos"\s*:\s*(\d+)', match)
                price = re.search(r'"price"\s*:\s*([\d.]+)', match)
                team = re.search(r'"team"\s*:\s*"([^"]*)"', match)
                status = re.search(r'"status"\s*:\s*"([^"]*)"', match)
                result.append({
                    "player_id": pid.group(1),
                    "name": name.group(1) if name else "",
                    "price": price.group(1) if price else "",
                    "position_id": pos.group(1) if pos else "",
                    "team": team.group(1) if team else "",
                    "status": status.group(1) if status else "",
                })
            if result:
                break
        return result

    def _parse_html_attrs(html: str) -> list[dict]:
        """Parsuje elementy HTML z atrybutami data-player-id."""
        result = []
        soup = BeautifulSoup(html, "lxml")
        for el in soup.select("[data-player-id]"):
            player_id = el.get("data-player-id", "")
            if not player_id:
                continue
            name_el = el.select_one(".name, .player-name")
            team_el = el.select_one(".team, .player-team")
            result.append({
                "player_id": player_id,
                "name": name_el.text.strip() if name_el else "",
                "price": el.get("data-player-price", ""),
                "position_id": el.get("data-player-pos", ""),
                "team": (team_el.text.strip() if team_el
                         else el.get("data-player-team", "")),
                "status": el.get("data-player-status", ""),
            })
        return result

    # Endpoint 1: transfer-info — może zwrócić JSON lub HTML z danymi
    try:
        resp = requests.get(
            f"{BASE_URL}/user-team/transfer-info/{slug}",
            headers=ajax_headers,
            cookies=cookies,
            timeout=30,
        )
        print(f"   transfer-info HTTP {resp.status_code}, "
              f"Content-Type: {resp.headers.get('Content-Type', '?')[:60]}")
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" in content_type:
                data = resp.json()
                player_list = (data.get("players") or data.get("data")
                               or data.get("available") or [])
                for p in player_list:
                    pid = str(p.get("id") or p.get("player_id") or "")
                    if pid:
                        players.append({
                            "player_id": pid,
                            "name": p.get("name", ""),
                            "price": str(p.get("price", "")),
                            "position_id": str(p.get("pos") or p.get("position_id") or ""),
                            "team": p.get("team", ""),
                            "status": p.get("status", ""),
                        })
            if not players:
                players = _parse_html_attrs(resp.text) or _parse_js_blocks(resp.text)
    except Exception as e:
        print(f"   ⚠️  Błąd transfer-info: {e}")

    # Endpoint 2: widok drużyny — HTML z danymi JS (jak scrape_team_squad)
    if not players:
        try:
            resp = requests.get(
                f"{BASE_URL}/user-team/view/{slug}",
                headers=browser_headers,
                cookies=cookies,
                timeout=30,
            )
            if resp.status_code == 200:
                players = _parse_html_attrs(resp.text) or _parse_js_blocks(resp.text)
        except Exception as e:
            print(f"   ⚠️  Błąd user-team/view: {e}")

    # Deduplikuj po player_id
    seen: set[str] = set()
    unique_players = []
    for p in players:
        if p["player_id"] not in seen:
            seen.add(p["player_id"])
            unique_players.append(p)

    print(f"   Znaleziono {len(unique_players)} zawodników w zakładce transferów")
    return unique_players


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
            headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
            },
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
        resp = requests.get(
            f"{BASE_URL}/stats-player/{player_id}",
            headers=HEADERS,
            cookies=dict(session.cookies),
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

    Używa czystych headerów przeglądarki (bez X-Requested-With), bo /stats
    zwraca HTML tylko dla normalnych requestów — AJAX header powoduje odpowiedź JSON.
    """
    print("📋 Scrapuję stronę ze statystykami...")
    all_players = []
    seen_ids: set[str] = set()

    # Czyste headery przeglądarki — jak scrape_team_squad
    browser_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": HEADERS["Accept-Language"],
        "Referer": f"{BASE_URL}/",
    }
    cookies = dict(session.cookies)

    # Strona /stats może mieć paginację lub filtrowanie
    # Spróbujmy pobrać dla każdej pozycji (1=GK, 2=DEF, 3=MID, 4=FWD)
    for pos in [1, 2, 3, 4]:
        pos_names = {1: "Bramkarze", 2: "Obrońcy", 3: "Pomocnicy", 4: "Napastnicy"}
        print(f"   Pozycja: {pos_names.get(pos, pos)}...")

        try:
            resp = requests.get(
                f"{BASE_URL}/stats",
                params={"pos": pos},
                headers=browser_headers,
                cookies=cookies,
                timeout=30,
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                players = soup.select("[data-player-id]")
                for el in players:
                    pid = el.get("data-player-id")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
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
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
            "Referer": f"{BASE_URL}/",
        }

        url = (f"{BASE_URL}/user-team/view/{slug}/{round_num}"
               if round_num is not None
               else f"{BASE_URL}/user-team/view/{slug}")

        # Thread-safe: użyj requests.get() z cookies z sesji
        resp = requests.get(
            url,
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

    browser_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        "Referer": f"{BASE_URL}/",
    }

    for i, team in enumerate(league_results):
        slug = team.get("team_slug", "")
        if not slug:
            continue

        # Aktualny skład (już pobrany)
        current_pids = {
            str(p.get("player_id"))
            for p in team.get("squad", [])
            if p.get("player_id")
        }

        # Skład z poprzedniej kolejki
        try:
            prev_squad_data = scrape_team_squad(session, slug, round_num=prev_round)
            prev_pids = {
                str(p.get("player_id"))
                for p in prev_squad_data.get("players", [])
                if p.get("player_id")
            }
        except Exception as e:
            if i < 3:
                print(f"   ⚠️  Błąd pobierania K{prev_round} dla {slug}: {e}")
            prev_pids = set()

        # Transfery IN = pojawili się w current, nie było ich w prev
        for pid in current_pids - prev_pids:
            transfers_in_count[pid] = transfers_in_count.get(pid, 0) + 1

        # Transfery OUT = byli w prev, nie ma ich w current
        for pid in prev_pids - current_pids:
            transfers_out_count[pid] = transfers_out_count.get(pid, 0) + 1

        if (i + 1) % 5 == 0 or (i + 1) == total_teams:
            print(f"   [{i + 1}/{total_teams}] drużyn przetworzono")

        time.sleep(REQUEST_DELAY)

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


# ============================================================
# FIXTURE TICKER — parsowanie terminarz.txt
# ============================================================

TEAM_ABBREVS = {
    "Arka Gdynia": "ARK", "Bruk-Bet Termalica Nieciecza": "BBT",
    "Cracovia": "CRA", "GKS Katowice": "GKS", "Górnik Zabrze": "GÓR",
    "Jagiellonia Białystok": "JAG", "Korona Kielce": "KOR",
    "Lech Poznań": "LPO", "Lechia Gdańsk": "LGD", "Legia Warszawa": "LEG",
    "Motor Lublin": "MOT", "Piast Gliwice": "PIA", "Pogoń Szczecin": "POG",
    "Radomiak Radom": "RAD", "Raków Częstochowa": "RAK", "Widzew Łódź": "WID",
    "Wisła Płock": "WPŁ", "Zagłębie Lubin": "ZAG",
}

# Mapowanie nazw drużyn z 90minut.pl → nazwy lokalne z terminarz.txt
NINETYM_TEAM_MAP = {
    "Jagiellonia Białystok": "Jagiellonia Białystok",
    "Jagiellonia B.": "Jagiellonia Białystok",
    "Legia Warszawa": "Legia Warszawa",
    "Lech Poznań": "Lech Poznań",
    "Lechia Gdańsk": "Lechia Gdańsk",
    "Górnik Zabrze": "Górnik Zabrze",
    "Pogoń Szczecin": "Pogoń Szczecin",
    "Widzew Łódź": "Widzew Łódź",
    "Wisła Płock": "Wisła Płock",
    "Zagłębie Lubin": "Zagłębie Lubin",
    "Raków Częstochowa": "Raków Częstochowa",
    "Bruk-Bet Termalica Nieciecza": "Bruk-Bet Termalica Nieciecza",
    "Bruk-Bet Termalica": "Bruk-Bet Termalica Nieciecza",
    "Termalica Bruk-Bet Nieciecza": "Bruk-Bet Termalica Nieciecza",
    "Termalica Nieciecza": "Bruk-Bet Termalica Nieciecza",
    "Korona Kielce": "Korona Kielce",
    "Cracovia": "Cracovia",
    "KS Cracovia": "Cracovia",
    "Cracovia Kraków": "Cracovia",
    "Arka Gdynia": "Arka Gdynia",
    "GKS Katowice": "GKS Katowice",
    "Piast Gliwice": "Piast Gliwice",
    "Radomiak Radom": "Radomiak Radom",
    "Motor Lublin": "Motor Lublin",
}

# ID rozgrywek Ekstraklasy na 90minut.pl (aktualizuj co sezon)
NINETYM_LIGA_ID = "14072"  # PKO BP Ekstraklasa 2025/2026


def _parse_90min_table(table) -> dict:
    """Parsuje pojedynczą tabelę ligową z 90minut.pl. Zwraca {raw_name: {gf, ga, mp}}."""
    results = {}
    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        # Znajdź nazwę drużyny — szukamy <a> z linkiem do klubu
        team_name = None
        for cell in cells:
            link = cell.find("a")
            if link:
                href = link.get("href") or ""
                if "klub" in href or "druzyna" in href or "/liga/" not in href:
                    candidate = link.get_text(strip=True)
                    if candidate and not candidate.isdigit() and len(candidate) > 2:
                        team_name = candidate
                        break

        if not team_name:
            for cell in cells[1:4]:
                text = cell.get_text(strip=True)
                if text and not text.isdigit() and len(text) > 3:
                    team_name = text
                    break

        if not team_name:
            continue

        # Znajdź liczbę meczów — pierwsza komórka z samą liczbą (po pozycji i nazwie)
        mp = 0
        for cell in cells[2:6]:
            text = cell.get_text(strip=True)
            if text.isdigit() and int(text) > 0:
                mp = int(text)
                break

        # Znajdź bramki w formacie "XX:XX" lub "XX-XX"
        goals_text = None
        for cell in cells:
            text = cell.get_text(strip=True)
            if re.match(r"^\d+[:\-]\d+$", text):
                goals_text = text
                break

        if not goals_text:
            continue

        parts = re.split(r"[:\-]", goals_text)
        if len(parts) == 2:
            results[team_name] = {"gf": int(parts[0]), "ga": int(parts[1]), "mp": mp}

    return results


def _map_team_name(raw_name: str) -> str:
    """Mapuje nazwę drużyny z 90minut.pl na lokalną z terminarz.txt."""
    local_name = NINETYM_TEAM_MAP.get(raw_name, raw_name)
    if local_name not in TEAM_ABBREVS:
        for local in TEAM_ABBREVS:
            if raw_name.lower() in local.lower() or local.lower() in raw_name.lower():
                return local
    return local_name


def _find_standings_tables(soup) -> list:
    """Znajduje tabele z klasyfikacją na stronie 90minut.pl (RAZEM, DOM, WYJAZD)."""
    tables = soup.find_all("table")
    standings = []
    for table in tables:
        header_text = table.get_text()
        if "Pkt" in header_text and "Bramki" in header_text:
            standings.append(table)
        elif not standings:
            # Fallback: tabela z >=16 wierszy i formatem bramek X:X
            rows = table.find_all("tr")
            if len(rows) >= 16 and re.search(r"\d+:\d+", table.get_text()):
                standings.append(table)
    return standings


def fetch_ekstraklasa_table() -> dict:
    """Scrapuje tabelę Ekstraklasy z 90minut.pl (bramki ogółem + dom/wyjazd)."""
    url = f"http://www.90minut.pl/liga/1/liga{NINETYM_LIGA_ID}.html"
    team_stats = {}
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()

        resp.encoding = resp.apparent_encoding or "iso-8859-2"
        soup = BeautifulSoup(resp.text, "lxml")

        standings = _find_standings_tables(soup)
        if not standings:
            print(f"  ⚠️  Nie znaleziono tabeli na 90minut.pl")
            return team_stats

        # Tabele w kolejności: RAZEM, DOM, WYJAZD
        razem = _parse_90min_table(standings[0])
        dom = _parse_90min_table(standings[1]) if len(standings) >= 2 else {}
        wyjazd = _parse_90min_table(standings[2]) if len(standings) >= 3 else {}

        for raw_name, data in razem.items():
            local_name = _map_team_name(raw_name)
            entry = {"gf": data["gf"], "ga": data["ga"], "mp": data["mp"]}

            # Dodaj dane domowe
            home = dom.get(raw_name, {})
            entry["gf_home"] = home.get("gf", 0)
            entry["ga_home"] = home.get("ga", 0)
            entry["mp_home"] = home.get("mp", 0)

            # Dodaj dane wyjazdowe
            away = wyjazd.get(raw_name, {})
            entry["gf_away"] = away.get("gf", 0)
            entry["ga_away"] = away.get("ga", 0)
            entry["mp_away"] = away.get("mp", 0)

            team_stats[local_name] = entry

        has_ha = bool(dom and wyjazd)
        print(f"  ⚽ 90minut.pl: pobrano statystyki {len(team_stats)} drużyn"
              f" {'(z podziałem dom/wyjazd)' if has_ha else '(tylko ogółem)'}")
    except Exception as e:
        print(f"  ⚠️  Błąd scrapowania z 90minut.pl: {e}")
    return team_stats


# ============================================================
# SCRAPING NOWYCH STATYSTYK Z EKSTRAKLASA.ORG
# ============================================================

# API do statystyk indywidualnych (xG, strzały, podania, dośrodkowania)
# Używa ukrytego API ekstraklasy (umpire-api.tisagroup.ch)
# Wymaga tokena autoryzacyjnego (token jest w localStorage strony)
EXTRA_STATS_API = "https://production-umpire-api.ekstraklasa.tisagroup.ch/api/v3/statistics"

# Parametry filtrów dla API statystyk zawodników
EXTRA_STATS_PARAMS = {
    "filter[context_type_eq]": "CompetitionSeason",
    "filter[resource_type_eq]": "SquadPlayer",
    "filter[resource_status_eq]": "active",
    "filter[context_id_eq]": "166",  # bieżąca sezona
    "page[number]": "0",
    "page[size]": "100",
    "include": "resource,resource.squad.team.club",
}

# Token autoryzacyjny - pobrany z localStorage strony (może wymagać odświeżenia)
# Token jest unikalny dla sesji przeglądarki, ale działa przez jakiś czas
EXTRA_API_TOKEN = "548e70be68e804aad3f7f779f43129ae"  # przykładowy token


def _fetch_extra_stat_page(url: str) -> list[dict]:
    """
    Pobiera dane z pojedynczej strony statystyk indywidualnych.
    
    Zwraca listę dict: {"name": "...", "team": "...", "value": numeric}
    """
    stats = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, headers=headers, timeout=30)
        # DEBUG: tymczasowy print statusu
        print(f"    status={resp.status_code}, len={len(resp.text)}")
        
        if resp.status_code != 200:
            return stats
        
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        
        # Szukaj tabeli z danymi — struktura może się różnić w zależności od strony
        # Typowe wzorce: tabela w <table> lub wiersze z klasą "player-row"
        
        # Metoda 1: szukaj tabeli z wierszami
        table = soup.select_one("table.stats-table, table.table, table.data")
        if table:
            for row in table.select("tbody tr, tr"):
                cells = row.select("td")
                if len(cells) >= 3:
                    # Sprawdź czy pierwsza komórka to pozycja (nie liczba)
                    first_cell = cells[0].get_text(strip=True)
                    if first_cell.isdigit():
                        continue  # To pozycja w tabeli, nie nazwa gracza
                    
                    # Format: nazwa, drużyna, wartość (lub odwrotnie)
                    # Spróbuj różne układy
                    name = ""
                    team = ""
                    value = 0
                    
                    # Próba 1: nazwa | drużyna | wartość
                    if len(cells) >= 3:
                        name = cells[0].get_text(strip=True)
                        team = cells[1].get_text(strip=True)
                        value = _safe_float(cells[2].get_text(strip=True))
                    
                    # Próba 2: poz | nazwa | drużyna | wartość
                    if len(cells) >= 4 and not name:
                        name = cells[1].get_text(strip=True)
                        team = cells[2].get_text(strip=True)
                        value = _safe_float(cells[3].get_text(strip=True))
                    
                    if name and value > 0:
                        stats.append({"name": name, "team": team, "value": value})
        
        # Metoda 2: szukaj elementów z danymi gracza (listy OL lub DIVy)
        if not stats:
            player_elements = soup.select(".player-row, .stat-row, [data-player]")
            for el in player_elements:
                name_el = el.select_one(".name, .player-name, [data-name]")
                team_el = el.select_one(".team, .club")
                value_el = el.select_one(".value, .stat-value, [data-value]")
                
                if name_el:
                    name = name_el.get_text(strip=True)
                    team = team_el.get_text(strip=True) if team_el else ""
                    value = _safe_float(value_el.get_text(strip=True)) if value_el else 0
                    
                    if name and value > 0:
                        stats.append({"name": name, "team": team, "value": value})
        
        # Metoda 3: fallback do OL z linkami do zawodników
        if not stats:
            player_links = soup.select("a[href*='/zawodnik/'], a[href*='/player/']")
            for link in player_links[:50]:  # Ogranicz do 50
                name = link.get_text(strip=True)
                if not name:
                    continue
                # Szukaj wartości statystyki w sąsiednim elemencie
                parent = link.find_parent("li") or link.find_parent("tr")
                if not parent:
                    continue
                value_text = parent.get_text(strip=True)
                # Wyciągnij liczbę z całego wiersza
                value_match = re.search(r"(\d+[,.]?\d*)\s*$", value_text)
                if value_match:
                    value = _safe_float(value_match.group(1))
                    if value > 0:
                        stats.append({"name": name, "team": "", "value": value})
        
    except Exception as e:
        print(f"    ⚠️  Błąd pobierania {url}: {e}")
    
    return stats


def fetch_extra_player_stats() -> dict:
    """
    Pobiera rozszerzone statystyki zawodników z ukrytego API ekstraklasy.
    
    API endpoint: production-umpire-api.ekstraklasa.tisagroup.ch/api/v3/statistics
    Wymaga tokena autoryzacyjnego w headerze Authorization.
    
    Zwraca dict z statystykami: xg, shots, shots_on_target, key_passes, crosses, crosses_accurate
    """
    print("\n📊 Pobieram rozszerzone statystyki z API ekstraklasy...")
    print(f"   Token: {EXTRA_API_TOKEN[:20]}...")
    
    all_stats = {
        "xg": {},
        "shots": {},
        "shots_on_target": {},
        "key_passes": {},
        "crosses": {},
        "crosses_accurate": {},
    }
    
    try:
        params = dict(EXTRA_STATS_PARAMS)
        # Pobieramy WIELU zawodników - bez sortowania po xG żeby zwiększyć pokrycie
        params["page[size]"] = "300"  # zwiększ limit do 300 zawodników
        
        headers = {
            "Authorization": EXTRA_API_TOKEN,
            "Referer": "https://www.ekstraklasa.org/",
        }
        
        resp = requests.get(EXTRA_STATS_API, params=params, headers=headers, timeout=30)
        
        if resp.status_code != 200:
            print(f"   HTTP {resp.status_code} - spróbuję bez tokena")
            # Fallback: użyj starej metody (pusta)
            return all_stats
        
        data = resp.json()
        items = data.get("data", [])
        
        if not items:
            print("   Brak danych")
            return all_stats
        
        # Build lookup z included
        inc_map = {inc["id"]: inc for inc in data.get("included", [])}
        
        for item in items:
            values = item.get("attributes", {}).get("values", {})
            
            # Pobierz ID zawodnika z relationships
            rel = item.get("relationships", {})
            player_id = rel.get("resource", {}).get("data", {}).get("id")
            if not player_id:
                continue
            
            # Pobierz dane zawodnika z included
            player = inc_map.get(player_id, {})
            p_attrs = player.get("attributes", {})
            first_name = p_attrs.get("first_name", "")
            last_name = p_attrs.get("last_name", "")
            name = f"{first_name} {last_name}".strip()
            
            if not name:
                continue
            
            # Pobierz drużynę (z relationships)
            squad_rel = p_attrs.get("squad", {})
            squad_id = squad_rel.get("id") if isinstance(squad_rel, dict) else None
            if squad_id:
                squad = inc_map.get(str(squad_id), {})
                team_rel = squad.get("relationships", {}).get("team", {}).get("data", {})
                team_id = team_rel.get("id") if team_rel else None
                if team_id:
                    team = inc_map.get(str(team_id), {})
                    club_rel = team.get("relationships", {}).get("club", {}).get("data", {})
                    club_id = club_rel.get("id") if club_rel else None
                    if club_id:
                        club = inc_map.get(str(club_id), {})
                        team_name = club.get("attributes", {}).get("name", "")
                    else:
                        team_name = ""
                else:
                    team_name = ""
            else:
                team_name = ""
            
            # Suma minut do obliczenia per/90
            minutes = int(values.get("minutes_played") or 0)
            if minutes <= 0:
                continue
            
            # Dodaj statystyki (jako sumy, nie per/90 - przeliczymy później)
            # xG
            xg = float(values.get("expected_goals") or 0)
            if xg > 0:
                all_stats["xg"][name] = xg
            
            # Strzały
            shots = int(values.get("shots") or 0)
            if shots > 0:
                all_stats["shots"][name] = shots
            
            # Strzały celne
            shots_ot = int(values.get("shots_on_target") or 0)
            if shots_ot > 0:
                all_stats["shots_on_target"][name] = shots_ot
            
            # Podania kluczowe
            kp = int(values.get("key_passes") or 0)
            if kp > 0:
                all_stats["key_passes"][name] = kp
            
            # Dośrodkowania
            crosses = int(values.get("crosses") or 0)
            if crosses > 0:
                all_stats["crosses"][name] = crosses
            
            # Dośrodkowania celne
            crosses_acc = int(values.get("crosses_accurate") or 0)
            if crosses_acc > 0:
                all_stats["crosses_accurate"][name] = crosses_acc
        
        # Podsumowanie
        print(f"   ✓ xG: {len(all_stats['xg'])} graczy")
        print(f"   ✓ Strzały: {len(all_stats['shots'])}")
        print(f"   ✓ Strzały celne: {len(all_stats['shots_on_target'])}")
        print(f"   ✓ Podania kluczowe: {len(all_stats['key_passes'])}")
        print(f"   ✓ Dośrodkowania: {len(all_stats['crosses'])}")
        print(f"   ✓ Dośrodkowania celne: {len(all_stats['crosses_accurate'])}")
        
    except Exception as e:
        print(f"   ⚠️  Błąd: {e}")
    
    return all_stats


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
    
    # DEBUG: sprawdź dopasowanie i pokaż kilka przykładów
    sample_matches = []  # dokładne dopasowania
    fuzzy_matches = []  # fuzzy po last name
    sample_misses = []
    
    # Build last name lookup dla fuzzy matching
    last_name_map = {}  # last_name -> [(player_id, full_name), ...]
    for ln, pid, full in fantasy_names_normalized:
        if ln not in last_name_map:
            last_name_map[ln] = []
        last_name_map[ln].append((pid, full))
    
    for stat_name, stat_data in extra_stats.items():
        for raw_name in stat_data.keys():
            norm_name = _normalize_name(raw_name)
            player_id = normalized_lookup.get(norm_name) or normalized_lookup.get(raw_name.lower())
            
            if player_id:
                sample_matches.append((raw_name, player_id))
            else:
                # Fuzzy matching: szukaj po ostatnim imieniu
                api_last = norm_name.split()[-1] if norm_name else ""
                if api_last and api_last in last_name_map:
                    player_id = last_name_map[api_last][0][0]
                    fuzzy_matches.append((raw_name, player_id, api_last))
                else:
                    sample_misses.append(raw_name)
    
    print(f"   DEBUG: dokładne {len(sample_matches)}, fuzzy {len(fuzzy_matches)}")
    print(f"   DEBUG: przykłady dokładne: {sample_matches[:3]}")
    print(f"   DEBUG: przykłady fuzzy: {fuzzy_matches[:3]}")
    print(f"   DEBUG: niedopasowane (pierwsze 5): {sample_misses[:5]}")
    
    # Przygotuj statystyki per 90 dla każdego zawodnika
    stats_per90 = {}  # player_id -> {stat: per90}
    
    for stat_name, stat_data in extra_stats.items():
        if not stat_data:
            continue
        
        for raw_name, raw_value in stat_data.items():
            # Normalizuj nazwę z ekstraklasa.org
            norm_name = _normalize_name(raw_name)
            player_id = normalized_lookup.get(norm_name) or normalized_lookup.get(raw_name.lower())
            
            # Fuzzy fallback: szukaj po last name
            if not player_id:
                api_last = norm_name.split()[-1] if norm_name else ""
                if api_last and api_last in last_name_map:
                    player_id = last_name_map[api_last][0][0]  # bierz pierwszy match
            
            if not player_id:
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


def compute_fdr(ekstra_stats: dict, fixtures_data: dict, current_round: int = 0, num_rounds: int = 6) -> dict:
    """Oblicza osobne wskaźniki ATK i DEF rywala (1-5) dla każdego meczu.

    ATK rywala = siła ataku rywala (wysoki = rywal dużo strzela = źle dla Twoich obrońców)
    DEF rywala = siła obrony rywala (wysoki = rywal mało traci = źle dla Twoich napastników)

    Skala 1-5 (kwantyle):
      1 = najsłabszy (korzystny mecz)
      5 = najsilniejszy (trudny mecz)
    """
    teams = fixtures_data.get("teams", [])
    rounds = fixtures_data.get("rounds", [])
    matches = fixtures_data.get("matches", {})
    abbrevs = fixtures_data.get("abbrevs", {})

    if not teams or not rounds or not ekstra_stats:
        return {"teams": [], "gameweeks": [], "team_strengths": {}}

    # Sprawdź czy mamy dane dom/wyjazd
    sample = next(iter(ekstra_stats.values()), {})
    has_ha = "gf_home" in sample and sample.get("mp_home", 0) > 0

    # Oblicz średnie ligowe
    total_gf_home = total_ga_home = total_mp_home = 0
    total_gf_away = total_ga_away = total_mp_away = 0

    for team in teams:
        st = ekstra_stats.get(team)
        if not st:
            continue
        if has_ha:
            total_gf_home += st.get("gf_home", 0)
            total_ga_home += st.get("ga_home", 0)
            total_mp_home += st.get("mp_home", 0)
            total_gf_away += st.get("gf_away", 0)
            total_ga_away += st.get("ga_away", 0)
            total_mp_away += st.get("mp_away", 0)
        else:
            mp = st.get("mp", 0) or 1
            total_gf_home += st["gf"]
            total_ga_home += st["ga"]
            total_mp_home += mp
            total_gf_away += st["gf"]
            total_ga_away += st["ga"]
            total_mp_away += mp

    avg_gf_home = total_gf_home / total_mp_home if total_mp_home else 1
    avg_ga_home = total_ga_home / total_mp_home if total_mp_home else 1
    avg_gf_away = total_gf_away / total_mp_away if total_mp_away else 1
    avg_ga_away = total_ga_away / total_mp_away if total_mp_away else 1

    # Siła ataku i obrony każdej drużyny
    team_strengths = {}
    for team in teams:
        st = ekstra_stats.get(team)
        if not st:
            team_strengths[team] = {"attack_h": 1.0, "attack_a": 1.0, "defense_h": 1.0, "defense_a": 1.0}
            continue

        if has_ha:
            mp_h = st.get("mp_home", 1) or 1
            mp_a = st.get("mp_away", 1) or 1
            gf_h_avg = st.get("gf_home", 0) / mp_h
            ga_h_avg = st.get("ga_home", 0) / mp_h
            gf_a_avg = st.get("gf_away", 0) / mp_a
            ga_a_avg = st.get("ga_away", 0) / mp_a
        else:
            mp = st.get("mp", 1) or 1
            gf_avg = st["gf"] / mp
            ga_avg = st["ga"] / mp
            gf_h_avg = gf_a_avg = gf_avg
            ga_h_avg = ga_a_avg = ga_avg

        team_strengths[team] = {
            "attack_h": round(gf_h_avg / avg_gf_home, 2) if avg_gf_home else 1.0,
            "attack_a": round(gf_a_avg / avg_gf_away, 2) if avg_gf_away else 1.0,
            "defense_h": round(ga_h_avg / avg_ga_home, 2) if avg_ga_home else 1.0,
            "defense_a": round(ga_a_avg / avg_ga_away, 2) if avg_ga_away else 1.0,
        }

    # Określ nadchodzące kolejki na podstawie dat meczów
    today = datetime.now()
    current_year = today.year

    def _round_is_past(round_num):
        """Sprawdza czy wszystkie mecze w kolejce już się odbyły."""
        ms = matches.get(str(round_num), [])
        if not ms:
            return True
        for m in ms:
            date_str = m.get("date", "")
            if not date_str:
                return False
            try:
                day, month = date_str.split(".")
                # Zakładamy bieżący rok; dla meczów lip-gru może być rok wcześniejszy
                match_date = datetime(current_year, int(month), int(day))
                if int(month) >= 7 and today.month <= 6:
                    match_date = datetime(current_year - 1, int(month), int(day))
                if match_date >= today:
                    return False  # Jest mecz w przyszłości
            except (ValueError, TypeError):
                return False
        return True

    upcoming = [r for r in rounds if not _round_is_past(r)]
    if not upcoming:
        upcoming = rounds[-num_rounds:]  # fallback: ostatnie kolejki
    shown_rounds = upcoming[:num_rounds]

    # Zbierz surowe wartości ATK i DEF rywala dla kwantyli
    raw_atk_vals = []
    raw_def_vals = []
    fixture_map = {}  # (team, round) -> {atk_raw, def_raw}

    for r in shown_rounds:
        ms = matches.get(str(r), [])
        for m in ms:
            home_team = m["home"]
            away_team = m["away"]
            opp_away = team_strengths.get(away_team, {"attack_a": 1.0, "defense_a": 1.0})
            opp_home = team_strengths.get(home_team, {"attack_h": 1.0, "defense_h": 1.0})

            # Dla gospodarza: rywal gra na wyjeździe
            atk_raw_h = opp_away["attack_a"]   # atak wyjazdowy rywala
            def_raw_h = opp_away["defense_a"]   # obrona wyjazdowa rywala (GA-based)

            # Dla gościa: rywal gra u siebie
            atk_raw_a = opp_home["attack_h"]    # atak domowy rywala
            def_raw_a = opp_home["defense_h"]   # obrona domowa rywala (GA-based)

            raw_atk_vals.extend([atk_raw_h, atk_raw_a])
            raw_def_vals.extend([def_raw_h, def_raw_a])
            fixture_map[(home_team, r)] = {"atk": atk_raw_h, "def": def_raw_h}
            fixture_map[(away_team, r)] = {"atk": atk_raw_a, "def": def_raw_a}

    # Kwantyle dla ATK (direct: wysoki attack_strength → wysoki rating 5)
    def _quantile_thresholds(vals):
        if not vals:
            return [0.8, 0.95, 1.05, 1.2]
        s = sorted(vals)
        n = len(s)
        return [s[max(0, int(n * 0.2) - 1)], s[max(0, int(n * 0.4) - 1)],
                s[max(0, int(n * 0.6) - 1)], s[max(0, int(n * 0.8) - 1)]]

    atk_thr = _quantile_thresholds(raw_atk_vals)
    def_thr = _quantile_thresholds(raw_def_vals)

    def _val_to_rating(val, thr):
        """Direct: niska wartość → rating 1, wysoka → rating 5."""
        if val <= thr[0]: return 1
        if val <= thr[1]: return 2
        if val <= thr[2]: return 3
        if val <= thr[3]: return 4
        return 5

    def _val_to_rating_inv(val, thr):
        """Inverted: niska wartość → rating 5 (silna obrona), wysoka → rating 1."""
        if val <= thr[0]: return 5
        if val <= thr[1]: return 4
        if val <= thr[2]: return 3
        if val <= thr[3]: return 2
        return 1

    # Buduj dane per drużyna
    fdr_teams = []
    for team in teams:
        ab = abbrevs.get(team, team[:3].upper())
        fixtures_list = []
        total_atk = 0
        total_def = 0
        for r in shown_rounds:
            ms = matches.get(str(r), [])
            fixture_info = None
            for m in ms:
                if m["home"] == team:
                    fixture_info = {"opponent": m["away"], "home": True, "date": m.get("date", "")}
                    break
                elif m["away"] == team:
                    fixture_info = {"opponent": m["home"], "home": False, "date": m.get("date", "")}
                    break
            if fixture_info:
                raw = fixture_map.get((team, r), {"atk": 1.0, "def": 1.0})
                atk_r = _val_to_rating(raw["atk"], atk_thr)
                # DEF: niska defense_strength = mało bramek traci = silna obrona = rating 5
                def_r = _val_to_rating_inv(raw["def"], def_thr)
                total_atk += atk_r
                total_def += def_r
                opp_ab = abbrevs.get(fixture_info["opponent"], fixture_info["opponent"][:3].upper())
                fixtures_list.append({
                    "gw": r,
                    "opponent": fixture_info["opponent"],
                    "opponent_short": opp_ab,
                    "home": fixture_info["home"],
                    "atk": atk_r,
                    "def": def_r,
                    "date": fixture_info["date"],
                })
            else:
                fixtures_list.append({"gw": r, "opponent": "", "opponent_short": "—", "home": True, "atk": 0, "def": 0, "date": ""})

        fdr_teams.append({
            "name": team,
            "short": ab,
            "total_atk": total_atk,
            "total_def": total_def,
            "fixtures": fixtures_list,
        })

    if shown_rounds:
        print(f"  📊 FDR: obliczono ATK/DEF dla {len(fdr_teams)} drużyn, kolejki K{shown_rounds[0]}-K{shown_rounds[-1]}")
    else:
        print("  📊 FDR: brak nadchodzących kolejek")

    return {
        "teams": fdr_teams,
        "gameweeks": shown_rounds,
        "team_strengths": {t: team_strengths.get(t, {}) for t in teams},
    }


MONTHS_PL = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
}

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
            date_match = re.search(r"(\d{1,2})\s+(\w+),\s*(\d{1,2}):(\d{2})\s*$", line)
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
                    if home and away and len(home) > 2 and not re.match(r'^\d', home):
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
    duets_data: list[dict],
    fixtures_data: dict,
    ekstra_stats: dict,
    fdr_data: dict,
    transfers_data: dict,
    predictions_data: list[dict],
    accuracy_history: list[dict],
    tuned_params: dict,
    league_history: dict,
    newsletter_data: list,
    timestamp: str,
    filename: str,
    has_archive: bool = False,
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
    duets_data_json = json.dumps(duets_data or [], ensure_ascii=False)
    fixtures_json = json.dumps(fixtures_data, ensure_ascii=False)
    ekstra_stats_json = json.dumps(ekstra_stats, ensure_ascii=False)
    fdr_data_json = json.dumps(fdr_data, ensure_ascii=False)
    transfers_data_json = json.dumps(transfers_data or {}, ensure_ascii=False)
    predictions_json = json.dumps(predictions_data or [], ensure_ascii=False)
    accuracy_json = json.dumps(accuracy_history or [], ensure_ascii=False)
    tuned_params_json = json.dumps(tuned_params or None, ensure_ascii=False)
    league_history_json = json.dumps(league_history or {"rounds": []}, ensure_ascii=False)
    newsletter_json = json.dumps(newsletter_data or [], ensure_ascii=False)
    has_season = len((league_history or {}).get("rounds", [])) > 0
    has_fixtures = len(fixtures_data.get("rounds", [])) > 0
    has_newsletter = len(newsletter_data or []) > 0
    has_transfers = bool((transfers_data or {}).get("transfers_in") or (transfers_data or {}).get("transfers_out"))
    has_predictions = len(predictions_data or []) > 0
    has_accuracy = len(accuracy_history or []) > 0

    # For stat cards
    all_tier = tiers.get("all", tiers.get("top100", tiers.get("top10", {})))
    all_owns = all_tier.get("ownership", []) if all_tier else []
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
/* ============================================================
   MOTYW CIEMNY (domyślny) — oparty na design.md
   ============================================================ */
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ background: #131313; }}
body {{
  min-height: 100vh;
  background: #131313;
  color: #ffffff;
  font-family: 'DM Sans', -apple-system, sans-serif;
  padding: 24px 16px;
}}
.container {{ max-width: 1400px; margin: 0 auto; padding: 0 16px; }}
@media (max-width: 768px) {{ .container {{ max-width: 100%; padding: 0 12px; }} }}
@media (min-width: 2000px) {{ .container {{ max-width: 1600px; }} }}

/* Header + Theme Toggle */
.header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }}
.header-left {{ display: flex; align-items: center; gap: 14px; }}
.logo {{ width: 48px; height: 48px; border-radius: 10px; object-fit: contain; }}
.header h1 {{ font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }}
.header .sub {{ font-size: 12px; color: #949494; margin: 0; }}

/* Theme Toggle Button */
.theme-toggle {{
  background: #2d2d2d;
  border: 1px solid #3cffd0;
  border-radius: 24px;
  color: #3cffd0;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.2s;
}}
.theme-toggle:hover {{ background: #3cffd0; color: #131313; }}

/* Stat Cards */
.stats-row {{ display: flex; gap: 12px; margin-top: 16px; overflow-x: auto; padding-bottom: 4px; flex-wrap: wrap; }}
.stat-card {{
  background: #2d2d2d;
  border: 1px solid #3cffd0;
  border-radius: 20px;
  padding: 16px 20px;
  flex: 1 1 calc(25% - 12px); min-width: 140px; max-width: 250px;
}}
.stat-card .val {{ font-size: 24px; font-weight: 800; }}
.stat-card .label {{ font-size: 11px; color: #949494; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.8px; }}
.stat-card .sub {{ font-size: 11px; color: #949494; margin-top: 4px; }}
.accent-cyan {{ border-left: 3px solid #3cffd0; }}
.accent-cyan .val {{ color: #3cffd0; }}
.accent-gold {{ border-left: 3px solid #fbbf24; }}
.accent-gold .val {{ color: #fbbf24; }}
.accent-green {{ border-left: 3px solid #10b981; }}
.accent-green .val {{ color: #10b981; }}
.accent-purple {{ border-left: 3px solid #5200ff; }}
.accent-purple .val {{ color: #5200ff; }}

/* Tabs */
.tabs {{ display: flex; gap: 4px; border-bottom: 1px solid #2d2d2d; flex-wrap: wrap; }}
.tab {{
  background: transparent; border: none; border-bottom: 2px solid transparent;
  color: #949494; padding: 10px 18px; font-size: 13px; font-weight: 600;
  cursor: pointer; border-radius: 8px 8px 0 0; transition: all 0.2s;
  font-family: inherit;
}}
.tab.active {{ background: #2d2d2d; border-bottom-color: #3cffd0; color: #ffffff; }}
.tab:hover {{ color: #3860be; }}
.archive-link {{ text-decoration: none; display: inline-block; }}
.archive-link.disabled {{ opacity: 0.4; pointer-events: none; cursor: default; }}

/* Filters */
.filters-row {{ display: flex; gap: 8px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
.pos-filters {{ display: flex; gap: 4px; align-items: center; }}
.pos-btn {{
  background: transparent; border: 1px solid #2d2d2d; color: #949494;
  padding: 4px 10px; font-size: 11px; font-weight: 700; cursor: pointer;
  border-radius: 6px; font-family: inherit; transition: all 0.15s;
}}
.pos-btn.active {{ border-color: transparent; color: #131313; }}
.pos-btn.active[data-pos="ALL"] {{ background: #3cffd0; }}
.pos-btn.active[data-pos="BR"] {{ background: #f59e0b; }}
.pos-btn.active[data-pos="OBR"] {{ background: #3b82f6; }}
.pos-btn.active[data-pos="POM"] {{ background: #10b981; }}
.pos-btn.active[data-pos="NAP"] {{ background: #ef4444; }}
.scope-toggle {{ display: flex; gap: 0; border-radius: 8px; overflow: hidden; border: 1px solid #2d2d2d; }}
.scope-btn {{
  background: transparent; border: none; color: #949494;
  padding: 6px 14px; font-size: 12px; font-weight: 600; cursor: pointer;
  font-family: inherit; transition: all 0.15s;
}}
.scope-btn.active {{ background: #3cffd0; color: #131313; }}

/* Section Title */
.section-title {{ display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }}
.section-title h2 {{ font-size: 16px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: #ffffff; }}
.section-title .line {{ flex: 1; height: 1px; background: linear-gradient(90deg, #2d2d2d, transparent); }}

/* Data Table */
.data-table {{ background: #2d2d2d; border-radius: 12px; overflow: hidden; width: 100%; overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
thead tr {{ background: #131313; }}
th {{ padding: 10px 14px; color: #949494; font-weight: 600; font-size: 11px; text-transform: uppercase; white-space: nowrap; }}
th.sortable {{ cursor: pointer; user-select: none; }}
th.sortable:hover {{ color: #ffffff; }}
th.sortable[title] {{ cursor: help; border-bottom: 1px dashed #2d2d2d; }}
td {{ padding: 10px 14px; border-top: 1px solid #131313; white-space: nowrap; }}
tr.highlight {{ background: rgba(251,191,36,0.06); }}

/* Badge pozycji */
.pos-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; color: #131313; }}
.pos-BR, .pos-1 {{ background: #f59e0b; }}
.pos-OBR, .pos-2 {{ background: #3b82f6; }}
.pos-POM, .pos-3 {{ background: #10b981; }}
.pos-NAP, .pos-4 {{ background: #ef4444; }}

/* Kapitan */
.captain-badge {{ display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; background: linear-gradient(135deg, #fbbf24, #f59e0b); color: #131313; font-size: 11px; font-weight: 800; }}

/* Bar */
.bar-wrap {{ display: flex; align-items: center; gap: 8px; }}
.bar-bg {{ width: 80px; height: 6px; background: #131313; border-radius: 3px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.6s ease; }}
.bar-val {{ font-size: 13px; color: #949494; min-width: 38px; text-align: right; }}

/* Tab Content */
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.footer {{ text-align: center; margin-top: 32px; color: #949494; font-size: 12px; }}
.text-right {{ text-align: right; }}
.text-center {{ text-align: center; }}
.text-left {{ text-align: left; }}
.fw-700 {{ font-weight: 700; }}
.fw-600 {{ font-weight: 600; }}
.c-muted {{ color: #949494; }}
.c-dim {{ color: #949494; }}
.empty-msg {{ padding: 40px; text-align: center; color: #949494; }}
.clickable {{ cursor: pointer; }}
.clickable:hover {{ color: #3860be; }}

/* ============================================================
   MOTYW JASNY (theme-fantasy) — aktywowany klasą html.theme-fantasy
   ============================================================ */
html.theme-fantasy {{ background: #f5f5f5; }}
html.theme-fantasy body {{ background: #f5f5f5; color: #131313; }}

html.theme-fantasy .header-left h1 {{ color: #131313; }}
html.theme-fantasy .header .sub {{ color: #5a5a5a; }}
html.theme-fantasy .theme-toggle {{ background: #ffffff; border-color: #309875; color: #309875; }}
html.theme-fantasy .theme-toggle:hover {{ background: #309875; color: #ffffff; }}

html.theme-fantasy .stat-card {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .stat-card .val {{ color: #131313; }}
html.theme-fantasy .stat-card .label {{ color: #5a5a5a; }}
html.theme-fantasy .stat-card .sub {{ color: #5a5a5a; }}

html.theme-fantasy .tab {{ color: #5a5a5a; }}
html.theme-fantasy .tab.active {{ background: #ffffff; border-bottom-color: #309875; color: #131313; }}
html.theme-fantasy .tab:hover {{ color: #3860be; }}
html.theme-fantasy .archive-link.disabled {{ opacity: 0.4; }}

html.theme-fantasy .pos-btn {{ border-color: #e0e0e0; color: #5a5a5a; }}
html.theme-fantasy .pos-btn.active {{ color: #ffffff; }}
html.theme-fantasy .scope-btn {{ color: #5a5a5a; }}
html.theme-fantasy .scope-btn.active {{ background: #309875; }}

html.theme-fantasy .section-title h2 {{ color: #131313; }}
html.theme-fantasy .section-title .line {{ background: linear-gradient(90deg, #e0e0e0, transparent); }}

html.theme-fantasy .data-table {{ background: #ffffff; border: 1px solid #e0e0e0; }}
html.theme-fantasy thead tr {{ background: #f5f5f5; }}
html.theme-fantasy th {{ color: #5a5a5a; }}
html.theme-fantasy th.sortable:hover {{ color: #131313; }}
html.theme-fantasy td {{ border-top-color: #e0e0e0; }}
html.theme-fantasy tr.highlight {{ background: rgba(48,152,117,0.06); }}

html.theme-fantasy .pos-badge {{ color: #131313; }}
html.theme-fantasy .captain-badge {{ color: #131313; }}
html.theme-fantasy .bar-bg {{ background: #e0e0e0; }}
html.theme-fantasy .bar-val {{ color: #5a5a5a; }}

html.theme-fantasy .footer {{ color: #5a5a5a; }}
html.theme-fantasy .c-muted {{ color: #5a5a5a; }}
html.theme-fantasy .c-dim {{ color: #5a5a5a; }}
html.theme-fantasy .empty-msg {{ color: #5a5a5a; }}
html.theme-fantasy .clickable:hover {{ color: #3860be; }}

/* Więcej komponentów dla obu motywów */
.roster-chip {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #2d2d2d;
  border: 1px solid #3cffd0;
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
  color: #ffffff;
}}
html.theme-fantasy .roster-chip {{ background: #ffffff; border-color: #e0e0e0; color: #131313; }}

.roster-chip .rc-badge {{ font-size: 9px; font-weight: 800; border-radius: 3px; padding: 1px 4px; }}
.rc-cap {{ background: #fbbf24; color: #131313; }}
.rc-res {{ background: #475569; color: #ffffff; }}
.rc-xi {{ background: #3cffd0; color: #131313; }}

.form-panel {{ background: #131313; border: 1px solid #2d2d2d; border-radius: 8px; padding: 12px 16px; display: flex; align-items: flex-end; gap: 16px; flex-wrap: wrap; }}
html.theme-fantasy .form-panel {{ background: #f5f5f5; border-color: #e0e0e0; }}

.form-chart {{ display: inline-flex; align-items: flex-end; gap: 3px; height: 48px; vertical-align: middle; }}
.form-chart.mini {{ height: 24px; gap: 2px; }}
.form-chart.mini .form-bar {{ width: 8px; }}
.form-chart.mini .form-val {{ font-size: 8px; top: -12px; color: #949494; font-weight: 500; }}
.form-chart.mini .form-rnd {{ display: none; }}
.form-bar {{ width: 14px; border-radius: 3px 3px 0 0; min-height: 2px; position: relative; display: inline-flex; flex-direction: column; align-items: center; justify-content: flex-start; }}
.form-bar .form-val {{ position: absolute; top: -16px; font-size: 10px; color: #ffffff; font-weight: 600; white-space: nowrap; }}
.form-bar .form-rnd {{ position: absolute; bottom: -16px; font-size: 9px; color: #949494; white-space: nowrap; }}
.form-bar.not-played {{ opacity: 0.35; border: 1px dashed #475569; background: transparent !important; }}
.form-avg {{ display: flex; flex-direction: column; align-items: center; margin-left: 8px; }}
.form-avg .fa-val {{ font-size: 20px; font-weight: 800; color: #3cffd0; }}
.form-avg .fa-lbl {{ font-size: 10px; color: #949494; text-transform: uppercase; letter-spacing: 0.5px; }}
html.theme-fantasy .form-avg .fa-val {{ color: #309875; }}
html.theme-fantasy .form-avg .fa-lbl {{ color: #5a5a5a; }}

.detail-row td {{ padding: 0 !important; border-top: none !important; }}
.detail-panel {{ background: #131313; border: 1px solid #2d2d2d; border-radius: 8px; padding: 12px 16px; margin: 4px 0 8px; display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-start; }}
html.theme-fantasy .detail-panel {{ background: #f5f5f5; border-color: #e0e0e0; }}

.detail-section {{ display: flex; flex-direction: column; gap: 4px; }}
.detail-section .ds-label {{ font-size: 10px; color: #949494; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }}
html.theme-fantasy .detail-section .ds-label {{ color: #5a5a5a; }}

.team-list {{ display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }}
.team-list-item {{ background: #2d2d2d; border: 1px solid #3cffd0; border-radius: 8px; }}
.team-list-item.active {{ border-color: #3cffd0; }}
html.theme-fantasy .team-list-item {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .team-list-item.active {{ border-color: #309875; }}

.team-list-header {{ display: flex; align-items: center; gap: 12px; padding: 10px 16px; cursor: pointer; transition: background 0.15s; }}
.team-list-header:hover {{ background: #3cffd0; }}
html.theme-fantasy .team-list-header:hover {{ background: #309875; }}
.team-list-rank {{ font-size: 13px; font-weight: 800; color: #3cffd0; min-width: 32px; }}
.team-list-name {{ font-size: 14px; font-weight: 700; color: #ffffff; flex: 1; text-transform: capitalize; }}
.team-list-pts {{ font-size: 12px; color: #949494; font-weight: 600; }}
.team-list-count {{ font-size: 11px; color: #949494; }}
html.theme-fantasy .team-list-rank {{ color: #309875; }}
html.theme-fantasy .team-list-name {{ color: #131313; }}
html.theme-fantasy .team-list-pts {{ color: #5a5a5a; }}
html.theme-fantasy .team-list-count {{ color: #5a5a5a; }}
html.theme-fantasy .team-stat {{ color: #5a5a5a; }}
html.theme-fantasy .team-stat b {{ color: #131313; }}
html.theme-fantasy .team-list-arrow {{ color: #949494; }}
html.theme-fantasy .diff-pos {{ background: rgba(16,185,129,0.1); }}
html.theme-fantasy .diff-neg {{ background: rgba(239,68,68,0.1); }}
html.theme-fantasy .diff-zero {{ background: rgba(100,116,139,0.1); }}

/* Fixture Ticker - Light Theme */
html.theme-fantasy .ft-table th {{ color: #5a5a5a; border-bottom-color: #e0e0e0; }}
html.theme-fantasy .ft-table td {{ border-bottom-color: #e0e0e0; }}
html.theme-fantasy .ft-table td.ft-team {{ color: #131313; }}
html.theme-fantasy .ft-table td.ft-team:hover {{ color: #309875; }}
html.theme-fantasy .ft-cell {{ background: #f5f5f5; color: #131313; }}
html.theme-fantasy .ft-cell .ft-ha {{ opacity: 0.7; }}
html.theme-fantasy .ft-cell-team {{ color: #131313; }}
html.theme-fantasy .ft-cell-team .ft-ha {{ opacity: 0.7; }}
html.theme-fantasy .ft-val {{ background: #e0e0e0; color: #131313; }}
html.theme-fantasy .ft-legend {{ color: #5a5a5a; }}
html.theme-fantasy .ft-legend-swatch {{ border: 1px solid #e0e0e0; }}

/* Rating Modal - Light Theme */
html.theme-fantasy .ft-modal-bg {{ background: rgba(0,0,0,0.4); }}
html.theme-fantasy .ft-modal {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .ft-modal h3 {{ color: #131313; }}
html.theme-fantasy .ft-modal-close {{ color: #5a5a5a; }}
html.theme-fantasy .ft-modal-close:hover {{ color: #131313; }}

/* FDR Tiles - Light Theme */
html.theme-fantasy .fdr-table th {{ color: #5a5a5a; border-bottom-color: #e0e0e0; }}
html.theme-fantasy .fdr-table td {{ border-bottom-color: #e0e0e0; }}
html.theme-fantasy .fdr-legend {{ color: #5a5a5a; }}
html.theme-fantasy .fdr-cell-team {{ color: #131313; }}
html.theme-fantasy .fdr-cell-team .fdr-ha {{ opacity: 0.7; }}
html.theme-fantasy .fdr-mini {{ background: #e0e0e0; color: #131313; }}

/* Fixture Planner - Light Theme */
html.theme-fantasy .fp-section {{ border-top-color: #e0e0e0; }}
html.theme-fantasy .fp-controls label {{ color: #5a5a5a; }}
html.theme-fantasy .fp-controls select {{ background: #ffffff; border-color: #e0e0e0; color: #131313; }}
html.theme-fantasy .fp-mode-btns {{ border-color: #e0e0e0; }}
html.theme-fantasy .fp-mode-btn {{ color: #5a5a5a; }}
html.theme-fantasy .fp-mode-btn.active {{ background: #309875; color: #ffffff; }}
html.theme-fantasy .fp-table th {{ color: #5a5a5a; border-bottom-color: #e0e0e0; }}
html.theme-fantasy .fp-table th:hover {{ color: #131313; }}
html.theme-fantasy .fp-table th.fp-sorted {{ color: #309875; }}
html.theme-fantasy .fp-table td {{ border-bottom-color: #e0e0e0; }}
html.theme-fantasy .fp-table td.fp-team-cell {{ color: #131313; }}
html.theme-fantasy .fp-table td.fp-team-cell:hover {{ color: #309875; }}
html.theme-fantasy .fp-table td.fp-team-cell.fp-selected {{ background: rgba(48,152,117,0.1); color: #309875; }}
html.theme-fantasy .fp-tile {{ background: #f5f5f5; }}
html.theme-fantasy .fp-rotation {{ background: #ffffff; border-color: #e0e0e0; color: #131313; }}
html.theme-fantasy .fp-rotation .fp-rot-label {{ color: #5a5a5a; }}
html.theme-fantasy .fp-summary {{ background: #ffffff; border-color: #e0e0e0; color: #131313; }}

/* Transfers Tab - Light Theme */
html.theme-fantasy .transfers-header h3 {{ color: #131313; }}
html.theme-fantasy .tr-gw-badge {{ background: #f5f5f5; border-color: #e0e0e0; color: #5a5a5a; }}

/* Predictions Tab - Light Theme */
html.theme-fantasy .pred-val {{ background: #f5f5f5; color: #131313; }}
html.theme-fantasy .pred-fdr-tile {{ background: #e0e0e0; color: #131313; }}
html.theme-fantasy .pred-fdr-used {{ background: rgba(0,0,0,0.05); }}
html.theme-fantasy .pred-legend {{ background: #f5f5f5; color: #5a5a5a; }}
html.theme-fantasy .pred-legend b {{ color: #131313; }}

/* Newsletter - Light Theme */
html.theme-fantasy .nl-card {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .nl-round {{ color: #309875; }}
html.theme-fantasy .nl-date {{ color: #949494; }}
html.theme-fantasy .nl-model {{ color: #949494; }}
html.theme-fantasy .nl-text {{ color: #131313; }}

/* Season Tracker - Light Theme */
html.theme-fantasy .season-wrap {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .season-btn {{ background: transparent; border: 1px solid #e0e0e0; color: #5a5a5a; }}
html.theme-fantasy .season-btn.active {{ background: #309875; color: #ffffff; }}
html.theme-fantasy .season-tooltip {{ background: #ffffff; border-color: #e0e0e0; color: #131313; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
html.theme-fantasy .season-legend-item {{ color: #5a5a5a; }}
html.theme-fantasy .trend-up {{ color: #10b981; }}
html.theme-fantasy .trend-down {{ color: #ef4444; }}
html.theme-fantasy .trend-flat {{ color: #949494; }}

/* Compare Tab - Light Theme */
html.theme-fantasy .cmp-search-input {{ background: #ffffff; border-color: #e0e0e0; color: #131313; }}
html.theme-fantasy .cmp-search-input:focus {{ border-color: #309875; }}
html.theme-fantasy .cmp-search-input::placeholder {{ color: #949494; }}
html.theme-fantasy .cmp-autocomplete {{ background: #ffffff; border-color: #e0e0e0; box-shadow: 0 8px 24px rgba(0,0,0,0.15); }}
html.theme-fantasy .cmp-ac-item {{ color: #131313; }}
html.theme-fantasy .cmp-ac-item:hover {{ background: #f5f5f5; }}
html.theme-fantasy .cmp-clear-btn {{ background: #e0e0e0; color: #5a5a5a; }}
html.theme-fantasy .cmp-chip {{ background: #f5f5f5; border-color: #e0e0e0; color: #131313; }}
html.theme-fantasy .cmp-table {{ background: #ffffff; }}
html.theme-fantasy .cmp-table th {{ background: #f5f5f5; color: #5a5a5a; border-bottom-color: #e0e0e0; }}
html.theme-fantasy .cmp-table td {{ color: #131313; border-top-color: #e0e0e0; }}
html.theme-fantasy .cmp-rot-wrap {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .cmp-fdr-table {{ color: #131313; }}
html.theme-fantasy .cmp-fdr-table th {{ color: #5a5a5a; border-bottom-color: #e0e0e0; }}

.team-list-arrow {{ font-size: 10px; color: #64748b; margin-left: 4px; }}
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
/* Fixture Ticker */
.ft-table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.ft-table th {{ padding: 6px 4px; text-align: center; font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #334155; }}
.ft-table th.ft-round {{ min-width: 80px; }}
.ft-table td {{ padding: 5px 4px; text-align: center; border-bottom: 1px solid #1e293b; }}
.ft-table td.ft-team {{ text-align: left; font-weight: 700; white-space: nowrap; padding-left: 8px; cursor: pointer; }}
.ft-table td.ft-team:hover {{ color: #22d3ee; }}
.ft-cell {{ border-radius: 4px; padding: 4px 6px; font-weight: 600; font-size: 12px; display: inline-block; min-width: 52px; text-align: center; }}
.ft-cell .ft-ha {{ font-size: 10px; font-weight: 400; opacity: 0.7; }}
.ft-cell-dual {{ display: flex; flex-direction: column; align-items: center; gap: 2px; min-width: 68px; }}
.ft-cell-team {{ font-size: 11px; font-weight: 600; color: #e2e8f0; white-space: nowrap; }}
.ft-cell-team .ft-ha {{ font-size: 10px; font-weight: 400; opacity: 0.7; }}
.ft-cell-vals {{ display: flex; gap: 2px; }}
.ft-val {{ border-radius: 3px; padding: 2px 5px; font-weight: 700; font-size: 10px; min-width: 28px; text-align: center; }}
.ft-legend {{ display: flex; gap: 12px; align-items: center; margin-bottom: 12px; font-size: 12px; color: #94a3b8; flex-wrap: wrap; }}
.ft-legend-item {{ display: flex; align-items: center; gap: 4px; }}
.ft-legend-swatch {{ width: 16px; height: 16px; border-radius: 3px; }}
/* Rating modal */
.ft-modal-bg {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); z-index: 1000; display: flex; align-items: center; justify-content: center; }}
.ft-modal {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px 32px; min-width: 340px; max-width: 90vw; position: relative; }}
.ft-modal h3 {{ margin: 0 0 16px; font-size: 18px; }}
.ft-modal-close {{ position: absolute; top: 12px; right: 16px; background: none; border: none; color: #94a3b8; font-size: 20px; cursor: pointer; }}
.ft-modal-close:hover {{ color: #e2e8f0; }}
/* FDR tiles */
.fdr-table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.fdr-table th {{ padding: 8px 6px; text-align: center; font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #334155; }}
.fdr-table td {{ padding: 5px 4px; text-align: center; border-bottom: 1px solid #1e293b; }}
.fdr-table td.fdr-team {{ text-align: left; font-weight: 700; white-space: nowrap; padding-left: 8px; }}
.fdr-sum {{ font-weight: 800; font-size: 15px; }}
.fdr-legend {{ display: flex; gap: 8px; align-items: center; margin-bottom: 14px; font-size: 12px; color: #94a3b8; flex-wrap: wrap; }}
.fdr-legend-item {{ display: flex; align-items: center; gap: 5px; }}
.fdr-legend-swatch {{ width: 20px; height: 20px; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }}
.fdr-cell {{ display: flex; flex-direction: column; align-items: center; gap: 3px; min-width: 80px; }}
.fdr-cell-team {{ font-size: 12px; font-weight: 600; color: #e2e8f0; white-space: nowrap; }}
.fdr-cell-team .fdr-ha {{ font-size: 10px; font-weight: 400; opacity: 0.7; }}
.fdr-cell-vals {{ display: flex; gap: 3px; }}
.fdr-mini {{ border-radius: 4px; padding: 2px 6px; font-size: 12px; font-weight: 700; min-width: 36px; text-align: center; display: inline-flex; align-items: center; gap: 2px; }}
.fdr-mini .fdr-lbl {{ font-size: 8px; font-weight: 600; opacity: 0.8; letter-spacing: 0.3px; }}
/* Fixture Planner */
.fp-section {{ margin-top: 32px; border-top: 2px solid #334155; padding-top: 24px; }}
.fp-controls {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }}
.fp-controls label {{ font-size: 12px; color: #94a3b8; font-weight: 600; }}
.fp-controls select {{ background: #0f172a; border: 1px solid #334155; color: #e2e8f0; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-family: inherit; cursor: pointer; }}
.fp-mode-btns {{ display: flex; gap: 0; border-radius: 8px; overflow: hidden; border: 1px solid #334155; }}
.fp-mode-btn {{ background: transparent; border: none; color: #64748b; padding: 5px 12px; font-size: 11px; font-weight: 700; cursor: pointer; font-family: inherit; transition: all 0.15s; }}
.fp-mode-btn.active {{ background: #22d3ee; color: #0f172a; }}
.fp-table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.fp-table th {{ padding: 8px 6px; text-align: center; font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #334155; cursor: pointer; user-select: none; }}
.fp-table th:hover {{ color: #e2e8f0; }}
.fp-table th.fp-sorted {{ color: #22d3ee; }}
.fp-table td {{ padding: 5px 4px; text-align: center; border-bottom: 1px solid #1e293b; }}
.fp-table td.fp-team-cell {{ text-align: left; font-weight: 700; white-space: nowrap; padding-left: 8px; cursor: pointer; }}
.fp-table td.fp-team-cell:hover {{ color: #22d3ee; }}
.fp-table td.fp-team-cell.fp-selected {{ background: rgba(34,211,238,0.12); color: #22d3ee; }}
.fp-tile {{ border-radius: 4px; padding: 4px 6px; font-weight: 600; font-size: 11px; display: inline-block; min-width: 56px; text-align: center; }}
.fp-tile .fp-ha {{ font-size: 9px; font-weight: 400; opacity: 0.7; }}
.fp-avg-cell {{ font-weight: 800; font-size: 14px; }}
.fp-rotation {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px 16px; margin-top: 12px; font-size: 13px; color: #e2e8f0; line-height: 1.6; }}
.fp-rotation .fp-rot-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 6px; }}
.fp-summary {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 14px 18px; margin-top: 16px; font-size: 13px; line-height: 2; color: #e2e8f0; }}
.fp-summary-line {{ display: flex; align-items: center; gap: 6px; }}
/* Transfers tab */
.transfers-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
@media (max-width: 768px) {{ .transfers-grid {{ grid-template-columns: 1fr; }} }}
.transfers-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }}
.transfers-header h3 {{ font-size: 14px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase; }}
.tr-filters-row {{ display: flex; gap: 8px; margin-bottom: 14px; align-items: center; flex-wrap: wrap; }}
.tr-gw-badge {{ background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 4px 12px; font-size: 12px; color: #94a3b8; font-weight: 600; }}
.price-up {{ color: #10b981; font-size: 11px; font-weight: 700; }}
.price-down {{ color: #ef4444; font-size: 11px; font-weight: 700; }}
.price-neutral {{ color: #64748b; font-size: 11px; }}
/* Predictions tab */
.pred-val {{
  font-size: 18px; font-weight: 800; padding: 4px 10px; border-radius: 6px;
  display: inline-block; min-width: 48px; text-align: center;
}}
.pred-fdr-tile {{
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 12px; font-weight: 700; min-width: 32px; text-align: center;
}}
.pred-fdr-used {{
  font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 4px;
  display: inline-block; background: rgba(255,255,255,0.05);
}}
.pred-confidence {{
  display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 10px;
  border-radius: 10px; letter-spacing: 0.3px;
}}
.pred-conf-high {{ background: rgba(16,185,129,0.2); color: #10b981; }}
.pred-conf-medium {{ background: rgba(251,191,36,0.2); color: #fbbf24; }}
.pred-conf-low {{ background: rgba(239,68,68,0.2); color: #ef4444; }}
.pred-conf-insufficient {{ background: rgba(100,116,139,0.2); color: #94a3b8; }}
.pred-conf-unavailable {{ background: rgba(239,68,68,0.15); color: #ef4444; }}
.pred-legend {{
  background: #1e293b; border-radius: 8px; padding: 12px 16px;
  margin-bottom: 16px; font-size: 12px; color: #94a3b8; line-height: 1.8;
}}
.pred-legend b {{ color: #e2e8f0; }}
.pred-filters {{ display: flex; gap: 8px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
/* --- Newsletter tab --- */
.nl-list {{ display: flex; flex-direction: column; gap: 16px; }}
.nl-card {{
  background: #1e293b; border-radius: 12px; padding: 20px 24px;
  border-left: 4px solid #F0B232;
}}
.nl-card-header {{
  display: flex; align-items: center; gap: 12px; margin-bottom: 12px;
}}
.nl-round {{
  font-size: 18px; font-weight: 800; color: #F0B232;
}}
.nl-date {{ font-size: 12px; color: #64748b; }}
.nl-model {{ font-size: 11px; color: #334155; margin-left: auto; }}
.nl-text {{
  font-size: 14px; color: #cbd5e1; line-height: 1.7; white-space: pre-wrap;
}}
/* --- Season tracker --- */
.season-wrap {{ background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
.season-controls {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
.season-btn {{
  background: transparent; border: 1px solid #334155; color: #64748b;
  padding: 5px 14px; font-size: 12px; font-weight: 600; cursor: pointer;
  border-radius: 6px; font-family: inherit; transition: all 0.15s;
}}
.season-btn.active {{ background: #22d3ee; color: #0f172a; border-color: transparent; }}
.season-chart {{ position: relative; width: 100%; overflow-x: auto; }}
.season-chart svg {{ display: block; }}
.season-tooltip {{
  position: absolute; pointer-events: none; background: #0f172a; border: 1px solid #334155;
  border-radius: 8px; padding: 8px 12px; font-size: 12px; color: #e2e8f0;
  white-space: nowrap; z-index: 10; opacity: 0; transition: opacity 0.15s;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}}
.season-tooltip.visible {{ opacity: 1; }}
.season-legend {{ display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 12px; }}
.season-legend-item {{
  display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
  color: #94a3b8; cursor: pointer; user-select: none; transition: opacity 0.2s;
}}
.season-legend-item.hidden {{ opacity: 0.3; text-decoration: line-through; }}
.season-legend-item .swatch {{ width: 14px; height: 3px; border-radius: 2px; }}
.season-table {{ margin-top: 20px; }}
.trend-up {{ color: #10b981; }}
.trend-down {{ color: #ef4444; }}
.trend-flat {{ color: #64748b; }}
/* ============================================================
   📖 PORÓWNYWARKA ZAWODNIKÓW — style
   Sekcje: wybór, karty, tabela statystyk, wykres formy, FDR
   ============================================================ */
.cmp-search-wrap {{
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 20px;
}}
.cmp-search-box {{
  position: relative; flex: 1; min-width: 200px;
}}
.cmp-search-input {{
  width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid #334155;
  background: #0f172a; color: #e2e8f0; font-size: 14px; font-family: inherit;
  outline: none; transition: border-color 0.2s;
}}
.cmp-search-input:focus {{ border-color: #22d3ee; }}
.cmp-search-input::placeholder {{ color: #64748b; }}
/* 📖 Autouzupełnianie — lista podpowiedzi pod polem wyszukiwania */
.cmp-autocomplete {{
  position: absolute; top: 100%; left: 0; right: 0; z-index: 100;
  background: #1e293b; border: 1px solid #334155; border-radius: 8px;
  max-height: 220px; overflow-y: auto; display: none; margin-top: 4px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}}
.cmp-autocomplete.visible {{ display: block; }}
.cmp-ac-item {{
  padding: 8px 14px; cursor: pointer; font-size: 13px; display: flex;
  align-items: center; gap: 8px; transition: background 0.1s;
}}
.cmp-ac-item:hover {{ background: #334155; }}
.cmp-ac-item .cmp-ac-team {{ color: #64748b; font-size: 11px; }}
.cmp-clear-btn {{
  background: #334155; border: none; color: #94a3b8; padding: 8px 16px;
  border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer;
  font-family: inherit; transition: all 0.15s;
}}
.cmp-clear-btn:hover {{ background: #475569; color: #e2e8f0; }}
.cmp-selected-chips {{
  display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px;
}}
.cmp-chip {{
  display: inline-flex; align-items: center; gap: 6px; background: #1e293b;
  border: 1px solid #334155; border-radius: 20px; padding: 4px 12px 4px 8px;
  font-size: 13px; color: #e2e8f0; animation: cmpChipIn 0.2s ease;
}}
@keyframes cmpChipIn {{
  from {{ opacity: 0; transform: scale(0.9); }}
  to {{ opacity: 1; transform: scale(1); }}
}}
.cmp-chip-remove {{
  background: none; border: none; color: #64748b; cursor: pointer;
  font-size: 16px; line-height: 1; padding: 0 2px; transition: color 0.15s;
}}
.cmp-chip-remove:hover {{ color: #ef4444; }}
/* 📖 Karty zawodników — obok siebie, responsywne */
.cmp-cards {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px; margin-bottom: 24px;
}}
.cmp-card {{
  background: #1e293b; border-radius: 12px; padding: 20px;
  border-top: 3px solid #22d3ee; animation: cmpChipIn 0.3s ease;
}}
.cmp-card:nth-child(2) {{ border-top-color: #fbbf24; }}
.cmp-card:nth-child(3) {{ border-top-color: #a78bfa; }}
.cmp-card-name {{ font-size: 16px; font-weight: 800; margin-bottom: 4px; }}
.cmp-card-meta {{ font-size: 12px; color: #94a3b8; margin-bottom: 12px; }}
.cmp-card-stats {{ display: flex; flex-direction: column; gap: 6px; }}
.cmp-card-stat {{
  display: flex; justify-content: space-between; font-size: 13px;
  padding: 4px 0; border-bottom: 1px solid #0f172a;
}}
.cmp-card-stat .cmp-stat-label {{ color: #64748b; }}
.cmp-card-stat .cmp-stat-val {{ font-weight: 700; color: #e2e8f0; }}
/* 📖 Tabela porównania — podświetlenie najlepszej wartości */
.cmp-table {{ background: #1e293b; border-radius: 12px; overflow: hidden; margin-bottom: 24px; overflow-x: auto; }}
.cmp-table table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
.cmp-table th {{ padding: 10px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; color: #64748b; font-weight: 600; background: #0f172a; }}
.cmp-table td {{ padding: 10px 14px; border-top: 1px solid #0f172a; text-align: center; }}
.cmp-table td:first-child {{ text-align: left; color: #94a3b8; font-weight: 600; font-size: 12px; }}
.cmp-table td.cmp-best {{ background: rgba(16,185,129,0.12); color: #10b981; font-weight: 800; }}
/* 📖 Wykres formy — SVG, jedna linia per zawodnik */
.cmp-chart-wrap {{
  background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 24px;
}}
.cmp-chart-title {{ font-size: 14px; font-weight: 700; margin-bottom: 12px; color: #e2e8f0; }}
.cmp-chart-legend {{
  display: flex; gap: 16px; margin-bottom: 12px; font-size: 12px; flex-wrap: wrap;
}}
.cmp-chart-legend-item {{ display: flex; align-items: center; gap: 6px; color: #94a3b8; }}
.cmp-chart-legend-swatch {{ width: 16px; height: 3px; border-radius: 2px; }}
.cmp-chart svg {{ display: block; width: 100%; }}
/* 📖 Siatka FDR — kolorowe kafelki jak w zakładce Terminarz */
.cmp-fdr-wrap {{
  background: #1e293b; border-radius: 12px; padding: 20px; overflow-x: auto;
}}
.cmp-fdr-title {{ font-size: 14px; font-weight: 700; margin-bottom: 12px; color: #e2e8f0; }}
.cmp-fdr-table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.cmp-fdr-table th {{ padding: 8px 10px; font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; border-bottom: 2px solid #334155; }}
.cmp-fdr-table td {{ padding: 6px 10px; text-align: center; border-bottom: 1px solid #0f172a; }}
.cmp-fdr-cell {{
  display: inline-flex; align-items: center; gap: 4px; border-radius: 4px;
  padding: 3px 8px; font-weight: 700; font-size: 12px;
}}
.cmp-fdr-cell .cmp-fdr-ha {{ font-size: 9px; font-weight: 400; opacity: 0.7; }}
.cmp-empty {{
  text-align: center; padding: 60px 20px; color: #64748b; font-size: 15px;
}}
.cmp-empty-icon {{ font-size: 48px; margin-bottom: 12px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="header-left">
      <img src="logo.PNG" alt="ScrapFEks" class="logo">
      <div>
        <h1>Fantasy Ekstraklasa</h1>
        <p class="sub">Dashboard · {timestamp}</p>
      </div>
    </div>
    <button class="theme-toggle" onclick="toggleTheme()">☀️ Light</button>
  </div>
  <div class="stats-row">
    <div class="stat-card accent-cyan">
      <div class="val">{teams_count}</div>
      <div class="label">Top drużyn</div>
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
      <button class="tab active" data-tab="players">⚽ Zawodnicy</button>
      {"<button class='tab' data-tab='teams'>📋 Liga CMF</button>" if has_league else ""}
      {"<button class='tab' data-tab='fixtures'>📅 Terminarz</button>" if has_fixtures else ""}
      {"<button class='tab' data-tab='transfers'>🔄 Transfery</button>" if has_transfers else ""}
      {"<button class='tab' data-tab='predictions'>🔮 Prognoza</button>" if has_predictions else ""}
      {"<button class='tab' data-tab='accuracy'>📊 Trafność</button>" if has_accuracy else ""}
      {"<button class='tab' data-tab='season'>📈 Sezon</button>" if has_season else ""}
{"<button class='tab' data-tab='newsletter'>📰 Newsletter</button>" if has_newsletter else ""}
      <button class="tab" data-tab="compare">⚖️ Porównanie</button>
      {f'<a href="archive/index.html" class="tab archive-link">📁 Archiwum</a>' if has_archive else '<span class="tab archive-link disabled">📁 Archiwum</span>'}
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
    <div id="tab-players" class="tab-content active"></div>
    <div id="tab-teams" class="tab-content"></div>
    <div id="tab-fixtures" class="tab-content"></div>
    <div id="tab-transfers" class="tab-content"></div>
    <div id="tab-predictions" class="tab-content"></div>
    <div id="tab-accuracy" class="tab-content"></div>
    <div id="tab-season" class="tab-content"></div>
    <div id="tab-newsletter" class="tab-content"></div>
    <div id="tab-compare" class="tab-content"></div>
  </div>
  <div class="footer">Fantasy Ekstraklasa Dashboard · {timestamp}</div>
</div>

// __JS_PLACEHOLDER__

<script>
const DATA = {data_json};
const PLAYERS = {players_json};
const ROSTERS = {rosters_json};
const LEAGUE_TEAMS = {teams_detail_json};
const DUETS_DATA = {duets_data_json};
const FIXTURES = {fixtures_json};
const EKSTRA_STATS = {ekstra_stats_json};
const FDR_DATA = {fdr_data_json};
const TRANSFERS_DATA = {transfers_data_json};
const PREDICTIONS = {predictions_json};
const ACCURACY_HISTORY = {accuracy_json};
const TUNED_PARAMS = {tuned_params_json};
const LEAGUE_HISTORY = {league_history_json};
const NEWSLETTER_DATA = {newsletter_json};
 const POS_MAP = {{BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD','1':'GK','2':'DEF','3':'MID','4':'FWD'}};
const POS_ID = {{'1':'BR','2':'OBR','3':'POM','4':'NAP',BR:'BR',OBR:'OBR',POM:'POM',NAP:'NAP',
  Bramkarz:'BR','Obrońca':'OBR',Pomocnik:'POM',Napastnik:'NAP'}};

let tab = 'players', pos = 'ALL', scope = '{{default_scope}}';
let selectedTeam = '';
let selectedDuet = '';
let currentTeamsView = 'teams';
// 📖 Stan porównywarki — tablica player_id wybranych zawodników (max 3)
let cmpSelected = [];
let sorts = {{
  players: {{col:'total_points', dir:'desc'}},
  teams: {{col:'_pos_order', dir:'asc'}},
  teams_list: {{col:'total_pts', dir:'desc'}},
  duets_list: {{col:'total_pts', dir:'desc'}},
}};

function num(v) {{
  if (v === null || v === undefined || v === '') return 0;
  const n = typeof v === 'string' ? parseFloat(v) : v;
  return isNaN(n) ? 0 : n;
}}
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
    if (av < bv) return s.dir === 'desc' ? 1 : -1;
    if (av > bv) return s.dir === 'desc' ? -1 : 1;
    return 0;
  }});
}}

// Detail panel — kliknięcie na zawodnika pokazuje formę + drużyny z ligi
function nameCell(name, pid, style, prefix) {{
  const attr = pid ? ' data-pid="'+pid+'"' : '';
  return '<td class="clickable roster-trigger"'+attr+' style="cursor:pointer;'+(style||'')+'">'+( prefix||'')+name+' <span style="font-size:10px;color:#64748b">▸</span></td>';
}}
function attachDetailClicks() {{
  document.querySelectorAll('.roster-trigger').forEach(td => {{
    td.onclick = function() {{
      const pid = this.dataset.pid || '';
      const row = this.closest('tr');
      const next = row.nextElementSibling;
      if (next && next.classList.contains('detail-row')) {{
        next.remove();
        return;
      }}
      document.querySelectorAll('.detail-row').forEach(r => r.remove());
      const cols = row.querySelectorAll('td').length;
      row.insertAdjacentHTML('afterend', detailRow(pid, cols));
    }};
  }});
}}

function formChart(form, mini) {{
  if (!form || !form.length) return '<span class="c-dim" style="font-size:11px">—</span>';
  const SCALE = 15;
  const MAX_H = mini ? 20 : 40;
  let h = '<div class="form-chart'+(mini ? ' mini' : '')+'">';
  form.forEach(f => {{
    const pts = f.pts || 0;
    const played = f.p !== false;
    const ht = Math.max(Math.abs(pts) / SCALE * MAX_H, 2);
    const c = !played ? '#334155' : pts >= 8 ? '#22d3ee' : pts >= 4 ? '#10b981' : pts >= 0 ? '#64748b' : '#ef4444';
    const np = !played ? ' not-played' : '';
    h += '<div class="form-bar'+np+'" style="height:'+ht+'px;background:'+c+'">';
    h += '<span class="form-val">'+(played ? pts : '—')+'</span>';
    h += '<span class="form-rnd">K'+f.r+'</span>';
    h += '</div>';
  }});
  h += '</div>';
  return h;
}}

function formAvg(form) {{
  if (!form || !form.length) return '—';
  const played = form.filter(f => f.p !== false);
  if (!played.length) return '—';
  const avg = played.reduce((s,f) => s + (f.pts||0), 0) / played.length;
  return avg.toFixed(1);
}}

function formAvgNum(form) {{
  if (!form || !form.length) return 0;
  const played = form.filter(f => f.p !== false);
  if (!played.length) return 0;
  return played.reduce((s,f) => s + (f.pts||0), 0) / played.length;
}}

function detailRow(pid, colspan) {{
  const r = ROSTERS[pid];
  if (!r || !r.length) {{
    return '<tr class="detail-row"><td colspan="'+colspan+'"><div class="detail-panel"><span class="c-dim" style="font-size:12px">Brak danych o drużynach ligowych</span></div></td></tr>';
  }}
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
  let h = '<tr class="detail-row"><td colspan="'+colspan+'"><div class="detail-panel">';
  h += '<div class="detail-section">';
  h += '<span class="ds-label">Drużyny w lidze ('+r.length+')</span>';
  h += '<div style="display:flex;flex-wrap:wrap;gap:4px">'+chips+'</div>';
  h += '</div></div></td></tr>';
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
  h += '<th class="text-center sortable" data-tab="players" data-col="_diff_global" title="Punkty zawodnika minus średnia punktów wszystkich grających na tej pozycji">±Avg'+arrow('players','_diff_global')+'</th>';
  if (hasLeague) {{
    h += '<th class="text-center sortable" data-tab="players" data-col="_diff_league" title="Punkty zawodnika minus średnia punktów graczy na tej pozycji w drużynach z Twojej ligi">±Liga'+arrow('players','_diff_league')+'</th>';
  }}
  h += '<th class="text-right sortable" data-tab="players" data-col="points_per_price">Pkt/Cena'+arrow('players','points_per_price')+'</th>';
  h += '<th class="text-center" style="min-width:80px">Forma</th>';
  h += '<th class="text-right sortable" data-tab="players" data-col="_form_avg" title="Średnia punktów z rozegranych meczów z ostatnich 5 kolejek uwzględnionych w formie">Średnia'+arrow('players','_form_avg')+'</th>';
  h += '<th class="text-right sortable" data-tab="players" data-col="popularity_pct" title="Oficjalny % popularności z API Fantasy Ekstraklasa — procent WSZYSTKICH graczy fantasy, którzy mają tego zawodnika w składzie">Pop.'+arrow('players','popularity_pct')+'</th>';
  if (hasOwn) {{
    h += '<th class="text-right sortable" data-tab="players" data-col="_own_squad" style="min-width:100px" title="% drużyn z wybranego zakresu (Top 10/100/Wszystkie/Liga), które mają tego zawodnika w składzie">W składzie'+arrow('players','_own_squad')+'</th>';
    h += '<th class="text-right sortable" data-tab="players" data-col="_own_starting" style="min-width:100px" title="% drużyn z wybranego zakresu, które mają tego zawodnika w Starting XI (nie na ławce)">Start XI'+arrow('players','_own_starting')+'</th>';
    h += '<th class="text-right sortable" data-tab="players" data-col="_own_captain" style="min-width:100px" title="% drużyn z wybranego zakresu, które mają tego zawodnika jako kapitana">Kapitan'+arrow('players','_own_captain')+'</th>';
  }}
  h += '</tr></thead><tbody>';

  // Dodaj dane ownership, formę i diff do sortowania
  data.forEach(p => {{
    const o = ownMap[p.player_id];
    p._own_squad = o ? num(o.squad_pct) : 0;
    p._own_starting = o ? num(o.starting_pct) : 0;
    p._own_captain = o ? num(o.captain_pct) : 0;
    const f = p.form || [];
    const played = f.filter(x => x.p !== false);
    p._form_avg = played.length ? played.reduce((s,x) => s + (x.pts||0), 0) / played.length : 0;
    const pk = POS_ID[p.position] || p.position || '';
    const pts = p.total_points || 0;
    p._diff_global = (POS_AVGS[pk] && pts > 0) ? Math.round((pts - POS_AVGS[pk]) * 10) / 10 : 0;
    p._diff_league = (LEAGUE_POS_AVGS[pk] && pts > 0) ? Math.round((pts - LEAGUE_POS_AVGS[pk]) * 10) / 10 : 0;
  }});
  data = sortData(data, 'players');

  data.forEach((p, i) => {{
    const pts = p.total_points || 0, price = p.price || 0, ppp = p.points_per_price || 0;
    const ptsC = pts >= 35 ? '#22d3ee' : pts >= 25 ? '#e2e8f0' : '#94a3b8';
    const pppC = ppp >= 15 ? '#10b981' : ppp >= 10 ? '#e2e8f0' : '#94a3b8';
    const pk = POS_ID[p.position] || p.position || '';
    h += '<tr><td class="c-muted fw-600">'+(i+1)+'</td>';
    h += nameCell(p.name, p.player_id, 'font-weight:600');
    h += '<td class="c-muted" style="font-size:13px">'+p.team+'</td>';
    h += '<td class="text-center">'+posBadge(pk)+'</td>';
    h += '<td class="text-right c-muted">'+price.toFixed(1)+'M</td>';
    h += '<td class="text-right fw-700" style="color:'+ptsC+'">'+pts+'</td>';
    h += '<td class="text-center">'+diffBadge(pts, POS_AVGS[pk])+'</td>';
    if (hasLeague) {{
      h += '<td class="text-center">'+diffBadge(pts, LEAGUE_POS_AVGS[pk])+'</td>';
    }}
    h += '<td class="text-right fw-600" style="color:'+pppC+'">'+ppp.toFixed(1)+'</td>';
    h += '<td class="text-center">'+formChart(p.form, true)+'</td>';
    const favg = p._form_avg;
    const favgC = favg >= 6 ? '#22d3ee' : favg >= 3 ? '#10b981' : '#94a3b8';
    h += '<td class="text-right fw-600" style="color:'+favgC+'">'+(favg > 0 ? favg.toFixed(1) : '—')+'</td>';
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

function renderDuets() {{
  if (!DUETS_DATA.length) return '<div class="empty-msg">Brak danych o duetach</div>';

  // Zmienne motywu dla kolorów (dark/light)
  const isLight = document.documentElement.classList.contains('theme-fantasy');
  const bgPanel = isLight ? '#f5f5f5' : '#0f172a';
  const cMuted = isLight ? '#5a5a5a' : '#94a3b8';
  const cLabel = isLight ? '#949494' : '#64748b';

  const dls = sorts.duets_list;
  function dlArrow(col) {{
    return dls.col === col ? (dls.dir === 'desc' ? ' ▼' : ' ▲') : '';
  }}

  const sortedDuets = [...DUETS_DATA].sort((a, b) => {{
    let av = a[dls.col], bv = b[dls.col];
    if (typeof av === 'string') {{
      if (av < bv) return dls.dir === 'desc' ? 1 : -1;
      if (av > bv) return dls.dir === 'desc' ? -1 : 1;
      return 0;
    }}
    av = num(av); bv = num(bv);
    if (av < bv) return dls.dir === 'desc' ? 1 : -1;
    if (av > bv) return dls.dir === 'desc' ? -1 : 1;
    return 0;
  }});

  let h = '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-center" style="width:50px">#</th>';
  h += '<th class="text-left sortable" data-tab="duets_list" data-col="duet_name">Duet'+dlArrow('duet_name')+'</th>';
  h += '<th class="text-left">Gracze</th>';
  h += '<th class="text-right sortable" data-tab="duets_list" data-col="autumn_pts">Jesień'+dlArrow('autumn_pts')+'</th>';
  h += '<th class="text-right sortable" data-tab="duets_list" data-col="spring_pts">Wiosna'+dlArrow('spring_pts')+'</th>';
  h += '<th class="text-right sortable" data-tab="duets_list" data-col="total_pts" style="font-size:13px;font-weight:800">SUMA'+dlArrow('total_pts')+'</th>';
  h += '<th class="text-center sortable" data-tab="duets_list" data-col="rank_change">Zmiana'+dlArrow('rank_change')+'</th>';
  h += '</tr></thead><tbody>';

  sortedDuets.forEach((d, i) => {{
    const pos = i + 1;
    const medal = pos === 1 ? '🥇' : pos === 2 ? '🥈' : pos === 3 ? '🥉' : pos;
    const isOpen = d.duet_name === selectedDuet;

    h += '<tr style="cursor:pointer" data-duetname="'+encodeURIComponent(d.duet_name)+'">';
    h += '<td class="text-center" style="font-size:'+(pos<=3?'18px':'14px')+'">'+medal+'</td>';
    h += '<td style="font-weight:600">'+d.duet_name+' <span style="font-size:10px;color:#475569">'+(isOpen?'▼':'▶')+'</span></td>';
    h += '<td style="font-size:12px;color:#94a3b8">'+d.players+'</td>';
    h += '<td class="text-right" style="color:#94a3b8">'+(d.autumn_pts||0)+'</td>';
    h += '<td class="text-right" style="color:#94a3b8">'+(d.spring_pts||0)+'</td>';
    h += '<td class="text-right" style="font-weight:800;font-size:15px">'+(d.total_pts||0)+'</td>';

    const rc = d.rank_change || 0;
    let changeHtml = '';
    if (rc > 0) changeHtml = '<span style="color:#10b981">▲'+rc+'</span>';
    else if (rc < 0) changeHtml = '<span style="color:#ef4444">▼'+Math.abs(rc)+'</span>';
    else changeHtml = '<span style="color:#64748b">–</span>';
    h += '<td class="text-center">'+changeHtml+'</td>';
    h += '</tr>';

    if (isOpen) {{
      h += '<tr><td colspan="7" style="padding:8px 16px;background:#0f172a">';
      h += '<div style="font-size:13px;line-height:1.8">';
      const t1sum = (d.team1_autumn||0) + (d.team1_spring||0);
      const t2sum = (d.team2_autumn||0) + (d.team2_spring||0);
      h += '<div style="display:flex;justify-content:space-between;max-width:500px">';
      h += '<span style="font-weight:600">'+d.team1_name+'</span>';
      h += '<span style="color:#94a3b8">'+d.team1_autumn+' + '+d.team1_spring+' = <b>'+t1sum+'</b></span>';
      h += '</div>';
      h += '<div style="display:flex;justify-content:space-between;max-width:500px">';
      h += '<span style="font-weight:600">'+d.team2_name+'</span>';
      h += '<span style="color:#94a3b8">'+d.team2_autumn+' + '+d.team2_spring+' = <b>'+t2sum+'</b></span>';
      h += '</div>';
      h += '</div>';
      h += '</td></tr>';
    }}
  }});

  h += '</tbody></table></div>';
  return h;
}}

function renderTeams() {{
  if (!LEAGUE_TEAMS.length) return '<div class="empty-msg">Brak danych o drużynach ligi</div>';

  // Zmienne motywu dla kolorów (dark/light)
  const isLight = document.documentElement.classList.contains('theme-fantasy');
  const bgBtn = isLight ? '#ffffff' : '#1e293b';
  const bgPanel = isLight ? '#f5f5f5' : '#0f172a';
  const cMuted = isLight ? '#5a5a5a' : '#94a3b8';

  let h = '<div class="section-title"><span style="font-size:22px">📋</span><h2>Liga CMF</h2><div class="line"></div></div>';

  // View toggle
  h += '<div class="view-toggle" style="display:flex;gap:8px;margin-bottom:16px">';
  h += '<button class="view-btn'+(currentTeamsView==='teams'?' active':'')+'" data-view="teams" style="padding:6px 16px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:600;background:'+(currentTeamsView==='teams'?'#3b82f6':bgBtn)+';color:'+(currentTeamsView==='teams'?'#fff':cMuted)+'">👥 Drużyny</button>';
  h += '<button class="view-btn'+(currentTeamsView==='duets'?' active':'')+'" data-view="duets" style="padding:6px 16px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:600;background:'+(currentTeamsView==='duets'?'#3b82f6':bgBtn)+';color:'+(currentTeamsView==='duets'?'#fff':cMuted)+'">👫 Duety</button>';
  h += '</div>';

  if (currentTeamsView === 'duets') return h + renderDuets();

  // Helpers for squad table
  const POS_ORDER = {{BR:1,OBR:2,POM:3,NAP:4}};
  const NCOLS = 10;

  // Build player ownership map: pid -> number of teams owning that player
  const playerOwnerCount = {{}};
  const totalTeams = LEAGUE_TEAMS.length;
  LEAGUE_TEAMS.forEach(team => {{
    if (team.players) team.players.forEach(p => {{
      playerOwnerCount[p.pid] = (playerOwnerCount[p.pid] || 0) + 1;
    }});
  }});

  function sortGroup(arr) {{
    const s = sorts.teams;
    return [...arr].sort((a,b) => {{
      let av = a[s.col], bv = b[s.col];
      if (typeof av === 'string') {{
        if (av < bv) return s.dir === 'desc' ? 1 : -1;
        if (av > bv) return s.dir === 'desc' ? -1 : 1;
        return 0;
      }}
      av = num(av); bv = num(bv);
      if (av < bv) return s.dir === 'desc' ? 1 : -1;
      if (av > bv) return s.dir === 'desc' ? -1 : 1;
      return 0;
    }});
  }}

  function renderSquadRow(p, idx) {{
    const pk = p._pk;
    const pts = p.pts || 0;
    const price = p.price || 0;
    let nameStyle = 'font-weight:600';
    if (p.C) nameStyle += ';color:#fbbf24';
    let r = '<tr><td class="c-muted fw-600">'+(idx+1)+'</td>';
    r += nameCell(p.name, p.pid, nameStyle, p.C ? '<span class="captain-badge" style="margin-right:4px">C</span> ' : '');
    r += '<td class="text-center">'+posBadge(pk)+'</td>';
    r += '<td class="text-right c-muted">'+price.toFixed(1)+'M</td>';
    r += '<td class="text-right fw-700">'+pts+'</td>';
    r += '<td class="text-center">'+diffBadge(pts, POS_AVGS[pk])+'</td>';
    r += '<td class="text-center">'+diffBadge(pts, LEAGUE_POS_AVGS[pk])+'</td>';
    const favg = p._form_avg;
    const favgC = favg >= 6 ? '#22d3ee' : favg >= 3 ? '#10b981' : '#94a3b8';
    r += '<td class="text-center">'+formChart(p.form, true)+'</td>';
    r += '<td class="text-right fw-600" style="color:'+favgC+'">'+(favg > 0 ? favg.toFixed(1) : '—')+'</td>';
    const imp = p._imp != null ? p._imp : 100;
    const impColor = imp >= 70 ? '#10b981' : imp >= 30 ? '#eab308' : '#ef4444';
    r += '<td class="text-center fw-600" style="color:'+impColor+'">'+imp+'%</td>';
    r += '</tr>';
    return r;
  }}

  // Sort teams by selected column
  const tls = sorts.teams_list;
  const sortedTeams = [...LEAGUE_TEAMS].sort((a, b) => {{
    let av, bv;
    if (tls.col === 'name') {{
      av = (a.display_name || a.slug.replace(/-/g,' ')).toLowerCase();
      bv = (b.display_name || b.slug.replace(/-/g,' ')).toLowerCase();
      if (av < bv) return tls.dir === 'desc' ? 1 : -1;
      if (av > bv) return tls.dir === 'desc' ? -1 : 1;
      return 0;
    }}
    av = num(a[tls.col]); bv = num(b[tls.col]);
    if (av < bv) return tls.dir === 'desc' ? 1 : -1;
    if (av > bv) return tls.dir === 'desc' ? -1 : 1;
    return 0;
  }});

  function tlArrow(col) {{
    return tls.col === col ? (tls.dir === 'desc' ? ' ▼' : ' ▲') : '';
  }}

  // Hockey-style table with expandable squads
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-center sortable" data-tab="teams_list" data-col="hockey_pos" style="width:50px">#'+tlArrow('hockey_pos')+'</th>';
  h += '<th class="text-left sortable" data-tab="teams_list" data-col="name">Drużyna'+tlArrow('name')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="autumn_pts">Jesień'+tlArrow('autumn_pts')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="best_gw_autumn" style="font-size:11px;color:#64748b">🔥 J'+tlArrow('best_gw_autumn')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="spring_pts">Wiosna'+tlArrow('spring_pts')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="best_gw_spring" style="font-size:11px;color:#64748b">🔥 W'+tlArrow('best_gw_spring')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="total_pts" style="font-size:13px;font-weight:800">SUMA'+tlArrow('total_pts')+'</th>';
  h += '<th class="text-center sortable" data-tab="teams_list" data-col="rank_change">Zmiana'+tlArrow('rank_change')+'</th>';
  h += '</tr></thead><tbody>';

  sortedTeams.forEach((t, i) => {{
    const pos = t.hockey_pos || (i + 1);
    const medal = pos === 1 ? '🥇' : pos === 2 ? '🥈' : pos === 3 ? '🥉' : pos;
    const tName = t.display_name || t.slug.replace(/-/g,' ');
    const isMyTeam = tName.toLowerCase() === 'tokusatsu soccer';
    const dimRow = t.autumn_only;
    const isOpen = t.slug === selectedTeam;
    const hasPlayers = t.players && t.players.length > 0;

    let rowCls = isMyTeam ? 'highlight' : '';
    let rowStyle = '';
    if (dimRow) rowStyle = 'opacity:0.45';
    if (hasPlayers) rowStyle += (rowStyle ? ';' : '') + 'cursor:pointer';

    h += '<tr'+(rowCls ? ' class="'+rowCls+'"' : '')+(rowStyle ? ' style="'+rowStyle+'"' : '')+' data-teamslug="'+t.slug+'">';
    h += '<td class="text-center" style="font-size:'+(pos<=3?'18px':'14px')+'">' + medal + '</td>';
    h += '<td style="font-weight:600">' + tName + (dimRow ? ' <span style="font-size:10px;color:#64748b">(nie gra)</span>' : '') + (hasPlayers ? ' <span style="font-size:10px;color:#475569">'+(isOpen?'▼':'▶')+'</span>' : '') + '</td>';
    h += '<td class="text-right" style="color:#94a3b8">' + (t.autumn_pts||0) + '</td>';
    h += '<td class="text-right" style="color:#64748b;font-size:12px">' + (t.best_gw_autumn > 0 ? t.best_gw_autumn : '—') + '</td>';
    h += '<td class="text-right" style="color:#94a3b8">' + (t.spring_pts||0) + '</td>';
    h += '<td class="text-right" style="color:#64748b;font-size:12px">' + (t.best_gw_spring > 0 ? t.best_gw_spring : '—') + '</td>';
    h += '<td class="text-right" style="font-weight:800;font-size:15px">' + (t.total_pts||0) + '</td>';

    const rc = t.rank_change || 0;
    let changeHtml = '';
    if (rc > 0) changeHtml = '<span style="color:#10b981">▲' + rc + '</span>';
    else if (rc < 0) changeHtml = '<span style="color:#ef4444">▼' + Math.abs(rc) + '</span>';
    else changeHtml = '<span style="color:#64748b">–</span>';
    h += '<td class="text-center">' + changeHtml + '</td>';
    h += '</tr>';

    // Expandable squad panel
    if (isOpen && hasPlayers) {{
      t.players.forEach(p => {{
        const pk = POS_ID[p.pos] || p.pos || '';
        p._pk = pk;
        p._pos_order = POS_ORDER[pk] || 99;
        p._diff_global = (POS_AVGS[pk] && (p.pts||0) > 0) ? Math.round(((p.pts||0) - POS_AVGS[pk]) * 10) / 10 : 0;
        p._diff_league = (LEAGUE_POS_AVGS[pk] && (p.pts||0) > 0) ? Math.round(((p.pts||0) - LEAGUE_POS_AVGS[pk]) * 10) / 10 : 0;
        p._form_avg = formAvgNum(p.form);
        const ownersExcl = (playerOwnerCount[p.pid] || 1) - 1;
        p._imp = totalTeams > 1 ? Math.round(((totalTeams - 1 - ownersExcl) / (totalTeams - 1)) * 100) : 100;
      }});

      h += '<tr><td colspan="8" style="padding:0;background:#0f172a">';
      h += '<div class="data-table" style="padding:4px 12px 12px">';
      h += '<table><thead><tr>';
      h += '<th class="text-left">#</th>';
      h += '<th class="text-left sortable" data-tab="teams" data-col="name">Zawodnik'+arrow('teams','name')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_pos_order">Poz'+arrow('teams','_pos_order')+'</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="price">Cena'+arrow('teams','price')+'</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="pts">Punkty'+arrow('teams','pts')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_diff_global" title="Punkty zawodnika minus średnia punktów wszystkich grających na tej pozycji">±Avg'+arrow('teams','_diff_global')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_diff_league" title="Punkty zawodnika minus średnia punktów graczy na tej pozycji w drużynach z Twojej ligi">±Liga'+arrow('teams','_diff_league')+'</th>';
      h += '<th class="text-center" style="min-width:80px">Forma</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="_form_avg" title="Średnia punktów z rozegranych meczów (ostatnie 5 kolejek przed obecną)">Średnia'+arrow('teams','_form_avg')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_imp" title="Differential ownership — im wyższy %, tym mniej managerów w lidze posiada tego zawodnika">Imp'+arrow('teams','_imp')+'</th>';
      h += '</tr></thead><tbody>';

      const starters = sortGroup(t.players.filter(p => !p.R));
      const reserves = sortGroup(t.players.filter(p => p.R));

      starters.forEach((p, idx) => {{ h += renderSquadRow(p, idx); }});
      if (reserves.length) {{
        h += '<tr><td colspan="'+NCOLS+'" style="padding:6px 0;border-top:1px dashed #334155"><span class="c-dim" style="font-size:11px;text-transform:uppercase;letter-spacing:1px">Ławka rezerwowych</span></td></tr>';
        reserves.forEach((p, idx) => {{ h += renderSquadRow(p, starters.length + idx); }});
      }}

      // Podsumowanie
      const totalPts = starters.reduce((s,p) => s + (p.pts||0), 0);
      const totalDiffG = t.players.reduce((s,p) => s + (p._diff_global||0), 0);
      const totalDiffL = t.players.reduce((s,p) => s + (p._diff_league||0), 0);
      h += '<tr style="border-top:2px solid #334155"><td colspan="4" class="fw-700" style="text-align:right;padding-top:10px">Razem:</td>';
      h += '<td class="text-right fw-700" style="padding-top:10px">'+totalPts+'</td>';
      const gCls = totalDiffG > 0 ? 'diff-pos' : totalDiffG < 0 ? 'diff-neg' : 'diff-zero';
      const lCls = totalDiffL > 0 ? 'diff-pos' : totalDiffL < 0 ? 'diff-neg' : 'diff-zero';
      h += '<td class="text-center" style="padding-top:10px"><span class="diff-badge '+gCls+'">'+(totalDiffG>0?'+':'')+totalDiffG.toFixed(0)+'</span></td>';
      h += '<td class="text-center" style="padding-top:10px"><span class="diff-badge '+lCls+'">'+(totalDiffL>0?'+':'')+totalDiffL.toFixed(0)+'</span></td>';
      const avgImp = t.players.length > 0 ? Math.round(t.players.reduce((s,p) => s + (p._imp||0), 0) / t.players.length) : 0;
      const avgImpColor = avgImp >= 70 ? '#10b981' : avgImp >= 30 ? '#eab308' : '#ef4444';
      h += '<td colspan="2"></td><td class="text-center fw-700" style="padding-top:10px;color:'+avgImpColor+'">Ø '+avgImp+'%</td></tr>';

      h += '</tbody></table></div>';
      h += '</td></tr>';
    }}
  }});

  h += '</tbody></table></div>';
  return h;
}}

// ============ FDR (Fixture Difficulty Rating) ============
const FDR_COLORS = {{
  1: {{bg:'#375523', fg:'#ffffff'}},
  2: {{bg:'#01FC7A', fg:'#000000'}},
  3: {{bg:'#E7E7E7', fg:'#000000'}},
  4: {{bg:'#FF1751', fg:'#ffffff'}},
  5: {{bg:'#80072D', fg:'#ffffff'}},
}};
const FDR_LABELS = {{1:'Bardzo łatwy', 2:'Łatwy', 3:'Średni', 4:'Trudny', 5:'Bardzo trudny'}};
let fdrSort = 'alpha'; // 'alpha' | 'def' | 'atk'

function fdrShowModal(team) {{
  const st = EKSTRA_STATS[team];
  const str = (FDR_DATA.team_strengths || {{}})[team];
  const abbr = FIXTURES.abbrevs[team] || team.substring(0,3).toUpperCase();
  const old = document.getElementById("ftModal");
  if (old) old.remove();
  const wrap = document.createElement("div");
  wrap.className = "ft-modal-bg";
  wrap.id = "ftModal";
  const gf = st ? st.gf : '?';
  const ga = st ? st.ga : '?';
  let strengthHtml = '';
  if (str) {{
    strengthHtml = '<div style="margin-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:8px">'
      +'<div style="text-align:center;background:#0f172a;border-radius:8px;padding:8px"><div style="font-size:10px;color:#64748b;text-transform:uppercase">Atak (D)</div><div style="font-size:20px;font-weight:800;color:#22d3ee">'+str.attack_h+'</div></div>'
      +'<div style="text-align:center;background:#0f172a;border-radius:8px;padding:8px"><div style="font-size:10px;color:#64748b;text-transform:uppercase">Atak (W)</div><div style="font-size:20px;font-weight:800;color:#22d3ee">'+str.attack_a+'</div></div>'
      +'<div style="text-align:center;background:#0f172a;border-radius:8px;padding:8px"><div style="font-size:10px;color:#64748b;text-transform:uppercase">Obrona (D)</div><div style="font-size:20px;font-weight:800;color:#f87171">'+str.defense_h+'</div></div>'
      +'<div style="text-align:center;background:#0f172a;border-radius:8px;padding:8px"><div style="font-size:10px;color:#64748b;text-transform:uppercase">Obrona (W)</div><div style="font-size:20px;font-weight:800;color:#f87171">'+str.defense_a+'</div></div>'
      +'</div>';
  }}
  wrap.innerHTML = '<div class="ft-modal"><button class="ft-modal-close" id="ftClose">✕</button>'
    +'<h3>'+abbr+' — '+team+'</h3>'
    +'<div style="display:flex;gap:24px;margin:16px 0">'
    +'<div style="flex:1;text-align:center"><div style="font-size:12px;color:#94a3b8;margin-bottom:4px">Strzelone (GF)</div><div style="font-size:28px;font-weight:800;color:#22d3ee">'+gf+'</div></div>'
    +'<div style="flex:1;text-align:center"><div style="font-size:12px;color:#94a3b8;margin-bottom:4px">Stracone (GA)</div><div style="font-size:28px;font-weight:800;color:#f87171">'+ga+'</div></div>'
    +'</div>'
    +strengthHtml
    +'<div style="font-size:11px;color:#64748b;text-align:center;margin-top:12px">Siła >1.0 = powyżej średniej ligowej &nbsp;|&nbsp; Dane z 90minut.pl</div>'
    +'</div>';
  document.body.appendChild(wrap);
  document.getElementById("ftClose").onclick = function() {{ wrap.remove(); }};
  wrap.onclick = function(e) {{ if (e.target === wrap) wrap.remove(); }};
}}

function renderFixtures() {{
  const fdrTeams = FDR_DATA.teams || [];
  const gws = FDR_DATA.gameweeks || [];
  if (!gws.length) return '<div class="empty-msg">Brak danych terminarza — sprawdź terminarz.txt i dane z 90minut.pl</div>';

  // Sortowanie
  let teams = [...fdrTeams];
  if (fdrSort === 'def') {{
    teams.sort((a,b) => a.total_def - b.total_def);
  }} else if (fdrSort === 'atk') {{
    teams.sort((a,b) => a.total_atk - b.total_atk);
  }} else {{
    teams.sort((a,b) => a.name.localeCompare(b.name, 'pl'));
  }}

  let h = '<div class="section-title"><span style="font-size:22px">📅</span><h2>Terminarz — trudność meczów</h2><div class="line"></div></div>';

  // Legenda
  h += '<div class="fdr-legend">';
  [1,2,3,4,5].forEach(r => {{
    const c = FDR_COLORS[r];
    h += '<span class="fdr-legend-item"><span class="fdr-legend-swatch" style="background:'+c.bg+';color:'+c.fg+'">'+r+'</span><span style="color:#94a3b8">'+FDR_LABELS[r]+'</span></span>';
  }});
  h += '</div>';

  h += '<div style="margin-bottom:10px;font-size:11px;color:#64748b;line-height:1.6">';
  h += '<span style="color:#22d3ee;font-weight:600">ATK</span> = siła ataku rywala (ważne dla obrońców/GK — zielony = słaby atak rywala) &nbsp;|&nbsp; ';
  h += '<span style="color:#f87171;font-weight:600">DEF</span> = siła obrony rywala (ważne dla napastników/pomocników — zielony = słaba obrona rywala)';
  h += '</div>';

  // Sort toggle
  h += '<div style="margin-bottom:12px;font-size:12px">';
  h += '<span class="c-dim">Sortuj: </span>';
  h += '<button class="scope-btn fdr-sort-btn" data-fdrsort="alpha" style="font-size:11px;padding:3px 10px">A-Z</button> ';
  h += '<button class="scope-btn fdr-sort-btn" data-fdrsort="def" style="font-size:11px;padding:3px 10px">Najłatwiejszy dla ataku ↑</button> ';
  h += '<button class="scope-btn fdr-sort-btn" data-fdrsort="atk" style="font-size:11px;padding:3px 10px">Najłatwiejszy dla obrony ↑</button>';
  h += '</div>';

  // Tabela
  h += '<div class="data-table" style="overflow-x:auto"><table class="fdr-table"><thead><tr>';
  h += '<th style="text-align:left;min-width:100px">Drużyna</th>';
  h += '<th style="min-width:56px">Σ ATK</th>';
  h += '<th style="min-width:56px">Σ DEF</th>';
  gws.forEach(gw => {{ h += '<th style="min-width:100px">K'+gw+'</th>'; }});
  h += '</tr></thead><tbody>';

  teams.forEach((team, ti) => {{
    h += '<tr>';
    h += '<td class="fdr-team fdr-team-click" data-fdrteam="'+ti+'" style="text-align:left;font-weight:700;white-space:nowrap;padding-left:8px;cursor:pointer">';
    h += '<span style="font-size:11px;color:#64748b;margin-right:3px">'+(ti+1)+'</span> '+team.short+'</td>';

    // Σ ATK
    const avgAtk = gws.length ? (team.total_atk / gws.length) : 3;
    const atkColor = avgAtk <= 2 ? '#10b981' : avgAtk <= 3 ? '#94a3b8' : '#ef4444';
    h += '<td><span class="fdr-sum" style="color:'+atkColor+'">'+team.total_atk+'</span></td>';

    // Σ DEF
    const avgDef = gws.length ? (team.total_def / gws.length) : 3;
    const defColor = avgDef <= 2 ? '#10b981' : avgDef <= 3 ? '#94a3b8' : '#ef4444';
    h += '<td><span class="fdr-sum" style="color:'+defColor+'">'+team.total_def+'</span></td>';

    // Dual ATK/DEF tiles per gameweek
    team.fixtures.forEach(f => {{
      if (!f.opponent) {{
        h += '<td>—</td>';
        return;
      }}
      const cA = FDR_COLORS[f.atk] || FDR_COLORS[3];
      const cD = FDR_COLORS[f.def] || FDR_COLORS[3];
      const ha = f.home ? 'D' : 'W';
      h += '<td title="'+f.opponent+' ('+(f.home ? 'dom' : 'wyjazd')+') '+f.date+'">';
      h += '<div class="fdr-cell">';
      h += '<div class="fdr-cell-team">'+f.opponent_short+' <span class="fdr-ha">('+ha+')</span></div>';
      h += '<div class="fdr-cell-vals">';
      h += '<span class="fdr-mini" style="background:'+cA.bg+';color:'+cA.fg+'"><span class="fdr-lbl">ATK</span>'+f.atk+'</span>';
      h += '<span class="fdr-mini" style="background:'+cD.bg+';color:'+cD.fg+'"><span class="fdr-lbl">DEF</span>'+f.def+'</span>';
      h += '</div></div></td>';
    }});

    h += '</tr>';
  }});

  h += '</tbody></table></div>';
  window._fdrTeams = teams;

  // 📋 Fixture Planner — sekcja dodana POD istniejącą siatką FDR
  h += renderFixturePlanner();

  return h;
}}

// ============ Fixture Planner ============
// 📖 LEKCJA: Fixture Planner pomaga planować transfery na kilka kolejek do przodu.
// Pokazuje które drużyny mają najłatwiejszy terminarz w wybranym zakresie,
// co pomaga w decyzjach transferowych — kupujesz zawodników z łatwym kalendarzem.

let fpMode = 'mix';        // 'atk' | 'def' | 'mix' — perspektywa pozycyjna
let fpSortCol = 'avg';     // kolumna sortowania: 'team','avg','sum','easy','hard' lub 'gwNN'
let fpSortDir = 'asc';     // kierunek sortowania
let fpGwFrom = 0;           // gameweek start (0 = auto)
let fpGwTo = 0;             // gameweek end (0 = auto)
let fpSelected = [];         // max 2 drużyny do rotation pair

function fpGetFdr(fixture, mode) {{
  // 📖 ATK mode: patrzymy na DEF rywala (słaba obrona = łatwo strzelić)
  // DEF mode: patrzymy na ATK rywala (słaby atak = mało stracimy)
  // MIX: średnia obu
  if (!fixture || !fixture.opponent) return 3;
  if (mode === 'atk') return fixture.def;
  if (mode === 'def') return fixture.atk;
  return Math.round((fixture.atk + fixture.def) / 2);
}}

function renderFixturePlanner() {{
  const fdrTeams = FDR_DATA.teams || [];
  const gws = FDR_DATA.gameweeks || [];
  if (!gws.length || !fdrTeams.length) return '';

  // Ustaw domyślne zakresy jeśli jeszcze nie ustawione
  if (fpGwFrom === 0) fpGwFrom = gws[0];
  if (fpGwTo === 0) fpGwTo = gws[gws.length - 1];

  // Waliduj zakres
  if (fpGwFrom < gws[0]) fpGwFrom = gws[0];
  if (fpGwTo > gws[gws.length - 1]) fpGwTo = gws[gws.length - 1];
  if (fpGwFrom > fpGwTo) fpGwFrom = fpGwTo;

  const selectedGws = gws.filter(g => g >= fpGwFrom && g <= fpGwTo);
  if (!selectedGws.length) return '';

  let h = '<div class="fp-section">';
  h += '<div class="section-title"><span style="font-size:22px">📋</span><h2>Fixture Planner</h2><div class="line"></div></div>';
  h += '<div style="margin-bottom:12px;font-size:12px;color:#64748b;line-height:1.6">';
  h += 'Planuj transfery na kilka kolejek do przodu. Wybierz zakres i perspektywę pozycyjną, aby znaleźć drużyny z najłatwiejszym terminarzem.';
  h += '</div>';

  // Kontrolki: zakres kolejek + tryb pozycyjny
  h += '<div class="fp-controls">';
  h += '<label>Od kolejki:</label>';
  h += '<select class="fp-gw-from">';
  gws.forEach(g => {{ h += '<option value="'+g+'"'+(g===fpGwFrom?' selected':'')+'>K'+g+'</option>'; }});
  h += '</select>';
  h += '<label>Do kolejki:</label>';
  h += '<select class="fp-gw-to">';
  gws.forEach(g => {{ h += '<option value="'+g+'"'+(g===fpGwTo?' selected':'')+'>K'+g+'</option>'; }});
  h += '</select>';

  // 📖 Tryb pozycyjny: ATK (dla napastników/pomocników), DEF (dla obrońców/bramkarzy), MIX (średnia)
  h += '<div class="fp-mode-btns">';
  h += '<button class="fp-mode-btn'+(fpMode==='atk'?' active':'')+'" data-fpmode="atk">ATK</button>';
  h += '<button class="fp-mode-btn'+(fpMode==='def'?' active':'')+'" data-fpmode="def">DEF</button>';
  h += '<button class="fp-mode-btn'+(fpMode==='mix'?' active':'')+'" data-fpmode="mix">MIX</button>';
  h += '</div>';
  h += '</div>';

  // Oblicz dane planera dla każdej drużyny
  const planData = fdrTeams.map(team => {{
    const fixturesInRange = selectedGws.map(gw => {{
      const f = team.fixtures.find(fx => fx.gw === gw);
      return f || null;
    }});
    const fdrValues = fixturesInRange.map(f => fpGetFdr(f, fpMode));
    const sum = fdrValues.reduce((a, b) => a + b, 0);
    const avg = fdrValues.length ? sum / fdrValues.length : 3;
    const easy = fdrValues.filter(v => v <= 2).length;
    const hard = fdrValues.filter(v => v >= 4).length;
    return {{
      name: team.name,
      short: team.short,
      fixtures: fixturesInRange,
      fdrValues: fdrValues,
      sum: sum,
      avg: avg,
      easy: easy,
      hard: hard,
    }};
  }});

  // Sortowanie
  const sortFns = {{
    'team': (a, b) => a.name.localeCompare(b.name, 'pl'),
    'avg': (a, b) => a.avg - b.avg,
    'sum': (a, b) => a.sum - b.sum,
    'easy': (a, b) => b.easy - a.easy,
    'hard': (a, b) => a.hard - b.hard,
  }};
  // Sortowanie po kolumnie kolejki: gwNN
  let sortFn = sortFns[fpSortCol];
  if (!sortFn && fpSortCol.startsWith('gw')) {{
    const gwIdx = selectedGws.indexOf(parseInt(fpSortCol.substring(2)));
    if (gwIdx >= 0) sortFn = (a, b) => a.fdrValues[gwIdx] - b.fdrValues[gwIdx];
  }}
  if (!sortFn) sortFn = sortFns['avg'];
  planData.sort((a, b) => {{
    const v = sortFn(a, b);
    return fpSortDir === 'desc' ? -v : v;
  }});

  // Nagłówek sortowania — helper
  function thClass(col) {{ return fpSortCol === col ? ' fp-sorted' : ''; }}
  function thArrow(col) {{ return fpSortCol === col ? (fpSortDir === 'asc' ? ' ↑' : ' ↓') : ''; }}

  // Tabela planera
  h += '<div class="data-table" style="overflow-x:auto"><table class="fp-table"><thead><tr>';
  h += '<th class="fp-sort'+thClass('team')+'" data-fpcol="team" style="text-align:left;min-width:80px">Drużyna'+thArrow('team')+'</th>';
  selectedGws.forEach(gw => {{
    h += '<th class="fp-sort'+thClass('gw'+gw)+'" data-fpcol="gw'+gw+'" style="min-width:68px">K'+gw+thArrow('gw'+gw)+'</th>';
  }});
  h += '<th class="fp-sort'+thClass('sum')+'" data-fpcol="sum" style="min-width:52px">Σ FDR'+thArrow('sum')+'</th>';
  h += '<th class="fp-sort'+thClass('avg')+'" data-fpcol="avg" style="min-width:52px">Śr.'+thArrow('avg')+'</th>';
  h += '<th class="fp-sort'+thClass('easy')+'" data-fpcol="easy" style="min-width:52px">Łatwych'+thArrow('easy')+'</th>';
  h += '<th class="fp-sort'+thClass('hard')+'" data-fpcol="hard" style="min-width:52px">Trudnych'+thArrow('hard')+'</th>';
  h += '</tr></thead><tbody>';

  planData.forEach((team, ti) => {{
    const isSelected = fpSelected.includes(team.name);
    h += '<tr>';
    h += '<td class="fp-team-cell'+(isSelected ? ' fp-selected' : '')+'" data-fpteam="'+team.name+'">';
    h += '<span style="font-size:11px;color:#64748b;margin-right:3px">'+(ti+1)+'</span> '+team.short+'</td>';

    // Kafelki FDR per kolejka
    team.fixtures.forEach((f, fi) => {{
      if (!f || !f.opponent) {{
        h += '<td>—</td>';
        return;
      }}
      const fdr = team.fdrValues[fi];
      const c = FDR_COLORS[fdr] || FDR_COLORS[3];
      const ha = f.home ? 'D' : 'W';
      h += '<td title="'+f.opponent+' ('+(f.home?'dom':'wyjazd')+') '+f.date+'">';
      h += '<span class="fp-tile" style="background:'+c.bg+';color:'+c.fg+'">'+f.opponent_short+' <span class="fp-ha">('+ha+')</span></span>';
      h += '</td>';
    }});

    // Suma FDR
    h += '<td><span class="fdr-sum" style="color:'+(team.avg<=2.5?'#10b981':team.avg<=3.5?'#94a3b8':'#ef4444')+'">'+team.sum+'</span></td>';

    // Średnia FDR (kolorowana)
    const avgColor = team.avg < 2.5 ? '#10b981' : team.avg > 3.5 ? '#ef4444' : '#94a3b8';
    h += '<td><span class="fp-avg-cell" style="color:'+avgColor+'">'+team.avg.toFixed(1)+'</span></td>';

    // Łatwych / Trudnych
    h += '<td style="color:#10b981;font-weight:700">'+team.easy+'</td>';
    h += '<td style="color:#ef4444;font-weight:700">'+team.hard+'</td>';

    h += '</tr>';
  }});

  h += '</tbody></table></div>';

  // 📖 LEKCJA: "Rotation pair" — dwie drużyny z uzupełniającymi się terminarzami.
  // Jeśli Lech ma trudny mecz w K28 ale Pogoń łatwy, i odwrotnie w K29 —
  // to świetna para do rotacji obrońców/bramkarzy. Zawsze masz kogoś z łatwym meczem.
  if (fpSelected.length === 2) {{
    const t1 = planData.find(t => t.name === fpSelected[0]);
    const t2 = planData.find(t => t.name === fpSelected[1]);
    if (t1 && t2) {{
      let bothEasy = 0;   // obie łatwy — marnowanie slota
      let coverage = 0;   // przynajmniej jedna łatwy
      const totalGws = selectedGws.length;
      for (let i = 0; i < totalGws; i++) {{
        const e1 = t1.fdrValues[i] <= 2;
        const e2 = t2.fdrValues[i] <= 2;
        if (e1 && e2) bothEasy++;
        if (e1 || e2) coverage++;
      }}
      h += '<div class="fp-rotation">';
      h += '<div class="fp-rot-label">🔄 Rotation Pair: '+t1.short+' + '+t2.short+'</div>';
      h += '<div>Pokrycie: <b style="color:#22d3ee">'+coverage+'/'+totalGws+'</b> kolejek (przynajmniej jedna drużyna z łatwym meczem)</div>';
      h += '<div>Marnowanie: <b style="color:#fbbf24">'+bothEasy+'/'+totalGws+'</b> kolejek (obie mają łatwy mecz jednocześnie)</div>';
      const score = totalGws > 0 ? Math.round(coverage / totalGws * 100) : 0;
      const scoreColor = score >= 80 ? '#10b981' : score >= 50 ? '#fbbf24' : '#ef4444';
      h += '<div style="margin-top:6px">Wynik rotacji: <b style="color:'+scoreColor+'">'+score+'%</b></div>';
      h += '</div>';
    }}
  }} else if (fpSelected.length === 1) {{
    h += '<div class="fp-rotation"><div class="fp-rot-label">🔄 Rotation Pair</div>';
    h += '<div style="color:#64748b">Kliknij drugą drużynę, aby zobaczyć wynik rotacji</div></div>';
  }}

  // 📖 Szybki widok "Najlepsze drużyny na X kolejek" — podsumowanie
  // Sortujemy osobno wg ATK (DEF rywali), DEF (ATK rywali), i ogólnie najtrudniejsze
  const atkRanked = fdrTeams.map(team => {{
    const vals = selectedGws.map(gw => {{
      const f = team.fixtures.find(fx => fx.gw === gw);
      return fpGetFdr(f, 'atk');
    }});
    return {{ short: team.short, avg: vals.reduce((a,b)=>a+b,0) / (vals.length||1) }};
  }}).sort((a,b) => a.avg - b.avg);

  const defRanked = fdrTeams.map(team => {{
    const vals = selectedGws.map(gw => {{
      const f = team.fixtures.find(fx => fx.gw === gw);
      return fpGetFdr(f, 'def');
    }});
    return {{ short: team.short, avg: vals.reduce((a,b)=>a+b,0) / (vals.length||1) }};
  }}).sort((a,b) => a.avg - b.avg);

  const hardRanked = [...atkRanked].sort((a,b) => b.avg - a.avg);

  // Najlepsza para rotacyjna — brute-force po wszystkich parach
  let bestPair = {{ t1: '', t2: '', coverage: 0 }};
  for (let i = 0; i < planData.length; i++) {{
    for (let j = i + 1; j < planData.length; j++) {{
      let cov = 0;
      for (let k = 0; k < selectedGws.length; k++) {{
        if (planData[i].fdrValues[k] <= 2 || planData[j].fdrValues[k] <= 2) cov++;
      }}
      if (cov > bestPair.coverage) {{
        bestPair = {{ t1: planData[i].short, t2: planData[j].short, coverage: cov }};
      }}
    }}
  }}

  h += '<div class="fp-summary">';
  h += '<div class="fp-summary-line"><span>🟢</span> <b>Najłatwiejszy (ATK):</b> ';
  h += atkRanked.slice(0,3).map(t => t.short+' (śr. '+t.avg.toFixed(1)+')').join(' — ');
  h += '</div>';
  h += '<div class="fp-summary-line"><span>🟢</span> <b>Najłatwiejszy (DEF):</b> ';
  h += defRanked.slice(0,3).map(t => t.short+' (śr. '+t.avg.toFixed(1)+')').join(' — ');
  h += '</div>';
  h += '<div class="fp-summary-line"><span>🔴</span> <b>Najtrudniejszy:</b> ';
  h += hardRanked.slice(0,3).map(t => t.short+' (śr. '+t.avg.toFixed(1)+')').join(' — ');
  h += '</div>';
  if (bestPair.t1) {{
    h += '<div class="fp-summary-line"><span>🔄</span> <b>Najlepsza para rotacyjna:</b> ';
    h += bestPair.t1+' + '+bestPair.t2+' (pokrycie '+bestPair.coverage+'/'+selectedGws.length+')';
    h += '</div>';
  }}
  h += '</div>';

  h += '</div>';  // end fp-section
  return h;
}}

// ============ Transfers Tab ============
let trPos = 'ALL';
let predPos = 'ALL';
if (!sorts.predictions) sorts.predictions = {{col:'predicted_points', dir:'desc'}};

function priceChangeHtml(pc) {{
  if (!pc) return '';
  const v = parseFloat(pc) || 0;
  if (v > 0) return ' <span class="price-up">↑ +' + v.toFixed(1) + 'M</span>';
  if (v < 0) return ' <span class="price-down">↓ ' + v.toFixed(1) + 'M</span>';
  return '';
}}

function renderTransfersTable(list, totalTeams, title, color) {{
  if (!list || !list.length) return '<div class="empty-msg" style="padding:24px">Brak danych</div>';

  const filtered = trPos === 'ALL' ? list : list.filter(p => {{
    const pk = POS_ID[p.position] || p.position || '';
    return pk === trPos;
  }});

  if (!filtered.length) return '<div class="empty-msg" style="padding:24px">Brak zawodników dla wybranej pozycji</div>';

  let h = '<div class="transfers-header"><span style="font-size:18px">'+title.split(' ')[0]+'</span>';
  h += '<h3 style="color:'+color+'">'+title.split(' ').slice(1).join(' ')+'</h3></div>';
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-left">#</th>';
  h += '<th class="text-left">Zawodnik</th>';
  h += '<th class="text-center">Poz</th>';
  h += '<th class="text-left" style="max-width:120px">Drużyna</th>';
  h += '<th class="text-right">Cena</th>';
  h += '<th style="min-width:120px">Drużyn</th>';
  h += '</tr></thead><tbody>';

  filtered.forEach((p, i) => {{
    const pk = POS_ID[p.position] || p.position || '';
    const pct = p.pct || 0;
    const barW = Math.min(pct, 100);
    const priceChg = priceChangeHtml(p.price_change);
    h += '<tr>';
    h += '<td class="c-muted fw-600">' + (i + 1) + '</td>';
    h += '<td class="fw-600">' + p.name + priceChg + '</td>';
    h += '<td class="text-center">' + posBadge(pk) + '</td>';
    h += '<td class="c-muted" style="font-size:12px;max-width:120px;white-space:normal">' + (p.team || '—') + '</td>';
    h += '<td class="text-right c-muted">' + (p.price ? p.price.toFixed(1) + 'M' : '—') + '</td>';
    h += '<td><div class="bar-wrap"><div class="bar-bg" style="width:80px"><div class="bar-fill" style="width:' + barW + '%;background:' + color + '"></div></div>';
    h += '<span class="bar-val">' + p.count + ' (' + pct.toFixed(1) + '%)</span></div></td>';
    h += '</tr>';
  }});
  h += '</tbody></table></div>';
  return h;
}}

function renderTransfers() {{
  const td = TRANSFERS_DATA;
  if (!td || (!td.transfers_in && !td.transfers_out)) {{
    return '<div class="empty-msg">Brak danych transferowych — upewnij się że liga prywatna jest skonfigurowana i rozegrano co najmniej 2 kolejki</div>';
  }}

  const gw = td.gameweek || '?';
  const prevGw = td.prev_gameweek || (gw - 1);
  const leagueCount = td.league_teams_count || 0;
  const tin = td.transfers_in || [];
  const tout = td.transfers_out || [];

  let h = '<div class="section-title"><span style="font-size:22px">🔄</span><h2>Transfery — K' + prevGw + ' → K' + gw + '</h2><div class="line"></div></div>';

  // Filters row
  h += '<div class="tr-filters-row">';
  h += '<div class="pos-filters">';
  ['ALL','BR','OBR','POM','NAP'].forEach(p => {{
    const labels = {{ALL:'ALL',BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD'}};
    const active = trPos === p ? ' active' : '';
    h += '<button class="pos-btn tr-pos-btn' + active + '" data-trpos="' + p + '" data-pos="' + p + '">' + labels[p] + '</button>';
  }});
  h += '</div>';
  h += '<span class="tr-gw-badge" style="margin-left:auto">K' + prevGw + ' → K' + gw + ' · ' + leagueCount + ' drużyn</span>';
  h += '</div>';

  // Two tables side by side
  h += '<div class="transfers-grid">';
  h += '<div>' + renderTransfersTable(tin, leagueCount, '🟢 Najpopularniejsze kupna', '#10b981') + '</div>';
  h += '<div>' + renderTransfersTable(tout, leagueCount, '🔴 Najpopularniejsze sprzedaże', '#ef4444') + '</div>';
  h += '</div>';

  return h;
}}

function renderPredictions() {{
  if (!PREDICTIONS || !PREDICTIONS.length) return '<div class="empty-msg">Brak danych prognoz — sprawdź czy predictor.py jest dostępny i dane FDR zostały obliczone</div>';

  let data = [...PREDICTIONS].filter(p => p.predicted_points !== null && p.predicted_points !== undefined);
  if (predPos !== 'ALL') data = data.filter(p => (POS_ID[p.position] || p.position) === predPos);
  if (!data.length) return '<div class="empty-msg">Brak prognoz dla wybranej pozycji</div>';

  // Sort
  const s = sorts.predictions;
  data.sort((a, b) => {{
    // Niedostępni zawodnicy ZAWSZE na końcu, niezależnie od sortowania
    if (a.unavailable && !b.unavailable) return 1;
    if (!a.unavailable && b.unavailable) return -1;
    if (a.unavailable && b.unavailable) {{
      // Wśród niedostępnych sortuj alfabetycznie
      const an = (a.name || '').toLowerCase();
      const bn = (b.name || '').toLowerCase();
      return an < bn ? -1 : an > bn ? 1 : 0;
    }}
    let av = a[s.col], bv = b[s.col];
    if (s.col === 'name' || s.col === 'team' || s.col === 'next_opponent') {{
      av = (av || '').toLowerCase(); bv = (bv || '').toLowerCase();
      if (av < bv) return s.dir === 'desc' ? 1 : -1;
      if (av > bv) return s.dir === 'desc' ? -1 : 1;
      return 0;
    }}
    av = num(av); bv = num(bv);
    if (av < bv) return s.dir === 'desc' ? 1 : -1;
    if (av > bv) return s.dir === 'desc' ? -1 : 1;
    return 0;
  }});

  function predArrow(col) {{
    return s.col === col ? (s.dir === 'desc' ? ' ▼' : ' ▲') : '';
  }}

  // Prediction value gradient: high = green, medium = yellow, low = gray
  function predGradient(val) {{
    if (val >= 8) return 'background:rgba(16,185,129,0.25);color:#10b981';
    if (val >= 6) return 'background:rgba(34,211,238,0.2);color:#22d3ee';
    if (val >= 4) return 'background:rgba(251,191,36,0.2);color:#fbbf24';
    if (val >= 2) return 'background:rgba(148,163,184,0.15);color:#94a3b8';
    return 'background:rgba(100,116,139,0.1);color:#64748b';
  }}

  function fdrTile(val) {{
    const c = FDR_COLORS[val] || FDR_COLORS[3];
    return '<span class="pred-fdr-tile" style="background:'+c.bg+';color:'+c.fg+'">'+val+'</span>';
  }}

  function fdrUsedLabel(position, fdr_mod) {{
    const pk = POS_ID[position] || position;
    let label = 'MIX';
    if (pk === 'NAP') label = 'DEF';
    else if (pk === 'OBR' || pk === 'BR') label = 'ATK';
    const color = fdr_mod > 1.0 ? '#10b981' : fdr_mod < 1.0 ? '#ef4444' : '#94a3b8';
    return '<span class="pred-fdr-used" style="color:'+color+'">'+label+' ×'+fdr_mod.toFixed(2)+'</span>';
  }}

  function confidenceBadge(conf) {{
    const map = {{
      high: {{emoji:'🟢', label:'high', cls:'pred-conf-high'}},
      medium: {{emoji:'🟡', label:'medium', cls:'pred-conf-medium'}},
      low: {{emoji:'🔴', label:'low', cls:'pred-conf-low'}},
      insufficient_data: {{emoji:'⚪', label:'insuf.', cls:'pred-conf-insufficient'}},
      unavailable: {{emoji:'⛔', label:'niedostępny', cls:'pred-conf-unavailable'}},
    }};
    const m = map[conf] || map.low;
    return '<span class="pred-confidence '+m.cls+'">'+m.emoji+' '+m.label+'</span>';
  }}

  let h = '<div class="section-title"><span style="font-size:22px">🔮</span><h2>Prognoza punktów — następna kolejka</h2><div class="line"></div></div>';

  // Legend
  h += '<div class="pred-legend">';
  h += '<b>NAP</b> / <b>POM</b> → FDR DEF rywala (słabsza obrona = wyższa prognoza) &nbsp;|&nbsp; ';
  h += '<b>BR</b> / <b>OBR</b> → FDR ATK rywala (słabszy atak = wyższa prognoza)';
  h += '</div>';

  // Position filters
  h += '<div class="pred-filters">';
  h += '<div class="pos-filters">';
  ['ALL','BR','OBR','POM','NAP'].forEach(p => {{
    const labels = {{ALL:'ALL',BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD'}};
    const active = predPos === p ? ' active' : '';
    h += '<button class="pos-btn pred-pos-btn'+active+'" data-predpos="'+p+'" data-pos="'+p+'">'+labels[p]+'</button>';
  }});
  h += '</div>';
  h += '<span style="margin-left:auto;font-size:12px;color:#64748b">'+data.length+' zawodników</span>';
  h += '</div>';

  // Table
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-left">#</th>';
  h += '<th class="text-left sortable" data-tab="predictions" data-col="name">Zawodnik'+predArrow('name')+'</th>';
  h += '<th class="text-center sortable" data-tab="predictions" data-col="position">Poz'+predArrow('position')+'</th>';
  h += '<th class="text-left sortable" data-tab="predictions" data-col="team">Drużyna'+predArrow('team')+'</th>';
  h += '<th class="text-center">Rywal</th>';
  h += '<th class="text-center">D/W</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="predicted_points">Prognoza'+predArrow('predicted_points')+'</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="base_avg">Śr. pkt'+predArrow('base_avg')+'</th>';
  h += '<th class="text-center">FDR ATK</th>';
  h += '<th class="text-center">FDR DEF</th>';
  h += '<th class="text-center">Użyty FDR</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="avg_minutes">Śr. min'+predArrow('avg_minutes')+'</th>';
  h += '<th class="text-center sortable" data-tab="predictions" data-col="confidence">Pewność'+predArrow('confidence')+'</th>';
  h += '</tr></thead><tbody>';

  data.forEach((p, i) => {{
    const pred = p.predicted_points || 0;
    const pk = POS_ID[p.position] || p.position || '';
    const oppFdrAtk = p.fdr_atk_opponent || 3;
    const oppFdrDef = p.fdr_def_opponent || 3;
    const fdrMod = p.fdr_modifier || 1.0;
    const avgMin = p.avg_minutes || 0;
    const baseAvg = p.base_avg || 0;
    const detail = p.detail || '';
    const isUnavailable = p.unavailable === true;
    const unavailableReason = p.availability_reason || '';

    // Wiersz dla niedostępnego zawodnika — przyciemniony, z markerem
    const rowStyle = isUnavailable ? ' style="opacity:0.55"' : '';
    h += '<tr'+rowStyle+'>';
    h += '<td class="c-muted fw-600">'+(i+1)+'</td>';
    h += '<td class="fw-600" title="'+detail.replace(/"/g,'&quot;')+'">'+p.name+(isUnavailable ? ' <span style="font-size:11px;color:#ef4444">⛔ '+unavailableReason+'</span>' : '')+'</td>';
    h += '<td class="text-center">'+posBadge(pk)+'</td>';
    h += '<td class="c-muted" style="font-size:13px">'+p.team+'</td>';

    // Rywal z FDR kolorem (używamy wyższego FDR)
    const oppName = p.opponent_short || p.next_opponent || '';
    const oppFdr = Math.max(oppFdrAtk, oppFdrDef);
    const oppC = FDR_COLORS[oppFdr] || FDR_COLORS[3];
    h += '<td class="text-center"><span class="pred-fdr-tile" style="background:'+oppC.bg+';color:'+oppC.fg+';font-size:11px;padding:3px 8px">'+oppName+'</span></td>';

    // Dom/Wyjazd
    h += '<td class="text-center">'+(p.is_home ? '🏠' : '✈️')+'</td>';

    // Prognoza — pogrubiona, gradient; dla niedostępnych: "—"
    if (isUnavailable) {{
      h += '<td class="text-right"><span class="pred-val" style="color:#64748b;font-style:italic">—</span></td>';
    }} else {{
      h += '<td class="text-right"><span class="pred-val" style="'+predGradient(pred)+'">'+pred.toFixed(1)+'</span></td>';
    }}

    // Średnia ważona
    const avgC = baseAvg >= 6 ? '#22d3ee' : baseAvg >= 3 ? '#10b981' : '#94a3b8';
    h += '<td class="text-right fw-600" style="color:'+avgC+'">'+baseAvg.toFixed(1)+'</td>';

    // FDR ATK/DEF rywala
    h += '<td class="text-center">'+fdrTile(oppFdrAtk)+'</td>';
    h += '<td class="text-center">'+fdrTile(oppFdrDef)+'</td>';

    // Użyty FDR
    h += '<td class="text-center">'+fdrUsedLabel(p.position, fdrMod)+'</td>';

    // Średnie minuty
    h += '<td class="text-right c-muted">'+Math.round(avgMin)+'&prime;</td>';

    // Pewność
    h += '<td class="text-center">'+confidenceBadge(p.confidence)+'</td>';

    h += '</tr>';
  }});

  h += '</tbody></table></div>';
  return h;
}}

function renderAccuracy() {{
  if (!ACCURACY_HISTORY || !ACCURACY_HISTORY.length) return '<div class="empty-msg">Brak danych trafności — uruchom scraper przynajmniej dwa razy, aby porównać prognozy z rzeczywistością</div>';

  const latest = ACCURACY_HISTORY[ACCURACY_HISTORY.length - 1];
  let h = '';

  // === STAT CARDS ===
  const maeByPos = latest.mae_by_pos || {{}};
  const posNames = Object.keys(maeByPos);
  let bestPos = '—';
  let bestPosVal = Infinity;
  posNames.forEach(p => {{ if (maeByPos[p] < bestPosVal) {{ bestPosVal = maeByPos[p]; bestPos = p; }} }});

  h += '<div class="stats-row">';
  h += '<div class="stat-card accent-cyan"><div class="val">' + latest.mae + ' pkt</div><div class="label">MAE ogólne</div><div class="sub">Średni błąd prognozy</div></div>';
  h += '<div class="stat-card accent-green"><div class="val">' + Math.round(latest.hit_rate * 100) + '%</div><div class="label">Hit rate</div><div class="sub">Błąd &lt; 3 pkt</div></div>';
  h += '<div class="stat-card accent-gold"><div class="val">' + bestPos + ' — ' + bestPosVal + '</div><div class="label">Najlepsza pozycja</div><div class="sub">Najniższy MAE</div></div>';
  h += '<div class="stat-card accent-purple"><div class="val">' + latest.top10_mae + ' pkt</div><div class="label">Top 10 MAE</div><div class="sub">Trafność liderów</div></div>';
  h += '</div>';

  // === MAE TREND CHART (SVG) ===
  if (ACCURACY_HISTORY.length >= 1) {{
    const W = 700, H = 250, PAD = 50, PADR = 30, PADT = 20, PADB = 40;
    const chartW = W - PAD - PADR, chartH = H - PADT - PADB;

    // Zbierz dane
    const rounds = ACCURACY_HISTORY.map(a => a.round);
    const allVals = [];
    ACCURACY_HISTORY.forEach(a => {{
      allVals.push(a.mae);
      ['BR','OBR','POM','NAP'].forEach(p => {{ if (a.mae_by_pos && a.mae_by_pos[p] !== undefined) allVals.push(a.mae_by_pos[p]); }});
    }});
    const minR = Math.min(...rounds), maxR = Math.max(...rounds);
    const maxV = Math.max(...allVals, 1);
    const rangeR = Math.max(maxR - minR, 1);

    const x = r => PAD + ((r - minR) / rangeR) * chartW;
    const y = v => PADT + chartH - (v / maxV) * chartH;

    let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;max-width:700px;height:auto;display:block;margin:20px auto;">';

    // Grid lines
    for (let i = 0; i <= 4; i++) {{
      const yy = PADT + (chartH / 4) * i;
      const val = (maxV * (4 - i) / 4).toFixed(1);
      svg += '<line x1="' + PAD + '" y1="' + yy + '" x2="' + (W - PADR) + '" y2="' + yy + '" stroke="#334155" stroke-width="1"/>';
      svg += '<text x="' + (PAD - 8) + '" y="' + (yy + 4) + '" text-anchor="end" fill="#64748b" font-size="11">' + val + '</text>';
    }}

    // X axis labels
    rounds.forEach(r => {{
      svg += '<text x="' + x(r) + '" y="' + (H - 8) + '" text-anchor="middle" fill="#64748b" font-size="11">K' + r + '</text>';
    }});

    // Position lines
    const posColors = {{BR:'#f59e0b', OBR:'#3b82f6', POM:'#10b981', NAP:'#ef4444'}};
    ['BR','OBR','POM','NAP'].forEach(pos => {{
      const pts = [];
      ACCURACY_HISTORY.forEach(a => {{
        if (a.mae_by_pos && a.mae_by_pos[pos] !== undefined) pts.push({{r: a.round, v: a.mae_by_pos[pos]}});
      }});
      if (pts.length > 1) {{
        const d = pts.map((p, i) => (i === 0 ? 'M' : 'L') + x(p.r) + ',' + y(p.v)).join(' ');
        svg += '<path d="' + d + '" fill="none" stroke="' + posColors[pos] + '" stroke-width="1.5" opacity="0.6"/>';
      }} else if (pts.length === 1) {{
        svg += '<circle cx="' + x(pts[0].r) + '" cy="' + y(pts[0].v) + '" r="4" fill="' + posColors[pos] + '" opacity="0.6"/>';
      }}
    }});

    // Overall MAE line (thick, white)
    if (ACCURACY_HISTORY.length > 1) {{
      const d = ACCURACY_HISTORY.map((a, i) => (i === 0 ? 'M' : 'L') + x(a.round) + ',' + y(a.mae)).join(' ');
      svg += '<path d="' + d + '" fill="none" stroke="#e2e8f0" stroke-width="2.5"/>';
    }}
    // Dots for overall MAE
    ACCURACY_HISTORY.forEach(a => {{
      svg += '<circle cx="' + x(a.round) + '" cy="' + y(a.mae) + '" r="4" fill="#e2e8f0"/>';
    }});

    svg += '</svg>';

    // Legend
    let legend = '<div style="display:flex;gap:16px;justify-content:center;flex-wrap:wrap;margin-bottom:16px;">';
    legend += '<span style="color:#e2e8f0;font-weight:700;font-size:12px;">━━ MAE ogólne</span>';
    Object.entries(posColors).forEach(([p, c]) => {{
      legend += '<span style="color:' + c + ';font-size:12px;">━ ' + p + '</span>';
    }});
    legend += '</div>';

    h += '<div class="section-title" style="margin-top:24px;"><h2>Trend MAE</h2><div class="line"></div></div>';
    h += '<div class="data-table" style="padding:16px;">' + svg + legend + '</div>';
  }}

  // === DETAIL TABLE (latest round) ===
  const details = latest.details || [];
  if (details.length) {{
    h += '<div class="section-title" style="margin-top:24px;"><h2>Szczegóły — Kolejka ' + latest.round + '</h2><div class="line"></div></div>';

    if (!sorts.accuracy) sorts.accuracy = {{col:'abs_error', dir:'asc'}};
    const s = sorts.accuracy;
    let sorted = [...details];
    sorted.forEach(d => {{ d.abs_error = Math.abs(d.error); }});
    sorted.sort((a, b) => {{
      let va = a[s.col], vb = b[s.col];
      if (typeof va === 'string') {{ va = va.toLowerCase(); vb = (vb||'').toLowerCase(); }}
      if (va < vb) return s.dir === 'asc' ? -1 : 1;
      if (va > vb) return s.dir === 'asc' ? 1 : -1;
      return 0;
    }});

    function accArrow(col) {{
      if (s.col !== col) return '';
      return s.dir === 'desc' ? ' ▼' : ' ▲';
    }}

    h += '<div class="data-table"><table><thead><tr>';
    h += '<th class="text-left sortable" data-tab="accuracy" data-col="name">Zawodnik' + accArrow('name') + '</th>';
    h += '<th class="text-center sortable" data-tab="accuracy" data-col="position">Poz' + accArrow('position') + '</th>';
    h += '<th class="text-left sortable" data-tab="accuracy" data-col="team">Drużyna' + accArrow('team') + '</th>';
    h += '<th class="text-right sortable" data-tab="accuracy" data-col="predicted">Prognoza' + accArrow('predicted') + '</th>';
    h += '<th class="text-right sortable" data-tab="accuracy" data-col="actual">Rzeczywistość' + accArrow('actual') + '</th>';
    h += '<th class="text-right sortable" data-tab="accuracy" data-col="abs_error">Błąd' + accArrow('abs_error') + '</th>';
    h += '</tr></thead><tbody>';

    sorted.forEach(d => {{
      const absErr = Math.abs(d.error);
      let errColor = '#ef4444';
      if (absErr < 2) errColor = '#10b981';
      else if (absErr < 4) errColor = '#94a3b8';

      const posClass = 'pos-' + (d.position || '');
      h += '<tr>';
      h += '<td class="text-left">' + (d.name || '') + '</td>';
      h += '<td class="text-center"><span class="pos-badge ' + posClass + '">' + (d.position || '') + '</span></td>';
      h += '<td class="text-left c-muted">' + (d.team || '') + '</td>';
      h += '<td class="text-right">' + (d.predicted != null ? d.predicted.toFixed(1) : '—') + '</td>';
      h += '<td class="text-right">' + (d.actual != null ? d.actual : '—') + '</td>';
      h += '<td class="text-right" style="color:' + errColor + ';font-weight:700;">' + absErr.toFixed(1) + '</td>';
      h += '</tr>';
    }});

    h += '</tbody></table></div>';
  }}

  // === AUTO-TUNING SECTION ===
  // Sekcja pokazuje status i wyniki auto-tunera parametrów predictora
  h += '<div class="section-title" style="margin-top:32px;"><h2>🔧 Auto-tuning</h2><div class="line"></div></div>';
  h += '<div class="data-table" style="padding:20px;">';

  if (!TUNED_PARAMS) {{
    // Tuning jeszcze nie miał wystarczająco danych — zbieramy historię
    const totalRounds = ACCURACY_HISTORY ? ACCURACY_HISTORY.length : 0;
    h += '<div style="text-align:center;padding:16px 0;">';
    h += '<div style="font-size:32px;margin-bottom:8px;">⏳</div>';
    h += '<div style="color:#94a3b8;font-size:14px;">Zbiera dane (' + totalRounds + '/4 kolejek)</div>';
    h += '<div style="color:#64748b;font-size:12px;margin-top:4px;">Auto-tuning uruchomi się automatycznie po zebraniu min. 4 kolejek historii trafności</div>';
    h += '</div>';
  }} else {{
    // Tuning został wykonany — pokazuj wyniki
    const tp = TUNED_PARAMS;

    // Domyślne wartości predictora (przed tuningiem)
    const defaults = {{
      decay: 0.85,
      fdr_strength: 1.0,
      home_away_bonus: 0.05,
    }};

    // Status: aktywny
    h += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;">';
    h += '<span style="background:#10b981;color:#fff;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:700;">✅ Aktywny</span>';
    h += '<span style="color:#94a3b8;font-size:13px;">' + tp.rounds_used + ' kolejek · ostatni tuning: ' + (tp.last_tuned || '—') + '</span>';
    h += '</div>';

    // Tabela porównawcza parametrów
    h += '<table style="width:100%;border-collapse:collapse;margin-bottom:20px;">';
    h += '<thead><tr>';
    h += '<th style="text-align:left;padding:8px 12px;border-bottom:1px solid #334155;color:#64748b;font-size:12px;font-weight:600;">PARAMETR</th>';
    h += '<th style="text-align:right;padding:8px 12px;border-bottom:1px solid #334155;color:#64748b;font-size:12px;font-weight:600;">DOMYŚLNA</th>';
    h += '<th style="text-align:right;padding:8px 12px;border-bottom:1px solid #334155;color:#64748b;font-size:12px;font-weight:600;">WYTUNOWANA</th>';
    h += '<th style="text-align:right;padding:8px 12px;border-bottom:1px solid #334155;color:#64748b;font-size:12px;font-weight:600;">ZMIANA</th>';
    h += '</tr></thead><tbody>';

    function tuneRow(label, key, fmt) {{
      const defVal = defaults[key];
      const tunedVal = tp[key];
      if (tunedVal === undefined || tunedVal === null) return '';
      const diff = tunedVal - defVal;
      const diffStr = diff > 0.001 ? '+' + fmt(diff) : diff < -0.001 ? fmt(diff) : '—';
      const diffColor = Math.abs(diff) > 0.001 ? '#f59e0b' : '#64748b';
      return '<tr>'
        + '<td style="padding:8px 12px;color:#e2e8f0;font-size:13px;">' + label + '</td>'
        + '<td style="text-align:right;padding:8px 12px;color:#64748b;font-size:13px;">' + fmt(defVal) + '</td>'
        + '<td style="text-align:right;padding:8px 12px;color:#e2e8f0;font-weight:700;font-size:13px;">' + fmt(tunedVal) + '</td>'
        + '<td style="text-align:right;padding:8px 12px;color:' + diffColor + ';font-size:13px;">' + diffStr + '</td>'
        + '</tr>';
    }}

    const f2 = v => (Math.round(v * 100) / 100).toFixed(2);
    h += tuneRow('Decay (zanik wag)', 'decay', f2);
    h += tuneRow('FDR Strength (siła FDR)', 'fdr_strength', f2);
    h += tuneRow('Home/Away Bonus', 'home_away_bonus', f2);

    h += '</tbody></table>';

    // Poprawa MAE
    if (tp.mae_before != null && tp.mae_after != null) {{
      const improved = tp.mae_after < tp.mae_before;
      const arrow = improved ? '↓' : '↑';
      const color = improved ? '#10b981' : '#ef4444';
      const sign = improved ? '' : '+';
      h += '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">';
      h += '<div style="background:#1e293b;border-radius:8px;padding:12px 20px;">';
      h += '<div style="color:#64748b;font-size:11px;font-weight:600;margin-bottom:4px;">POPRAWA MAE</div>';
      h += '<div style="font-size:18px;font-weight:700;">';
      h += '<span style="color:#94a3b8;">' + tp.mae_before.toFixed(1) + '</span>';
      h += ' <span style="color:#64748b;font-size:14px;">→</span> ';
      h += '<span style="color:#e2e8f0;">' + tp.mae_after.toFixed(1) + '</span>';
      const pct = tp.improvement_pct != null ? tp.improvement_pct : 0;
      h += ' <span style="color:' + color + ';font-size:14px;">(' + arrow + Math.abs(pct).toFixed(1) + '%)</span>';
      h += '</div>';
      h += '</div>';
      h += '</div>';
    }}
  }}

  h += '</div>';  // end data-table

  return h;
}}

// ========== SEASON TRACKER ==========
// Stan widoku sezonu — przechowywany poza renderSeason(), bo render() czyści DOM
let seasonView = 'positions';  // 'positions' lub 'points'
let seasonFilter = 'all';     // 'all', 'top5', 'bottom5'
let seasonHidden = {{}};       // {{teamName: true}} — ukryte linie

// Paleta kolorów czytelna na ciemnym tle
const SEASON_COLORS = [
  '#22d3ee','#f59e0b','#10b981','#a78bfa','#f472b6','#fb923c',
  '#38bdf8','#facc15','#4ade80','#c084fc','#fb7185','#fdba74',
  '#67e8f9','#fde047','#86efac','#d8b4fe','#fda4af','#fed7aa',
];

function renderSeason() {{
  const rounds = (LEAGUE_HISTORY.rounds || []);
  if (rounds.length < 1) {{
    return '<div class="empty-msg">Zbieranie danych — wykres pojawi się po 2+ kolejkach</div>';
  }}

  // Zbierz wszystkie drużyny (unikalne nazwy)
  const teamSet = new Set();
  rounds.forEach(r => (r.standings || []).forEach(s => teamSet.add(s.team)));
  const allTeams = [...teamSet];

  // Przypisz kolory
  const teamColor = {{}};
  allTeams.forEach((t, i) => teamColor[t] = SEASON_COLORS[i % SEASON_COLORS.length]);

  // Ostatnia kolejka — aktualne pozycje do filtrowania
  const lastRound = rounds[rounds.length - 1];
  const lastStandings = {{}};
  (lastRound.standings || []).forEach(s => lastStandings[s.team] = s);

  // Filtruj drużyny wg przełącznika
  let visibleTeams = allTeams;
  if (seasonFilter === 'top5') {{
    visibleTeams = allTeams.filter(t => lastStandings[t] && lastStandings[t].position <= 5);
  }} else if (seasonFilter === 'bottom5') {{
    const sorted = allTeams.filter(t => lastStandings[t]).sort((a, b) => lastStandings[b].position - lastStandings[a].position);
    visibleTeams = sorted.slice(0, 5);
  }}

  // Wymiary wykresu SVG
  const marginL = 44, marginR = 20, marginT = 20, marginB = 36;
  const numRounds = rounds.length;
  // Szerokość punktu danych: min 60px, dopasuj do ekranu
  const ptW = Math.max(60, Math.min(100, (900 - marginL - marginR) / Math.max(numRounds - 1, 1)));
  const chartW = marginL + marginR + ptW * Math.max(numRounds - 1, 1);
  const chartH = 320;
  const plotW = chartW - marginL - marginR;
  const plotH = chartH - marginT - marginB;

  // Zakres osi Y
  let yMin, yMax;
  if (seasonView === 'positions') {{
    // Pozycje: 1..maxPos (odwrócone — 1 na górze)
    const maxPos = allTeams.length || 1;
    yMin = 1;
    yMax = maxPos;
  }} else {{
    // Punkty łącznie: 0..max
    let maxPts = 0;
    rounds.forEach(r => (r.standings || []).forEach(s => {{ if (s.total_points > maxPts) maxPts = s.total_points; }}));
    yMin = 0;
    yMax = maxPts || 100;
  }}

  // Funkcje mapowania
  const xScale = (idx) => marginL + (numRounds > 1 ? idx / (numRounds - 1) * plotW : plotW / 2);
  const yScale = (val) => {{
    if (seasonView === 'positions') {{
      // Odwrócona oś — pozycja 1 na górze
      return marginT + (val - yMin) / (yMax - yMin) * plotH;
    }} else {{
      // Punkty rosnąco w górę
      return marginT + plotH - (val - yMin) / (yMax - yMin || 1) * plotH;
    }}
  }};

  // Buduj SVG
  let svg = '<svg width="' + chartW + '" height="' + chartH + '" xmlns="http://www.w3.org/2000/svg">';

  // Siatka i etykiety osi Y
  const yTicks = seasonView === 'positions'
    ? Array.from({{length: Math.min(yMax, 10)}}, (_, i) => i + 1)
    : (() => {{
        const step = Math.ceil(yMax / 6 / 10) * 10 || 10;
        const ticks = [];
        for (let v = 0; v <= yMax; v += step) ticks.push(v);
        return ticks;
      }})();

  yTicks.forEach(v => {{
    const y = yScale(v);
    svg += '<line x1="' + marginL + '" y1="' + y + '" x2="' + (chartW - marginR) + '" y2="' + y + '" stroke="#1e293b" stroke-width="1"/>';
    svg += '<text x="' + (marginL - 8) + '" y="' + (y + 4) + '" text-anchor="end" fill="#64748b" font-size="11" font-family="DM Sans,sans-serif">' + v + '</text>';
  }});

  // Etykiety osi X — numery kolejek
  rounds.forEach((r, i) => {{
    const x = xScale(i);
    svg += '<text x="' + x + '" y="' + (chartH - 8) + '" text-anchor="middle" fill="#64748b" font-size="11" font-family="DM Sans,sans-serif">' + r.round + '</text>';
  }});

  // Linie drużyn
  // Budujemy dane per drużyna: [{{x, y, round, team, position, total_points}}]
  const teamLines = {{}};
  visibleTeams.forEach(team => {{
    teamLines[team] = [];
    rounds.forEach((r, ri) => {{
      const s = (r.standings || []).find(s => s.team === team);
      if (s) {{
        const val = seasonView === 'positions' ? s.position : s.total_points;
        teamLines[team].push({{
          x: xScale(ri), y: yScale(val),
          round: r.round, team: team,
          position: s.position, total_points: s.total_points, round_points: s.round_points || 0,
        }});
      }}
    }});
  }});

  // Rysuj linie i punkty
  visibleTeams.forEach(team => {{
    if (seasonHidden[team]) return;
    const pts = teamLines[team];
    if (pts.length < 1) return;
    const color = teamColor[team];
    // Grubsza linia dla własnej drużyny (slug zawierający 'tokusatsu' lub pozycja 1)
    const isOwn = team.toLowerCase().includes('tokusatsu');
    const sw = isOwn ? 3 : 1.5;
    const opacity = isOwn ? 1 : 0.85;

    // Polyline
    const points = pts.map(p => p.x + ',' + p.y).join(' ');
    svg += '<polyline points="' + points + '" fill="none" stroke="' + color + '" stroke-width="' + sw + '" stroke-opacity="' + opacity + '" stroke-linejoin="round" stroke-linecap="round"/>';

    // Punkty danych (klikalne kółka)
    pts.forEach((p, pi) => {{
      svg += '<circle cx="' + p.x + '" cy="' + p.y + '" r="' + (isOwn ? 5 : 3.5) + '" fill="' + color + '" stroke="#0f172a" stroke-width="1.5"'
        + ' data-season-pt="1"'
        + ' data-tip="Kolejka ' + p.round + ': ' + p.team + ' — poz. ' + p.position + ' (' + p.total_points + ' pkt)"'
        + ' style="cursor:pointer" />';
    }});
  }});

  svg += '</svg>';

  // === Buduj HTML ===
  let h = '<div class="section-title"><span style="font-size:22px">📈</span><h2>Sezon — historia ligi</h2><div class="line"></div></div>';

  // Kontrolki
  h += '<div class="season-controls">';
  h += '<button class="season-btn' + (seasonView === 'positions' ? ' active' : '') + '" data-sview="positions">Pozycje</button>';
  h += '<button class="season-btn' + (seasonView === 'points' ? ' active' : '') + '" data-sview="points">Punkty łącznie</button>';
  h += '<span style="width:16px"></span>';
  h += '<button class="season-btn' + (seasonFilter === 'all' ? ' active' : '') + '" data-sfilter="all">Wszystkie</button>';
  h += '<button class="season-btn' + (seasonFilter === 'top5' ? ' active' : '') + '" data-sfilter="top5">Top 5</button>';
  h += '<button class="season-btn' + (seasonFilter === 'bottom5' ? ' active' : '') + '" data-sfilter="bottom5">Dolne 5</button>';
  h += '</div>';

  // Wykres
  h += '<div class="season-wrap">';
  h += '<div class="season-chart" id="seasonChart">';
  h += svg;
  h += '<div class="season-tooltip" id="seasonTooltip"></div>';
  h += '</div>';

  // Legenda
  h += '<div class="season-legend">';
  visibleTeams.forEach(team => {{
    const color = teamColor[team];
    const cls = seasonHidden[team] ? ' hidden' : '';
    h += '<span class="season-legend-item' + cls + '" data-steam="' + team.replace(/"/g, '&quot;') + '">';
    h += '<span class="swatch" style="background:' + color + '"></span>' + team;
    h += '</span>';
  }});
  h += '</div>';
  h += '</div>';  // season-wrap

  // === Tabela szczegółów ===
  if (lastRound && lastRound.standings && lastRound.standings.length > 0) {{
    h += '<div class="season-table"><div class="data-table"><table>';
    h += '<thead><tr>';
    h += '<th class="text-left">Drużyna</th><th class="text-center">Poz.</th><th class="text-right">Punkty</th>';
    h += '<th class="text-right">Średnia/kol.</th><th class="text-right">Najlepsza kol.</th><th class="text-right">Najgorsza kol.</th>';
    h += '<th class="text-center">Trend</th>';
    h += '</tr></thead><tbody>';

    // Oblicz statystyki per drużyna
    const teamStats = [];
    allTeams.forEach(team => {{
      const roundData = [];
      rounds.forEach(r => {{
        const s = (r.standings || []).find(s => s.team === team);
        if (s) roundData.push({{ round: r.round, pts: s.round_points || 0, pos: s.position, total: s.total_points }});
      }});
      if (roundData.length === 0) return;

      const last = roundData[roundData.length - 1];
      const totalPts = last.total;
      const avg = roundData.length > 0 ? (totalPts / roundData.length) : 0;

      // Najlepsza/najgorsza kolejka (po round_points)
      let bestRound = roundData[0], worstRound = roundData[0];
      roundData.forEach(rd => {{
        if (rd.pts > bestRound.pts) bestRound = rd;
        if (rd.pts < worstRound.pts) worstRound = rd;
      }});

      // Trend — zmiana pozycji w ostatnich 3 kolejkach
      let trend = 0;
      if (roundData.length >= 2) {{
        const recent = roundData.slice(-3);
        trend = recent[0].pos - recent[recent.length - 1].pos;
      }}

      teamStats.push({{
        team, position: last.pos, totalPts, avg,
        bestRound: bestRound.pts + ' (K' + bestRound.round + ')',
        worstRound: worstRound.pts + ' (K' + worstRound.round + ')',
        trend,
      }});
    }});

    // Sortuj po pozycji
    teamStats.sort((a, b) => a.position - b.position);

    teamStats.forEach(ts => {{
      const trendHtml = ts.trend > 0
        ? '<span class="trend-up">▲' + ts.trend + '</span>'
        : ts.trend < 0
          ? '<span class="trend-down">▼' + Math.abs(ts.trend) + '</span>'
          : '<span class="trend-flat">●</span>';
      const color = teamColor[ts.team] || '#e2e8f0';
      h += '<tr>';
      h += '<td class="text-left" style="color:' + color + ';font-weight:600">' + ts.team + '</td>';
      h += '<td class="text-center fw-700">' + ts.position + '</td>';
      h += '<td class="text-right fw-600">' + ts.totalPts + '</td>';
      h += '<td class="text-right">' + ts.avg.toFixed(1) + '</td>';
      h += '<td class="text-right" style="color:#10b981">' + ts.bestRound + '</td>';
      h += '<td class="text-right" style="color:#ef4444">' + ts.worstRound + '</td>';
      h += '<td class="text-center">' + trendHtml + '</td>';
      h += '</tr>';
    }});

    h += '</tbody></table></div></div>';
  }}

  return h;
}}

function attachSeasonHandlers() {{
  // Przełączniki widoku i filtra
  document.querySelectorAll('[data-sview]').forEach(btn => {{
    btn.onclick = () => {{ seasonView = btn.dataset.sview; render(); }};
  }});
  document.querySelectorAll('[data-sfilter]').forEach(btn => {{
    btn.onclick = () => {{ seasonFilter = btn.dataset.sfilter; render(); }};
  }});
  // Legenda — klik ukrywa/pokazuje linię
  document.querySelectorAll('.season-legend-item').forEach(item => {{
    item.onclick = () => {{
      const team = item.dataset.steam;
      seasonHidden[team] = !seasonHidden[team];
      render();
    }};
  }});
  // Tooltip na punktach wykresu
  const chart = document.getElementById('seasonChart');
  const tip = document.getElementById('seasonTooltip');
  if (chart && tip) {{
    chart.addEventListener('mouseover', (e) => {{
      const el = e.target.closest('[data-season-pt]');
      if (el) {{
        tip.textContent = el.dataset.tip;
        tip.classList.add('visible');
        const rect = chart.getBoundingClientRect();
        const cx = parseFloat(el.getAttribute('cx'));
        const cy = parseFloat(el.getAttribute('cy'));
        tip.style.left = (cx + 12) + 'px';
        tip.style.top = (cy - 10) + 'px';
      }}
    }});
    chart.addEventListener('mouseout', (e) => {{
      if (e.target.closest('[data-season-pt]')) {{
        tip.classList.remove('visible');
      }}
    }});
  }}
}}

// ============================================================
// 📖 PORÓWNYWARKA ZAWODNIKÓW
// Pozwala wybrać 2-3 graczy i porównać ich obok siebie:
// karty, tabela statystyk, wykres formy (SVG), siatka FDR.
// ============================================================

// 📖 Kolory przypisane do pozycji w kartach — stałe, czytelne
const CMP_COLORS = ['#22d3ee', '#fbbf24', '#a78bfa'];

function cmpAddPlayer(id) {{
  if (cmpSelected.length >= 3) return;
  if (cmpSelected.includes(id)) return;
  cmpSelected.push(id);
  render();
}}
function cmpRemovePlayer(id) {{
  cmpSelected = cmpSelected.filter(x => x !== id);
  render();
}}
function cmpClear() {{
  cmpSelected = [];
  render();
}}

function renderComparison() {{
  // 📖 Łączymy dane z PLAYERS i PREDICTIONS — PLAYERS mają formę i cenę,
  // PREDICTIONS mają prognozę, FDR, średnią minut itp.
  const allPlayers = PLAYERS.map(p => {{
    const pred = PREDICTIONS.find(pr => pr.player_id === p.player_id) || {{}};
    return {{...p, ...pred, _src: p}};
  }});

  let h = '<div class="section-title"><span style="font-size:22px">⚖️</span><h2>Porównanie zawodników</h2><div class="line"></div></div>';

  // --- Pole wyszukiwania ---
  h += '<div class="cmp-search-wrap">';
  h += '<div class="cmp-search-box">';
  h += '<input class="cmp-search-input" id="cmpSearchInput" type="text" placeholder="Wpisz imię zawodnika… (min 2, max 3)" autocomplete="off">';
  h += '<div class="cmp-autocomplete" id="cmpAutocomplete"></div>';
  h += '</div>';
  h += '<button class="cmp-clear-btn" onclick="cmpClear()">Wyczyść</button>';
  h += '</div>';

  // --- Chipy wybranych zawodników ---
  if (cmpSelected.length) {{
    h += '<div class="cmp-selected-chips">';
    cmpSelected.forEach((id, i) => {{
      const p = allPlayers.find(x => x.player_id === id);
      if (!p) return;
      const pk = POS_ID[p.position] || p.position || '';
      h += '<div class="cmp-chip" style="border-color:'+CMP_COLORS[i]+'">';
      h += posBadge(p.position) + ' <strong>' + p.name + '</strong> <span style="color:#64748b;font-size:11px">(' + p.team + ')</span>';
      h += '<button class="cmp-chip-remove" onclick="cmpRemovePlayer('+id+')">×</button>';
      h += '</div>';
    }});
    h += '</div>';
  }}

  // Jeśli mniej niż 2 zawodników — pokaż instrukcję
  if (cmpSelected.length < 2) {{
    h += '<div class="cmp-empty"><div class="cmp-empty-icon">⚖️</div>';
    h += 'Wybierz <strong>2 lub 3</strong> zawodników aby zobaczyć porównanie.<br>';
    h += '<span style="font-size:13px;color:#475569">Zacznij wpisywać nazwisko w polu powyżej.</span></div>';
    return h;
  }}

  // --- Zbierz dane wybranych graczy ---
  const selected = cmpSelected.map((id, i) => {{
    const p = allPlayers.find(x => x.player_id === id);
    return p ? {{...p, _color: CMP_COLORS[i]}} : null;
  }}).filter(Boolean);

  if (selected.length < 2) return h + '<div class="cmp-empty">Nie znaleziono danych dla wybranych zawodników.</div>';

  // === SEKCJA A: Karty zawodników ===
  h += '<div class="cmp-cards">';
  selected.forEach((p, i) => {{
    const pk = POS_ID[p.position] || p.position || '';
    const played = (p.form || []).filter(f => f.p);
    const formAvg = played.length ? (played.reduce((s,f) => s + f.pts, 0) / played.length).toFixed(1) : '—';
    const predPts = p.predicted_points != null ? p.predicted_points.toFixed(1) : '—';
    // 📖 Następny rywal z FDR — szukamy w FDR_DATA
    const teamFdr = (FDR_DATA.teams || []).find(t => t.name === p.team);
    const nextFix = teamFdr ? (teamFdr.fixtures || [])[0] : null;
    const nextOpp = nextFix ? nextFix.opponent_short : (p.next_opponent || '—');
    const nextFdrAtk = nextFix ? nextFix.atk : (p.fdr_atk_opponent || 3);
    const nextFdrDef = nextFix ? nextFix.def : (p.fdr_def_opponent || 3);
    // 📖 FDR uśredniony do jednej wartości (zależy od pozycji)
    const isAttacker = (pk === 'NAP' || pk === 'POM');
    const mainFdr = isAttacker ? nextFdrDef : nextFdrAtk;
    const fdrC = FDR_COLORS[mainFdr] || FDR_COLORS[3];
    const isHome = nextFix ? nextFix.home : p.is_home;
    const haLabel = isHome ? '(D)' : '(W)';

    h += '<div class="cmp-card" style="border-top-color:'+CMP_COLORS[i]+'">';
    h += '<div class="cmp-card-name">' + p.name + '</div>';
    h += '<div class="cmp-card-meta">' + posBadge(p.position) + ' · ' + p.team + '</div>';
    h += '<div class="cmp-card-stats">';
    h += '<div class="cmp-card-stat"><span class="cmp-stat-label">Cena</span><span class="cmp-stat-val">' + (p.price || 0).toFixed(1) + 'M</span></div>';
    h += '<div class="cmp-card-stat"><span class="cmp-stat-label">Łączne pkt</span><span class="cmp-stat-val">' + (p.total_points || 0) + '</span></div>';
    h += '<div class="cmp-card-stat"><span class="cmp-stat-label">Średnia (forma)</span><span class="cmp-stat-val">' + formAvg + '</span></div>';
    h += '<div class="cmp-card-stat"><span class="cmp-stat-label">Prognoza</span><span class="cmp-stat-val" style="color:#22d3ee">' + predPts + '</span></div>';
    h += '<div class="cmp-card-stat"><span class="cmp-stat-label">Następny rywal</span><span class="cmp-stat-val">';
    h += '<span class="cmp-fdr-cell" style="background:'+fdrC.bg+';color:'+fdrC.fg+'">' + nextOpp + ' <span class="cmp-fdr-ha">' + haLabel + '</span></span>';
    h += '</span></div>';
    h += '</div></div>';
  }});
  h += '</div>';

  // === SEKCJA B: Tabela statystyk ===
  // 📖 Definicje wierszy: [label, getter, mode]
  // mode: 'higher'=wyższe lepsze, 'lower'=niższe lepsze, 'neutral'=bez podświetlenia
  const rows = [
    ['Łączne pkt', p => p.total_points || 0, 'higher'],
    ['Cena', p => p.price || 0, 'lower'],
    ['Pkt/Cena', p => p.points_per_price || 0, 'higher'],
    ['Średnia (forma)', p => {{ const played = (p.form||[]).filter(f=>f.p); return played.length ? played.reduce((s,f)=>s+f.pts,0)/played.length : 0; }}, 'higher'],
    ['Prognoza', p => p.predicted_points || 0, 'higher'],
    ['Śr. minut', p => p.avg_minutes || 0, 'higher'],
    ['Popularność', p => parseFloat((p.popularity_pct||'0').replace('%','')) || 0, 'neutral'],
    ['Pewność prognozy', p => ({{high:3,medium:2,low:1}})[p.confidence] || 0, 'higher'],
  ];

  h += '<div class="cmp-table"><table>';
  h += '<thead><tr><th style="text-align:left">Statystyka</th>';
  selected.forEach((p,i) => {{ h += '<th style="color:'+CMP_COLORS[i]+'">' + p.name.split(' ').pop() + '</th>'; }});
  h += '</tr></thead><tbody>';

  rows.forEach(([label, getter, mode]) => {{
    const vals = selected.map(p => getter(p));
    // 📖 Znajdź najlepszą wartość — zależy od mode
    let bestIdx = -1;
    if (mode !== 'neutral') {{
      let best = mode === 'lower' ? Infinity : -Infinity;
      vals.forEach((v, i) => {{
        if ((mode === 'higher' && v > best) || (mode === 'lower' && v < best)) {{ best = v; bestIdx = i; }}
      }});
      // Jeśli remis — podświetl wszystkie z najlepszą wartością
    }}
    h += '<tr><td>' + label + '</td>';
    vals.forEach((v, i) => {{
      let display = v;
      // Formatowanie
      if (label === 'Cena') display = v.toFixed(1) + 'M';
      else if (label === 'Pkt/Cena' || label === 'Średnia (forma)' || label === 'Prognoza' || label === 'Śr. minut') display = v.toFixed(1);
      else if (label === 'Popularność') display = v.toFixed(0) + '%';
      else if (label === 'Pewność prognozy') display = ['—','Low','Medium','High'][v] || '—';
      const isBest = bestIdx !== -1 && v === vals[bestIdx] && mode !== 'neutral';
      h += '<td' + (isBest ? ' class="cmp-best"' : '') + '>' + display + '</td>';
    }});
    h += '</tr>';
  }});
  h += '</tbody></table></div>';

  // === SEKCJA C: Wykres formy (SVG) ===
  // 📖 Zbieramy punkty z formy, rysujemy linie SVG bez zewnętrznych bibliotek
  h += '<div class="cmp-chart-wrap">';
  h += '<div class="cmp-chart-title">📈 Forma — ostatnie kolejki</div>';
  h += '<div class="cmp-chart-legend">';
  selected.forEach((p,i) => {{
    h += '<div class="cmp-chart-legend-item"><span class="cmp-chart-legend-swatch" style="background:'+CMP_COLORS[i]+'"></span>' + p.name.split(' ').pop() + '</div>';
  }});
  h += '</div>';

  // Zbierz wszystkie unikalne kolejki
  const allRounds = new Set();
  selected.forEach(p => (p.form || []).forEach(f => allRounds.add(f.r)));
  const rounds = [...allRounds].sort((a,b) => a - b);

  if (rounds.length >= 2) {{
    const svgW = 500, svgH = 180, padL = 40, padR = 20, padT = 20, padB = 30;
    const chartW = svgW - padL - padR, chartH = svgH - padT - padB;
    let maxPts = 0;
    selected.forEach(p => (p.form||[]).forEach(f => {{ if (f.p && f.pts > maxPts) maxPts = f.pts; }}));
    if (maxPts === 0) maxPts = 10;
    maxPts = Math.ceil(maxPts * 1.15); // 📖 Trochę marginesu na górze

    const xScale = (idx) => padL + (idx / (rounds.length - 1)) * chartW;
    const yScale = (pts) => padT + chartH - (pts / maxPts) * chartH;

    h += '<div class="cmp-chart"><svg viewBox="0 0 '+svgW+' '+svgH+'" preserveAspectRatio="xMidYMid meet">';

    // Siatka Y
    for (let g = 0; g <= 4; g++) {{
      const yVal = Math.round(maxPts / 4 * g);
      const y = yScale(yVal);
      h += '<line x1="'+padL+'" y1="'+y+'" x2="'+(svgW-padR)+'" y2="'+y+'" stroke="#334155" stroke-width="0.5"/>';
      h += '<text x="'+(padL-6)+'" y="'+(y+4)+'" fill="#64748b" font-size="10" text-anchor="end">'+yVal+'</text>';
    }}

    // Etykiety X (numery kolejek)
    rounds.forEach((r, idx) => {{
      h += '<text x="'+xScale(idx)+'" y="'+(svgH-6)+'" fill="#64748b" font-size="10" text-anchor="middle">'+r+'</text>';
    }});

    // Linie per gracz
    selected.forEach((p, pi) => {{
      const form = p.form || [];
      const points = [];
      rounds.forEach((r, idx) => {{
        const f = form.find(ff => ff.r === r);
        if (f && f.p) points.push({{x: xScale(idx), y: yScale(f.pts), pts: f.pts}});
      }});
      if (points.length < 2) return;
      // 📖 Polyline — łączna linia z punktami
      const lineStr = points.map(pt => pt.x+','+pt.y).join(' ');
      h += '<polyline points="'+lineStr+'" fill="none" stroke="'+CMP_COLORS[pi]+'" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>';
      // Kropki
      points.forEach(pt => {{
        h += '<circle cx="'+pt.x+'" cy="'+pt.y+'" r="4" fill="'+CMP_COLORS[pi]+'" stroke="#1e293b" stroke-width="2"/>';
        h += '<text x="'+pt.x+'" y="'+(pt.y-8)+'" fill="'+CMP_COLORS[pi]+'" font-size="9" font-weight="700" text-anchor="middle">'+pt.pts+'</text>';
      }});
    }});

    h += '</svg></div>';
  }} else {{
    h += '<div style="color:#64748b;text-align:center;padding:20px">Za mało danych o formie.</div>';
  }}
  h += '</div>';

  // === SEKCJA D: FDR następne kolejki ===
  const fdrTeams = FDR_DATA.teams || [];
  const fdrGws = FDR_DATA.gameweeks || [];
  if (fdrGws.length) {{
    h += '<div class="cmp-fdr-wrap">';
    h += '<div class="cmp-fdr-title">📅 Trudność najbliższych meczów (FDR)</div>';
    h += '<div class="cmp-fdr-table"><table><thead><tr><th style="text-align:left">Kolejka</th>';
    selected.forEach((p,i) => {{ h += '<th style="color:'+CMP_COLORS[i]+'">' + p.name.split(' ').pop() + ' (' + (fdrTeams.find(t=>t.name===p.team)||{{}}).short + ')</th>'; }});
    h += '</tr></thead><tbody>';

    fdrGws.forEach(gw => {{
      h += '<tr><td style="text-align:left;font-weight:700;color:#94a3b8">' + gw + '</td>';
      selected.forEach((p, pi) => {{
        const teamFdr = fdrTeams.find(t => t.name === p.team);
        const fix = teamFdr ? (teamFdr.fixtures || []).find(f => f.gw === gw) : null;
        if (fix) {{
          const pk = POS_ID[p.position] || p.position || '';
          const isAtk = (pk === 'NAP' || pk === 'POM');
          const mainFdr = isAtk ? fix.def : fix.atk;
          const c = FDR_COLORS[mainFdr] || FDR_COLORS[3];
          const ha = fix.home ? '(D)' : '(W)';
          h += '<td><span class="cmp-fdr-cell" style="background:'+c.bg+';color:'+c.fg+'">' + fix.opponent_short + ' <span class="cmp-fdr-ha">' + ha + '</span></span></td>';
        }} else {{
          h += '<td style="color:#475569">—</td>';
        }}
      }});
      h += '</tr>';
    }});
    h += '</tbody></table></div></div>';
  }}

  return h;
}}

function render() {{
  document.getElementById('tab-players').innerHTML = tab === 'players' ? renderPlayers() : '';
  document.getElementById('tab-teams').innerHTML = tab === 'teams' ? renderTeams() : '';
  const ftEl = document.getElementById('tab-fixtures');
  if (ftEl) ftEl.innerHTML = tab === 'fixtures' ? renderFixtures() : '';
  const trEl = document.getElementById('tab-transfers');
  if (trEl) trEl.innerHTML = tab === 'transfers' ? renderTransfers() : '';
  const prEl = document.getElementById('tab-predictions');
  if (prEl) prEl.innerHTML = tab === 'predictions' ? renderPredictions() : '';
  const acEl = document.getElementById('tab-accuracy');
  if (acEl) acEl.innerHTML = tab === 'accuracy' ? renderAccuracy() : '';
  const seEl = document.getElementById('tab-season');
  if (seEl) seEl.innerHTML = tab === 'season' ? renderSeason() : '';
  const nlEl = document.getElementById('tab-newsletter');
  if (nlEl) nlEl.innerHTML = tab === 'newsletter' ? renderNewsletter() : '';
  const cmpEl = document.getElementById('tab-compare');
  if (cmpEl) cmpEl.innerHTML = tab === 'compare' ? renderComparison() : '';
  document.querySelectorAll('.tab-content').forEach(el => el.classList.toggle('active', el.id === 'tab-'+tab));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.pos-btn').forEach(b => b.classList.toggle('active', b.dataset.pos === pos));
  document.querySelectorAll('.scope-btn:not(.fdr-sort-btn)').forEach(b => b.classList.toggle('active', b.dataset.scope === scope));
  const fr = document.querySelector('.filters-row');
  if (fr) fr.style.display = (tab === 'players') ? 'flex' : 'none';
  // Transfers position filter handlers
  document.querySelectorAll('.tr-pos-btn').forEach(b => {{
    b.classList.toggle('active', b.dataset.trpos === trPos);
    b.onclick = () => {{ trPos = b.dataset.trpos; render(); }};
  }});
  // Predictions position filter handlers
  document.querySelectorAll('.pred-pos-btn').forEach(b => {{
    b.classList.toggle('active', b.dataset.predpos === predPos);
    b.onclick = () => {{ predPos = b.dataset.predpos; render(); }};
  }});
  // Sortable click handlers
  document.querySelectorAll('.sortable').forEach(th => {{
    th.onclick = () => {{
      const t = th.dataset.tab, col = th.dataset.col;
      if (sorts[t].col === col) sorts[t].dir = sorts[t].dir === 'desc' ? 'asc' : 'desc';
      else {{ sorts[t].col = col; sorts[t].dir = 'desc'; }}
      render();
    }};
  }});
  // Attach detail click handlers (form + roster)
  attachDetailClicks();
  // Season tab handlers (tooltip, legend, view toggle)
  if (tab === 'season') attachSeasonHandlers();
  // Team row click handlers (expand/collapse squad)
  document.querySelectorAll('tr[data-teamslug]').forEach(el => {{
    el.onclick = (e) => {{
      if (e.target.closest('a')) return;
      const slug = el.dataset.teamslug;
      selectedTeam = selectedTeam === slug ? '' : slug;
      render();
    }};
  }});
  // Duet row click handlers (expand/collapse)
  document.querySelectorAll('tr[data-duetname]').forEach(el => {{
    el.onclick = () => {{
      const name = decodeURIComponent(el.dataset.duetname);
      selectedDuet = selectedDuet === name ? '' : name;
      render();
    }};
  }});
  // View toggle (Drużyny / Duety)
  document.querySelectorAll('.view-btn').forEach(btn => {{
    btn.onclick = () => {{
      currentTeamsView = btn.dataset.view;
      render();
    }};
  }});
  // FDR sort handlers
  document.querySelectorAll('.fdr-sort-btn').forEach(b => {{
    b.classList.toggle('active', b.dataset.fdrsort === fdrSort);
    b.onclick = () => {{ fdrSort = b.dataset.fdrsort; render(); }};
  }});
  // FDR team click → show stats modal
  document.querySelectorAll('.fdr-team-click').forEach(td => {{
    td.onclick = () => {{
      const teams = window._fdrTeams || [];
      const t = teams[parseInt(td.dataset.fdrteam)];
      if (t) fdrShowModal(t.name);
    }};
  }});
  // Fixture Planner handlers
  const fpFrom = document.querySelector('.fp-gw-from');
  const fpTo = document.querySelector('.fp-gw-to');
  if (fpFrom) fpFrom.onchange = () => {{ fpGwFrom = parseInt(fpFrom.value); render(); }};
  if (fpTo) fpTo.onchange = () => {{ fpGwTo = parseInt(fpTo.value); render(); }};
  document.querySelectorAll('.fp-mode-btn').forEach(b => {{
    b.onclick = () => {{ fpMode = b.dataset.fpmode; render(); }};
  }});
  document.querySelectorAll('.fp-sort').forEach(th => {{
    th.onclick = () => {{
      const col = th.dataset.fpcol;
      if (fpSortCol === col) fpSortDir = fpSortDir === 'asc' ? 'desc' : 'asc';
      else {{ fpSortCol = col; fpSortDir = col === 'team' ? 'asc' : 'asc'; }}
      render();
    }};
  }});
  // 📖 Klik na drużynę w planerze — zaznacza do rotation pair (max 2)
  document.querySelectorAll('.fp-team-cell').forEach(td => {{
    td.onclick = () => {{
      const name = td.dataset.fpteam;
      const idx = fpSelected.indexOf(name);
      if (idx >= 0) {{ fpSelected.splice(idx, 1); }}
      else if (fpSelected.length < 2) {{ fpSelected.push(name); }}
      else {{ fpSelected = [name]; }}
      render();
    }};
  }});
  // 📖 Autouzupełnianie w porównywarce — nasłuchuje na wpisywanie tekstu
  // i wyświetla listę pasujących zawodników
  const cmpInput = document.getElementById('cmpSearchInput');
  const cmpAc = document.getElementById('cmpAutocomplete');
  if (cmpInput && cmpAc) {{
    cmpInput.value = '';
    cmpInput.oninput = () => {{
      const q = cmpInput.value.trim().toLowerCase();
      if (q.length < 2) {{ cmpAc.classList.remove('visible'); cmpAc.innerHTML = ''; return; }}
      // 📖 Szukamy w PLAYERS — filtrujemy po nazwisku, drużynie
      const matches = PLAYERS.filter(p =>
        !cmpSelected.includes(p.player_id) &&
        (p.name.toLowerCase().includes(q) || p.team.toLowerCase().includes(q))
      ).slice(0, 8);
      if (!matches.length) {{ cmpAc.classList.remove('visible'); cmpAc.innerHTML = ''; return; }}
      let acH = '';
      matches.forEach(p => {{
        acH += '<div class="cmp-ac-item" data-cmpid="'+p.player_id+'">';
        acH += posBadge(p.position) + ' <strong>' + p.name + '</strong>';
        acH += '<span class="cmp-ac-team">' + p.team + ' · ' + (p.price||0).toFixed(1) + 'M · ' + (p.total_points||0) + 'pkt</span>';
        acH += '</div>';
      }});
      cmpAc.innerHTML = acH;
      cmpAc.classList.add('visible');
      // Klik na element listy
      cmpAc.querySelectorAll('.cmp-ac-item').forEach(el => {{
        el.onclick = () => {{
          cmpAddPlayer(parseInt(el.dataset.cmpid));
          cmpAc.classList.remove('visible');
          cmpAc.innerHTML = '';
        }};
      }});
    }};
    // Zamknij autocomplete po kliknięciu poza
    document.addEventListener('click', (e) => {{
      if (!e.target.closest('.cmp-search-box')) {{
        cmpAc.classList.remove('visible');
      }}
    }});
  }}
}}

function renderNewsletter() {{
  // 📖 LEKCJA: NEWSLETTER_DATA to lista newsletterów wygenerowanych przez Gemini AI.
  // Wyświetlamy je od najnowszego — odwracamy listę przez slice().reverse().
  const items = (NEWSLETTER_DATA || []).slice().reverse();
  if (!items.length) {{
    return '<div class="empty-msg">Brak newsletterów — zostaną wygenerowane automatycznie po kolejce gdy GEMINI_API_KEY jest skonfigurowany</div>';
  }}
  let h = '<div class="nl-list">';
  for (const item of items) {{
    const round = item.round || '?';
    const dt = item.date || '';
    const text = (item.text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const model = item.model || 'AI';
    h += `<div class="nl-card">`;
    h += `<div class="nl-card-header">`;
    h += `<span class="nl-round">Kolejka ${{round}}</span>`;
    if (dt) h += `<span class="nl-date">${{dt}}</span>`;
    h += `<span class="nl-model">${{model}}</span>`;
    h += `</div>`;
    h += `<div class="nl-text">${{text}}</div>`;
    h += `</div>`;
  }}
  h += '</div>';
  return h;
}}

document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => {{ tab = t.dataset.tab; render(); }}));
document.querySelectorAll('.pos-btn').forEach(b => b.addEventListener('click', () => {{ pos = b.dataset.pos; render(); }}));
document.querySelectorAll('.scope-btn').forEach(b => b.addEventListener('click', () => {{ scope = b.dataset.scope; render(); }}));
render();
</script>
</body>
</html>'''

    # Theme toggle JS - z <script> bo wstawiamy w miejsce placeholderu
    theme_js = """<script>
    // Toggle z localStorage
    function toggleTheme() {
      const html = document.documentElement;
      const btn = document.querySelector('.theme-toggle');
      const isLight = html.classList.contains('theme-fantasy');
      if (isLight) {
        html.classList.remove('theme-fantasy');
        btn.textContent = '☀️ Light';
        localStorage.setItem('theme', 'dark');
      } else {
        html.classList.add('theme-fantasy');
        btn.textContent = '🌙 Dark';
        localStorage.setItem('theme', 'light');
      }
    }
    // Przywróć motyw po załadowaniu
    (function() {
      const theme = localStorage.getItem('theme');
      const html = document.documentElement;
      const btn = document.querySelector('.theme-toggle');
      if (theme === 'light') {
        html.classList.add('theme-fantasy');
        btn.textContent = '🌙 Dark';
      } else {
        btn.textContent = '☀️ Light';
      }
    })();
    </script>"""

    # Wstaw theme JS w placeholder (replace all occurrences)
    html = html.replace('// __JS_PLACEHOLDER__', theme_js, 1)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📊 Dashboard: {filename}")


# ============================================================
# GENEROWANIE INDEX ARCHIWUM
# ============================================================

def generate_archive_index(archive_dir: str = "docs/archive"):
    """
    Generuje stronę index.html z listą wszystkich archiwów sezonów.
    Skanuje katalog docs/archive/ w poszukiwaniu plików sezon-*.html.
    """
    import glob as glob_module
    import re

    # Sprawdź czy katalog istnieje
    if not os.path.exists(archive_dir):
        print(f"  ℹ️  Katalog archiwum nie istnieje: {archive_dir}")
        return False

    # Znajdź wszystkie pliki sezon-*.html
    pattern = os.path.join(archive_dir, "sezon-*.html")
    archive_files = glob_module.glob(pattern)

    if not archive_files:
        print(f"  ℹ️  Brak archiwów w katalogu: {archive_dir}")
        return False

    # Parsuj nazwy sezonów z plików
    archives = []
    for filepath in archive_files:
        filename = os.path.basename(filepath)
        # Wyciągnij nazwę sezonu: "sezon-2026 Wiosna.html" -> "2026 Wiosna"
        match = re.match(r"sezon-(.+)\.html$", filename)
        if match:
            season_name = match.group(1).strip()
            archives.append({
                "name": season_name,
                "filename": filename,
            })

    # Sortuj po nazwie (od najnowszego)
    archives.sort(key=lambda x: x["name"], reverse=True)

    if not archives:
        print(f"  ℹ️  Nie znaleziono archiwów sezonów")
        return False

    # CSS dla strony index archiwum (ten sam co dashboard)
    index_css = """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { background: #131313; }
    body {
      min-height: 100vh;
      background: #131313;
      color: #ffffff;
      font-family: 'DM Sans', -apple-system, sans-serif;
      padding: 24px 16px;
    }
    .container { max-width: 800px; margin: 0 auto; padding: 0 16px; }
    .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
    .header h1 { font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }
    .header .sub { font-size: 12px; color: #949494; margin: 0; }
    .back-link {
      color: #3cffd0;
      text-decoration: none;
      font-size: 14px;
      font-weight: 600;
      margin-bottom: 20px;
      display: inline-block;
    }
    .back-link:hover { color: #3860be; }
    .archive-list { display: flex; flex-direction: column; gap: 12px; }
    .archive-item {
      background: #2d2d2d;
      border: 1px solid #3cffd0;
      border-radius: 12px;
      padding: 16px 20px;
      transition: all 0.2s;
    }
    .archive-item:hover {
      background: #3cffd0;
    }
    .archive-item:hover .archive-name {
      color: #131313;
    }
    .archive-item:hover .archive-arrow {
      color: #131313;
    }
    .archive-item a {
      text-decoration: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .archive-name {
      font-size: 16px;
      font-weight: 700;
      color: #ffffff;
    }
    .archive-arrow {
      font-size: 18px;
      color: #3cffd0;
    }
    .empty-msg { padding: 40px; text-align: center; color: #949494; }
    .footer { text-align: center; margin-top: 32px; color: #949494; font-size: 12px; }

    /* Light theme */
    html.theme-fantasy { background: #f5f5f5; }
    html.theme-fantasy body { background: #f5f5f5; color: #131313; }
    html.theme-fantasy .header h1 { color: #131313; }
    html.theme-fantasy .header .sub { color: #5a5a5a; }
    html.theme-fantasy .back-link { color: #309875; }
    html.theme-fantasy .back-link:hover { color: #3860be; }
    html.theme-fantasy .archive-item { background: #ffffff; border-color: #e0e0e0; }
    html.theme-fantasy .archive-item:hover { background: #309875; }
    html.theme-fantasy .archive-item:hover .archive-name { color: #ffffff; }
    html.theme-fantasy .archive-item:hover .archive-arrow { color: #ffffff; }
    html.theme-fantasy .archive-name { color: #131313; }
    html.theme-fantasy .archive-arrow { color: #309875; }
    html.theme-fantasy .footer { color: #5a5a5a; }
    """

    # Theme toggle JS
    theme_js = """
    function toggleTheme() {
      const html = document.documentElement;
      const btn = document.querySelector('.theme-toggle');
      if (html.classList.contains('theme-fantasy')) {
        html.classList.remove('theme-fantasy');
        btn.textContent = '☀️ Light';
        localStorage.setItem('theme', 'dark');
      } else {
        html.classList.add('theme-fantasy');
        btn.textContent = '🌙 Dark';
        localStorage.setItem('theme', 'light');
      }
    }
    (function() {
      const theme = localStorage.getItem('theme');
      const html = document.documentElement;
      const btn = document.querySelector('.theme-toggle');
      if (theme === 'light') {
        html.classList.add('theme-fantasy');
        btn.textContent = '🌙 Dark';
      } else {
        btn.textContent = '☀️ Light';
      }
    })();
    """

    # Generuj HTML
    archives_html = ""
    for arch in archives:
        archives_html += f'''
        <div class="archive-item">
          <a href="{arch['filename']}">
            <span class="archive-name">📁 Sezon {arch['name']}</span>
            <span class="archive-arrow">→</span>
          </a>
        </div>'''

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ScrapFEks – Archiwum</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{index_css}</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <h1>📁 Archiwum Sezonów</h1>
      <p class="sub">ScrapFEks · {timestamp}</p>
    </div>
    <button class="theme-toggle" onclick="toggleTheme()">☀️ Light</button>
  </div>
  <a href="../index.html" class="back-link">← Powrót do bieżącego sezonu</a>

  <div class="archive-list">
    {archives_html}
  </div>

  <div class="footer">ScrapFEks Archiwum · {timestamp}</div>
</div>
<script>{theme_js}</script>
</body>
</html>"""

    # Zapisz plik
    index_path = os.path.join(archive_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  📁 Index archiwum wygenerowany: {index_path} ({len(archives)} sezonów)")
    return True


# ============================================================
# GENEROWANIE ARCHIWUM SEZONU
# ============================================================

def generate_archive_html(
    season_name: str,
    players: list[dict],
    league_teams_detail: list[dict],
    league_history: dict,
    timestamp: str,
    filename: str,
):
    """
    Generuje uproszczony HTML archiwum sezonu.
    Zawiera tylko zakładki: Zawodnicy, Liga CMF, Sezon.
    """
    import shutil
    import os

    # Przygotuj dane dla JS
    players_json = json.dumps(players[:200], ensure_ascii=False)  # Limit do 200 zawodników
    league_teams_json = json.dumps(league_teams_detail, ensure_ascii=False)
    league_history_json = json.dumps(league_history or {"rounds": []}, ensure_ascii=False)

    # CSS dla archiwum (uproszczony)
    archive_css = """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { background: #131313; }
    body {
      min-height: 100vh;
      background: #131313;
      color: #ffffff;
      font-family: 'DM Sans', -apple-system, sans-serif;
      padding: 24px 16px;
    }
    .container { max-width: 1400px; margin: 0 auto; padding: 0 16px; }
    .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
    .header-left { display: flex; align-items: center; gap: 14px; }
    .header h1 { font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }
    .header .sub { font-size: 12px; color: #949494; margin: 0; }
    .archive-badge {
      background: #5200ff;
      color: #fff;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 700;
    }
    .back-link {
      color: #3cffd0;
      text-decoration: none;
      font-size: 14px;
      font-weight: 600;
    }
    .back-link:hover { color: #3860be; }
    .tabs { display: flex; gap: 4px; border-bottom: 1px solid #2d2d2d; flex-wrap: wrap; margin-bottom: 16px; }
    .tab {
      background: transparent; border: none; border-bottom: 2px solid transparent;
      color: #949494; padding: 10px 18px; font-size: 13px; font-weight: 600;
      cursor: pointer; border-radius: 8px 8px 0 0; transition: all 0.2s;
      font-family: inherit;
    }
    .tab.active { background: #2d2d2d; border-bottom-color: #3cffd0; color: #ffffff; }
    .tab:hover { color: #3860be; }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    .data-table { background: #2d2d2d; border-radius: 12px; overflow: hidden; width: 100%; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    thead tr { background: #131313; }
    th { padding: 10px 14px; color: #949494; font-weight: 600; font-size: 11px; text-transform: uppercase; white-space: nowrap; }
    td { padding: 10px 14px; border-top: 1px solid #131313; white-space: nowrap; }
    .pos-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; color: #131313; }
    .pos-BR, .pos-1 { background: #f59e0b; }
    .pos-OBR, .pos-2 { background: #3b82f6; }
    .pos-POM, .pos-3 { background: #10b981; }
    .pos-NAP, .pos-4 { background: #ef4444; }
    .text-right { text-align: right; }
    .text-center { text-align: center; }
    .text-left { text-align: left; }
    .fw-700 { font-weight: 700; }
    .c-muted { color: #949494; }
    .empty-msg { padding: 40px; text-align: center; color: #949494; }
    .team-list { display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }
    .team-list-item { background: #2d2d2d; border: 1px solid #3cffd0; border-radius: 8px; }
    .team-list-header { display: flex; align-items: center; gap: 12px; padding: 10px 16px; cursor: pointer; }
    .team-list-rank { font-size: 13px; font-weight: 800; color: #3cffd0; min-width: 32px; }
    .team-list-name { font-size: 14px; font-weight: 700; color: #ffffff; flex: 1; text-transform: capitalize; }
    .team-list-pts { font-size: 12px; color: #949494; font-weight: 600; }
    .footer { text-align: center; margin-top: 32px; color: #949494; font-size: 12px; }
    .season-wrap { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
    .season-chart svg { display: block; }
    """

    # JS dla archiwum (uproszczony)
    archive_js = f"""
    const PLAYERS = {players_json};
    const LEAGUE_TEAMS = {league_teams_json};
    const LEAGUE_HISTORY = {league_history_json};
    const POS_MAP = {{BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD','1':'GK','2':'DEF','3':'MID','4':'FWD'}};
    const POS_ID = {{'1':'BR','2':'OBR','3':'POM','4':'NAP',BR:'BR',OBR:'OBR',POM:'POM',NAP:'NAP'}};

    let currentTab = 'players';

    function showTab(tabId) {{
      currentTab = tabId;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      document.querySelector('[data-tab="' + tabId + '"]').classList.add('active');
      document.getElementById('tab-' + tabId).classList.add('active');
    }}

    function posBadge(p) {{
      const k = POS_ID[p] || p;
      return '<span class="pos-badge pos-'+k+'">'+(POS_MAP[k]||k)+'</span>';
    }}

    function renderPlayers() {{
      let data = [...PLAYERS].sort((a,b) => (b.total_points||0) - (a.total_points||0));
      let h = '<div class="data-table"><table><thead><tr>';
      h += '<th class="text-left">#</th>';
      h += '<th class="text-left">Zawodnik</th>';
      h += '<th class="text-left">Drużyna</th>';
      h += '<th class="text-center">Poz</th>';
      h += '<th class="text-right">Cena</th>';
      h += '<th class="text-right">Punkty</th>';
      h += '</tr></thead><tbody>';

      data.forEach((p, i) => {{
        const pk = POS_ID[p.position] || p.position || '';
        const price = p.price || 0;
        const pts = p.total_points || 0;
        h += '<tr>';
        h += '<td class="c-muted fw-700">'+(i+1)+'</td>';
        h += '<td class="fw-700">'+(p.name||'')+'</td>';
        h += '<td class="c-muted" style="font-size:13px">'+(p.team||'')+'</td>';
        h += '<td class="text-center">'+posBadge(pk)+'</td>';
        h += '<td class="text-right c-muted">'+price.toFixed(1)+'M</td>';
        h += '<td class="text-right fw-700">'+pts+'</td>';
        h += '</tr>';
      }});

      h += '</tbody></table></div>';
      document.getElementById('players-content').innerHTML = h;
    }}

    function renderTeams() {{
      let data = [...LEAGUE_TEAMS].sort((a,b) => (b.total_points||0) - (a.total_points||0));
      let h = '<div class="team-list">';

      data.forEach((t, i) => {{
        h += '<div class="team-list-item">';
        h += '<div class="team-list-header">';
        h += '<span class="team-list-rank">'+(i+1)+'</span>';
        h += '<span class="team-list-name">'+(t.display_name||t.team_slug||'')+'</span>';
        h += '<span class="team-list-pts">'+(t.total_points||0)+' pkt</span>';
        h += '</div></div>';
      }});

      h += '</div>';
      document.getElementById('teams-content').innerHTML = h;
    }}

    function renderSeason() {{
      const rounds = (LEAGUE_HISTORY.rounds || []);
      if (rounds.length < 1) {{
        document.getElementById('season-content').innerHTML = '<div class="empty-msg">Brak danych sezonu</div>';
        return;
      }}

      // Prosta tabela wyników
      const lastRound = rounds[rounds.length - 1];
      const standings = lastRound.standings || [];
      standings.sort((a,b) => a.position - b.position);

      let h = '<div class="data-table"><table><thead><tr>';
      h += '<th class="text-left">Pozycja</th>';
      h += '<th class="text-left">Drużyna</th>';
      h += '<th class="text-right">Punkty</th>';
      h += '<th class="text-right">Pkt/kol</th>';
      h += '</tr></thead><tbody>';

      standings.forEach(s => {{
        const avg = rounds.length > 0 ? (s.total_points / rounds.length).toFixed(1) : 0;
        h += '<tr>';
        h += '<td class="fw-700">'+(s.position||'')+'</td>';
        h += '<td>'+(s.team||'')+'</td>';
        h += '<td class="text-right">'+(s.total_points||0)+'</td>';
        h += '<td class="text-right c-muted">'+avg+'</td>';
        h += '</tr>';
      }});

      h += '</tbody></table></div>';
      document.getElementById('season-content').innerHTML = h;
    }}

    document.addEventListener('DOMContentLoaded', function() {{
      renderPlayers();
      renderTeams();
      renderSeason();

      document.querySelectorAll('.tab').forEach(tab => {{
        tab.addEventListener('click', function() {{
          showTab(this.dataset.tab);
        }});
      }});
    }});
    """

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ScrapFEks – Archiwum Sezonu {season_name}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{archive_css}</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="header-left">
      <div>
        <h1>📊 ScrapFEks – Sezon {season_name}</h1>
        <p class="sub">Archiwum · {timestamp}</p>
      </div>
    </div>
    <span class="archive-badge">📦 Archiwum</span>
  </div>
  <a href="../index.html" class="back-link">← Powrót do bieżącego sezonu</a>

  <div class="tabs" style="margin-top: 20px;">
    <button class="tab active" data-tab="players">⚽ Zawodnicy</button>
    <button class="tab" data-tab="teams">📋 Liga CMF</button>
    <button class="tab" data-tab="season">📈 Sezon</button>
  </div>

  <div id="tab-players" class="tab-content active">
    <div id="players-content"><div class="empty-msg">Ładowanie...</div></div>
  </div>
  <div id="tab-teams" class="tab-content">
    <div id="teams-content"><div class="empty-msg">Ładowanie...</div></div>
  </div>
  <div id="tab-season" class="tab-content">
    <div id="season-content"><div class="empty-msg">Ładowanie...</div></div>
  </div>

  <div class="footer">ScrapFEks Archiwum · Sezon {season_name} · {timestamp}</div>
</div>
<script>{archive_js}</script>
</body>
</html>"""

    # Utwórz katalog docs/archive jeśli nie istnieje
    archive_dir = os.path.dirname(filename)
    os.makedirs(archive_dir, exist_ok=True)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📦 Archiwum wygenerowane: {filename}")


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

        # Buduj fixtures w formacie predictora: {team: {opponent, is_home}}
        pred_fixtures = {}
        for m in next_matches:
            pred_fixtures[m["home"]] = {"opponent": m["away"], "is_home": True}
            pred_fixtures[m["away"]] = {"opponent": m["home"], "is_home": False}

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
            players_for_pred.append(pp)

        # DEBUG: sprawdź dane przed predykcją
        if players_for_pred:
            sample = players_for_pred[0]
            print(f"   DEBUG: pierwszy gracz do pred={sample.get('name')}, xg_per90={sample.get('xg_per90')}")
        
        predictions_data = predict_all_players(players_for_pred, pred_fdr, pred_fixtures)
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

        # Zapisz CSV z prognozami
        if predictions_data:
            pred_csv = os.path.join(OUTPUT_DIR, f"fantasy_predictions_{timestamp}.csv")
            pred_fields = [
                "player_id", "name", "team", "position", "next_opponent", "is_home",
                "predicted_points", "base_avg", "fdr_modifier",
                "minutes_factor", "home_away_factor", "avg_minutes",
                "confidence", "detail",
                "unavailable", "availability_reason",  # status dostępności
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
                except Exception:
                    pass

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
                except Exception:
                    pass

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

    # Wczytaj historię newsletterów (newsletter_history.json) dla zakładki Newsletter
    from newsletter import load_newsletter_history
    newsletter_history = load_newsletter_history()

    # Generuj index archiwum (jeśli katalog istnieje)
    has_archive = generate_archive_index("docs/archive")

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
        duets_data=duets_data,
        fixtures_data=fixtures_data,
        ekstra_stats=ekstra_stats,
        fdr_data=fdr_data,
        transfers_data=transfers_data,
        predictions_data=predictions_data,
        accuracy_history=accuracy_history,
        tuned_params=tuned_params,
        league_history=league_history,
        newsletter_data=newsletter_history,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        filename=dashboard_file,
        has_archive=has_archive,
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
            gemini_key = os.environ.get("GEMINI_API_KEY")
            if gemini_key and is_day_before:
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
                    api_key=gemini_key,
                    round_number=discord_next_gw,
                )
            else:
                # Rozróżnij przyczynę pominięcia: brak klucza vs nie ten dzień
                if not gemini_key:
                    print("  ℹ️  Eksperci: brak GEMINI_API_KEY — pomijam generowanie")
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

            # Newsletter AI (Gemini) — generuj jeśli klucz API jest dostępny.
            # Błąd newslettera NIE przerywa wysyłki post-rounda.
            from newsletter import generate_newsletter
            gemini_key = os.environ.get("GEMINI_API_KEY")
            newsletter_text = None
            if gemini_key:
                newsletter_round_data = {
                    "round_number": current_round,
                    "league_data": discord_league,
                    "players_data": players,
                    "accuracy_data": accuracy_data,
                    "league_teams_detail": league_teams_detail,
                    "predictions_data": predictions_data,
                }
                newsletter_text = generate_newsletter(newsletter_round_data, gemini_key)
            else:
                print("  ℹ️  Newsletter: brak GEMINI_API_KEY — pomijam generowanie")

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

    # ============================================================
    # ARCHIWIZACJA SEZONU
    # ============================================================
    if ARCHIVE_SEASON:
        if not SEASON_NAME:
            print("\n❌ Błąd archiwizacji: SEASON_NAME jest wymagany (np. 2025-26)")
        else:
            print(f"\n📦 Archiwizacja sezonu {SEASON_NAME}...")

            # Ścieżka do archiwum
            archive_html_path = f"docs/archive/sezon-{SEASON_NAME}.html"

            # Generuj archiwum HTML
            generate_archive_html(
                season_name=SEASON_NAME,
                players=players,
                league_teams_detail=league_teams_detail,
                league_history=league_history,
                timestamp=timestamp,
                filename=archive_html_path,
            )

            # Przenieś dane do archiwum
            import shutil

            # Kopia autumn_points.json do docs/archive/
            archive_data_dir = "docs/archive"
            os.makedirs(archive_data_dir, exist_ok=True)

            if os.path.exists("autumn_points.json"):
                shutil.copy("autumn_points.json", f"{archive_data_dir}/autumn_points_{SEASON_NAME}.json")
                print(f"   📄 Skopiowano autumn_points.json → {archive_data_dir}/autumn_points_{SEASON_NAME}.json")

            # Opcjonalnie: skopiuj inne pliki danych
            if os.path.exists(json_file):
                shutil.copy(json_file, f"{archive_data_dir}/players_{SEASON_NAME}.json")
                print(f"   📄 Skopiowano {os.path.basename(json_file)} → {archive_data_dir}/")

            print(f"   ✅ Archiwizacja zakończona: docs/archive/sezon-{SEASON_NAME}.html")

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
