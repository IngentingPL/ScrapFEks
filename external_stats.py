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
    AUTUMN_LAST_ROUND,
    EXTRA_API_TOKEN,
    EXTRA_STATS_API,
    EXTRA_STATS_PARAMS,
    NINETYM_LIGA_ID,
    NINETYM_TEAM_MAP,
    TEAM_ABBREVS,
)
from network import _get_cached_external, _request_with_retry, _save_external_cache


def _parse_goals(text):
    """Rozbija tekst 'gf-ga' (lub 'gf:ga') na parę liczb. Zwraca (None, None) gdy nie parsowalne."""
    parts = re.split(r"[-:]", (text or "").strip())
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return None, None


def _parse_90min_combined_table(table) -> dict:
    """Parsuje nową tabelę 90minut.pl z grupami RAZEM/DOM/WYJAZD (jedna tabela).

    Wiersz drużyny ma 22 komórki; indeksy (0-based):
    1=nazwa (link 'klub'), 2=M. razem, 4-6=Z/R/P razem, 7=bramki RAZEM,
    8-10=Z/R/P dom, 11=bramki DOM, 12-14=Z/R/P wyjazd, 15=bramki WYJAZD.
    """
    results = {}
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 17:  # nagłówki/segregatory mają mniej komórek
            continue

        # Nazwa drużyny: <a> w komórce 2, href musi zawierać "klub"
        name_cell = cells[1]
        link = name_cell.find("a")
        href = (link.get("href") or "") if link else ""
        if not link or "klub" not in href:
            print(f"  ⚠️  90minut: pominięto wiersz '{name_cell.get_text(strip=True)}' (brak linku z 'klub' w href)")
            continue
        team_name = link.get_text(strip=True)

        # Liczba meczów: M. razem z komórki 3; dom/wyjazd jako suma Z+R+P
        try:
            mp = int(cells[2].get_text(strip=True))
        except ValueError:
            mp = 0

        def _sum3(indexes):
            """Sumuje zawartość 3 komórek (Z+R+P), ignoruje nieparsowalne."""
            total = 0
            for i in indexes:
                try:
                    total += int(cells[i].get_text(strip=True))
                except (ValueError, IndexError):
                    pass
            return total

        mp_home = _sum3([8, 9, 10])
        mp_away = _sum3([12, 13, 14])

        # Bramki z komórek 8/12/16 (format "gf-ga")
        gf, ga = _parse_goals(cells[7].get_text(strip=True))
        gf_home, ga_home = _parse_goals(cells[11].get_text(strip=True))
        gf_away, ga_away = _parse_goals(cells[15].get_text(strip=True))
        if gf is None or gf_home is None or gf_away is None:
            print(f"  ⚠️  90minut: pominięto '{team_name}' (nieparsowalne bramki)")
            continue

        # Walidacja spójności: dom + wyjazd muszą dać ogółem (tolerancja ±1)
        if abs((gf_home + gf_away) - gf) > 1:
            print(f"  ⚠️  90minut: pominięto '{team_name}' (gf_home+gf_away={gf_home + gf_away} != gf={gf})")
            continue

        results[team_name] = {
            "gf": gf, "ga": ga, "mp": mp,
            "gf_home": gf_home, "ga_home": ga_home, "mp_home": mp_home,
            "gf_away": gf_away, "ga_away": ga_away, "mp_away": mp_away,
        }
    return results


def _map_team_name(raw_name: str) -> str:
    """Mapuje nazwę drużyny z 90minut.pl na lokalną z terminarz.txt."""
    local_name = NINETYM_TEAM_MAP.get(raw_name, raw_name)
    if local_name not in TEAM_ABBREVS:
        for local in TEAM_ABBREVS:
            if raw_name.lower() in local.lower() or local.lower() in raw_name.lower():
                return local
    return local_name


def _find_standings_table(soup):
    """Znajduje właściwą tabelę STRUKTURALNIE: <tr>, którego bezpośrednie
    <td> zawierają teksty 'RAZEM', 'DOM', 'WYJAZD' (nagłówek grup kolumn)."""
    for tr in soup.find_all("tr"):
        texts = [td.get_text(strip=True) for td in tr.find_all("td", recursive=False)]
        if "RAZEM" in texts and "DOM" in texts and "WYJAZD" in texts:
            return tr.find_parent("table")
    return None


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

        table = _find_standings_table(soup)
        if table is None:
            print("  ⚠️  Nie znaleziono tabeli z nagłówkiem RAZEM/DOM/WYJAZD na 90minut.pl")
            return team_stats

        parsed = _parse_90min_combined_table(table)
        for raw_name, data in parsed.items():
            local_name = _map_team_name(raw_name)
            team_stats[local_name] = data

        has_ha = any(e.get("mp_home", 0) > 0 and e.get("mp_away", 0) > 0
                     for e in team_stats.values())
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


def generate_terminarz_from_90minut(start_round=1, end_round=None):
    """
    Generuje terminarz.txt na podstawie danych z 90minut.pl.
    
    Pobiera stronę ligi z 90minut.pl i parsuje strukturę kolejek:
    - Nagłówki kolejek: <table class="main" cellpadding="0"> z <u>Kolejka N
    - Tabela meczów: następna <table class="main" cellpadding="1">
    - Mecz rozegrany: komórka wyniku zawiera <a href="...mecz.php...">
    - Mecz przyszły/przełożony: komórka wyniku zawiera "-"
    - Strzelcy: wiersz <td colspan="4"> po meczu
    - Mecz przełożony: dodatkowy wiersz z informacją o odwołaniu
    
    Zapisuje wynik do /tmp/terminarz_generated.txt
    
    Args:
        start_round: numer pierwszej kolejki do pobrania (domyślnie 1)
        end_round: numer ostatniej kolejki (domyślnie AUTUMN_LAST_ROUND z config.py)
    
    Returns:
        ścieżka do wygenerowanego pliku lub None w przypadku błędu
    """
    if end_round is None:
        end_round = AUTUMN_LAST_ROUND
    
    url = f"http://www.90minut.pl/liga/1/liga{NINETYM_LIGA_ID}.html"
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        
        print(f"📥 Pobieram terminarz z 90minut.pl (kolejki {start_round}-{end_round})...")
        resp = _request_with_retry(requests.get, url, headers=headers, timeout=20)
        if resp is None:
            print("❌ Nie udało się pobrać strony 90minut.pl")
            return None
        
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "iso-8859-2"
        
        soup = BeautifulSoup(resp.text, "lxml")
        
        # Znajdź wszystkie tabele z klasą "main"
        all_tables = soup.find_all("table", class_="main")
        
        # Słownik do przechowywania kolejek: round_num -> {header, matches[]}
        rounds = {}
        current_round = None
        
        for table in all_tables:
            cellpadding = table.get("cellpadding", "")
            
            # Sprawdź czy to tabela nagłówka kolejki (cellpadding="0")
            if cellpadding == "0":
                # Szukaj tekstu "Kolejka N" w <u>
                u_tag = table.find("u")
                if u_tag:
                    text = u_tag.get_text(strip=True)
                    match = re.match(r"Kolejka\s+(\d+)\s*-\s*(.+)", text)
                    if match:
                        round_num = int(match.group(1))
                        round_date = match.group(2).strip()
                        if start_round <= round_num <= end_round:
                            current_round = round_num
                            rounds[current_round] = {
                                "header": f"Kolejka {round_num} - {round_date}",
                                "matches": []
                            }
                            print(f"  ✓ Znaleziono nagłówek: {rounds[current_round]['header']}")
                        else:
                            current_round = None
            
            # Sprawdź czy to tabela meczów (cellpadding="1") i mamy aktywną kolejkę
            elif cellpadding == "1" and current_round is not None:
                rows = table.find_all("tr")
                i = 0
                while i < len(rows):
                    row = rows[i]
                    cells = row.find_all("td")
                    
                    # Wiersz meczu ma 4 komórki
                    if len(cells) == 4:
                        # Gospodarz
                        home = cells[0].get_text(strip=True)
                        # Wynik lub "-"
                        score_cell = cells[1]
                        score_link = score_cell.find("a", href=re.compile(r"mecz\.php"))
                        if score_link:
                            score = score_link.get_text(strip=True)
                            is_played = True
                        else:
                            score = score_cell.get_text(strip=True)
                            is_played = False
                        
                        # Gość
                        away = cells[2].get_text(strip=True)
                        # Data/godzina/frekwencja
                        date_info = cells[3].get_text(strip=True)
                        
                        # Uprość nazwy drużyn (usuń pogrubienie)
                        home = re.sub(r"\s+", " ", home).strip()
                        away = re.sub(r"\s+", " ", away).strip()
                        
                        match_data = {
                            "home": home,
                            "away": away,
                            "score": score,
                            "date_info": date_info,
                            "is_played": is_played,
                            "scorers": None,
                            "postponed_info": None,
                            "extra_lines": []
                        }
                        
                        # Sprawdź następne wiersze (strzelcy, info o przełożeniu, dodatkowe info)
                        i += 1
                        while i < len(rows):
                            next_row = rows[i]
                            next_cells = next_row.find_all("td")
                            
                            # Wiersz strzelców lub info: colspan="4"
                            if len(next_cells) == 1 and next_cells[0].get("colspan") == "4":
                                # Używamy separator=' ' żeby wymusić spację między zagnieżdżonymi tagami
                                # np. <i>Léo Borges</i> 46 -> "Léo Borges 46" zamiast "Léo Borges46"
                                text = next_cells[0].get_text(separator=' ', strip=True)
                                # Redukujemy ewentualne wielokrotne spacje do pojedynczej
                                text = re.sub(r'\s+', ' ', text).strip()
                                
                                # Czy to info o przełożeniu?
                                if "odwołany" in text.lower() or "pierwotnym terminie" in text.lower():
                                    match_data["postponed_info"] = text
                                    i += 1
                                # Czy to strzelcy (nie zawiera "odwołany")?
                                elif text and not text.startswith("W ") and "kartką" not in text and "na " != text[:3]:
                                    match_data["scorers"] = text
                                    i += 1
                                # Inne dodatkowe linie
                                elif text:
                                    match_data["extra_lines"].append(text)
                                    i += 1
                                else:
                                    break
                            else:
                                break
                        
                        rounds[current_round]["matches"].append(match_data)
                        continue  # i już zwiększone w pętli while
                    
                    i += 1
        
        # Generuj wyjście w formacie terminarz.txt
        output_lines = []
        
        for round_num in sorted(rounds.keys()):
            round_data = rounds[round_num]
            
            # Pusta linia przed kolejką (oprócz pierwszej)
            if output_lines:
                output_lines.append("")
            
            # Nagłówek kolejki
            # Kolejka 1 bez spacji na początku, kolejki 2+ ze spacją
            if round_num == 1:
                output_lines.append(round_data["header"])
            else:
                output_lines.append(f" {round_data['header']}")
            
            output_lines.append("")  # Pusta linia po nagłówku
            
            for match in round_data["matches"]:
                # Linia meczu: Gospodarz\twynik\tGość\tdata
                line = f"{match['home']}\t{match['score']}\t{match['away']}\t{match['date_info']}"
                output_lines.append(line)
                
                # Strzelcy (jeśli są)
                if match["scorers"]:
                    output_lines.append(match["scorers"])
                
                # Dodatkowe linie (np. "na Synerise Arenie Kraków", info o kartkach, rzutach karnych)
                for extra in match["extra_lines"]:
                    output_lines.append(extra)
                
                # Info o przełożeniu (na końcu)
                if match["postponed_info"]:
                    output_lines.append(match["postponed_info"])
        
        # Zapisz do pliku
        output_path = "/tmp/terminarz_generated.txt"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))
            # Dodaj newline na końcu pliku
            f.write("\n")
        
        print(f"✅ Wygenerowano terminarz: {output_path}")
        print(f"   Kolejki: {len(rounds)}, mecze: {sum(len(r['matches']) for r in rounds.values())}")
        
        return output_path
        
    except Exception as e:
        print(f"❌ Błąd generowania terminarza: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # Testowe wywołanie
    result = generate_terminarz_from_90minut()
    if result:
        print(f"\nZapisano do: {result}")
