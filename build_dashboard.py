#!/usr/bin/env python3
"""
build_dashboard.py - przebudowuje dashboard HTML ze zapisanego snapshotu.

Snapshot tworzy scraper.py (output/dashboard_snapshot.json). Ten skrypt
wczytuje go i generuje HTML bez scrapowania, bez sieci i bez logowania.
Przydatne, gdy chcemy zmienić wygląd dashboardu i zobaczyć efekt
na starych danych.

Użycie:
    python build_dashboard.py
    python build_dashboard.py --snapshot output/dashboard_snapshot.json --out moje.html
"""

import argparse
import os
import sys

# Dodaj katalog skryptu do ścieżki importów (uruchamianie z dowolnego miejsca)
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from snapshot import load_dashboard_snapshot  # noqa: E402
from schedule import has_archive_season  # noqa: E402
from dashboard import generate_dashboard_html  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Buduje dashboard HTML ze snapshotu danych (bez sieci)."
    )
    parser.add_argument(
        "--snapshot",
        default=os.path.join(script_dir, "output", "dashboard_snapshot.json"),
        help="Ścieżka do pliku snapshotu (domyślnie output/dashboard_snapshot.json)",
    )
    parser.add_argument(
        "--out",
        default="/tmp/dashboard_from_snapshot.html",
        help="Gdzie zapisać HTML (domyślnie /tmp/dashboard_from_snapshot.html)",
    )
    args = parser.parse_args()

    snapshot = load_dashboard_snapshot(args.snapshot)
    if snapshot is None:
        print(f"❌ Brak snapshotu: {args.snapshot}. Uruchom najpierw scraper.py, aby go utworzyć.")
        sys.exit(1)

    inputs = snapshot["inputs"]
    # Nadpisz ścieżkę wyjścia — nie chcemy przypadkiem nadpisać docs/index.html
    inputs["filename"] = args.out
    timestamp = snapshot.get("generated_at") or ""

    generate_dashboard_html(**inputs, timestamp=timestamp, has_archive=has_archive_season())


if __name__ == "__main__":
    main()
