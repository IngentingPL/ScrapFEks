"""
predictor.py — Moduł prognozowania punktów Fantasy Ekstraklasa
==============================================================

📖 LEKCJA PROGRAMOWANIA:
Ten plik to "moduł" — samodzielny kawałek kodu, który robi jedną rzecz dobrze.
W Pythonie każdy plik .py to moduł, który inny plik może "zaimportować" i używać.
Np. w scraper.py napiszesz: from predictor import predict_points

Kluczowe koncepty użyte tutaj:
1. SŁOWNIKI (dict) — struktura klucz:wartość, np. {"Lech": 1.2, "Legia": 0.8}
2. LISTY (list) — uporządkowana kolekcja, np. [5, 8, 3, 10]
3. PĘTLA FOR — powtarza operację dla każdego elementu
4. FUNKCJA (def) — nazwany blok kodu, który przyjmuje dane i zwraca wynik
"""

import json
import os
from statistics import stdev

# ============================================================
# WCZYTYWANIE WYTUNOWANYCH PARAMETRÓW (auto-tuning)
# ============================================================
# 📖 LEKCJA: Wczytujemy parametry RAZ przy starcie modułu — to szybsze niż
# czytanie pliku za każdym razem, gdy wywołujemy predict_points.
# Jeśli plik nie istnieje — używamy wartości domyślnych (identyczne działanie).

def _load_tuned_params():
    """
    Wczytuje wytunowane parametry z pliku output/tuned_params.json.

    Jeśli plik nie istnieje lub jest uszkodzony — zwraca None.
    Wówczas predictor używa wbudowanych wartości domyślnych.
    """
    path = os.path.join("output", "tuned_params.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


# Wczytaj parametry raz przy imporcie modułu
_TUNED = _load_tuned_params()

# Parametry do użycia (wytunowane jeśli dostępne, w przeciwnym razie domyślne)
# decay=0.85: współczynnik zaniku dla średniej ważonej
# fdr_strength=1.0: siła wpływu FDR (mnożnik efektu)
# home_away_bonus=0.05: bonus za grę u siebie (home_factor = 1.0 + bonus)
_DEFAULT_DECAY = _TUNED.get("decay", 0.85) if _TUNED else 0.85
_DEFAULT_FDR_STRENGTH = _TUNED.get("fdr_strength", 1.0) if _TUNED else 1.0
_DEFAULT_HOME_AWAY_BONUS = _TUNED.get("home_away_bonus", 0.05) if _TUNED else 0.05

# Nowe parametry modyfikatorów (wytunowane jeśli dostępne, w przeciwnym razie domyślne)
_DEFAULT_TREND_THRESHOLD = _TUNED.get("trend_threshold", 2.0) if _TUNED else 2.0
_DEFAULT_TREND_BONUS = _TUNED.get("trend_bonus", 0.05) if _TUNED else 0.05
_DEFAULT_STABILITY_BONUS = _TUNED.get("stability_bonus", 0.03) if _TUNED else 0.03
_DEFAULT_STABILITY_PENALTY = _TUNED.get("stability_penalty", 0.03) if _TUNED else 0.03
_DEFAULT_OPPONENT_FORM_BONUS = _TUNED.get("opponent_form_bonus", 0.05) if _TUNED else 0.05
_DEFAULT_LOOKBACK_THRESHOLD_HIGH = _TUNED.get("lookback_threshold_high", 10) if _TUNED else 10
_DEFAULT_LOOKBACK_MAX = _TUNED.get("lookback_max", 7) if _TUNED else 7

if _TUNED:
    print(
        f"  🔧 Predictor: wczytano wytunowane parametry "
        f"(decay={_DEFAULT_DECAY}, fdr_strength={_DEFAULT_FDR_STRENGTH}, "
        f"home_away_bonus={_DEFAULT_HOME_AWAY_BONUS})"
    )

# ============================================================
# STAŁE — wartości, które nie zmieniają się w trakcie działania
# ============================================================

# Mapowanie pozycji fantasy → jakie FDR ich dotyczą
# NAP/POM atakują → interesuje nas słabość DEFENSYWY rywala
# BR/OBR bronią → interesuje nas siła OFENSYWY rywala
# POM jest pośrodku → oba wskaźniki mają znaczenie (ale DEF rywala ważniejsza)
POSITION_FDR_WEIGHTS = {
    "NAP": {"def_weight": 1.0, "atk_weight": 0.0},   # Napastnik: 100% FDR DEF rywala
    "POM": {"def_weight": 0.6, "atk_weight": 0.4},   # Pomocnik: 60% DEF + 40% ATK rywala
    "OBR": {"def_weight": 0.0, "atk_weight": 1.0},   # Obrońca: 100% FDR ATK rywala
    "BR":  {"def_weight": 0.0, "atk_weight": 1.0},   # Bramkarz: 100% FDR ATK rywala
}

# Ile ostatnich kolejek brać pod uwagę w średniej ważonej
DEFAULT_LOOKBACK = 5

# Minimalna liczba rozegranych kolejek, żeby prognoza miała sens
MIN_ROUNDS_FOR_PREDICTION = 2


# ============================================================
# FUNKCJE POMOCNICZE
# ============================================================

def weighted_average(values, decay=None):
    """
    Średnia ważona z malejącymi wagami (nowsze = ważniejsze).

    📖 LEKCJA: "decay" (zanik) to mnożnik wagi.
    Jeśli decay=0.85, to wagi to: 1.0, 0.85, 0.72, 0.61, 0.52...
    Ostatni mecz waży prawie 2x tyle co mecz sprzed 5 kolejek.

    Parametry:
        values: lista punktów z kolejek [najnowsza, ..., najstarsza]
        decay: współczynnik zaniku (0.0-1.0), mniejszy = nowsze ważniejsze.
               None = użyj wartości z tuned_params.json (lub 0.85 domyślnie).

    Zwraca:
        float — średnia ważona
    """
    if decay is None:
        decay = _DEFAULT_DECAY  # Wytunowany lub domyślny (0.85)

    if not values:
        return 0.0

    total_weight = 0.0
    total_value = 0.0

    for i, val in enumerate(values):
        # 📖 decay ** i oznacza "decay do potęgi i"
        # i=0 → 0.85^0 = 1.0 (najnowszy mecz, pełna waga)
        # i=1 → 0.85^1 = 0.85
        # i=2 → 0.85^2 = 0.72
        weight = decay ** i
        total_value += val * weight
        total_weight += weight

    return total_value / total_weight if total_weight > 0 else 0.0


def get_fdr_modifier(fdr_atk, fdr_def, position):
    """
    Oblicza modyfikator prognozy na podstawie FDR rywala i pozycji gracza.

    📖 LEKCJA: "Modyfikator" to mnożnik, który przesuwa prognozę w górę lub w dół.
    - Modyfikator > 1.0 = łatwy rywal → prognoza w GÓRĘ
    - Modyfikator < 1.0 = trudny rywal → prognoza w DÓŁ
    - Modyfikator = 1.0 = średni rywal → bez zmian

    FDR jest na skali 1-5, gdzie:
    - 1 = bardzo łatwy rywal
    - 3 = średni
    - 5 = bardzo trudny

    Konwersja FDR → modyfikator:
    FDR 1 → 1.20 (bonus +20%)
    FDR 2 → 1.10 (bonus +10%)
    FDR 3 → 1.00 (neutralny)
    FDR 4 → 0.90 (kara -10%)
    FDR 5 → 0.80 (kara -20%)

    Parametry:
        fdr_atk: FDR ofensywny rywala (1-5) — jak groźny jest rywal w ataku
        fdr_def: FDR defensywny rywala (1-5) — jak solidna jest obrona rywala
        position: pozycja gracza ("BR", "OBR", "POM", "NAP")

    Zwraca:
        float — modyfikator (np. 1.15 = prognoza +15%)
    """
    weights = POSITION_FDR_WEIGHTS.get(position, {"def_weight": 0.5, "atk_weight": 0.5})

    # 📖 LEKCJA: Dla napastnika (NAP) chcemy wiedzieć, czy OBRONA rywala jest słaba.
    # Słaba obrona rywala (wysokie FDR DEF z perspektywy ich słabości) = łatwiej strzelić gola.
    # Ale uwaga! FDR DEF rywala mówi nam jak TRUDNO jest im bronić.
    # Wysokie FDR DEF rywala = silna obrona = TRUDNIEJ strzelić.
    # Dlatego ODWRACAMY skalę: FDR 5 → 0.80 (trudno), FDR 1 → 1.20 (łatwo)

    # Konwersja: FDR → modyfikator (skala odwrócona)
    # FDR 1→1.20, 2→1.10, 3→1.00, 4→0.90, 5→0.80 (przy domyślnym fdr_strength=1.0)
    # fdr_strength kontroluje jak mocno FDR wpływa na prognozę:
    #   fdr_strength=0.5 → efekt o połowę słabszy
    #   fdr_strength=1.5 → efekt o połowę silniejszy
    _fdr_coeff = 0.10 * _DEFAULT_FDR_STRENGTH

    def fdr_to_modifier(fdr_value):
        return 1.0 + (3 - fdr_value) * _fdr_coeff

    # Dla napastnika/pomocnika: interesuje nas FDR DEF rywala (im słabsza obrona, tym lepiej)
    mod_from_def = fdr_to_modifier(fdr_def)

    # Dla bramkarza/obrońcy: interesuje nas FDR ATK rywala (im słabszy atak, tym lepiej)
    # UWAGA: tu odwrotna logika — słaby atak rywala to DOBRZE dla obrońcy
    mod_from_atk = fdr_to_modifier(fdr_atk)

    # Ważona kombinacja obu modyfikatorów
    modifier = (weights["def_weight"] * mod_from_def) + (weights["atk_weight"] * mod_from_atk)

    return modifier


def get_minutes_factor(avg_minutes):
    """
    Modyfikator bazujący na średniej liczbie minut na boisku.

    📖 LEKCJA: Gracz, który gra regularnie 90 minut, ma większe szanse
    na punkty niż ten wchodzący na 15 minut. Ten modyfikator to odzwierciedla.

    Parametry:
        avg_minutes: średnia minut z ostatnich N kolejek

    Zwraca:
        float — modyfikator (0.0-1.0)
    """
    if avg_minutes >= 80:
        return 1.0       # Pełny etatowiec
    elif avg_minutes >= 60:
        return 0.90       # Gra większość meczu
    elif avg_minutes >= 30:
        return 0.70       # Zmiennik / wchodzi z ławki
    elif avg_minutes > 0:
        return 0.40       # Epizodyczny
    else:
        return 0.0        # Nie gra


def get_home_away_factor(is_home):
    """
    Drobny bonus za grę u siebie.

    📖 LEKCJA: W piłce nożnej drużyna gospodarzy wygrywa statystycznie częściej.
    W Ekstraklasie różnica jest ~5-8% więcej punktów w domu.

    Parametry:
        is_home: True jeśli mecz u siebie, False jeśli wyjazd

    Zwraca:
        float — modyfikator (domyślnie: 1.05 dom, 0.97 wyjazd)

    Parametryzacja:
        home_away_bonus (z tuned_params lub domyślny 0.05):
          home_factor = 1.0 + home_away_bonus
          away_factor = 1.0 - home_away_bonus * 0.6
        Przy home_away_bonus=0.05: home=1.05, away=0.97 (domyślne)
    """
    bonus = _DEFAULT_HOME_AWAY_BONUS
    if is_home:
        return 1.0 + bonus
    else:
        return 1.0 - bonus * 0.6


# ============================================================
# NOWE MODYFIKATORY (trend, stabilność, clean sheet, forma rywala, kartki, lookback)
# ============================================================

def get_trend_modifier(recent_points):
    """
    Wykrywa czy gracz jest w trendzie ROSNĄCYM czy SPADKOWYM.

    📖 LEKCJA: "Trend" to kierunek zmian w czasie.
    Zamiast patrzeć na średnią (która mówi "ile zwykle"), patrzymy
    na ZMIANĘ — czy jest lepiej czy gorzej niż było.
    To jak w szkole: średnia 4.0 nie mówi, czy uczeń się poprawia
    czy pogarsza. Trend tak.

    Logika:
    - Punkty są posortowane od najnowszej do najstarszej
    - Odwracamy kolejność (od najstarszej do najnowszej) żeby policzyć trend
    - Średnia z 2 najnowszych MINUS średnia z 2 najstarszych = kierunek zmiany
    - Różnica > threshold → trend rosnący → bonus
    - Różnica < -threshold → trend spadkowy → kara

    Parametry:
        recent_points: lista punktów [najnowsza, ..., najstarsza]

    Zwraca:
        float — modyfikator (np. 1.05 = bonus za trend rosnący)
    """
    if len(recent_points) < 4:
        return 1.0

    # Odwróć: od najstarszej do najnowszej
    chronological = list(reversed(recent_points))

    # Średnia z 2 najstarszych vs 2 najnowszych
    old_avg = (chronological[0] + chronological[1]) / 2
    new_avg = (chronological[-1] + chronological[-2]) / 2
    diff = new_avg - old_avg

    threshold = _DEFAULT_TREND_THRESHOLD
    bonus = _DEFAULT_TREND_BONUS

    if diff > threshold:
        return 1.0 + bonus   # Trend rosnący
    elif diff < -threshold:
        return 1.0 - bonus   # Trend spadkowy
    else:
        return 1.0            # Neutralny


def get_stability_modifier(recent_points):
    """
    Ocenia stabilność gracza na podstawie zmienności jego punktów.

    📖 LEKCJA: "Odchylenie standardowe" (std) mierzy jak bardzo
    wartości odbiegają od średniej. Małe std = wartości blisko średniej.
    "Współczynnik zmienności" (CV) to std/średnia — pozwala porównywać
    zmienność graczy z różnymi średnimi (gracz z śr. 2 i std 1
    jest bardziej niestabilny niż gracz z śr. 10 i std 1).

    Gracz z punktami [5,5,5,5,5] jest bardziej przewidywalny niż [1,1,1,1,15].
    Stabilny gracz → pewniejsza prognoza → drobny bonus.
    Niestabilny gracz → prognoza mniej wiarygodna → drobna kara.

    Parametry:
        recent_points: lista punktów z ostatnich kolejek

    Zwraca:
        float — modyfikator (1.03 = stabilny, 0.97 = niestabilny, 1.0 = pomiędzy)
    """
    if len(recent_points) < 2:
        return 1.0

    avg = sum(recent_points) / len(recent_points)
    if avg <= 0:
        return 1.0

    # Oblicz odchylenie standardowe (moduł statistics)
    try:
        std = stdev(recent_points)
    except Exception:
        return 1.0

    # Współczynnik zmienności = std / średnia
    cv = std / avg

    if cv < 0.3:
        return 1.0 + _DEFAULT_STABILITY_BONUS    # Stabilny → bonus
    elif cv > 0.8:
        return 1.0 - _DEFAULT_STABILITY_PENALTY   # Niestabilny → kara
    else:
        return 1.0


def get_clean_sheet_modifier(player, fdr_atk_opponent):
    """
    Bonus clean sheet dla obrońców i bramkarzy.

    📖 LEKCJA: "Clean sheet" to mecz bez straty gola.
    W fantasy piłce obrońcy i bramkarze dostają za to bonus punktowy.
    Im więcej clean sheetów drużyna ma, tym bardziej prawdopodobne,
    że następny mecz też będzie bez straty gola — szczególnie
    przeciwko słabemu rywalowi.

    Dane o clean sheetach NIE SĄ dostępne w projekcie (brak pola clean_sheet
    ani goals_conceded w danych kolejek). Używamy FDR ATK rywala jako proxy:
    jeśli rywal ma słaby atak → większa szansa na clean sheet.

    Stosowany TYLKO dla pozycji OBR i BR.

    Parametry:
        player: dict z danymi gracza (musi zawierać "position")
        fdr_atk_opponent: FDR ofensywny rywala (1-5)

    Zwraca:
        float — modyfikator (np. 1.05 = bonus za słaby atak rywala)
    """
    position = player.get("position", "POM")

    # Stosuj TYLKO dla obrońców i bramkarzy
    if position not in ("OBR", "BR"):
        return 1.0

    # TODO: dodać scraping clean sheetów dla lepszej dokładności
    # Brak danych o clean sheetach — używamy FDR ATK rywala jako proxy
    if fdr_atk_opponent <= 2:
        return 1.05  # Rywal ze słabym atakiem → bonus CS
    elif fdr_atk_opponent >= 4:
        return 0.97  # Rywal z silnym atakiem → mniejsza szansa na CS
    else:
        return 1.0


def get_opponent_form_modifier(opponent_team, team_form_data):
    """
    Modyfikator bazujący na aktualnej formie rywala z ostatnich meczów.

    📖 LEKCJA: Statyczne FDR mówi "Raków jest ogólnie silny".
    Ale co jeśli Raków przegrał 4 z 5 ostatnich meczów? Forma rywala
    zmienia się w sezonie. Ten modyfikator łapie te zmiany —
    to jak sprawdzanie "aktualnej pogody" zamiast "średniej rocznej".

    Parametry:
        opponent_team: nazwa drużyny rywala
        team_form_data: dict z danymi o formie drużyn (None jeśli brak)

    Zwraca:
        float — modyfikator (1.05 = rywal w dołku, 0.95 = rywal w formie)
    """
    # TODO: dodać scraping formy drużyn dla dynamicznego FDR
    # Brak danych o formie drużyn w projekcie — pomijamy modyfikator
    if not team_form_data:
        return 1.0

    form = team_form_data.get(opponent_team)
    if not form:
        return 1.0

    # Oblicz win rate z ostatnich 5 meczów
    recent = form.get("recent_results", [])[:5]
    if not recent:
        return 1.0

    wins = sum(1 for r in recent if r == "W")
    win_rate = wins / len(recent)

    bonus = _DEFAULT_OPPONENT_FORM_BONUS

    if win_rate > 0.6:
        return 1.0 - bonus   # Rywal w formie → kara
    elif win_rate < 0.3:
        return 1.0 + bonus   # Rywal w dołku → bonus
    else:
        return 1.0


def get_dynamic_lookback(played_rounds_count):
    """
    Oblicza dynamiczny lookback na podstawie liczby rozegranych kolejek.

    📖 LEKCJA: Im więcej danych mamy, tym lepiej możemy prognozować.
    Ale za dużo starych danych "rozmywa" aktualną formę.
    Dynamiczny lookback to kompromis: więcej danych = patrzymy trochę dalej,
    ale wagi decay i tak faworyzują nowsze mecze.

    Logika:
    - ≥ 10 kolejek → lookback = 7 (więcej danych = stabilniejsza średnia)
    - 5-9 kolejek → lookback = 5 (domyślnie)
    - 2-4 kolejki → lookback = ilość dostępnych kolejek

    Parametry:
        played_rounds_count: ile kolejek gracz rozegrał

    Zwraca:
        int — lookback (ile kolejek brać pod uwagę)
    """
    threshold_high = _DEFAULT_LOOKBACK_THRESHOLD_HIGH
    lookback_max = _DEFAULT_LOOKBACK_MAX

    if played_rounds_count >= threshold_high:
        return lookback_max
    elif played_rounds_count >= 5:
        return DEFAULT_LOOKBACK  # 5
    else:
        return played_rounds_count  # 2-4: tyle ile mamy


def get_card_risk_modifier(recent_rounds):
    """
    Kara za ryzyko związane z kartkami (żółte i czerwone).

    📖 LEKCJA: W piłce po kumulacji żółtych kartek gracz dostaje
    automatyczną pauzę. Gracz, który często dostaje kartki, to ryzyko —
    może nie zagrać w następnym meczu. To jak sprawdzanie "historii
    mandatów" przed pożyczeniem komuś samochodu.

    Dane o kartkach SĄ dostępne w projekcie (pola yellow_cards i red_cards
    w danych kolejek).

    Logika:
    - Czerwona w ostatnim meczu → ×0.0 (pauzuje — nie gra!)
    - ≥ 3 żółte w 5 meczach → ×0.92 (ryzyko pauzy + agresywna gra)
    - 2 żółte w 5 meczach → ×0.96
    - Inaczej → ×1.0

    Parametry:
        recent_rounds: lista dict z danymi kolejek (z polami yellow_cards, red_cards)

    Zwraca:
        float — modyfikator (0.0 = pauzuje, 0.92 = duże ryzyko, 1.0 = OK)
    """
    if not recent_rounds:
        return 1.0

    # Sprawdź czerwoną kartkę w ostatnim meczu (recent_rounds[0] = najnowszy)
    last_round = recent_rounds[0]
    if last_round.get("red_cards", 0) > 0:
        return 0.0  # Czerwona → pauzuje

    # Policz żółte kartki z ostatnich 5 meczów
    last_5 = recent_rounds[:5]
    yellow_count = sum(r.get("yellow_cards", 0) for r in last_5)

    if yellow_count >= 3:
        return 0.92  # Duże ryzyko pauzy
    elif yellow_count >= 2:
        return 0.96  # Umiarkowane ryzyko
    else:
        return 1.0


# ============================================================
# MODYFIKATOR ROZSZERZONYCH STATYSTYK (xG, strzały, podania, dośrodkowania)
# ============================================================

# ============================================================
# GŁÓWNA FUNKCJA PREDYKCJI
# ============================================================

def predict_points(player, fdr_data, next_fixture, lookback=DEFAULT_LOOKBACK, decay=None):
    """
    Prognozuje punkty zawodnika na następną kolejkę.

    📖 LEKCJA: To jest "pipeline" (rurociąg) — dane przechodzą przez kilka kroków:
    1. Zbierz historyczne punkty → 2. Policz średnią ważoną →
    3. Zastosuj modyfikator FDR → 4. Zastosuj modyfikator minut →
    5. Zastosuj modyfikator dom/wyjazd → 6. Zwróć wynik

    Parametry:
        player: dict z danymi gracza (z fantasy_full JSON)
            Musi zawierać: "position", "rounds" (lista kolejek z "points", "minutes", "played")
        fdr_data: dict z FDR drużyn
            Format: {"Lech": {"atk": 4, "def": 2}, "Legia": {"atk": 5, "def": 4}, ...}
        next_fixture: dict z informacją o następnym meczu
            Format: {"opponent": "Legia", "is_home": True}
        lookback: ile ostatnich kolejek brać pod uwagę
        decay: współczynnik zaniku dla średniej ważonej.
               None = użyj wartości z tuned_params.json (lub 0.85 domyślnie).

    Zwraca:
        dict z prognozą:
        {
            "predicted_points": 6.2,
            "base_avg": 5.5,
            "fdr_modifier": 1.10,
            "minutes_factor": 1.0,
            "home_away_factor": 1.05,
            "confidence": "medium",
            "detail": "Średnia 5.5 × FDR 1.10 × min 1.00 × dom 1.05 = 6.2"
        }
    """
    position = player.get("position", "POM")
    rounds = player.get("rounds", [])

    # --- Krok 1: Zbierz WSZYSTKIE kolejki (włącznie z niegranymi, gdzie punkty = 0) ---
    # Poprawka: ta sama logika co w zakładce "Zawodnicy" - uwzględniamy wszystkie kolejki,
    # a dla niegranych meczy wstawiamy 0 punktów. Jest to średnia za ostatnie 5 kolejek
    # liczona ze WSZYSTKICH meczów (tzn. mecze gdzie zawodnik nie grał liczą się jako 0).

    # Sortuj wszystkie kolejki od najnowszej
    all_rounds = sorted(rounds, key=lambda r: r.get("round", 0), reverse=True)

    # Weź ostatnie 5 kolejek (lub mniej jeśli mniej dostępnych)
    last_5_rounds = all_rounds[:5]

    if len(last_5_rounds) < MIN_ROUNDS_FOR_PREDICTION:
        return {
            "predicted_points": None,
            "confidence": "insufficient_data",
            "detail": f"Za mało danych ({len(last_5_rounds)}/{MIN_ROUNDS_FOR_PREDICTION} kolejek)"
        }

    # Dla każdej kolejki: jeśli gracz zagrał - użyj punktów, jeśli nie - użyj 0
    recent_rounds = last_5_rounds
    recent_points = [r.get("points", 0) if r.get("played") else 0 for r in recent_rounds]

    # --- Krok 2: Średnia ważona punktów ---
    base_avg = weighted_average(recent_points, decay=decay)
    
    # Jeśli base_avg = 0 ale gracz w ogóle zagrał w sezonie, użyj minimalnej wartości
    # sprawdzamy WSZYSTKIE kolejki, nie tylko last 5
    total_played = len([r for r in rounds if r.get("played")])
    if base_avg == 0 and total_played > 0:
        base_avg = 0.5  # minimalna wartość bazowa dla aktywnych graczy

    # --- Krok 3: Modyfikator FDR ---
    opponent = next_fixture.get("opponent", "")
    opponent_fdr = fdr_data.get(opponent, {"atk": 3, "def": 3})  # domyślnie średni
    fdr_mod = get_fdr_modifier(
        fdr_atk=opponent_fdr["atk"],
        fdr_def=opponent_fdr["def"],
        position=position
    )

    # --- Krok 4: Modyfikator minut ---
    # Licz średnie minuty tylko z rozegranych meczów (tak jak wcześniej)
    played_recent = [r for r in recent_rounds if r.get("played")]
    if played_recent:
        recent_minutes = [r.get("minutes", 0) for r in played_recent]
        avg_minutes = sum(recent_minutes) / len(recent_minutes) if recent_minutes else 0
    else:
        avg_minutes = 0
    
    # Jeśli avg_minutes = 0 (nie grał w ostatnich 5), użyj średniej sezonowej
    if avg_minutes == 0 and total_played > 0:
        # Oblicz średnią sezonową
        season_minutes = [r.get("minutes", 0) for r in rounds if r.get("played")]
        if season_minutes:
            avg_minutes = sum(season_minutes) / len(season_minutes)
    
    min_factor = get_minutes_factor(avg_minutes)

    # --- Krok 5: Modyfikator dom/wyjazd ---
    is_home = next_fixture.get("is_home", False)
    ha_factor = get_home_away_factor(is_home)

    # --- Krok 6: Końcowa prognoza (istniejący pipeline) ---
    predicted = base_avg * fdr_mod * min_factor * ha_factor

    # --- Krok 7: Nowe modyfikatory ---
    trend_mod = get_trend_modifier(recent_points)
    stability_mod = get_stability_modifier(recent_points)
    cs_mod = get_clean_sheet_modifier(player, opponent_fdr["atk"])
    opp_form_mod = get_opponent_form_modifier(opponent, None)  # Brak danych o formie drużyn
    card_mod = get_card_risk_modifier(recent_rounds)

    predicted = predicted * trend_mod * stability_mod * cs_mod * opp_form_mod * card_mod

    # Zaokrąglij do 1 miejsca po przecinku
    predicted = round(predicted, 1)

    # Pewność prognozy
    if len(recent_rounds) >= 4:
        confidence = "high"
    elif len(recent_rounds) >= MIN_ROUNDS_FOR_PREDICTION:
        confidence = "medium"
    else:
        confidence = "low"

    # Buduj detail string — pokazuj tylko modyfikatory ≠ 1.0 żeby nie zaśmiecać
    detail_parts = [
        f"Śr. {round(base_avg, 1)}",
        f"× FDR {round(fdr_mod, 2)}",
        f"× min {round(min_factor, 2)}",
        f"× {'dom' if is_home else 'wyjazd'} {round(ha_factor, 2)}",
    ]
    if trend_mod != 1.0:
        detail_parts.append(f"× trend {round(trend_mod, 2)}")
    if stability_mod != 1.0:
        detail_parts.append(f"× stab {round(stability_mod, 2)}")
    if cs_mod != 1.0:
        detail_parts.append(f"× CS {round(cs_mod, 2)}")
    if opp_form_mod != 1.0:
        detail_parts.append(f"× forma_ryw {round(opp_form_mod, 2)}")
    if card_mod != 1.0:
        detail_parts.append(f"× kartki {round(card_mod, 2)}")
    detail_parts.append(f"= {predicted}")

    return {
        "predicted_points": predicted,
        "base_avg": round(base_avg, 1),
        "fdr_modifier": round(fdr_mod, 2),
        "fdr_atk_opponent": opponent_fdr["atk"],
        "fdr_def_opponent": opponent_fdr["def"],
        "minutes_factor": round(min_factor, 2),
        "home_away_factor": round(ha_factor, 2),
        "trend_modifier": round(trend_mod, 2),
        "stability_modifier": round(stability_mod, 2),
        "cs_modifier": round(cs_mod, 2),
        "opponent_form_modifier": round(opp_form_mod, 2),
        "card_risk_modifier": round(card_mod, 2),
        "avg_minutes": round(avg_minutes, 0),
        "rounds_used": len(recent_rounds),
        "confidence": confidence,
        "detail": " ".join(detail_parts),
    }


def predict_all_players(players, fdr_data, fixtures, lookback=DEFAULT_LOOKBACK):
    """
    Prognozuje punkty dla WSZYSTKICH zawodników.

    📖 LEKCJA: Ta funkcja to "wrapper" — opakowuje główną funkcję predict_points
    i wywołuje ją w pętli dla każdego gracza. To częsty wzorzec w programowaniu:
    masz jedną funkcję dla jednego elementu, i drugą, która ją stosuje do wielu.

    Parametry:
        players: lista graczy z fantasy_full JSON (mogą zawierać pola xg_per90, shots_on_target_per90, itp.)
        fdr_data: dict z FDR drużyn {"Lech": {"atk": 4, "def": 2}, ...}
        fixtures: dict z następnymi meczami {"Lech": {"opponent": "Legia", "is_home": True}, ...}
        lookback: ile ostatnich kolejek brać pod uwagę (domyślnie 5)

    Zwraca:
        lista dictów z prognozami (posortowana od najwyższej prognozy)
    """
    predictions = []

    for player in players:
        team = player.get("team", "")
        next_fix = fixtures.get(team)

        if not next_fix:
            continue  # Brak info o następnym meczu → pomijamy

        pred = predict_points(player, fdr_data, next_fix, lookback=lookback)

        predictions.append({
            "player_id": player.get("player_id"),
            "name": player.get("name", ""),
            "team": team,
            "position": player.get("position", ""),
            "price": player.get("price", 0),
            "total_points": player.get("total_points", 0),
            "popularity_pct": player.get("popularity_pct", ""),
            "next_opponent": next_fix.get("opponent", ""),
            "is_home": next_fix.get("is_home", False),
            **pred,  # 📖 ** "rozpakuje" dict — dodaje wszystkie klucze z pred do tego dicta
        })

    # Sortuj od najwyższej prognozy
    predictions.sort(key=lambda x: x.get("predicted_points") or 0, reverse=True)

    return predictions


# ============================================================
# PRZYKŁAD UŻYCIA (do testowania)
# ============================================================

if __name__ == "__main__":
    """
    📖 LEKCJA: Blok "if __name__ == '__main__'" uruchamia się TYLKO gdy
    odpalasz plik bezpośrednio (python predictor.py), ale NIE gdy go importujesz.
    Idealne do testowania modułu.
    """

    # Przykładowy gracz — napastnik z 5 kolejkami
    test_player = {
        "player_id": 123,
        "name": "Testowy Napastnik",
        "team": "Lech",
        "position": "NAP",
        "total_points": 45,
        "rounds": [
            {"round": 20, "played": True, "points": 10, "minutes": 90, "yellow_cards": 1, "red_cards": 0},
            {"round": 19, "played": True, "points": 3, "minutes": 90, "yellow_cards": 0, "red_cards": 0},
            {"round": 18, "played": True, "points": 5, "minutes": 78, "yellow_cards": 1, "red_cards": 0},
            {"round": 17, "played": True, "points": 8, "minutes": 90, "yellow_cards": 0, "red_cards": 0},
            {"round": 16, "played": True, "points": 2, "minutes": 85, "yellow_cards": 1, "red_cards": 0},
        ]
    }

    # Przykładowe FDR drużyn
    test_fdr = {
        "Raków":  {"atk": 4, "def": 4},   # Silny rywal — trudna obrona i atak
        "GKS":    {"atk": 2, "def": 1},   # Słaby rywal — łatwa obrona i atak
        "Legia":  {"atk": 5, "def": 3},   # Silny atak, średnia obrona
    }

    # Test 1: Napastnik vs słaba obrona (GKS)
    print("=== Test 1: NAP vs GKS (słaba obrona, dom) ===")
    result = predict_points(test_player, test_fdr, {"opponent": "GKS", "is_home": True})
    print(f"  Prognoza: {result['predicted_points']} pkt")
    print(f"  Szczegóły: {result['detail']}")
    print(f"  Nowe modyfikatory: trend={result['trend_modifier']}, stab={result['stability_modifier']}, "
          f"CS={result['cs_modifier']}, forma_ryw={result['opponent_form_modifier']}, "
          f"kartki={result['card_risk_modifier']}, lookback={result['dynamic_lookback']}")
    print()

    # Test 2: Napastnik vs silna obrona (Raków)
    print("=== Test 2: NAP vs Raków (silna obrona, wyjazd) ===")
    result = predict_points(test_player, test_fdr, {"opponent": "Raków", "is_home": False})
    print(f"  Prognoza: {result['predicted_points']} pkt")
    print(f"  Szczegóły: {result['detail']}")
    print()

    # Test 3: Ten sam gracz jako obrońca vs Legia (silny atak)
    test_defender = {**test_player, "position": "OBR", "name": "Testowy Obrońca"}
    print("=== Test 3: OBR vs Legia (silny atak, dom) ===")
    result = predict_points(test_defender, test_fdr, {"opponent": "Legia", "is_home": True})
    print(f"  Prognoza: {result['predicted_points']} pkt")
    print(f"  Szczegóły: {result['detail']}")
    print()

    # ============================================================
    # TESTY NOWYCH MODYFIKATORÓW
    # ============================================================

    print("=" * 60)
    print("TESTY NOWYCH MODYFIKATORÓW")
    print("=" * 60)

    # --- Test trend_modifier ---
    print("\n--- Test: get_trend_modifier ---")
    # Trend rosnący: stare [2, 3] → nowe [8, 10] → diff = 9 - 2.5 = 6.5 > 2.0
    rising = [10, 8, 3, 2]  # najnowsza do najstarszej
    print(f"  Rosnący {rising}: {get_trend_modifier(rising)}")  # Oczekiwane: 1.05

    # Trend spadkowy: stare [8, 10] → nowe [2, 3] → diff = 2.5 - 9 = -6.5 < -2.0
    falling = [2, 3, 8, 10]
    print(f"  Spadkowy {falling}: {get_trend_modifier(falling)}")  # Oczekiwane: 0.95

    # Neutralny: [5, 5, 5, 5]
    neutral = [5, 5, 5, 5]
    print(f"  Neutralny {neutral}: {get_trend_modifier(neutral)}")  # Oczekiwane: 1.0

    # Za mało danych: [5, 5, 5]
    short = [5, 5, 5]
    print(f"  Za mało danych {short}: {get_trend_modifier(short)}")  # Oczekiwane: 1.0

    # --- Test stability_modifier ---
    print("\n--- Test: get_stability_modifier ---")
    stable = [5, 5, 5, 5, 5]
    print(f"  Stabilny {stable}: {get_stability_modifier(stable)}")  # Oczekiwane: 1.03

    unstable = [1, 1, 1, 1, 15]
    print(f"  Niestabilny {unstable}: {get_stability_modifier(unstable)}")  # Oczekiwane: 0.97

    medium_var = [3, 5, 7, 4, 6]
    print(f"  Średni {medium_var}: {get_stability_modifier(medium_var)}")  # Oczekiwane: 1.0

    # --- Test clean_sheet_modifier ---
    print("\n--- Test: get_clean_sheet_modifier ---")
    defender = {"position": "OBR"}
    keeper = {"position": "BR"}
    forward = {"position": "NAP"}
    print(f"  OBR vs słaby atak (FDR=1): {get_clean_sheet_modifier(defender, 1)}")  # 1.05
    print(f"  BR vs słaby atak (FDR=2): {get_clean_sheet_modifier(keeper, 2)}")    # 1.05
    print(f"  OBR vs silny atak (FDR=4): {get_clean_sheet_modifier(defender, 4)}")  # 0.97
    print(f"  NAP (nie dotyczy): {get_clean_sheet_modifier(forward, 1)}")           # 1.0

    # --- Test opponent_form_modifier ---
    print("\n--- Test: get_opponent_form_modifier ---")
    print(f"  Brak danych (None): {get_opponent_form_modifier('Raków', None)}")  # 1.0

    # --- Test dynamic_lookback ---
    print("\n--- Test: get_dynamic_lookback ---")
    print(f"  12 kolejek: lookback={get_dynamic_lookback(12)}")  # 7
    print(f"  7 kolejek: lookback={get_dynamic_lookback(7)}")    # 5
    print(f"  3 kolejki: lookback={get_dynamic_lookback(3)}")    # 3

    # --- Test card_risk_modifier ---
    print("\n--- Test: get_card_risk_modifier ---")
    # 3 żółte w 5 meczach
    rounds_3y = [
        {"yellow_cards": 1, "red_cards": 0},
        {"yellow_cards": 0, "red_cards": 0},
        {"yellow_cards": 1, "red_cards": 0},
        {"yellow_cards": 0, "red_cards": 0},
        {"yellow_cards": 1, "red_cards": 0},
    ]
    print(f"  3 żółte/5 meczów: {get_card_risk_modifier(rounds_3y)}")  # 0.92

    # Czerwona w ostatnim meczu
    rounds_red = [
        {"yellow_cards": 0, "red_cards": 1},
        {"yellow_cards": 0, "red_cards": 0},
    ]
    print(f"  Czerwona ostatni mecz: {get_card_risk_modifier(rounds_red)}")  # 0.0

    # Brak kartek
    rounds_clean = [
        {"yellow_cards": 0, "red_cards": 0},
        {"yellow_cards": 0, "red_cards": 0},
    ]
    print(f"  Brak kartek: {get_card_risk_modifier(rounds_clean)}")  # 1.0

    # --- Test integracji: gracz z 12 kolejkami (dynamiczny lookback = 7) ---
    print("\n--- Test: Gracz z 12 kolejkami (lookback dynamiczny) ---")
    big_player = {
        "player_id": 999,
        "name": "Doświadczony Gracz",
        "team": "Lech",
        "position": "POM",
        "total_points": 80,
        "rounds": [
            {"round": i, "played": True, "points": 5 + (i % 3), "minutes": 90,
             "yellow_cards": 0, "red_cards": 0}
            for i in range(1, 13)
        ]
    }
    result = predict_points(big_player, test_fdr, {"opponent": "GKS", "is_home": True})
    print(f"  Prognoza: {result['predicted_points']} pkt (lookback={result['dynamic_lookback']})")
    print(f"  Szczegóły: {result['detail']}")
