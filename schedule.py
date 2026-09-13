"""
schedule.py - parsowanie terminarza meczów i czyszczenie starych
plików w output/.
"""

import os
import re
import glob

from config import MONTHS_PL, TEAM_ABBREVS


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
                # Obsługa dwóch formatów daty w nagłówku:
                # (a) "DD-DD miesiąc" np. "19-20 września" - ten sam miesiąc
                # (b) "DD miesiąc-DD miesiąc" np. "31 października-1 listopada" - przełom miesięcy
                header_part = line[len(round_match.group(0)):]
                # Format (b): przełom miesięcy - dzień i miesiąc przed myślnikiem
                cross_month_match = re.search(r"(\d{1,2})\s+(\w+)\s*[–\-]", header_part)
                if cross_month_match:
                    day = cross_month_match.group(1)
                    month = MONTHS_PL.get(cross_month_match.group(2).lower())
                    if month:
                        current_round_date = f"{int(day):02d}.{month:02d}"
                else:
                    # Format (a): ten sam miesiąc - tylko dzień przed myślnikiem
                    header_date = re.search(r"(\d{1,2})[–\-]\d*\s+(\w+)", header_part)
                    if header_date:
                        month = MONTHS_PL.get(header_date.group(2).lower())
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
                # Obsługa formatów: "DrużynaA\t-\tDrużynaB" lub "DrużynaA\t2-1\tDrużynaB" (z wynikiem)
                parts = re.split(r'\t+\d*-\d*\t+', teams_part)
                if len(parts) != 2:
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
                    away_part = parts[1].strip()
                    # Pomijamy linie z cyframi — to listy strzelców (np. "Luis Palma 57 - Kike Hermoso 52"),
                    # a nie mecze. Nazwy drużyn Ekstraklasy nigdy nie zawierają cyfr.
                    # Dodatkowo pomijamy linie wyglądające na opisy zdarzeń (np. "żółtą kartką został...")
                    # WALIDACJA: mecz akceptowany jeśli:
                    # (a) away to znana drużyna (w TEAM_ABBREVS), LUB
                    # (b) w away jest poprawna data (format: "DD miesiąca, GG:MM")
                    # Punkt (b) to zabezpieczenie na przyszłość dla nowych klubów po awansie
                    date_in_away = re.search(r'^(.+?)(\d{1,2}\s+(?:stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|września|października|listopada|grudnia),\s*\d{1,2}:\d{2})', away_part, re.IGNORECASE)
                    if date_in_away:
                        away = date_in_away.group(1).strip()
                        # Sprawdź czy miesiąc jest poprawny
                        month_match = re.search(r'(\d{1,2})\s+(\w+),', away_part)
                        if month_match:
                            month_name = month_match.group(2).lower()
                            month = MONTHS_PL.get(month_name)
                            if month:
                                date_valid = True
                                match_date = f"{int(month_match.group(1)):02d}.{month:02d}"
                            else:
                                date_valid = False
                                match_date = current_round_date
                        else:
                            date_valid = False
                            match_date = current_round_date
                    else:
                        away = away_part
                        date_valid = False
                        match_date = current_round_date
                    # Główny warunek: (znana drużyna) OR (poprawna data w linii)
                    # Sprawdź czy home lub away to znane drużyny — zabezpieczenie na przyszłość
                    is_known_team = (home in TEAM_ABBREVS) or (away in TEAM_ABBREVS)
                    if home and away and len(home) > 2 and not re.match(r'^\d', home) \
                            and not re.search(r'\d', home) and not re.search(r'\d', away) \
                            and not re.search(r'żółt|kartk|czerwon|ukar|sędzi', home, re.IGNORECASE) \
                            and (is_known_team or date_valid):
                        teams_set.add(home)
                        teams_set.add(away)
                        matches_by_round[current_round].append({
                            "home": home,
                            "away": away,
                            "date": match_date,
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


def cleanup_old_output_files():
    """
    Usuwa stare pliki z output/ z timestampem w nazwie, zachowując N najnowszych.
    NIGDY nie rusza plików stanu (dashboard.html, league_teams_detail.json,
    external_cache.json, league_squads_history.json, itp.).
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
