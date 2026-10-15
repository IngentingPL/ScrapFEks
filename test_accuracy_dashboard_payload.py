"""Test: oryginalna historia trafności zachowuje "predictions",
ale payload dashboardu (snapshot JSON i HTML) już nie.

accuracy_history.json musi przechowywać zapisane prognozy — fallback
evaluate_predictions korzysta z nich, gdy CSV prognoz już usunięto.
Snapshot i HTML nie potrzebują tych danych, więc scraper przekazuje
do dashboard_inputs kopię historii bez pola "predictions"
(scraper.strip_predictions_from_history).

Uruchomienie:
    python test_accuracy_dashboard_payload.py
"""

import csv
import json
import os
import sys
import tempfile

# Dodaj katalog główny do ścieżki (żeby importować z repo)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import accuracy
import scraper


def _build_history_entry(history_path, predictions_path):
    """Wygeneruj realny wpis historii (z polem "predictions") przez evaluate_predictions."""
    accuracy.ACCURACY_HISTORY_FILE = history_path
    with open(predictions_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "player_id", "name", "position", "team",
                "predicted_points", "round_number",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "player_id": "480",
            "name": "Bartosz Nowak",
            "position": "POM",
            "team": "GKS",
            "predicted_points": "18.4",
            "round_number": "10",
        })

    players = [{
        "player_id": "480",
        "name": "Bartosz Nowak",
        "rounds": [{"round": 10, "played": True, "points": 11}],
    }]
    entry = accuracy.evaluate_predictions(predictions_path, players, 10)
    assert entry is not None, "evaluate_predictions powinno zwrócić wpis"
    return entry


def test_payload_without_predictions_history_keeps_them():
    original_path = accuracy.ACCURACY_HISTORY_FILE
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = os.path.join(temp_dir, "accuracy_history.json")
            predictions_path = os.path.join(temp_dir, "predictions.csv")

            entry = _build_history_entry(history_path, predictions_path)

            # Nowy wpis ma pole "predictions" (zapisywane do accuracy_history.json)
            assert "predictions" in entry
            assert entry["predictions"][0]["predicted_points"] == "18.4"

            accuracy.save_accuracy_history([entry])
            with open(history_path, encoding="utf-8") as file:
                history_on_disk = json.load(file)
            # Plik accuracy_history.json zachowuje predictions (fallback evaluate)
            assert history_on_disk[0]["predictions"][0]["predicted_points"] == "18.4"

            # Payload dashboardu = kopia bez "predictions"
            payload = scraper.strip_predictions_from_history(history_on_disk)
            assert all("predictions" not in e for e in payload)
            # Pozostałe pola wpisu nietknięte
            assert payload[0]["round"] == 10
            assert payload[0]["mae"] == entry["mae"]
            assert payload[0]["details"][0]["actual"] == 11

            # Oryginalna lista (i plik) nie została zmutowana
            assert history_on_disk[0]["predictions"][0]["predicted_points"] == "18.4"

            # Snapshot/HTML serializują accuracy_history jako JSON —
            # symulujemy to, co robi dashboard.py / snapshot.py
            snapshot_inputs = {"accuracy_history": payload}
            assert '"predictions"' not in json.dumps(snapshot_inputs, ensure_ascii=False)

            # Brzegi: None i pusta lista → pusta lista, bez błędu
            assert scraper.strip_predictions_from_history(None) == []
            assert scraper.strip_predictions_from_history([]) == []
    finally:
        accuracy.ACCURACY_HISTORY_FILE = original_path
    print("OK: historia (w pamięci i na dysku) zachowuje predictions, payload — nie")


def test_dashboard_inputs_use_stripped_history():
    with open("scraper.py", encoding="utf-8") as file:
        source = file.read()
    # main() buduje payload przez helper i przekazuje go do dashboard_inputs
    assert "accuracy_history_payload = strip_predictions_from_history(accuracy_history)" in source
    assert "accuracy_history=accuracy_history_payload," in source
    # surowa historia (z predictions) nie trafia już do dashboard_inputs
    assert "accuracy_history=accuracy_history," not in source
    print("OK: dashboard_inputs korzysta z historii bez predictions")


if __name__ == "__main__":
    test_payload_without_predictions_history_keeps_them()
    test_dashboard_inputs_use_stripped_history()
    print("\nWszystkie testy przeszły ✅")
