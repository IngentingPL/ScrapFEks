"""
config.py - cała konfiguracja scraper.py: URL-e, nagłówki HTTP,
zmienne środowiskowe, mapy nazw drużyn. Jeden plik, żeby zmiana
konfiguracji nie wymagała szukania po całym scraper.py.
"""
import os
import time


# ============================================================
# BLOK A – konfiguracja ze środowiska
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


# ============================================================
# BLOK B – URL-e, nagłówki, SCRIPT_START, OUTPUT_DIR
# ============================================================

# Globalny czas startu
SCRIPT_START = time.time()

# Plik wyjściowy
OUTPUT_DIR = "output"

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

# Nagłówki przeglądarki (czyste, bez X-Requested-With) – używane przy żądaniach HTML
BROWSER_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": HEADERS["Accept-Language"],
}

# Nagłówki do endpointów AJAX POST (ranking-list itp.)
RANKING_HEADERS = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}


# ============================================================
# BLOK C – pozostałe stałe modułowe
# ============================================================

# Skróty nazw drużyn (używane w FDR i terminarzu)
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

# Token autoryzacyjny - pobrany ze zmiennej środowiskowej EXTRAKLASA_API_TOKEN
# Jeśli nie ustawiony, rozszerzone statystyki są pomijane
EXTRA_API_TOKEN = os.environ.get("EXTRAKLASA_API_TOKEN", "")  # fallback: pusty string

# Nazwy miesięcy po polsku (używane przy parsowaniu terminarz.txt)
MONTHS_PL = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
}
