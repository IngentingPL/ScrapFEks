"""
accuracy.py — Moduł śledzenia trafności prognoz Fantasy Ekstraklasa
===================================================================

Ten plik porównuje prognozy z rzeczywistymi punktami po każdej kolejce.
Dzięki temu wiemy, jak dokładny jest nasz model prognozowania.

Główne metryki:
- MAE (Mean Absolute Error) — o ile punktów średnio się mylimy
- Hit rate — jak często prognoza jest blisko rzeczywistości
- MAE per pozycja — dla jakiej pozycji model działa najlepiej

Używa TYLKO standardowej biblioteki Pythona (csv, json, os, datetime).
"""

import csv
import json
import os
import sys
from datetime import datetime


# Ścieżka do pliku z historią trafności — tu zapisujemy wyniki po każdej kolejce
ACCURACY_HISTORY_FILE = os.path.join("output", "accuracy_history.json")

# Próg "bliskiej prognozy" — jeśli błąd < ta wartość, uznajemy trafienie
HIT_THRESHOLD = 3


def load_predictions_from_csv(csv_path):
    """
    Wczytuje plik CSV z prognozami i zwraca listę słowników.

    Każdy wiersz CSV staje się słownikiem, np:
    {"player_id": "480", "name": "Bartosz Nowak", "predicted_points": "7.5", ...}

    CSV to format "wartości rozdzielone przecinkami" — prosty sposób
    na przechowywanie danych tabelarycznych w pliku tekstowym.
    """
    predictions = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                predictions.append(row)
    except FileNotFoundError:
        print(f"  ⚠️  Plik prognoz nie istnieje: {csv_path}")
    return predictions


def extract_round_points(player_data, round_number):
    """
    Wyciąga punkty zawodnika z konkretnej kolejki.

    Dane kolejek gracza wyglądają tak:
    [{'round': 20, 'points': 7, 'played': True}, {'round': 21, 'points': 6, 'played': True}, ...]
    Szukamy wpisu gdzie 'round' == round_number i zwracamy 'points'.

    Zwraca None jeśli zawodnik nie grał w tej kolejce.
    """
    rounds = player_data.get("rounds", [])  # Poprawione: "rounds" zamiast "form" (bug od marca 2026)

    # rounds może być stringiem (z CSV) albo listą (z JSON)
    if isinstance(rounds, str):
        try:
            # Zamień string na listę — ast.literal_eval byłby bezpieczniejszy,
            # ale rounds używa True/False co wymaga specjalnej obsługi
            rounds = rounds.replace("True", "true").replace("False", "false")
            rounds = json.loads(rounds.replace("'", '"'))
        except (json.JSONDecodeError, ValueError):
            return None

    if not isinstance(rounds, list):
        return None

    for entry in rounds:
        if isinstance(entry, dict) and entry.get("round") == round_number:
            if entry.get("played"):  # played = czy grał w tej kolejce
                return entry.get("points", 0)
    return None


def build_player_lookup(players_data):
    """
    Buduje słownik player_id → dane gracza dla szybkiego wyszukiwania.

    Zamiast za każdym razem przeszukiwać całą listę graczy,
    robimy "lookup" (indeks) — jak spis treści w książce.
    Klucz to player_id, wartość to cały słownik z danymi gracza.
    """
    lookup = {}
    for player in players_data:
        pid = str(player.get("player_id", ""))
        if pid:
            lookup[pid] = player
    return lookup


def compute_accuracy(predictions, players_data, round_number):
    """
    Oblicza metryki trafności prognoz dla jednej kolejki.

    Kroki:
    1. Dla każdego zawodnika z prognoz — znajdź jego rzeczywiste punkty
    2. Oblicz błąd (prognoza minus rzeczywistość)
    3. Policz statystyki zbiorcze (MAE, hit rate, itp.)

    Parametry:
        predictions: lista słowników z prognozami (z CSV)
        players_data: lista słowników z aktualnymi danymi graczy
        round_number: numer kolejki do sprawdzenia

    Zwraca:
        słownik z metrykami lub None (jeśli brak danych do porównania)
    """

    # Budujemy "lookup" — szybki dostęp do gracza po player_id
    player_lookup = build_player_lookup(players_data)

    # Lista porównań: każdy element to jeden zawodnik z prognozą i rzeczywistością
    comparisons = []

    for pred in predictions:
        pid = str(pred.get("player_id", ""))

        # Jeśli prognoza nie ma player_id — nie możemy dopasować, pomijamy
        if not pid or pid not in player_lookup:
            continue

        # Próbujemy odczytać prognozowaną wartość
        try:
            predicted = float(pred.get("predicted_points", 0))
        except (ValueError, TypeError):
            continue

        # Szukamy rzeczywistych punktów z tej kolejki
        actual = extract_round_points(player_lookup[pid], round_number)

        # Jeśli zawodnik nie grał — nie porównujemy
        if actual is None:
            continue

        # Obliczamy błąd: ile się pomyliliśmy
        error = predicted - actual       # Może być ujemny (prognoza za niska)
        abs_error = abs(error)            # Wartość bezwzględna — zawsze >= 0

        comparisons.append({
            "player_id": pid,
            "name": pred.get("name", ""),
            "position": pred.get("position", ""),
            "team": pred.get("team", ""),
            "predicted": round(predicted, 1),
            "actual": actual,
            "error": round(error, 1),
            "abs_error": round(abs_error, 1),
        })

    # Jeśli nie udało się porównać żadnego zawodnika — zwracamy None
    if not comparisons:
        return None

    # === METRYKI ZBIORCZE ===

    # MAE = Mean Absolute Error = średnia z wartości bezwzględnych błędów
    # Mówi nam: "o ile punktów średnio się mylę"
    all_abs_errors = [c["abs_error"] for c in comparisons]
    mae = sum(all_abs_errors) / len(all_abs_errors)

    # MAE per pozycja — rozbijamy zawodników na grupy wg pozycji
    # i liczymy MAE osobno dla każdej, żeby wiedzieć gdzie model jest najlepszy
    mae_by_pos = {}
    for position in ["BR", "OBR", "POM", "NAP"]:
        pos_errors = [c["abs_error"] for c in comparisons if c["position"] == position]
        if pos_errors:
            mae_by_pos[position] = round(sum(pos_errors) / len(pos_errors), 1)

    # Top 10 MAE — sprawdzamy trafność dla 10 najwyżej prognozowanych
    # Bo to ci, których wybieramy do składu — najważniejsze żeby tu trafić
    sorted_by_pred = sorted(comparisons, key=lambda x: x["predicted"], reverse=True)
    top10 = sorted_by_pred[:10]
    top10_mae = sum(c["abs_error"] for c in top10) / len(top10) if top10 else 0

    # Hit rate = procent zawodników, gdzie error < próg (domyślnie 3 pkt)
    # Mówi nam: "jak często jestem blisko rzeczywistości"
    hits = sum(1 for c in comparisons if c["abs_error"] < HIT_THRESHOLD)
    hit_rate = hits / len(comparisons)

    # Największe pudła — sortujemy po abs_error malejąco
    # Raz sortujemy po abs_error i używamy w 3 miejscach
    comparisons_sorted = sorted(comparisons, key=lambda x: x["abs_error"])
    worst = comparisons_sorted[-5:][::-1]  # ostatnie 5, odwrócone (malejąco)
    worst_misses = [
        {"name": w["name"], "predicted": w["predicted"], "actual": w["actual"], "error": w["error"]}
        for w in worst
    ]

    # Najlepsze trafienia — sortujemy po abs_error rosnąco
    best = comparisons_sorted[:5]
    best_hits = [
        {"name": b["name"], "predicted": b["predicted"], "actual": b["actual"], "error": b["error"]}
        for b in best
    ]

    return {
        "round": round_number,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "mae": round(mae, 1),
        "mae_by_pos": mae_by_pos,
        "top10_mae": round(top10_mae, 1),
        "hit_rate": round(hit_rate, 2),
        "sample_size": len(comparisons),
        "worst_misses": worst_misses,
        "best_hits": best_hits,
        "details": [
            {
                "player_id": c["player_id"],
                "name": c["name"],
                "position": c["position"],
                "team": c["team"],
                "predicted": c["predicted"],
                "actual": c["actual"],
                "error": c["error"],
            }
            for c in comparisons_sorted
        ],
    }


def load_accuracy_history():
    """
    Wczytuje historię trafności z pliku JSON.

    Plik zawiera listę wyników z poprzednich kolejek.
    Jeśli plik nie istnieje — zwracamy pustą listę (pierwszy raz).
    """
    if not os.path.exists(ACCURACY_HISTORY_FILE):
        return []
    try:
        with open(ACCURACY_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_accuracy_history(history):
    """
    Zapisuje historię trafności do pliku JSON.

    JSON (JavaScript Object Notation) to format tekstowy do przechowywania
    danych strukturalnych — czytelny zarówno dla ludzi, jak i komputerów.
    """
    os.makedirs(os.path.dirname(ACCURACY_HISTORY_FILE), exist_ok=True)
    with open(ACCURACY_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def find_latest_predictions_csv(output_dir="output"):
    """
    Znajduje najnowszy plik z prognozami w katalogu output.

    Pliki mają nazwy typu: fantasy_predictions_20260314_224444.csv
    Sortujemy je po nazwie (która zawiera datę) i bierzemy ostatni.
    """
    try:
        files = [
            f for f in os.listdir(output_dir)
            if f.startswith("fantasy_predictions_") and f.endswith(".csv")
        ]
    except FileNotFoundError:
        return None

    if not files:
        return None

    # Sortujemy po nazwie — bo nazwa zawiera timestamp (YYYYMMDD_HHMMSS)
    files.sort()
    return os.path.join(output_dir, files[-1])


def evaluate_predictions(predictions_csv_path, current_players_data, round_number):
    """
    Główna funkcja — porównuje prognozy z rzeczywistością i zapisuje wyniki.

    Wywoływana z scraper.py po pobraniu aktualnych danych.

    Parametry:
        predictions_csv_path: ścieżka do CSV z prognozami (z poprzedniego uruchomienia)
        current_players_data: lista słowników z aktualnymi danymi graczy
        round_number: numer kolejki, której dotyczą prognozy

    Zwraca:
        słownik z metrykami lub None
    """
    if not predictions_csv_path or not os.path.exists(predictions_csv_path):
        print("  📊 Trafność: brak pliku prognoz — pomijam (pierwsze uruchomienie?)")
        return None

    if not current_players_data:
        print("  📊 Trafność: brak danych graczy — pomijam")
        return None

    print(f"\n📊 Sprawdzam trafność prognoz dla kolejki {round_number}...")

    # Wczytaj prognozy z pliku CSV
    predictions = load_predictions_from_csv(predictions_csv_path)
    if not predictions:
        print("  ⚠️  Pusty plik prognoz — pomijam")
        return None

    print(f"  Wczytano {len(predictions)} prognoz z {os.path.basename(predictions_csv_path)}")

    # Guard: sprawdź czy plik prognoz dotyczy tej samej kolejki
    # (nowe pliki CSV mają kolumnę round_number, stare nie — nie blokujemy na nich)
    first_pred = predictions[0]
    csv_round = first_pred.get("round_number")
    if csv_round is not None:
        try:
            csv_round = int(csv_round)
        except (ValueError, TypeError):
            pass  # nieudana konwersja → traktuj jak brak kolumny
        else:
            if csv_round != round_number:
                print(f"  ⚠️ Plik prognoz dotyczy kolejki {csv_round}, "
                      f"a sprawdzamy kolejkę {round_number} — pomijam")
                return None

    # Oblicz metryki trafności
    result = compute_accuracy(predictions, current_players_data, round_number)
    if not result:
        print("  ⚠️  Nie udało się porównać żadnego zawodnika — pomijam")
        return None

    # Wczytaj historię i dodaj nowy wynik
    history = load_accuracy_history()

    # Sprawdź czy ta kolejka już jest w historii — jeśli tak, nadpisz
    history = [h for h in history if h.get("round") != round_number]
    history.append(result)

    # Sortuj historię po numerze kolejki
    history.sort(key=lambda x: x.get("round", 0))

    # Przycinamy "details" starszych wpisów, żeby plik nie rósł bez ograniczenia.
    # Najnowszy wpis (ostatni) zostaje bez zmian – dashboard wyświetla pełną tabelę tylko dla niego.
    # Starsze wpisy zachowują tylko player_id i actual – tuner.py potrzebuje tylko tych 2 pól.
    trimmed_count = 0
    size_before_kb = sys.getsizeof(history) / 1024

    if len(history) > 1:
        for entry in history[:-1]:
            if "details" in entry:
                entry["details"] = [
                    {"player_id": d["player_id"], "actual": d["actual"]}
                    for d in entry["details"]
                ]
                trimmed_count += 1

    if trimmed_count > 0:
        size_after_kb = sys.getsizeof(history) / 1024
        print(f"  🧹 Przycięto details w {trimmed_count} starszych wpisach historii")
        print(f"     Rozmiar accuracy_history.json: {size_before_kb:.1f} KB → {size_after_kb:.1f} KB")

    # Zapisz zaktualizowaną historię
    save_accuracy_history(history)

    # Wyświetl podsumowanie
    print(f"  ✅ Kolejka {round_number}: MAE = {result['mae']} pkt, Hit rate = {result['hit_rate']:.0%}")
    print(f"     Próbka: {result['sample_size']} zawodników")
    if result['mae_by_pos']:
        pos_str = ", ".join(f"{k}: {v}" for k, v in sorted(result['mae_by_pos'].items()))
        print(f"     MAE per pozycja: {pos_str}")
    print(f"     Top 10 MAE: {result['top10_mae']} pkt")

    return result
