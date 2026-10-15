"""Test aktualizacji częściowej trafności trwającej kolejki."""

import csv
import json
import os
import tempfile

import accuracy


def test_refresh_same_round_without_csv():
    original_path = accuracy.ACCURACY_HISTORY_FILE
    with tempfile.TemporaryDirectory() as temp_dir:
        history_path = os.path.join(temp_dir, "accuracy_history.json")
        predictions_path = os.path.join(temp_dir, "predictions.csv")
        accuracy.ACCURACY_HISTORY_FILE = history_path
        with open(predictions_path, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["player_id", "name", "position", "team", "predicted_points"],
            )
            writer.writeheader()
            writer.writerow({
                "player_id": "480",
                "name": "Bartosz Nowak",
                "position": "POM",
                "team": "GKS",
                "predicted_points": "18.4",
            })

        partial = [{
            "player_id": "480",
            "name": "Bartosz Nowak",
            "rounds": [
                {"round": 10, "played": True, "points": 11},
                {"round": 10, "played": False, "points": 0},
            ],
        }]
        first = accuracy.evaluate_predictions(predictions_path, partial, 10)
        assert first["details"][0]["actual"] == 11

        final = [{
            "player_id": "480",
            "name": "Bartosz Nowak",
            "rounds": [
                {"round": 10, "played": True, "points": 11},
                {"round": 10, "played": True, "points": 14},
            ],
        }]
        second = accuracy.evaluate_predictions(None, final, 10)
        assert second["details"][0]["actual"] == 25

        with open(history_path, encoding="utf-8") as file:
            history = json.load(file)
        assert len(history) == 1
        assert history[0]["round"] == 10
        assert history[0]["details"][0]["actual"] == 25
        assert history[0]["predictions"][0]["predicted_points"] == "18.4"
    accuracy.ACCURACY_HISTORY_FILE = original_path
    print("OK: wpis K10 zastąpiono; actual 11 -> 25 także bez zachowanego CSV")


if __name__ == "__main__":
    test_refresh_same_round_without_csv()
