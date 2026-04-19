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
        return 1.0 + (3 - fdr_value) * 0.10

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

    # --- Krok 1: Zbierz punkty z ostatnich N rozegranych kolejek ---
    # 📖 LEKCJA: "List comprehension" — skrócony zapis pętli, który tworzy nową listę
    # [wyrażenie FOR element IN lista IF warunek]
    played_rounds = [r for r in rounds if r.get("played")]

    # Sortuj od najnowszej kolejki
    played_rounds.sort(key=lambda r: r.get("round", 0), reverse=True)

    # Weź ostatnich N
    recent_rounds = played_rounds[:lookback]

    if len(recent_rounds) < MIN_ROUNDS_FOR_PREDICTION:
        return {
            "predicted_points": None,
            "confidence": "insufficient_data",
            "detail": f"Za mało danych ({len(recent_rounds)}/{MIN_ROUNDS_FOR_PREDICTION} kolejek)"
        }

    # --- Krok 2: Średnia ważona punktów ---
    recent_points = [r.get("points", 0) for r in recent_rounds]
    base_avg = weighted_average(recent_points, decay=decay)

    # --- Krok 3: Modyfikator FDR ---
    opponent = next_fixture.get("opponent", "")
    opponent_fdr = fdr_data.get(opponent, {"atk": 3, "def": 3})  # domyślnie średni
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
    if len(recent_rounds) >= 4:
        confidence = "high"
    elif len(recent_rounds) >= MIN_ROUNDS_FOR_PREDICTION:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "predicted_points": predicted,
        "base_avg": round(base_avg, 1),
        "fdr_modifier": round(fdr_mod, 2),
        "fdr_atk_opponent": opponent_fdr["atk"],
        "fdr_def_opponent": opponent_fdr["def"],
        "minutes_factor": round(min_factor, 2),
        "home_away_factor": round(ha_factor, 2),
        "avg_minutes": round(avg_minutes, 0),
        "rounds_used": len(recent_rounds),
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
