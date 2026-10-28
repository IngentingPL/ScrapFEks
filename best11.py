"""
best11.py — "Najlepsza Jedenastka" (Best11)
===========================================

Moduł buduje idealny skład na bazie prognoz predictora i sprawdza,
jak taki skład wypałby na prawdziwych punktach:

1. HISTORIA (output/best11_history.json) — dla każdej rozegranej kolejki
   zapisujemy skład wybrany PO PROGNOZACH (to byśmy wybrali przed meczami),
   a potem dokładamy realne punkty tych graczy. Dzięki temu widzimy,
   jak dobry byłby nasz "dream team" na tle najlepszej drużyny ligi CMF.

2. NASTĘPNA KOLEJKA (output/best11_next.json) — proponowany skład
   na nadchodzącą kolejkę, liczony z aktualnych prognoz predictora.

Zasady wyboru składu (wszystko deterministyczne — ten sam zestaw danych
DAJE ZAWSZE TEN SAM wynik):
- skład = 1 bramkarz (GK) + 10 zawodników z pola (DEF/MID/FWD),
- na każdej pozycji bierzemy graczy z najwyższą prognozą,
  remis prognoz → wygrywa nazwisko wcześniejsze alfabetycznie,
- formacja (np. 4-4-2) to ta, która daje najwyższą prognozowaną sumę;
  remis między formacjami → wygrywa formacja wcześniejsza na liście FORMACJE,
- kapitan = gracz z najwyższą prognozą w składzie (remis → alfabetycznie);
  jego PUNKTY REALNE liczymy razy MNOZNIK_KAPITANA (jak w grze fantasy),
- jeśli dla jakiejś formacji brakuje graczy na którejś pozycji
  (np. tylko 2 obrońcy mają prognozy) — formację pomijamy.

Moduł używa TYLKO standardowej biblioteki Pythona (csv, json, os)
i funkcji round_points z utils.py. Funkcje obliczeniowe są "czyste"
(bez sieci i zapisu na dysk) — łatwo je testować.
"""

import csv
from datetime import datetime, timezone
import json
import os
import re

from utils import round_points, _normalize_name, normalize_team_name

# ============================================================
# STAŁE
# ============================================================

# Ile razy punkty kapitana liczą się do sumy drużyny (jak w grze fantasy).
MNOZNIK_KAPITANA = 2

# Lista formacji w formacie (obrońcy, pomocnicy, napastnicy).
# Bramkarz jest zawsze dokładnie 1, więc 10 zawodników z pola = 11 graczy.
# KOLEJNOŚĆ LISTY MA ZNACZENIE: przy remisie prognozowanej sumy wygrywa
# formacja wcześniejsza na liście (deterministyczny remis).
FORMACJE = [
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
]

# Pozycje z gry fantasy → krótkie nazwy używane w plikach JSON Best11.
MAPA_POZYCJI = {
    "BR": "GK",   # bramkarz
    "OBR": "DEF",  # obrońca
    "POM": "MID",  # pomocnik
    "NAP": "FWD",  # napastnik
    "GK": "GK",    # już znormalizowana pozycja z picku Best11
    "DEF": "DEF",
    "MID": "MID",
    "FWD": "FWD",
}

# Pliki wynikowe — leżą obok accuracy_history.json (katalog output/).
BEST11_HISTORY_FILE = os.path.join("output", "best11_history.json")
BEST11_NEXT_FILE = os.path.join("output", "best11_next.json")
BEST11_PICKS_FILE = os.path.join("output", "best11_picks.json")
LEAGUE_HISTORY_FILE = os.path.join("output", "league_history.json")
LEAGUE_TEAMS_DETAIL_FILE = os.path.join("output", "league_teams_detail.json")
TERMINARZ_FILE = "terminarz.txt"


# ============================================================
# FUNKCJE POMOCNICZE (czyste — bez dysku i sieci)
# ============================================================

def _na_float(wartosc):
    """Bezpiecznie zamień wartość na float.

    Zwraca None, gdy zamiana się nie uda (np. pusty string z CSV
    albo None z predictora dla "insufficient_data").
    """
    if wartosc is None:
        return None
    try:
        return float(wartosc)
    except (TypeError, ValueError):
        return None


def _klucz_rankingu(prognoza):
    """Klucz sortowania graczy: wyższa prognoza = wyżej na liście,
    remis prognoz → nazwisko wcześniejsze alfabetycznie.

    _normalize_name usuwa polskie znaki i zamienia na małe litery,
    więc "Łukasz" i "Lukasz" porównują się tak samo (deterministycznie).
    """
    return (-prognoza["predicted"], _normalize_name(prognoza["name"]))


def normalizuj_prognozy(prognozy):
    """Zamienia prognozy z dowolnego źródła (CSV, accuracy history,
    predictor) na jeden wspólny format.

    Każda prognoza po normalizacji to słownik:
        {"player_id", "name", "team", "position" (GK/DEF/MID/FWD),
         "predicted" (float)}

    Pomijamy:
    - graczy bez znanej pozycji (np. pusta pozycja w CSV),
    - graczy bez liczbowej prognozy (predicted_points=None / ""
      — np. "insufficient_data" z predictora).

    Wynik jest posortowany: prognoza malejąco, remis → alfabetycznie.
    """
    wynik = []
    for p in prognozy or []:
        if not isinstance(p, dict):
            continue
        pozycja = MAPA_POZYCJI.get(p.get("position", ""))
        if not pozycja:
            continue
        # CSV ma kolumnę "predicted_points", details w accuracy history
        # mają pole "predicted" — obsłużymy oba.
        predicted = _na_float(p.get("predicted_points", p.get("predicted")))
        if predicted is None:
            continue
        wynik.append({
            "player_id": str(p.get("player_id", "") or ""),
            "id": p.get("id", p.get("player_id")),
            "name": p.get("name", "") or "",
            "team": p.get("team", "") or "",
            "position": pozycja,
            "predicted": predicted,
            "opponents": _lista_json(p.get("opponents")),
            "is_home_list": _lista_json(p.get("is_home_list")),
            "fixtures_count": int(_na_float(p.get("fixtures_count")) or 0),
        })
    wynik.sort(key=_klucz_rankingu)
    return wynik


def _lista_json(value):
    """CSV przechowuje niektóre listy jako JSON-tekst; odtwarzamy je tutaj."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []
    return []


def wybierz_sklad(prognozy, formacja):
    """Wybiera 11 graczy dla JEDNEJ formacji, np. (4, 4, 2).

    Na każdej pozycji bierzemy graczy z najwyższą prognozą
    (lista prognoz jest już posortowana deterministycznie).

    Zwraca listę 11 graczy w kolejności GK → DEF → MID → FWD
    albo None, gdy na którejś pozycji jest za mało graczy
    (niepełny skład → formację pomijamy).
    """
    obr, pom, nap = formacja
    wymagane = [("GK", 1), ("DEF", obr), ("MID", pom), ("FWD", nap)]
    sklad = []
    for pozycja, ile in wymagane:
        kandydaci = [p for p in prognozy if p["position"] == pozycja]
        if len(kandydaci) < ile:
            return None  # niepełny skład — pomijamy tę formację
        sklad.extend(kandydaci[:ile])
    return sklad


def _nazwa_formacji(formacja):
    """Zamienia krotkę formacji na czytelny napis: (4, 4, 2) → "4-4-2"."""
    return "-".join(str(liczba) for liczba in formacja)


def wybierz_formacje_i_sklad(prognozy):
    """Szuka formacji z najwyższą prognozowaną sumą punktów.

    Przechodzimy po FORMACJE w zapisanej kolejności. Przy remisie sumy
    wygrywa formacja wcześniejsza na liście (porównujemy przez ">",
    więc równa suma nie zamienia obecnego zwycięzcy).

    predicted_total liczy kapitana podwójnie (jak w grze fantasy):
    suma prognoz 11 graczy + dodatkowa prognoza kapitana.

    Zwraca krotkę (formacja, sklad, kapitan, predicted_total)
    albo None, gdy żadnej formacji nie da się ustawić.
    """
    najlepszy = None
    for formacja in FORMACJE:
        sklad = wybierz_sklad(prognozy, formacja)
        if sklad is None:
            continue
        # Kapitan = najwyższa prognoza w składzie (remis → alfabetycznie).
        # min() z tym samym kluczem sortowania daje pierwszego "z góry".
        kapitan = min(sklad, key=_klucz_rankingu)
        total = (
            sum(p["predicted"] for p in sklad)
            + (MNOZNIK_KAPITANA - 1) * kapitan["predicted"]
        )
        if najlepszy is None or total > najlepszy[3]:
            najlepszy = (formacja, sklad, kapitan, total)
    return najlepszy


def _wczytaj_teams_detail(path=LEAGUE_TEAMS_DETAIL_FILE):
    """Wczytuje nazwy wyświetlane drużyn CMF z danych używanych przez tabelę."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def najlepszy_cmf(league_history, round_number, league_teams_detail=None):
    """Znajduje najlepszą drużynę ligi CMF w danej kolejce.

    Źródło: output/league_history.json — league_tracker zapisuje tam
    surowe (raw) pole round_points dla każdej drużyny. Bierzemy drużynę
    z najwyższą liczbą punktów w kolejce; remis → pierwsza z tabeli
    (tabela jest posortowana wg pozycji, więc wybór jest deterministyczny).

    Zwraca {"name": ..., "points": ...} albo None, gdy brak danych
    dla tej kolejki.
    """
    for runda in (league_history or {}).get("rounds", []):
        if runda.get("round") != round_number:
            continue
        najlepszy = None  # (drużyna, punkty)
        for druzyna in runda.get("standings", []):
            punkty = _na_float(druzyna.get("round_points"))
            if punkty is None:
                continue
            if najlepszy is None or punkty > najlepszy[1]:
                najlepszy = (druzyna, punkty)
        if najlepszy is None:
            return None
        druzyna, punkty = najlepszy
        slug = druzyna.get("slug", "")
        team_rows = league_teams_detail
        if team_rows is None:
            team_rows = _wczytaj_teams_detail()
        szczegoly = next(
            (t for t in team_rows if slug and t.get("slug") == slug),
            {},
        )
        if not szczegoly.get("display_name") and league_teams_detail is not None:
            # W scraperze nazwy są dopisywane później, więc sprawdź też
            # ostatni zapisany plik używany przez tabelę ligi.
            zapisane = _wczytaj_teams_detail()
            szczegoly = next(
                (t for t in zapisane if slug and t.get("slug") == slug),
                szczegoly,
            )
        nazwa = szczegoly.get("display_name")
        if nazwa:
            return {"name": nazwa, "slug": slug, "points": punkty}
        # Jeśli brak nazwy do tabeli, zachowujemy zarówno nazwę ze standings,
        # jak i slug, żeby później dało się rozpoznać drużynę.
        return {
            "name": druzyna.get("team", "") or slug,
            "slug": slug,
            "points": punkty,
        }
    return None


def czy_kolejka_jest_kompletna(round_number, fixtures_data, terminarz_path=TERMINARZ_FILE):
    """Sprawdza, czy każdy mecz kolejki ma wynik w używanym terminarzu.

    Samo upłynięcie daty meczu nie wystarcza — przełożone spotkanie mogłoby
    nadal czekać na rozegranie. Dlatego dla każdego meczu z fixtures_data
    szukamy wyniku w odpowiadającym mu wierszu terminarza.
    """
    mecze = (fixtures_data or {}).get("matches", {}).get(str(round_number), [])
    if not mecze:
        return False

    try:
        with open(terminarz_path, "r", encoding="utf-8") as f:
            linie = f.readlines()
    except OSError:
        return False

    sekcja = []
    w_sekcji = False
    wzorzec_kolejki = re.compile(r"^\s*Kolejka\s+(\d+)", re.IGNORECASE)
    for linia in linie:
        naglowek = wzorzec_kolejki.match(linia)
        if naglowek:
            if w_sekcji:
                break
            w_sekcji = int(naglowek.group(1)) == int(round_number)
            continue
        if w_sekcji:
            sekcja.append(linia.rstrip("\n"))

    if not w_sekcji:
        return False

    for mecz in mecze:
        gospodarze = normalize_team_name(mecz.get("home", ""))
        goscie = normalize_team_name(mecz.get("away", ""))
        wynik_jest = False
        for linia in sekcja:
            pola = [p.strip() for p in linia.split("\t")]
            if len(pola) < 3:
                continue
            if (normalize_team_name(pola[0]) != gospodarze
                    or normalize_team_name(pola[2]) != goscie):
                continue
            # W terminarzu wynik ma zapis „2 : 1”, a godzina „18:00”.
            if re.fullmatch(r"\d+\s+:\s+\d+", pola[1]):
                wynik_jest = True
                break
        if not wynik_jest:
            return False
    return True


def zbuduj_wpis_historii(
    round_number, prognozy_raw, actual_lookup, best_cmf,
    zrodlo="dokładne", zrodlo_info=None,
):
    """Buduje jeden wpis historii Best11 dla ROZEGRANEJ kolejki.

    Parametry:
        round_number:  numer kolejki,
        prognozy_raw:  prognozy w surowym formacie (z CSV albo accuracy),
        actual_lookup: funkcja (player_id) → realne punkty gracza
                       z tej kolejki; brak danych gracza = 0,
        best_cmf:      {"name", "points"} najlepszej drużyny ligi CMF
                       w tej kolejce albo None.

    Zwraca słownik-payload gotowy do JSON albo None, gdy nie da się
    ustawić żadnej formacji (za mało graczy z prognozami).
    """
    prognozy = normalizuj_prognozy(prognozy_raw)
    wybrane = wybierz_formacje_i_sklad(prognozy)
    if wybrane is None:
        return None
    formacja, sklad, kapitan, predicted_total = wybrane

    gracze = []
    actual_total = 0.0
    for p in sklad:
        # Brak realnych punktów gracza (nie zagrał / brak danych) = 0.
        actual = actual_lookup(p["player_id"])
        czy_kapitan = p is kapitan
        # W składzie zapisujemy bazowe punkty gracza, a do sumy dodajemy
        # dodatkową kopię punktów kapitana zgodnie z mnożnikiem x2.
        actual_total += actual * (MNOZNIK_KAPITANA if czy_kapitan else 1)
        gracze.append({
            "id": p["id"],
            "position": p["position"],
            "name": p["name"],
            "team": p["team"],
            "predicted": p["predicted"],
            "actual": round(actual, 1),
            "opponents": p["opponents"],
            "is_home_list": p["is_home_list"],
            "fixtures_count": p["fixtures_count"],
            "is_captain": czy_kapitan,
        })

    wpis = {
        "round": round_number,
        "formation": _nazwa_formacji(formacja),
        "players": gracze,
        "captain": kapitan["name"],
        "predicted_total": round(predicted_total, 1),
        "actual_total": round(actual_total, 1),
        "best_cmf": best_cmf,
        "zrodlo": zrodlo,
        # Różnica: o ile Best11 zdobył mniej/więcej niż najlepsza
        # drużyna ligi CMF w tej kolejce.
        "difference": (
            round(actual_total - best_cmf["points"], 1) if best_cmf else None
        ),
    }
    if zrodlo_info:
        wpis["zrodlo_info"] = zrodlo_info
    return wpis


def zbuduj_nastepny_sklad(round_number, prognozy_raw):
    """Buduje payload Best11 na NASTĘPNĄ kolejkę (meczy jeszcze nierozegrane).

    Wybór identyczny jak w historii, ale zamiast realnych punktów
    mamy "actual": None. Zwraca None, gdy składu nie da się ustawić.
    """
    prognozy = normalizuj_prognozy(prognozy_raw)
    wybrane = wybierz_formacje_i_sklad(prognozy)
    if wybrane is None:
        return None
    formacja, sklad, kapitan, predicted_total = wybrane

    gracze = [
        {
            "position": p["position"],
            "id": p["id"],
            "name": p["name"],
            "team": p["team"],
            "predicted": p["predicted"],
            "actual": None,  # mecze jeszcze nie rozegrane
            "opponents": p["opponents"],
            "is_home_list": p["is_home_list"],
            "fixtures_count": p["fixtures_count"],
            "is_captain": p is kapitan,
        }
        for p in sklad
    ]
    return {
        "round": round_number,
        "formation": _nazwa_formacji(formacja),
        "players": gracze,
        "captain": kapitan["name"],
        "predicted_total": round(predicted_total, 1),
    }


# ============================================================
# ZBIERANIE DANYCH (CSV, accuracy history, dane graczy)
# ============================================================

def _prognozy_z_csv(csv_path, round_number=None):
    """Wczytuje prognozy z pliku fantasy_predictions_*.csv.

    Zwraca listę wierszy (słowników) albo pustą listę, gdy pliku brak.
    Jeśli w CSV jest kolumna round_number i wskazuje inną kolejkę niż
    oceniana — zwracamy pustą listę (guard jak w evaluate_predictions).
    """
    if not csv_path or not os.path.exists(csv_path):
        return []
    wiersze = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                wiersze.append(row)
    except (OSError, csv.Error) as e:
        print(f"  ⚠️  Best11: błąd czytania prognoz {csv_path} ({e})")
        return []

    if wiersze and round_number is not None:
        raw_round = wiersze[0].get("round_number")
        try:
            csv_round = int(raw_round)
        except (TypeError, ValueError):
            csv_round = None  # stary CSV bez kolumny — nie blokujemy
        if csv_round is not None and csv_round != round_number:
            print(
                f"  ⚠️  Best11: plik prognoz dotyczy kolejki {csv_round}, "
                f"a oceniamy kolejkę {round_number} — pomijam"
            )
            return []
    return wiersze


def _wpis_accuracy(accuracy_history, round_number):
    """Zwraca wpis accuracy history dla danej kolejki albo None."""
    for entry in accuracy_history or []:
        if isinstance(entry, dict) and entry.get("round") == round_number:
            return entry
    return None


def _prognozy_z_wpisu(entry):
    """Wyciąga KOMPLETNE prognozy z wpisu accuracy history.

    Kompletne dane to:
    - pole "predictions" (zapisane prognozy z evaluate_predictions), albo
    - pełne "details" (każdy ma nazwę, pozycję i prognozę).

    Przycięte details starszych wpisów mają tylko player_id i actual —
    z nich NIE da się ustawić składu, więc zwracamy None (pomijamy
    kolejkę zamiast zgadywać prognozy).
    """
    if not isinstance(entry, dict):
        return None
    predictions = entry.get("predictions") or []
    if predictions:
        # Niekompletne wiersze i tak odrzuci normalizacja.
        return predictions
    details = entry.get("details") or []
    if details and all(
        isinstance(d, dict)
        and d.get("name")
        and d.get("position")
        and _na_float(d.get("predicted")) is not None
        for d in details
    ):
        return details
    return None


def _prognozy_z_pick(pick):
    """Zamienia zamrożony skład z JSON na wejście wspólne dla oceny historii."""
    if not isinstance(pick, dict) or not isinstance(pick.get("players"), list):
        return None
    return [
        {
            "player_id": str(player.get("id", player.get("player_id", "")) or ""),
            "id": player.get("id", player.get("player_id")),
            "name": player.get("name", ""),
            "team": player.get("team", ""),
            "position": player.get("position", ""),
            "predicted": player.get("predicted"),
            "opponents": player.get("opponents", []),
            "is_home_list": player.get("is_home_list", []),
            "fixtures_count": player.get("fixtures_count", 0),
        }
        for player in pick["players"]
        if isinstance(player, dict)
    ]


def _actual_z_graczy(players_data, round_number):
    """Buduje funkcję (player_id) → realne punkty w kolejce.

    Realne punkty bierzemy z aktualnych danych zawodników przez
    utils.round_points — sumuje ono rozegrane mecze w rundzie,
    więc obsługuje też DGW (2 mecze w jednej kolejce).
    Brak gracza / gracz nie zagrał → 0 punktów.
    """
    lookup = {}
    for p in players_data or []:
        pid = str(p.get("player_id", "") or "")
        if pid:
            lookup[pid] = round_points(p, round_number)

    def actual_for(player_id):
        punkty = lookup.get(str(player_id))
        return float(punkty) if punkty is not None else 0.0

    return actual_for


def _actual_z_details(entry):
    """Buduje funkcję (player_id) → realne punkty ze zapisanych details.

    Używane dla starszych kolejek, gdy danych zawodników już nie mamy.
    details zawsze zawierają pole "actual" (też po przycięciu).
    Brak gracza w details (nie zagrał) → 0 punktów.
    """
    mapa = {}
    for d in (entry or {}).get("details") or []:
        if isinstance(d, dict):
            pid = str(d.get("player_id", "") or "")
            if pid:
                mapa[pid] = d.get("actual")

    def actual_for(player_id):
        punkty = mapa.get(str(player_id))
        return float(punkty) if punkty is not None else 0.0

    return actual_for


# ============================================================
# ODCZYT / ZAPIS PLIKÓW JSON
# ============================================================

def wczytaj_best11_history(path=BEST11_HISTORY_FILE):
    """Wczytuje output/best11_history.json.

    Zwraca listę wpisów; [] gdy pliku jeszcze nie ma.
    Zwraca None, gdy plik ISTNIEJE, ale jest uszkodzony — wtedy
    aktualizuj_historie_best11 nic nie zapisze (nie nadpiszemy danych,
    które dałoby się uratować ręcznie).
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  ⚠️  Best11: plik historii {path} jest uszkodzony ({e}) — pomijam zapis")
        return None
    return data if isinstance(data, list) else []


def zapisz_best11_history(history, path=BEST11_HISTORY_FILE):
    """Zapisuje historię Best11 atomowo (najpierw .tmp, potem podmiana)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def wczytaj_best11_picks(path=BEST11_PICKS_FILE):
    """Wczytuje zamrożone składy; brak/uszkodzenie nie zatrzymuje scrapera."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def zapisz_best11_picks(picks, path=BEST11_PICKS_FILE):
    """Zapisuje picki atomowo, jak snapshot: tmp, flush/fsync i os.replace."""
    parent_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent_dir, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(picks, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def wczytaj_league_history(path=LEAGUE_HISTORY_FILE):
    """Wczytuje output/league_history.json (dane ligi CMF).

    Gdy pliku brak albo jest uszkodzony — zwracamy pustą strukturę
    (Best11 wtedy tylko nie będzie miał best_cmf, ale dalej zadziała).
    """
    if not os.path.exists(path):
        return {"rounds": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"rounds": []}
    if not isinstance(data, dict) or "rounds" not in data:
        return {"rounds": []}
    return data


# ============================================================
# GŁÓWNE FUNKCJE WYWOŁYWANE ZE SCRAPER.PY
# ============================================================

def aktualizuj_historie_best11(
    round_number,
    predictions_csv_path=None,
    players_data=None,
    accuracy_history=None,
    league_history_path=LEAGUE_HISTORY_FILE,
    history_path=BEST11_HISTORY_FILE,
    fixtures_data=None,
    league_teams_detail=None,
    expected_forecast_count=None,
    terminarz_path=TERMINARZ_FILE,
    picks_path=BEST11_PICKS_FILE,
):
    """Aktualizuje output/best11_history.json.

    Wywoływane ze scraper.py w tym samym miejscu co evaluate_predictions:
    ten sam warunek (current_round), ten sam numer kolejki i ten sam
    plik prognoz.

    Jak to działa:
    1. Bieżąca kolejka: wpis powstaje dopiero, gdy każdy mecz ma wynik.
       Najpierw używamy zamrożonego picku, potem CSV, a na końcu
       przybliżonych danych accuracy history.
       W trakcie kolejki istniejący wpis nie jest zmieniany.
    2. Starsze kolejki: tylko te, które mają w accuracy history
       kompletne dane prognoz (pole "predictions" albo pełne "details").
       Przycięte wpisy (tylko player_id + actual) pomijamy — nie
       odtwarzamy prognoz na podstawie domysłów. Kolejki już obecne
       w historii Best11 nie są liczone ponownie (idempotentność).

    Historia jest zawsze sortowana po numerze kolejki. Zwraca historię
    (listę) albo pustą listę, gdy plik historii jest uszkodzony.
    """
    history = wczytaj_best11_history(history_path)
    if history is None:
        # Uszkodzony plik — nie nadpisujemy, użytkownik naprawi ręcznie.
        return []
    league_history = wczytaj_league_history(league_history_path)
    if round_number and not czy_kolejka_jest_kompletna(
        round_number, fixtures_data, terminarz_path
    ):
        print(
            f"  ℹ️  Best11: kolejka {round_number} nie ma wyników "
            "dla wszystkich meczów — historii nie zmieniam"
        )
        return history
    zmieniono = False

    # --- 1) Bieżąca kolejka ---
    if round_number:
        saved_picks = wczytaj_best11_picks(picks_path)
        saved_pick = saved_picks.get(str(round_number), saved_picks.get(round_number))
        prognozy = _prognozy_z_pick(saved_pick)
        wpis_accuracy = None
        if prognozy:
            zrodlo = "zapisany"
        else:
            prognozy = _prognozy_z_csv(predictions_csv_path, round_number)
            zrodlo = "csv" if prognozy else "przyblizone"
        if not prognozy:
            # CSV prognoz już usunięto — użyj zapisanych prognoz z accuracy.
            wpis_accuracy = _wpis_accuracy(accuracy_history, round_number)
            prognozy = _prognozy_z_wpisu(wpis_accuracy)
        if prognozy:
            zrodlo_wpisu = zrodlo
            info = None
            if zrodlo == "przyblizone":
                details_count = len((wpis_accuracy or {}).get("details") or [])
                expected_count = expected_forecast_count or len(prognozy)
                info = (
                    f"details: {details_count}; prognoza porównawcza: "
                    f"{expected_count}; różnica: {expected_count - details_count}"
                )
                saved_forecasts = len((wpis_accuracy or {}).get("predictions") or [])
                if saved_forecasts:
                    info += (
                        f"; prognozy tej kolejki: {saved_forecasts}; "
                        f"brakujące details względem nich: "
                        f"{max(saved_forecasts - details_count, 0)}"
                    )
            wpis = zbuduj_wpis_historii(
                round_number,
                prognozy,
                _actual_z_graczy(players_data or [], round_number),
                najlepszy_cmf(league_history, round_number, league_teams_detail),
                zrodlo=zrodlo_wpisu,
                zrodlo_info=info,
            )
            if wpis:
                # Zastąp ewentualny stary wpis tej samej kolejki (bez duplikatów).
                history = [e for e in history if e.get("round") != round_number]
                history.append(wpis)
                zmieniono = True
                print(
                    f"  🏆 Best11: kolejka {round_number} — formacja "
                    f"{wpis['formation']}, kapitan {wpis['captain']}, "
                    f"prognoza {wpis['predicted_total']} pkt, realnie "
                    f"{wpis['actual_total']} pkt (źródło: {zrodlo_wpisu})"
                )
            else:
                print(
                    f"  ℹ️  Best11: za mało prognoz, aby ustawić skład "
                    f"dla kolejki {round_number} — pomijam"
                )
        else:
            print(
                f"  ℹ️  Best11: brak kompletnych prognoz dla kolejki "
                f"{round_number} — pomijam"
            )

    # --- 2) Starsze kolejki z accuracy history (idempotentnie) ---
    istniejace = {e.get("round") for e in history if isinstance(e, dict)}
    for entry in accuracy_history or []:
        if not isinstance(entry, dict):
            continue
        r = entry.get("round")
        if not r or r == round_number or r in istniejace:
            continue
        if not czy_kolejka_jest_kompletna(r, fixtures_data, terminarz_path):
            continue
        prognozy = _prognozy_z_wpisu(entry)
        if not prognozy:
            # Przycięte details (tylko player_id + actual) — pomijamy.
            continue
        if not entry.get("details"):
            # Bez details nie mamy realnych punktów — pomijamy.
            continue
        details_count = len(entry.get("details") or [])
        expected_count = expected_forecast_count or len(prognozy)
        zrodlo_wpisu = "przyblizone"
        info = (
            f"details: {details_count}; prognoza porównawcza: "
            f"{expected_count}; różnica: {expected_count - details_count}"
        )
        if zrodlo_wpisu == "przyblizone":
            saved_forecasts = len(entry.get("predictions") or [])
            if saved_forecasts:
                info += (
                    f"; prognozy tej kolejki: {saved_forecasts}; "
                    f"brakujące details względem nich: "
                    f"{max(saved_forecasts - details_count, 0)}"
                )
        wpis = zbuduj_wpis_historii(
            r,
            prognozy,
            _actual_z_details(entry),
            najlepszy_cmf(league_history, r, league_teams_detail),
            zrodlo=zrodlo_wpisu,
            zrodlo_info=info,
        )
        if wpis:
            history.append(wpis)
            istniejace.add(r)
            zmieniono = True
            print(
                f"  🏆 Best11: dodano historyczną kolejkę {r} — "
                f"formacja {wpis['formation']}, realnie "
                f"{wpis['actual_total']} pkt"
            )

    if zmieniono:
        history.sort(key=lambda e: e.get("round", 0) if isinstance(e, dict) else 0)
        zapisz_best11_history(history, history_path)
    return history


def zapisz_nastepny_sklad(
    predictions_data,
    round_number,
    path=BEST11_NEXT_FILE,
    picks_path=BEST11_PICKS_FILE,
):
    """Zapisuje output/best11_next.json — proponowany skład na następną
    kolejkę z aktualnych prognoz predictora.

    Zwraca payload (słownik) albo None, gdy prognoz brak lub składu
    nie da się ustawić.
    """
    if not predictions_data or not round_number:
        print("  ℹ️  Best11: brak prognoz na następną kolejkę — pomijam")
        # Pusta wartość zapobiega pokazaniu starego składu z poprzedniego runu.
        _zapisz_json_atomowo(None, path)
        return None
    payload = zbuduj_nastepny_sklad(round_number, predictions_data)
    if payload is None:
        print("  ℹ️  Best11: za mało prognoz, aby ustawić skład na następną kolejkę")
        # Pusta wartość zapobiega pokazaniu starego składu z poprzedniego runu.
        _zapisz_json_atomowo(None, path)
        return None
    _zapisz_json_atomowo(payload, path)

    # Zapisujemy tylko pick bieżącej prognozy, a pozostałe kolejki zostają.
    picks = wczytaj_best11_picks(picks_path)
    picks[str(round_number)] = {
        **payload,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    # Zachowujemy dziesięć najnowszych numerów kolejek.
    uporzadkowane = sorted(
        picks.items(), key=lambda item: _numer_kolejki(item[0]), reverse=True
    )[:10]
    zapisz_best11_picks(dict(uporzadkowane), picks_path)
    print(
        f"  🏆 Best11: skład na kolejkę {round_number} — formacja "
        f"{payload['formation']}, kapitan {payload['captain']}, "
        f"prognoza {payload['predicted_total']} pkt → {os.path.basename(path)}"
    )
    return payload


def _numer_kolejki(key):
    """Pozwala bezpiecznie sortować klucze kolejki zapisane w JSON."""
    try:
        return int(key)
    except (TypeError, ValueError):
        return -1


def _zapisz_json_atomowo(data, path):
    """Zapisuje JSON do pliku tymczasowego i dopiero potem podmienia plik."""
    parent_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent_dir, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
