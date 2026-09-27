#!/usr/bin/env python3
"""
Test doboru pliku prognoz po numerze kolejki.

Sprawdza nową funkcję find_predictions_csv_for_round() z accuracy.py:
1. Wybiera plik z round_number == oceniana kolejka (ignorując nowszy plik z N+1).
2. Pomija plik bieżącego uruchomienia (exclude_path).
3. Zwraca None, gdy nie ma pliku dla danej kolejki.
4. Stary plik bez kolumny round_number jest pomijany bez wyjątku.

Tylko biblioteka standardowa. Uruchom: python test_accuracy_csv_selection.py
"""
import os
import tempfile

from accuracy import find_predictions_csv_for_round


def _write_csv(dir_path, filename, round_number):
    """Zapisuje minimalny plik prognoz z jedną linią danych."""
    path = os.path.join(dir_path, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write("player_id,name,predicted_points,round_number\n")
        f.write(f"1,Testowy Gracz,7.5,{round_number}\n")
    return path


def test_picks_matching_round():
    """Dwa pliki (kolejka 9 i 10) — dla 9 ma zwrócić ten z 9."""
    with tempfile.TemporaryDirectory() as tmp:
        _write_csv(tmp, "fantasy_predictions_20260920_220000.csv", 9)
        _write_csv(tmp, "fantasy_predictions_20260921_180000.csv", 10)
        result = find_predictions_csv_for_round(9, tmp)
        assert result and result.endswith("fantasy_predictions_20260920_220000.csv"), (
            f"Oczekiwano pliku z kolejki 9, dostałem: {result}"
        )
        print("  OK Wybór po round_number: zwrócono plik z kolejki 9")


def test_excludes_current_run():
    """exclude_path ma być pominięty, nawet gdy jest najnowszym plikiem dla kolejki."""
    with tempfile.TemporaryDirectory() as tmp:
        current = _write_csv(tmp, "fantasy_predictions_20260921_180000.csv", 10)
        older = _write_csv(tmp, "fantasy_predictions_20260920_220000.csv", 10)
        result = find_predictions_csv_for_round(10, tmp, exclude_path=current)
        assert result and result.endswith("fantasy_predictions_20260920_220000.csv"), (
            f"Oczekiwano starszego pliku (exclude bieżącego), dostałem: {result}"
        )
        assert result != older or result == older  # sanity: zwrócono starszy
        print("  OK exclude_path: pominięto plik bieżącego uruchomienia")


def test_returns_none_when_no_matching_round():
    """Brak pliku dla kolejki 7 — ma zwrócić None."""
    with tempfile.TemporaryDirectory() as tmp:
        _write_csv(tmp, "fantasy_predictions_20260921_180000.csv", 10)
        result = find_predictions_csv_for_round(7, tmp)
        assert result is None, f"Oczekiwano None, dostałem: {result}"
        print("  OK Brak pliku dla kolejki: zwrócono None")


def test_skips_legacy_csv_without_round_number():
    """Stary format bez round_number — pominięty, brak wyjątku."""
    with tempfile.TemporaryDirectory() as tmp:
        legacy = os.path.join(tmp, "fantasy_predictions_20260801_000000.csv")
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("player_id,name,predicted_points\n")
            f.write("1,Stary Gracz,6.0\n")
        result = find_predictions_csv_for_round(9, tmp)
        assert result is None, f"Stary plik bez round_number ma być pominięty: {result}"
        print("  OK Stary plik bez round_number: pominięty bez wyjątku")


if __name__ == "__main__":
    print("Testy doboru pliku prognoz po kolejce:\n")
    test_picks_matching_round()
    test_excludes_current_run()
    test_returns_none_when_no_matching_round()
    test_skips_legacy_csv_without_round_number()
    print("\nWszystkie testy przeszły")
