#!/usr/bin/env python3
"""
Test rozdzielonej formuły potential_value dla BR, OBR, POM, NAP.
Używa rzeczywistych danych z cache'u Karpińskiego.
Zapisuje log do /tmp/potential_value_test_<timestamp>.log
"""
import sys, os, json
from datetime import datetime

# Dodaj katalog projektu do PYTHONPATH (potrzebne do importów)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from karpinski_client import get_karpinski_stats
from predictor import predict_points

# ------------------------------------------------------------
# Gracze testowi (ID z mostu Karpińskiego)
# ------------------------------------------------------------
TEST_PLAYERS = [
    {"player_id": 2805, "name": "Otto Hindrich",  "position": "BR",  "position_full": "Bramkarz"},
    {"player_id": 1319, "name": "Paweł Wszołek",   "position": "OBR", "position_full": "Obrońca"},
    {"player_id": 2880, "name": "Marko Bozic",     "position": "POM", "position_full": "Pomocnik"},
    {"player_id": 1987, "name": "Jordi Sánchez",   "position": "NAP", "position_full": "Napastnik"},
]

# Minimalne dane potrzebne predict_points (2 rozegrane kolejki, neutralny FDR, brak xA)
FAKE_ROUNDS = [
    {"round": 20, "played": True, "points": 5, "minutes": 90},
    {"round": 19, "played": True, "points": 3, "minutes": 90},
]
FAKE_FDR = {"GKS": {"atk": 3, "def": 3}}
FAKE_FIXTURE = {"opponent": "GKS", "is_home": True}


def compute_manual(player_dict):
    """Ręczne obliczenie potential_value — ta sama logika co w predictor.py."""
    pos = player_dict.get("position", "")
    if pos == "BR":
        gp = player_dict.get("goals_prevented") or 0
        cs = player_dict.get("clean_sheet_rate") or 0
        return gp + cs, {"goals_prevented": gp, "clean_sheet_rate": cs, "formula": "goals_prevented + clean_sheet_rate"}
    elif pos == "OBR":
        cs = player_dict.get("clean_sheet_rate") or 0
        gc = player_dict.get("goals_conceded_per_90") or 0
        xg = player_dict.get("xg_per_90") or 0
        xa = player_dict.get("xa_per_90") or 0
        cc = player_dict.get("chances_created_per_90") or 0
        baza = cs - (gc / 3)
        pv = baza + xg + xa + (cc * 0.1)
        return pv, {
            "clean_sheet_rate": cs, "goals_conceded_per_90": gc,
            "baza = CS - GC/3": round(baza, 4),
            "xg_per_90": xg, "xa_per_90": xa,
            "chances_created_per_90": cc,
            "formula": "baza + xg_per_90 + xa_per_90 + chances_created_per_90 * 0.1",
        }
    else:  # POM, NAP
        s = player_dict.get("shots_per_90") or 0
        cc = player_dict.get("chances_created_per_90") or 0
        return s + cc, {"shots_per_90": s, "chances_created_per_90": cc, "formula": "shots_per_90 + chances_created_per_90"}


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"/tmp/potential_value_test_{timestamp}.log"
    results = []

    header = f"{'='*70}\n  Test potential_value — BR / OBR / POM+NAP (rozdzielona formuła)\n{'='*70}\n"
    results.append(header)

    for tp in TEST_PLAYERS:
        pid = tp["player_id"]
        name = tp["name"]
        pos = tp["position"]
        pos_full = tp["position_full"]

        # Pobierz statystyki Karpińskiego
        stats = get_karpinski_stats(pid)

        if not stats:
            results.append(f"\n{'─'*70}")
            results.append(f"❌ {name} ({pos_full}, ID {pid}): BRAK DANYCH w moście/adv_table")
            results.append(f"{'─'*70}")
            print(f"❌ {name}: brak danych w moście/adv_table")
            continue

        # Zbuduj player dict z polami potrzebnymi do potential_value
        player = {
            "player_id": pid,
            "name": name,
            "position": pos,
            "team": "TEST",
            "rounds": FAKE_ROUNDS.copy(),
            "goals_prevented": stats.get("goals_prevented"),
            "clean_sheet_rate": stats.get("clean_sheet_rate"),
            "goals_conceded_per_90": stats.get("goals_conceded_per_90"),
            "xg_per_90": stats.get("expected_goals"),
            "xa_per_90": stats.get("expected_assists"),
            "shots_per_90": stats.get("shots_per_90"),
            "chances_created_per_90": stats.get("chances_created_per_90"),
            "percentile_xa": stats.get("percentile_xa"),
            "percentile_xg": stats.get("percentile_xg"),
        }

        # Obliczenie ręczne
        manual_pv, components = compute_manual(player)

        # Obliczenie przez predict_points (sprawdzenie czy daje ten sam wynik)
        pred = predict_points(player, FAKE_FDR, FAKE_FIXTURE)
        pred_pv = pred.get("potential_value")

        # Sprawdzenie zgodności
        if pred_pv is not None and manual_pv is not None:
            match = "✅" if abs(manual_pv - pred_pv) < 0.01 else "❌ RÓŻNICA!"
        else:
            match = "⚠️  Nie można porównać (None)"

        section = [
            f"\n{'─'*70}",
            f"🎯 {name}  |  {pos_full} ({pos})  |  ID {pid}",
            f"{'─'*70}",
        ]

        # Wyświetl składowe formuły
        for key, val in components.items():
            if key == "formula":
                section.append(f"  📐 Formuła: {val}")
            elif isinstance(val, float):
                section.append(f"  📊 {key}: {val}")
            else:
                section.append(f"  📊 {key}: {val}")

        section.append(f"")
        section.append(f"  🔢 Ręcznie: potential_value = {round(manual_pv, 4) if manual_pv is not None else 'None'}")
        section.append(f"  🤖 predict_points: potential_value = {pred_pv}")
        section.append(f"  {match}")

        # Pokaż też pozostałe statystyki z adv_table dla kontekstu
        extra = []
        for k in ["expected_assists", "expected_goals", "percentile_xa", "percentile_xg", "rating"]:
            val = stats.get(k)
            if val is not None:
                extra.append(f"     {k}: {val}")
        if extra:
            section.append(f"  📋 Pozostałe statystyki Karpińskiego:")
            section.extend(extra)

        section.append(f"{'─'*70}")
        results.extend(section)

        for line in section:
            print(line)

    # Podsumowanie
    summary = [
        f"\n{'='*70}",
        f"  Test zakończony — {datetime.now().isoformat()}",
        f"  Gracze: Hindrich (BR), Wszołek (OBR), Bozic (POM), Sánchez (NAP)",
        f"  Log zapisany do: {log_path}",
        f"{'='*70}",
    ]
    results.extend(summary)

    # Zapisz do pliku
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(results))

    for line in summary:
        print(line)


if __name__ == "__main__":
    main()
