"""
external_stats.py - pobieranie zewnętrznych statystyk:
tabela z 90minut.pl (GF/GA per drużyna) i rozszerzone statystyki
zawodników z API ekstraklasy (xG, strzały, podania kluczowe).
Dane cache'owane 24h w output/external_cache.json.
"""

import re

import requests
from bs4 import BeautifulSoup

from config import (
    EXTRA_API_TOKEN,
    EXTRA_STATS_API,
    EXTRA_STATS_PARAMS,
    NINETYM_LIGA_ID,
    NINETYM_TEAM_MAP,
    TEAM_ABBREVS,
)
from network import _get_cached_external, _request_with_retry, _save_external_cache


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
    # Cache 24h — unikamy ponownego scrapowania 90minut.pl przy każdym runie
    cached = _get_cached_external("90minut_table")
    if cached is not None:
        return cached

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
        # Retry logic na wypadek problemów sieciowych
        resp = _request_with_retry(requests.get, url, headers=headers, timeout=20)
        if resp is None:
            return team_stats  # pusty słownik, bo nie udało się pobrać
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
    # Zapisz do cache tylko jeśli udało się pobrać niepuste dane
    if team_stats:
        _save_external_cache("90minut_table", team_stats)
    return team_stats


def fetch_extra_player_stats() -> dict:
    """
    Pobiera rozszerzone statystyki zawodników z ukrytego API ekstraklasy.
    
    API endpoint: production-umpire-api.ekstraklasa.tisagroup.ch/api/v3/statistics
    Wymaga tokena autoryzacyjnego w headerze Authorization.
    
    Zwraca dict z statystykami: xg, shots, shots_on_target, key_passes, crosses, crosses_accurate
    """
    # Cache 24h — unikamy ponownego odpytywania API ekstraklasy przy każdym runie
    cached = _get_cached_external("extra_player_stats")
    if cached is not None:
        return cached

    # Sprawdź czy token API jest dostępny – jeśli nie, pomiń rozszerzone statystyki
    if not EXTRA_API_TOKEN:
        print("\n⚠️  Brak EXTRAKLASA_API_TOKEN – pomijam rozszerzone statystyki")
        return {}

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
    
    # Zapisz do cache tylko jeśli pobrano niepuste dane (np. jest przynajmniej jeden wpis w xg)
    if any(v for v in all_stats.values()):
        _save_external_cache("extra_player_stats", all_stats)
    return all_stats
