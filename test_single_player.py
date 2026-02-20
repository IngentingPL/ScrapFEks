#!/usr/bin/env python3
"""
Szybki test - pobierz dane jednego zawodnika.
Użyj tego, żeby sprawdzić czy cookies działają.

Użycie:
    python test_single_player.py [player_id]

Przykład:
    python test_single_player.py 2123
"""

import requests
from bs4 import BeautifulSoup
import json
import sys
import os

# ============================================================
# COOKIES - z env var lub wpisz ręcznie
# ============================================================
SESSION_COOKIE = os.environ.get("FANTASY_SESSION_COOKIE", "")
RAW_COOKIES = os.environ.get("FANTASY_RAW_COOKIES", "")
# ============================================================

BASE_URL = "https://fantasy.ekstraklasa.org"
PLAYER_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 2123

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/145.0.0.0",
    "X-Requested-With": "XMLHttpRequest",
}

session = requests.Session()
session.headers.update(headers)

if RAW_COOKIES:
    session.headers["Cookie"] = RAW_COOKIES
elif SESSION_COOKIE:
    session.cookies.set("PHPSESSID", SESSION_COOKIE, domain="fantasy.ekstraklasa.org")

print(f"🔍 Pobieram dane zawodnika ID={PLAYER_ID}...")
print(f"   URL: {BASE_URL}/stats-player/{PLAYER_ID}")
print()

resp = session.get(f"{BASE_URL}/stats-player/{PLAYER_ID}")
print(f"   Status: {resp.status_code}")

if resp.status_code != 200:
    print(f"   ❌ Błąd! Sprawdź cookies i ID zawodnika.")
    sys.exit(1)

data = resp.json()
html = data.get("data", {}).get("message", "")

if not html:
    print(f"   ❌ Pusta odpowiedź. Zawodnik o ID={PLAYER_ID} nie istnieje.")
    sys.exit(1)

soup = BeautifulSoup(html, "lxml")

# Parsuj dane
name_el = soup.select_one(".player-name")
name = name_el.get_text(separator=" | ", strip=True) if name_el else "?"

info_table = soup.select_one(".player-inf table")
info = {}
if info_table:
    for row in info_table.select("tr"):
        cells = row.select("td")
        if len(cells) >= 2:
            info[cells[0].text.strip().rstrip(":")] = cells[1].text.strip()

print(f"   ✅ Znaleziono zawodnika!")
print()
print(f"   👤 {name}")
for k, v in info.items():
    print(f"      {k}: {v}")

# Statystyki per kolejka
stats_table = soup.select_one("#statsTab table")
if stats_table:
    print(f"\n   📊 Statystyki per kolejka:")
    print(f"   {'Kol':>4} {'Przeciwnik':<12} {'Min':>4} {'Br':>3} {'As':>3} {'ŻK':>3} {'CK':>3} {'Pkt':>4}")
    print(f"   {'-'*45}")
    for row in stats_table.select("tbody tr"):
        cells = row.select("td")
        colspan = row.select_one("td[colspan]")
        if colspan and "nie grał" in colspan.text.lower():
            kol = cells[0].text.strip()
            opp = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            print(f"   {kol:>4} {opp:<12} {'-- nie grał --':>25}")
        elif len(cells) >= 9:
            vals = [c.text.strip() for c in cells]
            print(f"   {vals[0]:>4} {cells[1].get_text(strip=True):<12} "
                  f"{vals[2]:>4} {vals[3]:>3} {vals[4]:>3} "
                  f"{vals[6]:>3} {vals[7]:>3} {vals[8]:>4}")

print(f"\n   🔗 Pełna odpowiedź JSON zapisana w: test_response.json")
with open("test_response.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
