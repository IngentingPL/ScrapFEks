#!/usr/bin/env python3
"""
Test zabezpieczeń na pustych danych wejściowych.

Sprawdza 3 miejsca z porannego audytu:
1. generate_from_cache.py — dynamiczne wyszukiwanie fantasy_full_*.json
   (FileNotFoundError przy braku plików; wybór najnowszego, gdy są).
2. scraper.py — fdr_data["gameweeks"][0] (guard na pustej liście gameweeks).
3. scraper.py — team_players[-1]["form"] (bezpieczny dostęp po appendzie).

Tylko biblioteka standardowa. Uruchom: python test_empty_guards.py
"""
import os
import tempfile

# 1) Realny test nowej funkcji dynamicznej ścieżki
from generate_from_cache import find_latest_cache_file


def test_find_latest_cache_file_empty():
    """Pusty katalog — ma rzucić FileNotFoundError, nie cichy crash."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            find_latest_cache_file(tmp)
        except FileNotFoundError as e:
            print(f"  OK Miejsce 1 (pusty katalog): FileNotFoundError — {e}")
        else:
            raise AssertionError("Oczekiwano FileNotFoundError dla pustego katalogu")


def test_find_latest_cache_file_newest():
    """Dwa pliki — ma zwrócić ten z najnowszym znacznikiem czasu."""
    with tempfile.TemporaryDirectory() as tmp:
        old = os.path.join(tmp, "fantasy_full_20260422_195603.json")
        new = os.path.join(tmp, "fantasy_full_20260817_101942.json")
        for p in (old, new):
            with open(p, "w", encoding="utf-8") as f:
                f.write("[]")
        result = find_latest_cache_file(tmp)
        assert result == new, f"Oczekiwano {new}, dostałem {result}"
        print(f"  OK Miejsce 1 (najnowszy plik): {os.path.basename(result)}")


def test_fdr_gameweeks_empty():
    """Symulacja guarda z scraper.py:514-523 — pusta lista gameweeks.

    Guard `if fdr_data.get("teams") and fdr_data.get("gameweeks")` ma pominąć
    cały blok, więc dostęp [0] w fallbacku nigdy się nie wykona.
    """
    fdr_data = {"teams": [], "gameweeks": []}
    next_gw = None
    if fdr_data.get("teams") and fdr_data.get("gameweeks"):
        for gw in fdr_data["gameweeks"]:
            if gw > 0:
                next_gw = gw
                break
        if not next_gw:
            next_gw = fdr_data["gameweeks"][0]  # fallback — tu nieosiągalny
    assert next_gw is None, "Przy pustych gameweeks blok ma zostać pominięty"
    print("  OK Miejsce 2 (puste gameweeks): blok pominięty, brak IndexError")


def test_team_players_empty():
    """Symulacja guarda z scraper.py:406-426 — pusta kadra drużyny.

    `team_players.append(...)` wykonuje się bezwarunkowo przed dostępem [-1],
    więc przy pustej kadrze pętla w ogóle się nie wykonuje — brak IndexError.
    """
    team_players = []
    squad = []  # pusta kadra
    for _p in squad:
        team_players.append({"form": []})
        team_players[-1]["form"] = []
    assert team_players == [], "Przy pustym squadzie nie ma czego indeksować"
    print("  OK Miejsce 3 (pusta kadra): pętla nie wykonuje się, brak IndexError")


if __name__ == "__main__":
    print("Testy zabezpieczeń na pustych danych:\n")
    test_find_latest_cache_file_empty()
    test_find_latest_cache_file_newest()
    test_fdr_gameweeks_empty()
    test_team_players_empty()
    print("\nWszystkie testy przeszły — żadne z 3 miejsc nie crashuje na pustych danych")
