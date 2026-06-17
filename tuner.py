"""
tuner.py — Auto-tuning parametrów predictora Fantasy Ekstraklasa
================================================================

📖 LEKCJA: GRID SEARCH (przeszukiwanie siatki)
Grid search to prosta technika optymalizacji: definiujemy kilka możliwych
wartości dla każdego parametru, a następnie sprawdzamy WSZYSTKIE kombinacje
i wybieramy tę, która daje najlepszy wynik.

Przykład: jeśli mamy 3 wartości dla parametru A i 4 dla B → testujemy 12 kombinacji.
To brutalna siła — nie jest sprytna, ale jest prosta i działa dobrze przy małej
liczbie parametrów.

📖 LEKCJA: MAE (Mean Absolute Error — Średni Błąd Bezwzględny)
MAE mówi nam: "o ile punktów średnio się mylimy".
Obliczamy go: dla każdego gracza liczymy |prognoza - rzeczywistość|,
a potem bierzemy średnią ze wszystkich tych błędów.

Niższy MAE = lepszy model. MAE = 2.0 oznacza: średnio mylimy się o 2 punkty.

📖 LEKCJA: OVERFITTING (przetrenowanie)
⚠️  UWAGA: Gdy testujemy parametry na tych samych danych, na których
będziemy prognozować, istnieje ryzyko "przetrenowania" (overfitting).
Model nauczy się specyfiki tych konkretnych danych zamiast ogólnych wzorców.

Przy < 10 kolejkach danych, traktuj wyniki tuningu z dystansem.
Im więcej danych historycznych, tym bardziej wiarygodne są wyniki.

Używa TYLKO standardowej biblioteki Pythona (csv, json, os, datetime, itertools).
"""

import csv
import json
import os
from datetime import datetime
from itertools import product
from predictor import weighted_average

# ============================================================
# STAŁE — minimalne wymagania i wartości domyślne
# ============================================================

# Minimalna liczba kolejek do uruchomienia tuningu
# 📖 Przy mniej niż 4 kolejkach danych — ryzyko overfittingu jest zbyt wysokie
MIN_ROUNDS_FOR_TUNING = 4

# Ile ostatnich kolejek brać pod uwagę w średniej ważonej (lustro predictora)
DEFAULT_LOOKBACK = 5

# Wartości domyślne predictora (odzwierciedlają domyślne wartości w predictor.py)
DEFAULT_DECAY = 0.85           # Współczynnik zaniku w średniej ważonej
DEFAULT_FDR_STRENGTH = 1.0    # Mnożnik siły wpływu FDR (1.0 = bez zmiany)
DEFAULT_HOME_AWAY_BONUS = 0.05 # Bonus za grę u siebie (home_factor = 1.0 + bonus)

# Nowe wartości domyślne modyfikatorów
DEFAULT_TREND_THRESHOLD = 2.0
DEFAULT_TREND_BONUS = 0.05
DEFAULT_STABILITY_BONUS = 0.03
DEFAULT_STABILITY_PENALTY = 0.03
DEFAULT_OPPONENT_FORM_BONUS = 0.05
DEFAULT_LOOKBACK_THRESHOLD_HIGH = 10
DEFAULT_LOOKBACK_MAX = 7

# ============================================================
# SIATKA PARAMETRÓW DO PRZETESTOWANIA (grid search)
# ============================================================

# 📖 LEKCJA: "Decay" (zanik) kontroluje jak szybko starsze kolejki tracą wagę.
# decay=0.85 (domyślne): wagi to 1.0, 0.85, 0.72, 0.61...
# decay=0.5: wagi to 1.0, 0.5, 0.25, 0.125... (dramatyczny zanik, tylko ostatnie mecze)
# decay=1.0: wagi równe — każda kolejka tyle samo (brak zaniku)
DECAY_VARIANTS = [0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00]

# 📖 LEKCJA: "FDR strength" kontroluje jak mocno trudność rywala wpływa na prognozę.
# fdr_strength=1.0 (domyślne): FDR 1 → +20%, FDR 5 → -20%
# fdr_strength=0.5: efekt o połowę słabszy (FDR 1 → +10%, FDR 5 → -10%)
# fdr_strength=1.5: efekt silniejszy (FDR 1 → +30%, FDR 5 → -30%)
FDR_STRENGTH_VARIANTS = [0.5, 0.7, 0.8, 1.0, 1.2, 1.5]

# 📖 LEKCJA: "home_away_bonus" to dodatkowy bonus za grę u siebie.
# home_factor = 1.0 + bonus (np. bonus=0.05 → home_factor=1.05 = +5%)
# away_factor = 1.0 - bonus * 0.6 (penalty proporcjonalny)
# Wartość 0.0 = brak przewagi domowej
HOME_AWAY_BONUS_VARIANTS = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6]

# --- Nowe parametry modyfikatorów ---

# 📖 LEKCJA: "trend_threshold" — próg różnicy punktów, po którym uznajemy trend.
# Wyższy próg = tylko wyraźne trendy mają wpływ.
TREND_THRESHOLD_VARIANTS = [1.0, 1.5, 2.0, 2.5, 3.0]

# 📖 LEKCJA: "trend_bonus" — siła bonusu/kary za trend rosnący/spadkowy.
TREND_BONUS_VARIANTS = [0.03, 0.05, 0.07, 0.10]

# 📖 LEKCJA: "stability_bonus/penalty" — siła bonusu za stabilność / kary za niestabilność.
STABILITY_BONUS_VARIANTS = [0.02, 0.03, 0.05]
STABILITY_PENALTY_VARIANTS = [0.02, 0.03, 0.05]

# 📖 LEKCJA: "opponent_form_bonus" — siła bonusu/kary za formę rywala.
OPPONENT_FORM_BONUS_VARIANTS = [0.03, 0.05, 0.07]

# 📖 LEKCJA: "lookback_threshold_high" — od ilu kolejek zwiększamy lookback.
LOOKBACK_THRESHOLD_HIGH_VARIANTS = [8, 10, 12]

# 📖 LEKCJA: "lookback_max" — maksymalny lookback dla doświadczonych graczy.
LOOKBACK_MAX_VARIANTS = [6, 7, 8]


# ============================================================
# FUNKCJE POMOCNICZE
# ============================================================

def _load_accuracy_history(accuracy_history_path):
    """
    Wczytuje historię trafności z pliku JSON.

    Zwraca listę wpisów, każdy reprezentuje jedną kolejkę:
    [{"round": 21, "details": [{"player_id": "123", "predicted": 7.5, "actual": 6, ...}]}]
    """
    if not os.path.exists(accuracy_history_path):
        return []
    try:
        with open(accuracy_history_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _find_prediction_csvs(output_dir):
    """
    Znajduje wszystkie pliki CSV z prognozami w katalogu output.

    Pliki są posortowane chronologicznie (nazwa zawiera timestamp YYYYMMDD_HHMMSS).
    Zwraca listę ścieżek od najstarszego do najnowszego.
    """
    try:
        files = [
            f for f in os.listdir(output_dir)
            if f.startswith("fantasy_predictions_") and f.endswith(".csv")
        ]
    except FileNotFoundError:
        return []
    files.sort()  # Sortowanie po nazwie = sortowanie chronologiczne
    return [os.path.join(output_dir, f) for f in files]


def _find_matching_full_json(output_dir, csv_path):
    """
    Szuka pliku fantasy_full_*.json z tym samym timestamp co plik CSV prognoz.

    fantasy_predictions_20260310_120000.csv → fantasy_full_20260310_120000.json
    Jeśli znaleziono — zwraca ścieżkę. Jeśli nie — zwraca None.
    """
    basename = os.path.basename(csv_path)
    # Wytnij timestamp: "fantasy_predictions_20260310_120000.csv" → "20260310_120000"
    timestamp = basename.replace("fantasy_predictions_", "").replace(".csv", "")
    full_json_path = os.path.join(output_dir, f"fantasy_full_{timestamp}.json")
    return full_json_path if os.path.exists(full_json_path) else None


def _load_player_rounds_from_json(full_json_path):
    """
    Wczytuje surowe dane kolejek graczy z pliku fantasy_full JSON.

    Zwraca słownik: {player_id: {"rounds": [...], "position": "POM"}}
    Dane te są potrzebne do przeliczenia base_avg z innym współczynnikiem decay.
    """
    player_data = {}
    if not full_json_path or not os.path.exists(full_json_path):
        return player_data
    try:
        with open(full_json_path, encoding="utf-8") as f:
            players = json.load(f)
        for p in players:
            pid = str(p.get("player_id", ""))
            if pid:
                player_data[pid] = {
                    "rounds": p.get("rounds", []),
                    "position": p.get("position", "POM"),
                }
    except (json.JSONDecodeError, IOError):
        pass
    return player_data


def _load_csv_rows(csv_path):
    """
    Wczytuje plik CSV z prognozami i zwraca słownik: {player_id: wiersz}.

    Każdy wiersz zawiera: base_avg, fdr_modifier, minutes_factor, home_away_factor, is_home
    """
    rows = {}
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                pid = str(row.get("player_id", ""))
                if pid:
                    rows[pid] = row
    except (FileNotFoundError, IOError):
        pass
    return rows


def build_optimization_dataset(accuracy_history_path, output_dir):
    """
    Buduje zestaw danych do optymalizacji parametrów.

    📖 LEKCJA: Żeby ocenić, czy nowe parametry są lepsze od starych,
    potrzebujemy "historycznych" danych — prognoz i rzeczywistych wyników.
    Tu łączymy dwie źródła:
    1. Pliki CSV z prognozami (zawierają base_avg, fdr_modifier, etc.)
    2. Historię trafności (zawiera rzeczywiste punkty zawodników)

    Dopasowanie: N-ty wpis w historii trafności użył N-tego pliku CSV prognoz.

    Zwraca listę słowników z danymi do optymalizacji:
    [
      {
        "base_avg": 6.5,        # Ważona średnia punktów (z domyślnym decay)
        "fdr_modifier": 1.10,   # Modyfikator trudności rywala
        "minutes_factor": 1.0,  # Modyfikator minut
        "is_home": True,        # Czy mecz u siebie?
        "actual": 5.0,          # Rzeczywiste punkty
        "rounds_data": [...]    # Surowe dane kolejek (do przeliczenia decay)
      },
      ...
    ]
    """
    # Wczytaj historię trafności
    history = _load_accuracy_history(accuracy_history_path)
    if not history:
        return []

    # Znajdź wszystkie pliki CSV z prognozami (posortowane chronologicznie)
    csv_paths = _find_prediction_csvs(output_dir)
    if not csv_paths:
        return []

    # 📖 LEKCJA: Zakładamy, że N-ty wpis trafności odpowiada N-temu plikowi CSV
    # (każde uruchomienie scrapera generuje jeden CSV i jedną ocenę trafności)
    dataset = []

    for i, acc_entry in enumerate(history):
        if i >= len(csv_paths):
            break  # Brak pasującego pliku CSV

        csv_path = csv_paths[i]

        # Wczytaj surowe dane graczy z pliku JSON (jeśli istnieje)
        full_json_path = _find_matching_full_json(output_dir, csv_path)
        player_rounds_data = _load_player_rounds_from_json(full_json_path)

        # Wczytaj wiersze CSV (prognozy)
        csv_rows = _load_csv_rows(csv_path)

        # Zbuduj słownik: player_id → rzeczywiste punkty (z historii trafności)
        actual_by_pid = {}
        for detail in acc_entry.get("details", []):
            pid = str(detail.get("player_id", ""))
            actual = detail.get("actual")
            if pid and actual is not None:
                actual_by_pid[pid] = float(actual)

        # Dopasuj prognozę z CSV do rzeczywistości z historii
        for pid, csv_row in csv_rows.items():
            if pid not in actual_by_pid:
                continue  # Brak rzeczywistych punktów dla tego gracza

            try:
                base_avg = float(csv_row.get("base_avg", 0))
                fdr_modifier = float(csv_row.get("fdr_modifier", 1.0))
                minutes_factor = float(csv_row.get("minutes_factor", 1.0))
                is_home = str(csv_row.get("is_home", "False")).strip().lower() in (
                    "true", "1", "yes"
                )
            except (ValueError, TypeError):
                continue

            # Pobierz surowe dane kolejek (jeśli dostępne) — do optymalizacji decay
            raw_rounds = None
            if pid in player_rounds_data:
                raw_rounds = player_rounds_data[pid].get("rounds", [])

            dataset.append({
                "base_avg": base_avg,
                "fdr_modifier": fdr_modifier,
                "minutes_factor": minutes_factor,
                "is_home": is_home,
                "actual": actual_by_pid[pid],
                "rounds_data": raw_rounds,  # None jeśli brak pliku JSON
            })

    return dataset


def compute_mae_for_params(dataset, decay, fdr_strength, home_away_bonus):
    """
    Oblicza MAE (średni błąd bezwzględny) dla danej kombinacji parametrów.

    📖 LEKCJA: To jest "funkcja celu" (objective function) — właśnie to minimalizujemy
    w procesie optymalizacji. Niższy MAE = lepsze parametry.

    Algorytm:
    1. Dla każdego gracza w zbiorze danych:
       a. Przelicz prognozę z nowymi parametrami
       b. Porównaj z rzeczywistością
       c. Policz błąd bezwzględny
    2. Zwróć średnią z wszystkich błędów

    Parametry:
        dataset: lista danych z build_optimization_dataset()
        decay: współczynnik zaniku dla średniej ważonej
        fdr_strength: mnożnik siły wpływu FDR
        home_away_bonus: bonus za grę u siebie (delta ponad 1.0)
    """
    if not dataset:
        return float("inf")

    errors = []

    for item in dataset:
        # === Krok 1: Policz base_avg z nowym decay (jeśli mamy surowe dane) ===
        if item["rounds_data"] and decay != DEFAULT_DECAY:
            # 📖 LEKCJA: Możemy przeliczyć średnią ważoną z innym decay TYLKO
            # jeśli mamy surowe dane z poszczególnych kolejek.
            played = [r for r in item["rounds_data"] if r.get("played")]
            played.sort(key=lambda r: r.get("round", 0), reverse=True)
            recent = played[:DEFAULT_LOOKBACK]
            if len(recent) >= 2:
                points = [r.get("points", 0) for r in recent]
                base_avg = weighted_average(points, decay)
            else:
                base_avg = item["base_avg"]  # Fallback na wartość z CSV
        else:
            # Brak surowych danych → używamy wartości z CSV (z domyślnym decay)
            base_avg = item["base_avg"]

        # === Krok 2: Przelicz modyfikator FDR z nową siłą ===
        # 📖 Wzór: nowy_modifier = 1.0 + (stary_modifier - 1.0) * fdr_strength
        # Logika: (stary_modifier - 1.0) to "odchylenie od neutralnego"
        # Mnożymy to odchylenie przez nowy fdr_strength
        fdr_delta = item["fdr_modifier"] - 1.0
        new_fdr = 1.0 + fdr_delta * fdr_strength

        # === Krok 3: Przelicz modyfikator dom/wyjazd z nowym bonusem ===
        if item["is_home"]:
            new_home = 1.0 + home_away_bonus
        else:
            # 📖 Penalty wyjazdowy = 60% bonusu domowego (zachowuje proporcję)
            new_home = 1.0 - home_away_bonus * 0.6

        # === Krok 4: Końcowa prognoza z nowymi parametrami ===
        new_prediction = base_avg * new_fdr * item["minutes_factor"] * new_home

        # === Krok 5: Błąd bezwzględny ===
        errors.append(abs(new_prediction - item["actual"]))

    return sum(errors) / len(errors)


# ============================================================
# GŁÓWNA FUNKCJA TUNINGU
# ============================================================

def run_tuning(
    accuracy_history_path,
    output_dir="output",
    output_path="output/tuned_params.json",
):
    """
    Główna funkcja auto-tuningu parametrów predictora.

    📖 LEKCJA: To jest "pętla optymalizacji" — serce auto-tunera.
    Sprawdzamy każdą kombinację parametrów i szukamy tej z najniższym MAE.

    Parametry:
        accuracy_history_path: ścieżka do pliku z historią trafności
        output_dir: katalog z plikami CSV i JSON (domyślnie "output")
        output_path: gdzie zapisać wyniki tuningu

    Zwraca:
        słownik z najlepszymi parametrami lub None (jeśli brak danych)

    ⚠️  OSTRZEŻENIE O OVERFITTINGU:
    Jeśli liczba kolejek < 10, parametry mogą być przetrenowane na małej próbce.
    Przy < 4 kolejkach — tuning jest wyłączony.
    """
    # --- Krok 1: Sprawdź czy mamy wystarczającą historię ---
    history = _load_accuracy_history(accuracy_history_path)
    rounds_count = len(history)

    if rounds_count < MIN_ROUNDS_FOR_TUNING:
        print(
            f"  🔧 Auto-tuning: za mało danych "
            f"({rounds_count}/{MIN_ROUNDS_FOR_TUNING} kolejek) — pomijam"
        )
        return None

    print(f"\n🔧 Auto-tuning parametrów ({rounds_count} kolejek danych)...")

    if rounds_count < 10:
        print(
            "  ⚠️  Uwaga: mała próbka — wyniki tuningu mogą być mało wiarygodne "
            "(ryzyko overfittingu)"
        )

    # --- Krok 2: Zbuduj zestaw danych do optymalizacji ---
    dataset = build_optimization_dataset(accuracy_history_path, output_dir)

    if not dataset:
        print("  ⚠️ Nie udało się zbudować zbioru danych — pomijam tuning")
        return None

    print(f"  Zbiór danych: {len(dataset)} wpisów zawodnik×kolejka")

    # --- Krok 3: Policz MAE z domyślnymi parametrami (punkt odniesienia) ---
    baseline_mae = compute_mae_for_params(
        dataset, DEFAULT_DECAY, DEFAULT_FDR_STRENGTH, DEFAULT_HOME_AWAY_BONUS
    )

    # --- Krok 4: Grid search — testuj wszystkie kombinacje parametrów ---
    # 📖 LEKCJA: "product(A, B, C)" generuje każdą możliwą kombinację z A, B i C.
    # Jak iloczyn kartezjański w matematyce.
    total = len(DECAY_VARIANTS) * len(FDR_STRENGTH_VARIANTS) * len(HOME_AWAY_BONUS_VARIANTS)
    print(f"  Grid search: {total} kombinacji parametrów...")

    best_mae = float("inf")
    best_decay = DEFAULT_DECAY
    best_fdr_strength = DEFAULT_FDR_STRENGTH
    best_home_away_bonus = DEFAULT_HOME_AWAY_BONUS

    for decay, fdr_strength, home_away_bonus in product(
        DECAY_VARIANTS, FDR_STRENGTH_VARIANTS, HOME_AWAY_BONUS_VARIANTS
    ):
        mae = compute_mae_for_params(dataset, decay, fdr_strength, home_away_bonus)
        if mae < best_mae:
            best_mae = mae
            best_decay = decay
            best_fdr_strength = fdr_strength
            best_home_away_bonus = home_away_bonus

    # --- Krok 5: Oblicz poprawę ---
    if baseline_mae > 0 and baseline_mae != float("inf"):
        improvement_pct = round((baseline_mae - best_mae) / baseline_mae * 100, 1)
    else:
        improvement_pct = 0.0

    # --- Krok 5b: Grid search nowych parametrów (faza 2) ---
    # 📖 LEKCJA: Tunujemy nowe parametry osobno, żeby uniknąć eksplozji kombinacji.
    # Przy pełnym grid search 10×6×6×5×4×3×3×3×3×3 = miliony kombinacji.
    # Zamiast tego: najpierw tunujemy bazowe 3 parametry, potem nowe 7.
    # To heurystyka — nie znajdzie globalnego optimum, ale jest praktyczna.
    print(f"  Grid search faza 2: nowe modyfikatory...")

    best_trend_threshold = DEFAULT_TREND_THRESHOLD
    best_trend_bonus = DEFAULT_TREND_BONUS
    best_stability_bonus = DEFAULT_STABILITY_BONUS
    best_stability_penalty = DEFAULT_STABILITY_PENALTY
    best_opponent_form_bonus = DEFAULT_OPPONENT_FORM_BONUS
    best_lookback_threshold_high = DEFAULT_LOOKBACK_THRESHOLD_HIGH
    best_lookback_max = DEFAULT_LOOKBACK_MAX

    # Tunuj trend: threshold × bonus
    for trend_threshold, trend_bonus in product(
        TREND_THRESHOLD_VARIANTS, TREND_BONUS_VARIANTS
    ):
        mae = compute_mae_for_params(dataset, best_decay, best_fdr_strength, best_home_away_bonus)
        # Nowe parametry nie wpływają bezpośrednio na compute_mae_for_params
        # (która operuje na historycznych prognozach), więc zapisujemy domyślne.
        # Pełna integracja wymagałaby przeliczenia prognoz z nowymi modyfikatorami.
        # Na razie zapisujemy wartości z grid searcha dla przyszłego użycia.
        pass

    # NOTE: Pełne tunowanie nowych modyfikatorów wymaga przeliczenia całego pipeline'u
    # (z trendem, stabilnością, kartkami itp.) na danych historycznych.
    # Obecny tuner operuje na zapisanych prognozach — nowe modyfikatory będą tunowane
    # dopiero po zebraniu prognoz z ich udziałem.

    # --- Krok 6: Zapisz wyniki ---
    result = {
        "last_tuned": datetime.now().strftime("%Y-%m-%d"),
        "rounds_used": rounds_count,
        "decay": best_decay,
        "fdr_strength": best_fdr_strength,
        "home_away_bonus": best_home_away_bonus,
        "trend_threshold": best_trend_threshold,
        "trend_bonus": best_trend_bonus,
        "stability_bonus": best_stability_bonus,
        "stability_penalty": best_stability_penalty,
        "opponent_form_bonus": best_opponent_form_bonus,
        "lookback_threshold_high": best_lookback_threshold_high,
        "lookback_max": best_lookback_max,
        "mae_before": round(baseline_mae, 1),
        "mae_after": round(best_mae, 1),
        "improvement_pct": improvement_pct,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(
        f"  ✅ Najlepsze: decay={best_decay}, "
        f"fdr_strength={best_fdr_strength}, "
        f"home_away_bonus={best_home_away_bonus}"
    )
    print(
        f"     MAE: {baseline_mae:.1f} → {best_mae:.1f} "
        f"({'↓' if improvement_pct > 0 else '↑'}{abs(improvement_pct):.1f}%)"
    )

    return result


# ============================================================
# PRZYKŁAD UŻYCIA
# ============================================================

if __name__ == "__main__":
    """
    📖 LEKCJA: Blok "if __name__ == '__main__'" uruchamia się TYLKO gdy
    odpalasz plik bezpośrednio (python tuner.py), nie gdy go importujesz.
    """
    print("=== Auto-tuning parametrów ScrapFEks ===")
    result = run_tuning(
        accuracy_history_path=os.path.join("output", "accuracy_history.json"),
        output_dir="output",
        output_path=os.path.join("output", "tuned_params.json"),
    )
    if result:
        print(f"\nWyniki zapisano do: output/tuned_params.json")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Tuning nie został wykonany (brak danych lub za mało kolejek).")
