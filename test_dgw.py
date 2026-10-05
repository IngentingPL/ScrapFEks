"""
test_dgw.py — Testy syntetyczne dla Double Gameweek (DGW)
===========================================================

Testy weryfikujące:
1. Drużyna z 2 meczami w kolejce (DGW) → 2 wpisy w fixtures
2. predicted_points = suma dwóch pojedynczych prognoz
3. Kolejka z 1 meczem = wynik jak dotąd (backward compat)

Uruchomienie:
    python test_dgw.py
"""

import sys
import os

# Dodaj katalog główny do ścieżki (żeby importować z repo)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from predictor import predict_points, predict_all_players


def test_dgw_suma_prognoz():
    """
    Test DGW: zawodnik z drużyny grającej 2 mecze w kolejce.
    predicted_points powinno być sumą prognoz z obu meczów.
    """
    print("\n=== Test DGW: suma prognoz ===")
    
    # Zawodnik GKS (ma DGW w K10)
    player = {
        "player_id": 1,
        "name": "Test GKS Zawodnik",
        "team": "gks katowice",  # normalizowana nazwa
        "position": "NAP",
        "total_points": 45,
        "rounds": [
            {"round": 9, "played": True, "points": 8, "minutes": 90},
            {"round": 8, "played": True, "points": 5, "minutes": 90},
            {"round": 7, "played": True, "points": 7, "minutes": 90},
            {"round": 6, "played": True, "points": 6, "minutes": 85},
        ]
    }
    
    # FDR dla rywali
    fdr_data = {
        "rakow czestochowa": {"atk": 4, "def": 4},  # trudny rywal
        "wieczysta krakow": {"atk": 2, "def": 2},   # słaby rywal
    }
    
    # DGW: 2 mecze dla GKS
    fixtures = {
        "gks katowice": [
            {"opponent": "rakow czestochowa", "is_home": False},  # mecz 1
            {"opponent": "wieczysta krakow", "is_home": True},    # mecz 2
        ]
    }
    
    # Prognoza osobno dla każdego meczu (do porównania)
    pred1 = predict_points(player, fdr_data, fixtures["gks katowice"][0])
    pred2 = predict_points(player, fdr_data, fixtures["gks katowice"][1])
    
    print(f"  Mecz 1 (Raków wyjazd): {pred1['predicted_points']} pkt")
    print(f"  Mecz 2 (Wieczysta dom): {pred2['predicted_points']} pkt")
    print(f"  Suma: {pred1['predicted_points'] + pred2['predicted_points']} pkt")
    
    # Pełna prognoza przez predict_all_players
    result = predict_all_players([player], fdr_data, fixtures)
    
    assert len(result) == 1, f"Oczekiwano 1 wynik, otrzymano {len(result)}"
    
    combined = result[0]
    expected_sum = round(pred1['predicted_points'] + pred2['predicted_points'], 1)
    actual_sum = combined['predicted_points']
    
    print(f"  predict_all_players: {actual_sum} pkt")
    print(f"  Opponents: {combined.get('opponents', 'N/A')}")
    print(f"  Fixtures count: {combined.get('fixtures_count', 'N/A')}")
    
    # Porównanie z tolerancją (zaokrąglenia)
    tolerance = 0.2
    assert abs(actual_sum - expected_sum) < tolerance, \
        f"DGW: oczekiwano {expected_sum} pkt, otrzymano {actual_sum}"
    
    # Sprawdź nowe pola DGW
    assert combined.get('fixtures_count') == 2, "DGW: fixtures_count powinno być 2"
    assert len(combined.get('opponents', [])) == 2, "DGW: opponents powinno mieć 2 elementy"
    assert len(combined.get('is_home_list', [])) == 2, "DGW: is_home_list powinno mieć 2 elementy"
    
    print("  ✅ DGW: suma prognoz OK")
    return True


def test_single_match_backward_compat():
    """
    Test backward compat: drużyna z 1 meczem w kolejce.
    Wynik powinien być taki sam jak przed DGW.
    """
    print("\n=== Test Single Match (backward compat) ===")
    
    # Zawodnik Legii (1 mecz w kolejce)
    player = {
        "player_id": 2,
        "name": "Test Legia Zawodnik",
        "team": "legia warszawa",
        "position": "POM",
        "total_points": 60,
        "rounds": [
            {"round": 9, "played": True, "points": 6, "minutes": 90},
            {"round": 8, "played": True, "points": 8, "minutes": 90},
            {"round": 7, "played": True, "points": 4, "minutes": 78},
        ]
    }
    
    # FDR dla rywala
    fdr_data = {
        "wisla krakow": {"atk": 3, "def": 3},
    }
    
    # Normalny mecz (1 mecz)
    fixtures = {
        "legia warszawa": [
            {"opponent": "wisla krakow", "is_home": True},
        ]
    }
    
    # Prognoza przez predict_points
    pred = predict_points(player, fdr_data, fixtures["legia warszawa"][0])
    
    # Prognoza przez predict_all_players
    result = predict_all_players([player], fdr_data, fixtures)
    
    assert len(result) == 1, f"Oczekiwano 1 wynik, otrzymano {len(result)}"
    
    combined = result[0]
    
    print(f"  predict_points: {pred['predicted_points']} pkt")
    print(f"  predict_all_players: {combined['predicted_points']} pkt")
    print(f"  Opponents: {combined.get('opponents', 'N/A')}")
    print(f"  Fixtures count: {combined.get('fixtures_count', 'N/A')}")
    
    # Porównanie
    tolerance = 0.1
    assert abs(combined['predicted_points'] - pred['predicted_points']) < tolerance, \
        f"Single match: oczekiwano {pred['predicted_points']} pkt, otrzymano {combined['predicted_points']}"
    
    # Sprawdź pola (1 mecz)
    assert combined.get('fixtures_count') == 1, "Single: fixtures_count powinno być 1"
    assert len(combined.get('opponents', [])) == 1, "Single: opponents powinno mieć 1 element"
    
    # Backward compat: next_opponent i is_home powinny być dostępne
    assert combined.get('next_opponent') == "wisla krakow", "Single: next_opponent powinno być dostępne"
    assert combined.get('is_home') == True, "Single: is_home powinno być dostępne"
    
    print("  ✅ Single match: backward compat OK")
    return True


def test_dgw_normalizacja_wejscia():
    """
    Test normalizacji wejścia: dict zamiast listy powinien działać.
    (dla backward compat z tuner.py i accuracy.py)
    """
    print("\n=== Test Normalizacja Wejścia (dict -> list) ===")
    
    player = {
        "player_id": 3,
        "name": "Test Stary Format",
        "team": "lech poznan",
        "position": "OBR",
        "total_points": 40,
        "rounds": [
            {"round": 9, "played": True, "points": 5, "minutes": 90},
            {"round": 8, "played": True, "points": 6, "minutes": 90},
        ]
    }
    
    # Stary format: dict zamiast listy
    fdr_data = {
        "gornik zabrze": {"atk": 3, "def": 2},
    }
    
    fixtures = {
        "lech poznan": {"opponent": "gornik zabrze", "is_home": False}  # dict zamiast listy!
    }
    
    # Powinno działać (normalizacja w predict_all_players)
    result = predict_all_players([player], fdr_data, fixtures)
    
    assert len(result) == 1, f"Oczekiwano 1 wynik, otrzymano {len(result)}"
    
    combined = result[0]
    
    print(f"  predicted_points: {combined['predicted_points']} pkt")
    print(f"  fixtures_count: {combined.get('fixtures_count', 'N/A')}")
    
    # Powinno być potraktowane jako lista 1-elementowa
    assert combined.get('fixtures_count') == 1, "Stary format: fixtures_count powinno być 1"
    
    print("  ✅ Normalizacja wejścia OK")
    return True


def test_dgw_wiele_zawodnikow():
    """
    Test mieszany: niektórzy zawodnicy mają DGW, inni nie.
    """
    print("\n=== Test Mieszany (DGW + Single) ===")
    
    players = [
        {
            "player_id": 1,
            "name": "GKS Zawodnik (DGW)",
            "team": "gks katowice",
            "position": "NAP",
            "total_points": 45,
            "rounds": [
                {"round": 9, "played": True, "points": 8, "minutes": 90},
                {"round": 8, "played": True, "points": 7, "minutes": 90},
            ],
        },
        {
            "player_id": 2,
            "name": "Legia Zawodnik (Single)",
            "team": "legia warszawa",
            "position": "POM",
            "total_points": 60,
            "rounds": [
                {"round": 9, "played": True, "points": 6, "minutes": 90},
                {"round": 8, "played": True, "points": 5, "minutes": 90},
            ],
        },
    ]
    
    fdr_data = {
        "rakow czestochowa": {"atk": 4, "def": 4},
        "wieczysta krakow": {"atk": 2, "def": 2},
        "wisla krakow": {"atk": 3, "def": 3},
    }
    
    # DGW dla GKS, Single dla Legii
    fixtures = {
        "gks katowice": [
            {"opponent": "rakow czestochowa", "is_home": False},
            {"opponent": "wieczysta krakow", "is_home": True},
        ],
        "legia warszawa": [
            {"opponent": "wisla krakow", "is_home": True},
        ],
    }
    
    result = predict_all_players(players, fdr_data, fixtures)
    
    assert len(result) == 2, f"Oczekiwano 2 wyniki, otrzymano {len(result)}"
    
    # Znajdź wyniki po nazwiskach
    by_name = {p['name']: p for p in result}
    
    gks_player = by_name.get("GKS Zawodnik (DGW)")
    legia_player = by_name.get("Legia Zawodnik (Single)")
    
    assert gks_player is not None, "Nie znaleziono zawodnika GKS"
    assert legia_player is not None, "Nie znaleziono zawodnika Legii"
    
    print(f"  GKS (DGW): {gks_player['predicted_points']} pkt, fixtures_count={gks_player['fixtures_count']}")
    print(f"  Legia (Single): {legia_player['predicted_points']} pkt, fixtures_count={legia_player['fixtures_count']}")
    
    # Weryfikacja struktury
    assert gks_player['fixtures_count'] == 2, "GKS powinien mieć 2 mecze"
    assert legia_player['fixtures_count'] == 1, "Legia powinna mieć 1 mecz"
    
    # GKS powinien mieć wyższą prognozę (suma z 2 meczów)
    # UWAGA: NAP vs słaby rywal może mieć niższą prognozę niż POM vs średni rywal
    # Sprawdzamy tylko że oba mają poprawne prognozy
    assert gks_player['predicted_points'] is not None and gks_player['predicted_points'] > 0, \
        "GKS powinien mieć prognozę"
    assert legia_player['predicted_points'] is not None and legia_player['predicted_points'] > 0, \
        "Legia powinna mieć prognozę"
    
    # GKS powinien mieć wyższą prognozę (bo ma 2 mecze, nawet jeśli jeden jest trudny)
    # Suma 2 meczów powinna być wyższa niż 1 mecz
    assert gks_player['predicted_points'] > legia_player['predicted_points'], \
        f"GKS (DGW, {gks_player['predicted_points']} pkt) powinien mieć wyższą prognozę niż Legia (Single, {legia_player['predicted_points']} pkt)"
    
    print("  ✅ Mieszany test OK")
    return True


def main():
    """Główna funkcja testująca — uruchamia wszystkie testy."""
    print("=" * 60)
    print("Testy DGW (Double Gameweek)")
    print("=" * 60)
    
    tests = [
        test_dgw_suma_prognoz,
        test_single_match_backward_compat,
        test_dgw_normalizacja_wejscia,
        test_dgw_wiele_zawodnikow,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            if test_func():
                passed += 1
        except AssertionError as e:
            print(f"  ❌ FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Wyniki: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
