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

# środek skali trudności FDR (skala 1-5) - używany jako neutralny fallback
FDR_NEUTRAL = 3


# ============================================================
# FUNKCJE POMOCNICZE
# ============================================================

def weighted_average(values, decay=0.85):
    """
    Średnia ważona z malejącymi wagami (nowsze = ważniejsze).

    📖 LEKCJA: "decay" (zanik) to mnożnik wagi.
    Jeśli decay=0.85, to wagi to: 1.0, 0.85, 0.72, 0.61, 0.52...
    Ostatni mecz waży prawie 2x tyle co mecz sprzed 5 kolejek.

    Parametry:
        values: lista punktów z kolejek [najnowsza, ..., najstarsza]
        decay: współczynnik zaniku (0.0-1.0), mniejszy = nowsze ważniejsze

    Zwraca:
        float — średnia ważona
    """
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


def parse_ownership_pct(pct_str):
    """
    Parsuje string popularności np. '12.3%' na float 12.3.
    Zwraca 100.0 (maksimum) jeśli nie udało się sparsować -
    bezpieczny fallback, żeby gracz nie był przypadkowo wybierany
    jako "differential" przy błędnych danych.
    """
    if not pct_str:
        return 100.0
    try:
        return float(str(pct_str).replace("%", "").strip())
    except (ValueError, TypeError):
        return 100.0


def captain_differential_score(pred):
    """
    Liczy "differential captain score": predicted_points * (1 - ownership% / 100).
    Im niższy ownership przy wysokiej prognozie, tym wyższy wynik -
    nagradza kapitanów, których mało kto wybrał.
    """
    pts = pred.get("predicted_points") or 0.0
    own = parse_ownership_pct(pred.get("popularity_pct", "100%"))
    return pts * (1.0 - own / 100.0)


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
    # FDR 1→1.20, 2→1.10, 3→1.00, 4→0.90, 5→0.80
    def fdr_to_modifier(fdr_value):
        return 1.0 + (FDR_NEUTRAL - fdr_value) * 0.10

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
        float — modyfikator (1.05 dom, 0.97 wyjazd)
    """
    return 1.05 if is_home else 0.97


# ============================================================
# GŁÓWNA FUNKCJA PREDYKCJI
# ============================================================

def predict_points(player, fdr_data, next_fixture, lookback=DEFAULT_LOOKBACK, decay=0.85):
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
        decay: współczynnik zaniku dla średniej ważonej

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

    # --- Krok 0: Sprawdź dostępność zawodnika ---
    # Jeśli zawodnik ma status niedostępności (kontuzja, zawieszenie, "nie zagra"),
    # zwracamy prognozę 0 z flagą unavailable zamiast normalnej predykcji.
    availability = player.get("availability_status")
    if availability:
        return {
            "predicted_points": 0,
            "unavailable": True,
            "availability_reason": availability,
            "confidence": "unavailable",
            "confidence_rank": -1,
            "detail": f"⛔ {availability} — zawodnik niedostępny"
        }

    # --- Krok 1: Zbierz punkty z ostatnich N rozegranych kolejek ---
    # 📖 LEKCJA: "List comprehension" — skrócony zapis pętli, który tworzy nową listę
    # [wyrażenie FOR element IN lista IF warunek]
    played_rounds = [r for r in rounds if r.get("played")]

    # Sortuj od najnowszej kolejki
    played_rounds.sort(key=lambda r: r.get("round", 0), reverse=True)

    # Weź ostatnich N
    recent_rounds = played_rounds[:lookback]
    n_rounds = len(recent_rounds)

    if n_rounds < MIN_ROUNDS_FOR_PREDICTION:
        return {
            "predicted_points": None,
            "confidence": "insufficient_data",
            "confidence_rank": 0,
            "detail": f"Za mało danych ({n_rounds}/{MIN_ROUNDS_FOR_PREDICTION} kolejek)"
        }

    # --- Krok 2: Średnia ważona punktów ---
    recent_points = [r.get("points", 0) for r in recent_rounds]
    base_avg = weighted_average(recent_points, decay=decay)

    # --- Krok 2.5: Modyfikatory xA i xG (expected assists/goals) z conceptuallyfootball ---
    # Zawodnik z wysokim xa_per_90 ma bonus do prognozy (tworzy więcej szans)
    # Mediana xA/90 w Ekstraklasie to ≈0.07 — każde 0.1 powyżej to +1% bonusu
    # Maksymalny bonus: +15%, maksymalna kara: -10%
    xa = player.get("xa_per_90")
    if xa is not None and xa > 0:
        xa_bonus = min(max((xa - 0.07) * 10, -0.10), 0.15)
        base_avg = base_avg * (1 + xa_bonus)

    # Modyfikator xG — ten sam mechanizm co xA
    # Mediana xG/90 w Ekstraklasie to ≈0.10 — każde 0.1 powyżej to +1% bonusu
    # Maksymalny bonus: +15%, maksymalna kara: -10%
    xg = player.get("xg_per_90")
    if xg is not None and xg > 0:
        xg_bonus = min(max((xg - 0.10) * 10, -0.10), 0.15)
        base_avg = base_avg * (1 + xg_bonus)

    # --- Krok 2.6: Modyfikator goals_prevented (tylko dla bramkarzy) ---
    # Bramkarz z wysokim goals_prevented zapobiega większej liczbie goli niż oczekiwano
    # goals_prevented = xG dla strzałów na bramkę minus faktycznie stracone gole
    # Skala: każde 1.0 goals_prevented × 0.15 = +15% bonusu, capped -20%/+20%
    # ⚠️ Startowa skala, nie skalibrowana — do dostrojenia tunerem później,
    # dokładnie jak przy wcześniejszych /3 i ×0.1
    if position == "BR":
        gp = player.get("goals_prevented")
        if gp is not None:
            gp_bonus = min(max(gp * 0.15, -0.20), 0.20)
            base_avg = base_avg * (1 + gp_bonus)

    # --- Krok 3: Modyfikator FDR ---
    opponent = next_fixture.get("opponent", "")
    if opponent and opponent not in fdr_data:
        print(f"[FDR fallback] Brak dopasowania dla '{opponent}', używam FDR_NEUTRAL")
    opponent_fdr = fdr_data.get(opponent, {"atk": FDR_NEUTRAL, "def": FDR_NEUTRAL})  # domyślnie średni
    fdr_mod = get_fdr_modifier(
        fdr_atk=opponent_fdr["atk"],
        fdr_def=opponent_fdr["def"],
        position=position
    )

    # --- Krok 4: Modyfikator minut ---
    recent_minutes = [r.get("minutes", 0) for r in recent_rounds]
    avg_minutes = sum(recent_minutes) / len(recent_minutes) if recent_minutes else 0
    min_factor = get_minutes_factor(avg_minutes)

    # --- Krok 5: Modyfikator dom/wyjazd ---
    is_home = next_fixture.get("is_home", False)
    ha_factor = get_home_away_factor(is_home)

    # --- Krok 6: Końcowa prognoza ---
    predicted = base_avg * fdr_mod * min_factor * ha_factor

    # Zaokrąglij do 1 miejsca po przecinku
    predicted = round(predicted, 1)

    # Pewność prognozy
    if n_rounds >= 4:
        confidence = "high"
    elif n_rounds >= MIN_ROUNDS_FOR_PREDICTION:
        confidence = "medium"
    else:
        confidence = "low"

    # --- Krok 6.5: Dodatkowe wskaźniki do sortowania / analizy ---
    # used_fdr_value — surowa wartość FDR (1-5) faktycznie użyta do prognozy
    # Dla NAP/POM liczy się defensywa rywala, dla OBR/BR — ofensywa rywala
    if position in ("NAP", "POM"):
        used_fdr_value = opponent_fdr["def"]
    else:
        used_fdr_value = opponent_fdr["atk"]

    # potential_value — średnia percentyli Karpińskiego, pozycyjnie znormalizowana
    # Każda pozycja ma własny zestaw składników. Pomijamy None, średnia tylko z dostępnych.
    # Dla OBR: percentile_goals_conceded jest ODWRÓCONY (wysoki percentyl straconych = źle)
    if position == "BR":
        components = [
            player.get("percentile_goals_prevented"),
            player.get("percentile_clean_sheet"),
        ]
    elif position == "OBR":
        pgc = player.get("percentile_goals_conceded")
        components = [
            player.get("percentile_clean_sheet"),
            (100 - pgc) if pgc is not None else None,  # ⚠️ ODWRÓCONE: wysoki percentyl straconych = źle
            player.get("percentile_xg"),
            player.get("percentile_xa"),
            player.get("percentile_chances_created"),
        ]
    else:  # POM / NAP
        components = [
            player.get("percentile_shots"),
            player.get("percentile_chances_created"),
        ]

    valid = [c for c in components if c is not None]
    if valid:
        potential_value = sum(valid) / len(valid)
    else:
        potential_value = None

    return {
        "predicted_points": predicted,
        "base_avg": round(base_avg, 1),
        "fdr_modifier": round(fdr_mod, 2),
        "fdr_atk_opponent": opponent_fdr["atk"],
        "fdr_def_opponent": opponent_fdr["def"],
        "minutes_factor": round(min_factor, 2),
        "home_away_factor": round(ha_factor, 2),
        "avg_minutes": round(avg_minutes, 0),
        "rounds_used": n_rounds,
        "used_fdr_value": used_fdr_value,
        "potential_value": round(potential_value, 2) if potential_value is not None else None,
        # confidence_rank — numeryczna ranga do sortowania (string confidence bez zmian do wyświetlania)
        "confidence_rank": {"high": 3, "medium": 2, "low": 1, "insufficient_data": 0, "unavailable": -1}.get(confidence, -1),
        "confidence": confidence,
        "detail": (
            f"Śr. {round(base_avg, 1)} × FDR {round(fdr_mod, 2)} "
            f"× min {round(min_factor, 2)} × {'dom' if is_home else 'wyjazd'} "
            f"{round(ha_factor, 2)} = {predicted}"
        ),
    }


def predict_all_players(players, fdr_data, fixtures, lookback=DEFAULT_LOOKBACK):
    """
    Prognozuje punkty dla WSZYSTKICH zawodników.

    📖 LEKCJA: Ta funkcja to "wrapper" — opakowuje główną funkcję predict_points
    i wywołuje ją w pętli dla każdego gracza. To częsty wzorzec w programowaniu:
    masz jedną funkcję dla jednego elementu, i drugą, która ją stosuje do wielu.

    Parametry:
        players: lista graczy z fantasy_full JSON
        fdr_data: dict z FDR drużyn {"Lech": {"atk": 4, "def": 2}, ...}
        fixtures: dict z następnymi meczami {"Lech": {"opponent": "Legia", "is_home": True}, ...}

    Zwraca:
        lista dictów z prognozami (posortowana od najwyższej prognozy)
    """
    predictions = []

    for player in players:
        team = player.get("team", "")
        next_fix = fixtures.get(team)

        if not next_fix:
            print(f"[Prognoza skip] Brak meczu dla '{team}' — pomijam '{player.get('name', '')}'")
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
            # xA i percentyle z conceptually_client (przekazywane przez scraper.py)
            "xa_per_90": player.get("xa_per_90"),
            "percentile_xa": player.get("percentile_xa"),
            "percentile_xg": player.get("percentile_xg"),
            "karpinski_slug": player.get("karpinski_slug"),
            "xg_per_90": player.get("xg_per_90"),
            "shots_per_90": player.get("shots_per_90"),
            "chances_created_per_90": player.get("chances_created_per_90"),
            "clean_sheet_rate": player.get("clean_sheet_rate"),
            "goals_conceded_per_90": player.get("goals_conceded_per_90"),
            "goals_prevented": player.get("goals_prevented"),
            "percentile_shots": player.get("percentile_shots"),
            "percentile_chances_created": player.get("percentile_chances_created"),
            "percentile_clean_sheet": player.get("percentile_clean_sheet"),
            "percentile_goals_conceded": player.get("percentile_goals_conceded"),
            "percentile_goals_prevented": player.get("percentile_goals_prevented"),
            "karpinski_rating": player.get("karpinski_rating"),
            **pred,  # 📖 ** "rozpakuje" dict — dodaje wszystkie klucze z pred do tego dicta
        })

    # Sortuj: najpierw dostępni zawodnicy wg prognozy malejąco, potem niedostępni (prognoza 0)
    # Niedostępni zawodnicy zawsze na końcu listy, niezależnie od sortowania
    available, unavailable = [], []
    for p in predictions:
        (unavailable if p.get("unavailable") else available).append(p)
    available.sort(key=lambda x: x.get("predicted_points") or 0, reverse=True)
    # Niedostępnych zostawiamy w kolejności alfabetycznej
    unavailable.sort(key=lambda x: x.get("name", "").lower())

    return available + unavailable


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
            {"round": 20, "played": True, "points": 10, "minutes": 90},
            {"round": 19, "played": True, "points": 3, "minutes": 90},
            {"round": 18, "played": True, "points": 5, "minutes": 78},
            {"round": 17, "played": True, "points": 8, "minutes": 90},
            {"round": 16, "played": True, "points": 2, "minutes": 85},
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
    # Test POTENTIAL_VALUE: średnia percentyli wg pozycji
    # ============================================================
    print("=" * 70)
    print("Test POTENTIAL_VALUE: średnia percentyli (pozycyjnie znormalizowana)")
    print("=" * 70)
    print()

    # Wspólne FDR / fixture dla wszystkich testowanych graczy
    test_fdr = {
        "Raków":  {"atk": 4, "def": 4},
        "GKS":    {"atk": 2, "def": 1},
        "Legia":  {"atk": 5, "def": 3},
    }

    # --- BR: Ondřej Hindrich (simulowane dane) ---
    # Składniki: [percentile_goals_prevented, percentile_clean_sheet]
    hindrich = {
        "player_id": 99901,
        "name": "Ondřej Hindrich",
        "team": "GKS",
        "position": "BR",
        "total_points": 55,
        "rounds": [
            {"round": 20, "played": True, "points": 6, "minutes": 90},
            {"round": 19, "played": True, "points": 2, "minutes": 90},
            {"round": 18, "played": True, "points": 8, "minutes": 90},
            {"round": 17, "played": True, "points": 4, "minutes": 90},
        ],
        "percentile_goals_prevented": 88.0,
        "percentile_clean_sheet": 35.0,
    }

    # --- OBR: Paweł Wszołek (simulowane dane) ---
    # Składniki: [percentile_clean_sheet, (100 - percentile_goals_conceded), percentile_xg, percentile_xa, percentile_chances_created]
    # ⚠️ percentile_goals_conceded jest ODWRÓCONY
    wszolek = {
        "player_id": 99902,
        "name": "Paweł Wszołek",
        "team": "Legia",
        "position": "OBR",
        "total_points": 70,
        "rounds": [
            {"round": 20, "played": True, "points": 9, "minutes": 90},
            {"round": 19, "played": True, "points": 7, "minutes": 90},
            {"round": 18, "played": True, "points": 12, "minutes": 90},
            {"round": 17, "played": True, "points": 5, "minutes": 90},
        ],
        "percentile_clean_sheet": 65.0,
        "percentile_goals_conceded": 20.0,   # ⚠️ niski percentyl straconych = DOBRZE → (100-20)=80
        "percentile_xg": 45.0,
        "percentile_xa": 72.0,
        "percentile_chances_created": 60.0,
    }

    # --- POM: Adrian Bozic (simulowane dane) ---
    # Składniki: [percentile_shots, percentile_chances_created]
    bozic = {
        "player_id": 99903,
        "name": "Adrian Bozic",
        "team": "Raków",
        "position": "POM",
        "total_points": 62,
        "rounds": [
            {"round": 20, "played": True, "points": 8, "minutes": 90},
            {"round": 19, "played": True, "points": 6, "minutes": 90},
            {"round": 18, "played": True, "points": 11, "minutes": 90},
            {"round": 17, "played": True, "points": 4, "minutes": 78},
        ],
        "percentile_shots": 85.0,
        "percentile_chances_created": 70.0,
    }

    # --- NAP: Juan Sánchez (simulowane dane) ---
    # Składniki: [percentile_shots, percentile_chances_created]
    sanchez = {
        "player_id": 99904,
        "name": "Juan Sánchez",
        "team": "GKS",
        "position": "NAP",
        "total_points": 80,
        "rounds": [
            {"round": 20, "played": True, "points": 12, "minutes": 90},
            {"round": 19, "played": True, "points": 9, "minutes": 90},
            {"round": 18, "played": True, "points": 7, "minutes": 85},
            {"round": 17, "played": True, "points": 14, "minutes": 90},
        ],
        "percentile_shots": 92.0,
        "percentile_chances_created": 55.0,
    }

    # Uruchom predykcję i zbierz potential_value
    test_players = [hindrich, wszolek, bozic, sanchez]
    results = {}
    for tp in test_players:
        res = predict_points(tp, test_fdr, {"opponent": tp["team"], "is_home": True})
        results[tp["name"]] = res
        pos = tp["position"]
        pv = res["potential_value"]
        print(f"[{pos}] {tp['name']:20s} → potential_value = {pv}")

    print()

    # Rozpiska składników (ręczna weryfikacja)
    print("─" * 70)
    print("RĘCZNA WERYFIKACJA SKŁADNIKÓW:")
    print("─" * 70)

    # BR — Hindrich
    br_comp = [88.0, 35.0]  # percentile_goals_prevented, percentile_clean_sheet
    br_avg = sum(br_comp) / len(br_comp)
    print(f"\n[BR] Ondřej Hindrich:")
    print(f"  percentile_goals_prevented  = 88.0")
    print(f"  percentile_clean_sheet       = 35.0")
    print(f"  → składniki (wszystkie):     {br_comp}")
    print(f"  → średnia:                   {br_avg}  (oczekiwane: {results['Ondřej Hindrich']['potential_value']})")
    assert results["Ondřej Hindrich"]["potential_value"] == br_avg, f"BR mismatch: {results['Ondřej Hindrich']['potential_value']} != {br_avg}"

    # OBR — Wszołek
    obr_comp = [
        65.0,      # percentile_clean_sheet
        100 - 20.0, # (100 - percentile_goals_conceded) = 80
        45.0,       # percentile_xg
        72.0,       # percentile_xa
        60.0,       # percentile_chances_created
    ]
    obr_avg = sum(obr_comp) / len(obr_comp)
    print(f"\n[OBR] Paweł Wszołek:")
    print(f"  percentile_clean_sheet       = 65.0")
    print(f"  percentile_goals_conceded    = 20.0 → ODWRÓCONE: (100-20) = 80.0")
    print(f"  percentile_xg                = 45.0")
    print(f"  percentile_xa                = 72.0")
    print(f"  percentile_chances_created   = 60.0")
    print(f"  → składniki (wszystkie):     {obr_comp}")
    print(f"  → średnia:                   {obr_avg}  (oczekiwane: {results['Paweł Wszołek']['potential_value']})")
    assert results["Paweł Wszołek"]["potential_value"] == obr_avg, f"OBR mismatch: {results['Paweł Wszołek']['potential_value']} != {obr_avg}"

    # POM — Bozic
    pom_comp = [85.0, 70.0]  # percentile_shots, percentile_chances_created
    pom_avg = sum(pom_comp) / len(pom_comp)
    print(f"\n[POM] Adrian Bozic:")
    print(f"  percentile_shots             = 85.0")
    print(f"  percentile_chances_created   = 70.0")
    print(f"  → składniki (wszystkie):     {pom_comp}")
    print(f"  → średnia:                   {pom_avg}  (oczekiwane: {results['Adrian Bozic']['potential_value']})")
    assert results["Adrian Bozic"]["potential_value"] == pom_avg, f"POM mismatch: {results['Adrian Bozic']['potential_value']} != {pom_avg}"

    # NAP — Sánchez
    nap_comp = [92.0, 55.0]  # percentile_shots, percentile_chances_created
    nap_avg = sum(nap_comp) / len(nap_comp)
    print(f"\n[NAP] Juan Sánchez:")
    print(f"  percentile_shots             = 92.0")
    print(f"  percentile_chances_created   = 55.0")
    print(f"  → składniki (wszystkie):     {nap_comp}")
    print(f"  → średnia:                   {nap_avg}  (oczekiwane: {results['Juan Sánchez']['potential_value']})")
    assert results["Juan Sánchez"]["potential_value"] == nap_avg, f"NAP mismatch: {results['Juan Sánchez']['potential_value']} != {nap_avg}"

    # --- Test edge-case: OBR z None percentile_goals_conceded (powinno być pominięte) ---
    obr_missing = {
        "player_id": 99905,
        "name": "Test OBR (brak pgc)",
        "team": "Legia",
        "position": "OBR",
        "total_points": 40,
        "rounds": [
            {"round": 20, "played": True, "points": 5, "minutes": 90},
            {"round": 19, "played": True, "points": 3, "minutes": 90},
            {"round": 18, "played": True, "points": 6, "minutes": 90},
            {"round": 17, "played": True, "points": 4, "minutes": 90},
        ],
        "percentile_clean_sheet": 50.0,
        "percentile_goals_conceded": None,
        "percentile_xg": 30.0,
        "percentile_xa": 40.0,
        "percentile_chances_created": 55.0,
    }
    r_missing = predict_points(obr_missing, test_fdr, {"opponent": "Legia", "is_home": True})
    expected_missing = (50.0 + 30.0 + 40.0 + 55.0) / 4  # pgc None → pominięty
    print(f"\n[OBR*] Test OBR (brak pgc):")
    print(f"  składniki (bez pgc):         [50.0, 30.0, 40.0, 55.0]")
    print(f"  → średnia:                   {expected_missing}  (oczekiwane: {r_missing['potential_value']})")
    assert r_missing["potential_value"] == expected_missing, f"OBR missing pgc mismatch"

    # --- Test edge-case: wszystkie składniki None → potential_value = None ---
    all_none = {
        "player_id": 99906,
        "name": "Test All None",
        "team": "GKS",
        "position": "POM",
        "total_points": 20,
        "rounds": [
            {"round": 20, "played": True, "points": 2, "minutes": 90},
            {"round": 19, "played": True, "points": 1, "minutes": 90},
            {"round": 18, "played": True, "points": 3, "minutes": 90},
            {"round": 17, "played": True, "points": 2, "minutes": 90},
        ],
        "percentile_shots": None,
        "percentile_chances_created": None,
    }
    r_none = predict_points(all_none, test_fdr, {"opponent": "GKS", "is_home": True})
    print(f"\n[POM*] Test All None:")
    print(f"  składniki:                   [] (wszystkie None)")
    print(f"  → potential_value:           {r_none['potential_value']} (oczekiwane: None)")
    assert r_none["potential_value"] is None, f"All-none should return None, got {r_none['potential_value']}"

    # --- Zapis logu do /tmp ---
    from datetime import datetime as dt_mod
    log_path = f"/tmp/potential_value_test_{dt_mod.now().strftime('%Y%m%d_%H%M%S')}.log"
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("=== Test POTENTIAL_VALUE — średnia percentyli ===\n")
        log.write(f"Czas: {dt_mod.now().isoformat()}\n\n")
        for name, r in results.items():
            log.write(f"{name:25s} potential_value = {r['potential_value']}\n")
        log.write(f"\nEdge case (OBR bez pgc): potential_value = {r_missing['potential_value']} "
                  f"(expected: {expected_missing})\n")
        log.write(f"Edge case (all None):    potential_value = {r_none['potential_value']} "
                  f"(expected: None)\n")
        log.write(f"\nWszystkie asercje: {'✅ PASS' if True else '❌ FAIL'}\n")

    print(f"\n📄 Log zapisany: {log_path}")
    print(f"✅ Wszystkie testy potential_value przeszły.\n")

    # ============================================================
    # Test 4: percentile i confidence_rank — różne poziomy pewności
    # ============================================================
    print("=" * 70)
    print("Test 4: percentile & confidence_rank — sprawdzenie rangowania")
    print("=" * 70)
    print()

    import sys, os, tempfile

    # Gracz z wysoką pewnością (4+ kolejek), ma percentile_xa ale bez percentile_xg
    player_high = {
        **test_player,
        "name": "Gracz High",
        "percentile_xa": 85,
        "percentile_xg": None,
        "rounds": [
            {"round": 20, "played": True, "points": 10, "minutes": 90},
            {"round": 19, "played": True, "points": 6, "minutes": 90},
            {"round": 18, "played": True, "points": 5, "minutes": 78},
            {"round": 17, "played": True, "points": 8, "minutes": 90},
        ]
    }

    # Gracz ze średnią pewnością (2-3 kolejki), ma percentile_xg zamiast xa
    player_med = {
        **test_player,
        "name": "Gracz Medium",
        "percentile_xa": None,
        "percentile_xg": 60,
        "rounds": [
            {"round": 20, "played": True, "points": 7, "minutes": 90},
            {"round": 19, "played": True, "points": 4, "minutes": 85},
        ]
    }

    # Gracz z niską pewnością — symulujemy ręcznie (predict_points da insufficient_data
    # dla 2 kolejek gdy MIN_ROUNDS_FOR_PREDICTION=2, więc potrzebujemy 3+ kolejek
    # do low confidence — dajemy dokładnie 2 kolejki (czyli >=MIN ale <4 → medium!).
    # Poprawka: low confidence wymaga n_rounds w [MIN_ROUNDS_FOR_PREDICTION, 4),
    # czyli dla MIN=2 → 2 lub 3 kolejki. Więc 2 kolejki = medium (>=2), 3 kolejki = medium.
    # Żeby dostać low, potrzebujemy mniej niż MIN_ROUNDS_FOR_PREDICTION kolejek...
    # Ale wtedy insufficient_data! Więc "low" jest obecnie nieosiągalne przy domyślnych
    # ustawieniach (MIN_ROUNDS=2 → >=2 to medium, >=4 to high, brak stanu pośredniego).
    # Symulujemy "low" przez bezpośredni dict (bez predict_points) żeby przetestować
    # confidence_rank dla wszystkich wartości.

    # Zamiast kombinować – użyjemy predict_points dla gracza który ma confidence "low"
    # robiąc override MIN_ROUNDS_FOR_PREDICTION lub podając gracza z 1 kolejką.
    # predict_points zwróci insufficient_data dla 1 kolejki (1 < MIN=2).
    # Wniosek: przy domyślnych stałych "low" nie występuje, ale kod wciąż
    # uwzględnia tę wartość w mapowaniu confidence_rank.
    # Testujemy: high (4 kolejki), medium (2-3 kolejki), insufficient_data (0-1 kolejki).
    # Potem ręcznie weryfikujemy że low=1 i unavailable=-1 są w mapowaniu.

    # --- high confidence (4 kolejki) ---
    r_high = predict_points(player_high, test_fdr, {"opponent": "GKS", "is_home": True})
    print(f"[high]   {player_high['name']}: confidence={r_high['confidence']}, "
          f"confidence_rank={r_high['confidence_rank']}")

    # --- medium confidence (2 kolejki, >=MIN, <4) ---
    r_med = predict_points(player_med, test_fdr, {"opponent": "GKS", "is_home": True})
    print(f"[medium] {player_med['name']}: confidence={r_med['confidence']}, "
          f"confidence_rank={r_med['confidence_rank']}")

    # --- insufficient_data (gracz z 0 rozegranych kolejek) ---
    player_no_data = {
        **test_player,
        "name": "Gracz NoData",
        "percentile_xa": None,
        "percentile_xg": None,
        "rounds": []
    }
    r_no = predict_points(player_no_data, test_fdr, {"opponent": "GKS", "is_home": True})
    print(f"[insuf]  {player_no_data['name']}: confidence={r_no['confidence']}, "
          f"confidence_rank={r_no['confidence_rank']}")

    # --- unavailable (kontuzja) ---
    player_injured = {
        **test_player,
        "name": "Gracz Kontuzjowany",
        "availability_status": "Kontuzja – pauzuje 2 tygodnie",
        "percentile_xa": 90,
        "percentile_xg": 88,
    }
    r_inj = predict_points(player_injured, test_fdr, {"opponent": "GKS", "is_home": True})
    print(f"[unavail] {player_injured['name']}: confidence={r_inj['confidence']}, "
          f"confidence_rank={r_inj['confidence_rank']}")

    print()

    # --- Weryfikacja kolejności confidence_rank ---
    results = [r_high, r_med, r_no, r_inj]
    # Sortuj malejąco po confidence_rank
    sorted_by_rank = sorted(results, key=lambda r: r["confidence_rank"], reverse=True)
    confidences = [r["confidence"] for r in sorted_by_rank]
    ranks = [r["confidence_rank"] for r in sorted_by_rank]

    print("Kolejność po confidence_rank (malejąco):")
    for i, r in enumerate(sorted_by_rank):
        print(f"  {i+1}. {r['confidence']:20s} (rank={r['confidence_rank']})")

    expected_order = ["high", "medium", "insufficient_data", "unavailable"]
    passed = confidences == expected_order
    print(f"\n{'✅' if passed else '❌'} Oczekiwano: {expected_order}")
    print(f"   Otrzymano:  {confidences}")
    print()
    print()

    # --- Zapis logu do /tmp ---
    log_path = "/tmp/predictor_test_confidence_rank.log"
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("=== Test confidence_rank & percentile ===\n")
        for r in results:
            log.write(f"  {r.get('detail', '')} | confidence={r['confidence']} "
                      f"| rank={r['confidence_rank']}\n")
        log.write(f"\nSortowanie: {confidences}\n")
        log.write(f"Oczekiwano: {expected_order}\n")
        log.write(f"Wynik: {'PASS' if passed else 'FAIL'}\n")

    print(f"📄 Log zapisany do: {log_path}")

    if not passed:
        print("\n❌ TEST NIEZALICZONY — confidence_rank nie odzwierciedla oczekiwanej kolejności!")
        sys.exit(1)

    print("✅ Test confidence_rank zakończony sukcesem.")

    # ============================================================
    # Test xG + goals_prevented: STARA vs NOWA prognoza
    # ============================================================
    print()
    print("=" * 70)
    print("Test xG + goals_prevented: STARA vs NOWA prognoza")
    print("=" * 70)
    print()

    # --- Test: Hindrich (BR) — goals_prevented = 3.5 (świetny bramkarz) ---
    hindrich_test = {
        "player_id": 99901,
        "name": "Ondřej Hindrich",
        "team": "GKS",
        "position": "BR",
        "total_points": 55,
        "rounds": [
            {"round": 20, "played": True, "points": 6, "minutes": 90},
            {"round": 19, "played": True, "points": 2, "minutes": 90},
            {"round": 18, "played": True, "points": 8, "minutes": 90},
            {"round": 17, "played": True, "points": 4, "minutes": 90},
        ],
        "xa_per_90": 0.02,         # niskie xA (bramkarz)
        "xg_per_90": 0.0,           # brak xG (bramkarz)
        "goals_prevented": 3.5,     # ⭐ wysoki goals_prevented — powinien dostać bonus
        "percentile_goals_prevented": 88.0,
        "percentile_clean_sheet": 35.0,
    }

    # --- Test: Wszołek (OBR) — xA=0.15, xG=0.05 ---
    wszolek_test = {
        "player_id": 99902,
        "name": "Paweł Wszołek",
        "team": "Legia",
        "position": "OBR",
        "total_points": 70,
        "rounds": [
            {"round": 20, "played": True, "points": 9, "minutes": 90},
            {"round": 19, "played": True, "points": 7, "minutes": 90},
            {"round": 18, "played": True, "points": 12, "minutes": 90},
            {"round": 17, "played": True, "points": 5, "minutes": 90},
        ],
        "xa_per_90": 0.15,          # dobre xA jak na obrońcę
        "xg_per_90": 0.05,          # niskie xG (obrońca)
        "goals_prevented": None,    # nie dotyczy OBR
        "percentile_clean_sheet": 65.0,
        "percentile_goals_conceded": 20.0,
        "percentile_xg": 45.0,
        "percentile_xa": 72.0,
        "percentile_chances_created": 60.0,
    }

    # --- Test: Bozic (POM) — xA=0.25, xG=0.12 ---
    bozic_test = {
        "player_id": 99903,
        "name": "Adrian Bozic",
        "team": "Raków",
        "position": "POM",
        "total_points": 62,
        "rounds": [
            {"round": 20, "played": True, "points": 8, "minutes": 90},
            {"round": 19, "played": True, "points": 6, "minutes": 90},
            {"round": 18, "played": True, "points": 11, "minutes": 90},
            {"round": 17, "played": True, "points": 4, "minutes": 78},
        ],
        "xa_per_90": 0.25,          # ⭐ bardzo wysokie xA — oczekujemy dużego bonusu
        "xg_per_90": 0.12,          # lekkie xG
        "goals_prevented": None,    # nie dotyczy POM
        "percentile_shots": 85.0,
        "percentile_chances_created": 70.0,
    }

    # --- Test: Sánchez (NAP) — xA=0.08, xG=0.45 ---
    sanchez_test = {
        "player_id": 99904,
        "name": "Juan Sánchez",
        "team": "GKS",
        "position": "NAP",
        "total_points": 80,
        "rounds": [
            {"round": 20, "played": True, "points": 12, "minutes": 90},
            {"round": 19, "played": True, "points": 9, "minutes": 90},
            {"round": 18, "played": True, "points": 7, "minutes": 85},
            {"round": 17, "played": True, "points": 14, "minutes": 90},
        ],
        "xa_per_90": 0.08,          # przeciętne xA
        "xg_per_90": 0.45,          # ⭐ bardzo wysokie xG — oczekujemy dużego bonusu
        "goals_prevented": None,    # nie dotyczy NAP
        "percentile_shots": 92.0,
        "percentile_chances_created": 55.0,
    }

    test_players_new = [hindrich_test, wszolek_test, bozic_test, sanchez_test]

    # --- Ręczne obliczenie STAREJ prognozy (tylko xA, bez xG, bez goals_prevented) ---
    # Tu replikujemy logikę STAREGO predict_points (sprzed tej zmiany):
    # base_avg * (1 + xa_bonus) * fdr * min * ha
    # gdzie xa_bonus = clamp((xa - 0.07) * 10, -0.10, 0.15)

    def old_predict(player, fdr_data, fixture):
        """Symuluje STARY predict_points — tylko xA, bez xG i goals_prevented."""
        position = player.get("position", "POM")
        rounds = player.get("rounds", [])
        played_rounds = [r for r in rounds if r.get("played")]
        played_rounds.sort(key=lambda r: r.get("round", 0), reverse=True)
        recent_rounds = played_rounds[:DEFAULT_LOOKBACK]
        recent_points = [r.get("points", 0) for r in recent_rounds]
        base_avg = weighted_average(recent_points, decay=0.85)

        # Tylko xA (stary mechanizm)
        xa = player.get("xa_per_90")
        if xa is not None and xa > 0:
            xa_bonus = min(max((xa - 0.07) * 10, -0.10), 0.15)
            base_avg = base_avg * (1 + xa_bonus)

        # FDR
        opponent = fixture.get("opponent", "")
        opponent_fdr = fdr_data.get(opponent, {"atk": FDR_NEUTRAL, "def": FDR_NEUTRAL})
        fdr_mod = get_fdr_modifier(opponent_fdr["atk"], opponent_fdr["def"], position)

        # Minuty
        recent_minutes = [r.get("minutes", 0) for r in recent_rounds]
        avg_minutes = sum(recent_minutes) / len(recent_minutes) if recent_minutes else 0
        min_factor = get_minutes_factor(avg_minutes)

        # Dom/wyjazd
        is_home = fixture.get("is_home", False)
        ha_factor = get_home_away_factor(is_home)

        return round(base_avg * fdr_mod * min_factor * ha_factor, 1)

    # Wspólny FDR i fixture
    test_fdr_xg = {
        "Raków":  {"atk": 4, "def": 4},
        "GKS":    {"atk": 2, "def": 1},
        "Legia":  {"atk": 5, "def": 3},
    }

    print(f"{'Gracz':<25s} {'Pozycja':<6s} {'STARA (tylko xA)':<18s} {'NOWA (xA+xG+gp)':<18s} {'Różnica':<10s} {'Co zadziałało'}")
    print("-" * 110)

    lines = []
    for p in test_players_new:
        fixture = {"opponent": p["team"], "is_home": True}
        old_pred = old_predict(p, test_fdr_xg, fixture)
        new_pred = predict_points(p, test_fdr_xg, fixture)["predicted_points"]
        diff = round(new_pred - old_pred, 1)

        # Ustal, co zadziałało
        effects = []
        pos = p["position"]
        if p.get("xg_per_90") and p["xg_per_90"] > 0:
            effects.append(f"xG={p['xg_per_90']}")
        if pos == "BR" and p.get("goals_prevented") is not None:
            effects.append(f"gp={p['goals_prevented']}")
        effect_str = ", ".join(effects) if effects else "—"

        line = f"{p['name']:<25s} {pos:<6s} {old_pred:<18.1f} {new_pred:<18.1f} {diff:+.1f}{'':>5s} {effect_str}"
        print(line)
        lines.append(line)

    print()

    # --- Zapis logu do /tmp ---
    log_path = f"/tmp/predictor_xg_gp_test_{dt_mod.now().strftime('%Y%m%d_%H%M%S')}.log"
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("=== Test xG + goals_prevented: STARA vs NOWA prognoza ===\n")
        log.write(f"Czas: {dt_mod.now().isoformat()}\n\n")
        log.write(f"{'Gracz':<25s} {'Pozycja':<6s} {'STARA':<8s} {'NOWA':<8s} {'Różnica':<10s} {'Co zadziałało'}\n")
        log.write("-" * 80 + "\n")
        for p in test_players_new:
            fixture = {"opponent": p["team"], "is_home": True}
            old_pred = old_predict(p, test_fdr_xg, fixture)
            new_pred = predict_points(p, test_fdr_xg, fixture)["predicted_points"]
            diff = round(new_pred - old_pred, 1)
            effects = []
            pos = p["position"]
            if p.get("xg_per_90") and p["xg_per_90"] > 0:
                effects.append(f"xG={p['xg_per_90']}")
            if pos == "BR" and p.get("goals_prevented") is not None:
                effects.append(f"gp={p['goals_prevented']}")
            effect_str = ", ".join(effects) if effects else "—"
            log.write(f"{p['name']:<25s} {pos:<6s} {old_pred:<8.1f} {new_pred:<8.1f} {diff:+.1f}{'':>5s} {effect_str}\n")

        # --- Ręczna weryfikacja dla Hindricha (BR) ---
        log.write("\n--- Ręczna weryfikacja: Ondřej Hindrich (BR) ---\n")
        p = hindrich_test
        fixture = {"opponent": "GKS", "is_home": True}
        # base_avg z ostatnich 4 kolejek (6,2,8,4) z decay=0.85
        points = [6, 2, 8, 4]
        wa = weighted_average(points, 0.85)
        log.write(f"  weighted_average: {wa:.2f}\n")
        # xA bonus: (0.02 - 0.07) * 10 = -0.50, clamped do -0.10
        xa_bonus = min(max((0.02 - 0.07) * 10, -0.10), 0.15)
        log.write(f"  xA bonus: {xa_bonus:.3f} (xa=0.02)\n")
        # xG bonus: xg=0.0 → pomijamy
        log.write(f"  xG bonus: pominięty (xg=0.0)\n")
        # goals_prevented bonus: 3.5 * 0.15 = 0.525, capped do 0.20
        gp_bonus = min(max(3.5 * 0.15, -0.20), 0.20)
        log.write(f"  goals_prevented bonus: {gp_bonus:.3f} (gp=3.5)\n")
        # FDR: GKS atk=2 → fdr_mod = 1.0 + (3-2)*0.10 = 1.10
        log.write(f"  FDR modifier: 1.10 (GKS atk=2)\n")
        # HA: is_home=True → 1.05
        log.write(f"  home/away factor: 1.05\n")
        # STARA: wa * (1+xa) * fdr * ha = wa * 0.90 * 1.10 * 1.05
        old_manual = wa * (1 + xa_bonus) * 1.10 * 1.05
        log.write(f"  STARA ręcznie: {wa:.2f} × 0.90 × 1.10 × 1.05 = {old_manual:.1f}\n")
        # NOWA: wa * (1+xa) * (1+gp) * fdr * ha = wa * 0.90 * 1.20 * 1.10 * 1.05
        new_manual = wa * (1 + xa_bonus) * (1 + gp_bonus) * 1.10 * 1.05
        log.write(f"  NOWA  ręcznie: {wa:.2f} × 0.90 × 1.20 × 1.10 × 1.05 = {new_manual:.1f}\n")

        # --- Ręczna weryfikacja dla Bozica (POM) ---
        log.write("\n--- Ręczna weryfikacja: Adrian Bozic (POM) ---\n")
        p = bozic_test
        points = [8, 6, 11, 4]
        wa2 = weighted_average(points, 0.85)
        log.write(f"  weighted_average: {wa2:.2f}\n")
        xa_bonus2 = min(max((0.25 - 0.07) * 10, -0.10), 0.15)
        log.write(f"  xA bonus: {xa_bonus2:.3f} (xa=0.25)\n")
        xg_bonus2 = min(max((0.12 - 0.10) * 10, -0.10), 0.15)
        log.write(f"  xG bonus: {xg_bonus2:.3f} (xg=0.12)\n")
        log.write(f"  goals_prevented: N/D (POM)\n")
        # FDR dla POM vs Raków: def_weight=0.6, atk_weight=0.4
        # fdr_to_modifier(4) = 1.0 + (3-4)*0.10 = 0.90 → oba = 0.90
        log.write(f"  FDR modifier: 0.90 (Raków def=4, atk=4)\n")
        log.write(f"  home/away factor: 1.05 (dom)\n")
        old_manual2 = wa2 * (1 + xa_bonus2) * 0.90 * 1.05
        log.write(f"  STARA ręcznie: {wa2:.2f} × {1+xa_bonus2:.3f} × 0.90 × 1.05 = {old_manual2:.1f}\n")
        new_manual2 = wa2 * (1 + xa_bonus2) * (1 + xg_bonus2) * 0.90 * 1.05
        log.write(f"  NOWA  ręcznie: {wa2:.2f} × {1+xa_bonus2:.3f} × {1+xg_bonus2:.3f} × 0.90 × 1.05 = {new_manual2:.1f}\n")

    print(f"📄 Log zapisany: {log_path}")
    print("✅ Test xG + goals_prevented zakończony.")
