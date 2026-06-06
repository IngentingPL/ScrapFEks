"""
league_tracker.py — Kumulatywny tracker pozycji druzyn w lidze prywatnej.

Przy kazdym uruchomieniu scrapera zapisuje stan ligi (pozycje, punkty)
do pliku league_history.json. Stare kolejki sa zachowywane, nowe dopisywane.
Jesli kolejka juz istnieje — aktualizuje ja (nie duplikuje).
"""

import json
import os


def save_round_standings(
    league_data: list[dict],
    round_number: int,
    output_path: str,
) -> None:
    """
    Zapisz stan ligi po danej kolejce do kumulatywnego pliku JSON.

    league_data: lista druzyn z fetch_league_teams() — kazda ma:
        slug, total_points, last_points, max_points, position
    round_number: numer biezacej kolejki
    output_path: sciezka do league_history.json
    """
    if not league_data or not round_number:
        return

    # Zbuduj standings dla tej kolejki
    # Sortuj po pozycji (position z API) lub total_points malejaco
    sorted_teams = sorted(
        league_data,
        key=lambda t: (t.get("position") or 999, -(t.get("total_points") or 0)),
    )

    standings = []
    for i, team in enumerate(sorted_teams):
        slug = team.get("slug", "")
        # Nazwa wyswietlana: display_name jesli dostepny, inaczej slug -> spacje
        display_name = team.get("display_name") or slug.replace("-", " ")
        total_pts = team.get("total_points", 0) or 0
        last_pts = team.get("last_points", 0) or 0
        position = team.get("position") or (i + 1)

        standings.append({
            "team": display_name,
            "slug": slug,
            "total_points": total_pts,
            "position": position,
            "round_points": last_pts,
        })

    new_round = {
        "round": round_number,
        "standings": standings,
    }

    # Wczytaj istniejace dane lub stworz nowe
    history = {"rounds": []}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, dict) or "rounds" not in history:
                history = {"rounds": []}
        except (json.JSONDecodeError, IOError):
            history = {"rounds": []}

    # Sprawdz czy kolejka juz istnieje — jesli tak, zaktualizuj
    existing_idx = None
    for idx, r in enumerate(history["rounds"]):
        if r.get("round") == round_number:
            existing_idx = idx
            break

    if existing_idx is not None:
        history["rounds"][existing_idx] = new_round
    else:
        history["rounds"].append(new_round)

    # Sortuj kolejki po numerze
    history["rounds"].sort(key=lambda r: r["round"])

    # Zapisz plik
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"   📈 Zapisano stan ligi (kolejka {round_number}, {len(standings)} druzyn) -> {os.path.basename(output_path)}")


def load_league_history(output_path: str = "output/league_history.json") -> dict:
    """
    Wczytuje historię ligi z pliku JSON.
    Zwraca dict z kluczem "rounds" — listą kolejek.
    Jeśli plik nie istnieje lub jest uszkodzony, zwraca {"rounds": []}.

    📖 LEKCJA: Ta funkcja to odpowiednik save_round_standings, ale do odczytu.
    Dodana jako alias dla starego API scrapera, które oczekiwało funkcji
    load_league_history().
    """
    if not os.path.exists(output_path):
        return {"rounds": []}
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "rounds" not in data:
            return {"rounds": []}
        return data
    except (json.JSONDecodeError, IOError):
        return {"rounds": []}
