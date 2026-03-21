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

    # Scrapuj składy i zbieraj unikalne player_id
    seen: set[str] = set()
    players: list[dict] = []

    for i, slug in enumerate(slugs):
        try:
            squad_data = scrape_team_squad(session, slug)
            for p in squad_data.get("players", []):
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
            if (i + 1) % 50 == 0:
                print(f"   Postęp: {i + 1}/{len(slugs)} drużyn, "
                      f"{len(players)} unikalnych zawodników...")
            time.sleep(REQUEST_DELAY)
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
                continue
            date_match = re.search(r"(\d{1,2})\s+(\w+),\s*(\d{1,2}):(\d{2})\s*$", line)
            if date_match and current_round:
                day = int(date_match.group(1))
                month_name = date_match.group(2)
                month = MONTHS_PL.get(month_name)
                if not month:
                    continue
                # Wyciągnij drużyny
                teams_part = line[:date_match.start()].strip()
                parts = re.split(r'\t+-\t+', teams_part)
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

    teams = sorted(teams_set)
    # Buduj skróty — użyj zdefiniowanych lub generuj z pierwszych 3 liter
    abbrevs = {}
    for t in teams:
        abbrevs[t] = TEAM_ABBREVS.get(t, t[:3].upper())

    rounds = sorted(matches_by_round.keys())
    # Konwertuj klucze na string dla JSON
    matches_json = {str(r): matches_by_round[r] for r in rounds}

    return {
        "rounds": rounds,
        "matches": matches_json,
        "teams": teams,
        "abbrevs": abbrevs,
    }


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
    fixtures_data: dict,
    ekstra_stats: dict,
    fdr_data: dict,
    transfers_data: dict,
    predictions_data: list[dict],
    accuracy_history: list[dict],
    tuned_params: dict,
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
    fixtures_json = json.dumps(fixtures_data, ensure_ascii=False)
    ekstra_stats_json = json.dumps(ekstra_stats, ensure_ascii=False)
    fdr_data_json = json.dumps(fdr_data, ensure_ascii=False)
    transfers_data_json = json.dumps(transfers_data or {}, ensure_ascii=False)
    predictions_json = json.dumps(predictions_data or [], ensure_ascii=False)
    accuracy_json = json.dumps(accuracy_history or [], ensure_ascii=False)
    tuned_params_json = json.dumps(tuned_params or None, ensure_ascii=False)
    has_fixtures = len(fixtures_data.get("rounds", [])) > 0
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
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  min-height: 100vh;
  background: linear-gradient(180deg, #0b1120 0%, #0f172a 100%);
  color: #e2e8f0;
  font-family: 'DM Sans', -apple-system, sans-serif;
  padding: 24px 16px;
}}
.container {{ max-width: 95vw; margin: 0 auto; }}
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
th.sortable[title] {{ cursor: help; border-bottom: 1px dashed #475569; }}
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
.form-panel {{
  background: #0f172a; border: 1px solid #1e293b; border-radius: 8px;
  padding: 12px 16px; display: flex; align-items: flex-end; gap: 16px; flex-wrap: wrap;
}}
.form-chart {{
  display: inline-flex; align-items: flex-end; gap: 3px; height: 48px; vertical-align: middle;
}}
.form-chart.mini {{
  height: 24px; gap: 2px;
}}
.form-chart.mini .form-bar {{ width: 8px; }}
.form-chart.mini .form-val {{ font-size: 8px; top: -12px; color: #94a3b8; font-weight: 500; }}
.form-chart.mini .form-rnd {{ display: none; }}
.form-bar {{
  width: 14px; border-radius: 3px 3px 0 0; min-height: 2px; position: relative;
  display: inline-flex; flex-direction: column; align-items: center; justify-content: flex-start;
}}
.form-bar .form-val {{
  position: absolute; top: -16px; font-size: 10px; color: #e2e8f0; font-weight: 600; white-space: nowrap;
}}
.form-bar .form-rnd {{
  position: absolute; bottom: -16px; font-size: 9px; color: #64748b; white-space: nowrap;
}}
.form-bar.not-played {{ opacity: 0.35; border: 1px dashed #475569; background: transparent !important; }}
.form-avg {{
  display: flex; flex-direction: column; align-items: center; margin-left: 8px;
}}
.form-avg .fa-val {{ font-size: 20px; font-weight: 800; color: #22d3ee; }}
.form-avg .fa-lbl {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }}
.detail-row td {{ padding: 0 !important; border-top: none !important; }}
.detail-panel {{
  background: #0f172a; border: 1px solid #1e293b; border-radius: 8px;
  padding: 12px 16px; margin: 4px 0 8px; display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-start;
}}
.detail-section {{ display: flex; flex-direction: column; gap: 4px; }}
.detail-section .ds-label {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }}
.team-list {{ display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }}
.team-list-item {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; }}
.team-list-item.active {{ border-color: #22d3ee; }}
.team-list-header {{ display: flex; align-items: center; gap: 12px; padding: 10px 16px; cursor: pointer; transition: background 0.15s; }}
.team-list-header:hover {{ background: #334155; }}
.team-list-rank {{ font-size: 13px; font-weight: 800; color: #22d3ee; min-width: 32px; }}
.team-list-name {{ font-size: 14px; font-weight: 700; color: #e2e8f0; flex: 1; text-transform: capitalize; }}
.team-list-pts {{ font-size: 12px; color: #94a3b8; font-weight: 600; }}
.team-list-count {{ font-size: 11px; color: #64748b; }}
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
.pred-legend {{
  background: #1e293b; border-radius: 8px; padding: 12px 16px;
  margin-bottom: 16px; font-size: 12px; color: #94a3b8; line-height: 1.8;
}}
.pred-legend b {{ color: #e2e8f0; }}
.pred-filters {{ display: flex; gap: 8px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
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
  </div>
  <div class="footer">Fantasy Ekstraklasa Dashboard · {timestamp}</div>
</div>

<script>
const DATA = {data_json};
const PLAYERS = {players_json};
const ROSTERS = {rosters_json};
const LEAGUE_TEAMS = {teams_detail_json};
const FIXTURES = {fixtures_json};
const EKSTRA_STATS = {ekstra_stats_json};
const FDR_DATA = {fdr_data_json};
const TRANSFERS_DATA = {transfers_data_json};
const PREDICTIONS = {predictions_json};
const ACCURACY_HISTORY = {accuracy_json};
const TUNED_PARAMS = {tuned_params_json};

const POS_MAP = {{BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD','1':'GK','2':'DEF','3':'MID','4':'FWD'}};
const POS_ID = {{'1':'BR','2':'OBR','3':'POM','4':'NAP',BR:'BR',OBR:'OBR',POM:'POM',NAP:'NAP',
  Bramkarz:'BR','Obrońca':'OBR',Pomocnik:'POM',Napastnik:'NAP'}};

let tab = 'players', pos = 'ALL', scope = '{default_scope}';
let selectedTeam = '';
let sorts = {{
  players: {{col:'total_points', dir:'desc'}},
  teams: {{col:'_pos_order', dir:'asc'}},
  teams_list: {{col:'total_pts', dir:'desc'}},
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
  h += '<th class="text-right sortable" data-tab="players" data-col="_form_avg" title="Średnia punktów z rozegranych meczów (ostatnie 5 kolejek przed obecną)">Średnia'+arrow('players','_form_avg')+'</th>';
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

function renderTeams() {{
  if (!LEAGUE_TEAMS.length) return '<div class="empty-msg">Brak danych o drużynach ligi</div>';

  let h = '<div class="section-title"><span style="font-size:22px">📋</span><h2>Liga CMF</h2><div class="line"></div></div>';

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

    h += '<tr>';
    h += '<td class="c-muted fw-600">'+(i+1)+'</td>';
    h += '<td class="fw-600" title="'+detail.replace(/"/g,'&quot;')+'">'+p.name+'</td>';
    h += '<td class="text-center">'+posBadge(pk)+'</td>';
    h += '<td class="c-muted" style="font-size:13px">'+p.team+'</td>';

    // Rywal z FDR kolorem (używamy wyższego FDR)
    const oppName = p.opponent_short || p.next_opponent || '';
    const oppFdr = Math.max(oppFdrAtk, oppFdrDef);
    const oppC = FDR_COLORS[oppFdr] || FDR_COLORS[3];
    h += '<td class="text-center"><span class="pred-fdr-tile" style="background:'+oppC.bg+';color:'+oppC.fg+';font-size:11px;padding:3px 8px">'+oppName+'</span></td>';

    // Dom/Wyjazd
    h += '<td class="text-center">'+(p.is_home ? '🏠' : '✈️')+'</td>';

    // Prognoza — pogrubiona, gradient
    h += '<td class="text-right"><span class="pred-val" style="'+predGradient(pred)+'">'+pred.toFixed(1)+'</span></td>';

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
  // Team row click handlers (expand/collapse squad)
  document.querySelectorAll('tr[data-teamslug]').forEach(el => {{
    el.onclick = (e) => {{
      if (e.target.closest('a')) return;
      const slug = el.dataset.teamslug;
      selectedTeam = selectedTeam === slug ? '' : slug;
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

        # Forma: 5 kolejek PRZED obecną kolejką (w tym nierozegrane)
        rounds = p.get("rounds", [])
        before_current = [r for r in rounds if r.get("round", 0) < current_round] if current_round else rounds
        last5 = before_current[-5:] if before_current else []
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
                "R": p.get("is_reserve", False),
                "form": [],
            })
            # Dodaj formę — 5 kolejek przed obecną kolejką (w tym nierozegrane)
            pr = full.get("rounds", [])
            before_current = [r for r in pr if r.get("round", 0) < current_round] if current_round else pr
            last5 = before_current[-5:] if before_current else []
            team_players[-1]["form"] = [{"r": r.get("round", 0), "pts": r.get("points", 0) if r.get("played") else 0, "p": bool(r.get("played"))} for r in last5]

        league_teams_detail.append({
            "slug": slug,
            "rank": rank,
            "pts": team_pts,
            "players": team_players,
        })
    # Sortuj po pozycji
    league_teams_detail.sort(key=lambda t: t.get("rank") or 999)

    # 8.5 Parse terminarz for fixture ticker
    fixtures_data = parse_terminarz("terminarz.txt")
    if fixtures_data["rounds"]:
        print(f"  📅 Terminarz: {len(fixtures_data['rounds'])} kolejek, {len(fixtures_data['teams'])} drużyn")

    # 8.6 Scrapuj statystyki bramkowe z 90minut.pl
    ekstra_stats = fetch_ekstraklasa_table()

    # 8.7 Oblicz FDR (Fixture Difficulty Rating)
    fdr_data = compute_fdr(ekstra_stats, fixtures_data, current_round=current_round)

    # 8.8 Prognoza punktów (predictor)
    predictions_data = []
    if fdr_data.get("teams") and fdr_data.get("gameweeks"):
        # Znajdź pierwszą nierozgraną kolejkę
        next_gw = fdr_data["gameweeks"][0]
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

        predictions_data = predict_all_players(players_for_pred, pred_fdr, pred_fixtures)

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

            # Wczytaj poprzedni ranking
            prev_ranking = {}
            if os.path.exists(hockey_prev_file):
                try:
                    with open(hockey_prev_file, "r", encoding="utf-8") as f:
                        prev_ranking = json.load(f)
                except Exception:
                    pass

            # Oblicz rank_change vs. poprzednie uruchomienie
            current_ranking = {}
            for i, t in enumerate(league_teams_detail):
                combined_pos = i + 1
                norm_key = normalize_team_name(t.get("display_name", t["slug"].replace("-", " ")))
                current_ranking[norm_key] = combined_pos
                prev_pos = prev_ranking.get(norm_key)
                t["rank_change"] = (prev_pos - combined_pos) if prev_pos is not None else 0
                t["hockey_pos"] = combined_pos

            # Zapisz aktualny ranking do pliku
            with open(hockey_prev_file, "w", encoding="utf-8") as f:
                json.dump(current_ranking, f, ensure_ascii=False, indent=2)

            print(f"   ✅ Przygotowano {len(league_teams_detail)} drużyn do klasyfikacji łącznej")
        except Exception as e:
            print(f"   ⚠️  Błąd ładowania danych jesiennych: {e}")

    # Wczytaj wytunowane parametry dla dashboardu (mogły zostać właśnie zaktualizowane)
    tuned_params_file = os.path.join(OUTPUT_DIR, "tuned_params.json")
    tuned_params = None
    if os.path.exists(tuned_params_file):
        try:
            with open(tuned_params_file, encoding="utf-8") as f:
                tuned_params = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

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
        fixtures_data=fixtures_data,
        ekstra_stats=ekstra_stats,
        fdr_data=fdr_data,
        transfers_data=transfers_data,
        predictions_data=predictions_data,
        accuracy_history=accuracy_history,
        tuned_params=tuned_params,
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
    if predictions_data:
        print(f"   - fantasy_predictions_{timestamp}.csv (prognoza punktów)")
    print(f"   - dashboard.html (interaktywny dashboard)")
    print(f"🕐 Koniec: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
