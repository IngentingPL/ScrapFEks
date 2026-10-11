"""
snapshot.py - zapis i odczyt snapshotu danych dashboardu.

Scraper przed wygenerowaniem HTML zapisuje wszystkie dane wejściowe
dashboardu do jednego pliku JSON (output/dashboard_snapshot.json).
Dzięki temu można potem przebudować HTML (build_dashboard.py)
bez ponownego scrapowania, bez sieci i bez logowania.
"""

import json
import os

# Wersja schematu snapshotu — zwiększaj przy zmianie struktury "inputs"
SCHEMA_VERSION = 1

# Domyślna ścieżka pliku snapshotu (względem katalogu projektu)
SNAPSHOT_PATH = os.path.join("output", "dashboard_snapshot.json")


def build_snapshot(inputs: dict, generated_at: str) -> dict:
    """Buduje słownik snapshotu ze stałą kolejnością kluczy:
    schema_version, generated_at, inputs."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "inputs": inputs,
    }


def save_dashboard_snapshot(inputs: dict, generated_at: str, path: str = SNAPSHOT_PATH) -> str:
    """Zapisuje snapshot danych dashboardu ATOMOWO.

    Najpierw piszemy do pliku tymczasowego (path + ".tmp"), robimy flush
    i fsync, a dopiero potem os.replace — dzięki temu nawet przy przerwaniu
    skryptu w połowie zapisu stary snapshot nie zostanie uszkodzony.
    Zwraca ścieżkę zapisanego pliku.
    """
    data = build_snapshot(inputs, generated_at)

    # Upewnij się, że katalog nadrzędny istnieje (np. output/)
    parent_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent_dir, exist_ok=True)

    tmp_path = path + ".tmp"  # plik tymczasowy w tym samym katalogu
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)  # bez sort_keys — kolejność kluczy zostaje
        f.flush()
        os.fsync(f.fileno())  # wymuś zapis na dysk przed atomowym podmianą
    os.replace(tmp_path, path)
    return path


def load_dashboard_snapshot(path: str = SNAPSHOT_PATH):
    """Wczytuje snapshot jako słownik. Zwraca None, gdy plik nie istnieje."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
