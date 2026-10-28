"""Testy logiki wyboru i zapisu Najlepszej Jedenastki."""

import csv
import json
import os
import tempfile

from best11 import (
    FORMACJE,
    MNOZNIK_KAPITANA,
    aktualizuj_historie_best11,
    czy_kolejka_jest_kompletna,
    najlepszy_cmf,
    normalizuj_prognozy,
    wybierz_formacje_i_sklad,
    wybierz_sklad,
    zapisz_nastepny_sklad,
)


def _prognozy_testowe():
    """Przygotowuje wystarczająco dużą pulę graczy na wszystkie formacje."""
    gracze = [
        {"player_id": "gk", "name": "Bramkarz", "team": "A", "position": "BR", "predicted_points": 10},
        {"player_id": "d1", "name": "Def 1", "team": "A", "position": "OBR", "predicted_points": 10},
        {"player_id": "d2", "name": "Def 2", "team": "B", "position": "OBR", "predicted_points": 9},
        {"player_id": "d3", "name": "Def 3", "team": "C", "position": "OBR", "predicted_points": 8},
        {"player_id": "d4", "name": "Def 4", "team": "D", "position": "OBR", "predicted_points": 7},
        {"player_id": "d5", "name": "Def 5", "team": "E", "position": "OBR", "predicted_points": 1},
        {"player_id": "m1", "name": "Mid 1", "team": "A", "position": "POM", "predicted_points": 12},
        {"player_id": "m2", "name": "Mid 2", "team": "B", "position": "POM", "predicted_points": 11},
        {"player_id": "m3", "name": "Mid 3", "team": "C", "position": "POM", "predicted_points": 10},
        {"player_id": "m4", "name": "Mid 4", "team": "D", "position": "POM", "predicted_points": 9},
        {"player_id": "m5", "name": "Mid 5", "team": "E", "position": "POM", "predicted_points": 8},
        {"player_id": "f1", "name": "Fwd 1", "team": "A", "position": "NAP", "predicted_points": 13},
        {"player_id": "f2", "name": "Fwd 2", "team": "B", "position": "NAP", "predicted_points": 6},
        {"player_id": "f3", "name": "Fwd 3", "team": "C", "position": "NAP", "predicted_points": 5},
    ]
    for index, player in enumerate(gracze):
        player.update({
            "opponents": [f"Rywal {index}"],
            "is_home_list": [index % 2 == 0],
            "fixtures_count": 1,
        })
    return gracze


def test_limity_pozycji_dla_kazdej_formacji():
    """Każda formacja zawiera dokładnie 1 GK i poprawną liczbę graczy z pola."""
    prognozy = normalizuj_prognozy(_prognozy_testowe())
    assert FORMACJE == [
        (3, 4, 3), (3, 5, 2), (4, 3, 3), (4, 4, 2),
        (4, 5, 1), (5, 3, 2), (5, 4, 1),
    ]
    for formacja in FORMACJE:
        sklad = wybierz_sklad(prognozy, formacja)
        assert sklad is not None
        assert len(sklad) == 11
        assert sum(p["position"] == "GK" for p in sklad) == 1
        assert sum(p["position"] == "DEF" for p in sklad) == formacja[0]
        assert sum(p["position"] == "MID" for p in sklad) == formacja[1]
        assert sum(p["position"] == "FWD" for p in sklad) == formacja[2]


def test_wybiera_najlepsza_formacje_na_przykladzie():
    """Ręcznie policzony wynik wskazuje 4-5-1 jako najlepszą formację."""
    wynik = wybierz_formacje_i_sklad(normalizuj_prognozy(_prognozy_testowe()))
    assert wynik is not None
    formacja, sklad, kapitan, suma = wynik
    # 4-5-1: 10 + 34 + 50 + 13 = 107; kapitan Fwd 1 dodaje jeszcze 13.
    assert formacja == (4, 5, 1)
    assert len(sklad) == 11
    assert suma == 120
    assert kapitan["name"] == "Fwd 1"


def test_kapitan_ma_najwyzsza_prognoze_i_mnoznik_x2():
    """Kapitan ma najwyższą prognozę, a jego punkty realne liczą się x2."""
    prognozy = normalizuj_prognozy(_prognozy_testowe())
    formacja, sklad, kapitan, _ = wybierz_formacje_i_sklad(prognozy)
    assert kapitan["predicted"] == max(p["predicted"] for p in sklad)
    assert MNOZNIK_KAPITANA == 2

    from best11 import zbuduj_wpis_historii

    wpis = zbuduj_wpis_historii(
        12,
        _prognozy_testowe(),
        lambda player_id: 3 if player_id == "f1" else 0,
        {"name": "CMF", "points": 20},
    )
    assert wpis["captain"] == "Fwd 1"
    kapitan_wpis = next(p for p in wpis["players"] if p["is_captain"])
    assert kapitan_wpis["actual"] == 3  # zapisujemy bazowe punkty gracza
    assert wpis["actual_total"] == 6  # suma uwzględnia mnożnik kapitana


def test_za_malo_graczy_zwraca_none():
    """Niepełna pula nie może utworzyć niepełnego składu."""
    tylko_bramkarz_i_obroncy = [
        {"name": "GK", "position": "BR", "predicted_points": 1},
        {"name": "Def 1", "position": "OBR", "predicted_points": 1},
        {"name": "Def 2", "position": "OBR", "predicted_points": 1},
    ]
    assert wybierz_formacje_i_sklad(normalizuj_prognozy(tylko_bramkarz_i_obroncy)) is None


def test_zapis_historii_jest_idempotentny():
    """Powtórna ocena tej samej kolejki zastępuje wpis zamiast go dublować."""
    with tempfile.TemporaryDirectory() as katalog:
        csv_path = os.path.join(katalog, "predictions.csv")
        league_path = os.path.join(katalog, "league_history.json")
        history_path = os.path.join(katalog, "best11_history.json")
        prognozy = _prognozy_testowe()
        with open(csv_path, "w", newline="", encoding="utf-8") as plik:
            writer = csv.DictWriter(plik, fieldnames=list(prognozy[0]) + ["round_number"])
            writer.writeheader()
            for row in prognozy:
                writer.writerow({**row, "round_number": 12})
        with open(league_path, "w", encoding="utf-8") as plik:
            json.dump({"rounds": [{
                "round": 12,
                "standings": [{"team": "CMF Najlepsi", "round_points": 20}],
            }]}, plik)
        terminarz_path = os.path.join(katalog, "terminarz.txt")
        with open(terminarz_path, "w", encoding="utf-8") as plik:
            plik.write("Kolejka 12\nA\t2 : 1\tB\t23 października,\n")
        fixtures_data = {"matches": {"12": [{"home": "A", "away": "B"}]}}

        gracze = [
            {"player_id": row["player_id"], "rounds": [
                {"round": 12, "played": True, "points": 3 if row["player_id"] == "f1" else 0}
            ]}
            for row in prognozy
        ]
        pierwszy = aktualizuj_historie_best11(
            12, csv_path, gracze, [], league_path, history_path,
            fixtures_data=fixtures_data,
            terminarz_path=terminarz_path,
        )
        drugi = aktualizuj_historie_best11(
            12, csv_path, gracze, [], league_path, history_path,
            fixtures_data=fixtures_data,
            terminarz_path=terminarz_path,
        )
        assert len(pierwszy) == len(drugi) == 1
        assert drugi[0]["round"] == 12
        with open(history_path, encoding="utf-8") as plik:
            zapisane = json.load(plik)
        assert len(zapisane) == 1


def test_niekompletna_kolejka_nie_zapisuje_ani_nie_nadpisuje():
    """Wynik bez jednego z zaplanowanych meczów nie zmienia historii."""
    with tempfile.TemporaryDirectory() as katalog:
        history_path = os.path.join(katalog, "best11_history.json")
        league_path = os.path.join(katalog, "league_history.json")
        terminarz_path = os.path.join(katalog, "terminarz.txt")
        poprzedni_wpis = [{"round": 12, "formation": "stary wpis"}]
        with open(history_path, "w", encoding="utf-8") as plik:
            json.dump(poprzedni_wpis, plik)
        with open(league_path, "w", encoding="utf-8") as plik:
            json.dump({"rounds": []}, plik)
        with open(terminarz_path, "w", encoding="utf-8") as plik:
            plik.write(
                "Kolejka 12\n"
                "A\t2 : 1\tB\t23 października,\n"
                "C\t18:00\tD\t25 października, 18:00\n"
            )
        fixtures_data = {"matches": {"12": [
            {"home": "A", "away": "B"},
            {"home": "C", "away": "D"},
        ]}}
        assert not czy_kolejka_jest_kompletna(12, fixtures_data, terminarz_path)

        przed = open(history_path, "rb").read()
        po = aktualizuj_historie_best11(
            12,
            predictions_csv_path=None,
            players_data=[],
            accuracy_history=[],
            league_history_path=league_path,
            history_path=history_path,
            fixtures_data=fixtures_data,
            terminarz_path=terminarz_path,
        )
        assert po == poprzedni_wpis
        assert open(history_path, "rb").read() == przed


def test_kolejka_kompletna_wymaga_wynikow_dgw():
    """DGW jest kompletne tylko wtedy, gdy wynik ma każdy z jego meczów."""
    with tempfile.TemporaryDirectory() as katalog:
        terminarz_path = os.path.join(katalog, "terminarz.txt")
        with open(terminarz_path, "w", encoding="utf-8") as plik:
            plik.write(
                "Kolejka 12\n"
                "A\t2 : 1\tB\t23 października,\n"
                "A\t0 : 0\tC\t25 października,\n"
            )
        fixtures_data = {"matches": {"12": [
            {"home": "A", "away": "B"},
            {"home": "A", "away": "C"},
        ]}}
        assert czy_kolejka_jest_kompletna(12, fixtures_data, terminarz_path)


def test_nazwa_cmf_pochodzi_z_tabeli_ligi():
    """Wpis CMF używa nazwy wyświetlanej i zachowuje slug."""
    wynik = najlepszy_cmf(
        {"rounds": [{"round": 12, "standings": [
            {"team": "wynalazcy wslizgu", "slug": "wynalazcy-wslizgu", "round_points": 57},
        ]}]},
        12,
        [{"slug": "wynalazcy-wslizgu", "display_name": "Wynalazcy Wslizgu"}],
    )
    assert wynik == {
        "name": "Wynalazcy Wslizgu",
        "slug": "wynalazcy-wslizgu",
        "points": 57.0,
    }


def test_historia_oznacza_brakujace_details_jako_przyblizone():
    """Niepełna liczba details w porównaniu z forecastem oznacza przybliżenie."""
    with tempfile.TemporaryDirectory() as katalog:
        csv_path = os.path.join(katalog, "predictions.csv")
        league_path = os.path.join(katalog, "league_history.json")
        history_path = os.path.join(katalog, "best11_history.json")
        terminarz_path = os.path.join(katalog, "terminarz.txt")
        prognozy = _prognozy_testowe()
        with open(csv_path, "w", newline="", encoding="utf-8") as plik:
            writer = csv.DictWriter(plik, fieldnames=list(prognozy[0]) + ["round_number"])
            writer.writeheader()
            for row in prognozy:
                writer.writerow({**row, "round_number": 12})
        with open(league_path, "w", encoding="utf-8") as plik:
            json.dump({"rounds": []}, plik)
        with open(terminarz_path, "w", encoding="utf-8") as plik:
            plik.write("Kolejka 12\nA\t1 : 0\tB\t23 października,\n")
        fixtures_data = {"matches": {"12": [{"home": "A", "away": "B"}]}}
        entry = {
            "round": 12,
            "predictions": prognozy,
            "details": [{"player_id": "f1", "actual": 2}],
        }
        wpisy = aktualizuj_historie_best11(
            12,
            predictions_csv_path=None,
            players_data=[],
            accuracy_history=[entry],
            league_history_path=league_path,
            history_path=history_path,
            fixtures_data=fixtures_data,
            expected_forecast_count=10,
            terminarz_path=terminarz_path,
        )
        assert wpisy[0]["zrodlo"] == "przyblizone"
        assert "różnica: 9" in wpisy[0]["zrodlo_info"]


def test_pick_zapisuje_tylko_kolejke_prognozy_i_zachowuje_pozostale():
    """Nowy przebieg zmienia swój pick, ale nie rusza picków innych kolejek."""
    with tempfile.TemporaryDirectory() as katalog:
        picks_path = os.path.join(katalog, "best11_picks.json")
        next_path = os.path.join(katalog, "best11_next.json")
        stare = {
            "11": {"round": 11, "players": [{"name": "Pick K11"}]},
            "12": {"round": 12, "players": [{"name": "Pick K12"}]},
        }
        with open(picks_path, "w", encoding="utf-8") as plik:
            json.dump(stare, plik)

        pick13 = zapisz_nastepny_sklad(_prognozy_testowe(), 13, next_path, picks_path)
        with open(picks_path, encoding="utf-8") as plik:
            po_k13 = json.load(plik)
        assert set(po_k13) == {"11", "12", "13"}
        assert po_k13["11"] == stare["11"]
        assert po_k13["12"] == stare["12"]
        assert po_k13["13"]["round"] == 13
        assert po_k13["13"]["saved_at"]
        assert pick13["round"] == 13

        zapisz_nastepny_sklad(_prognozy_testowe(), 14, next_path, picks_path)
        with open(picks_path, encoding="utf-8") as plik:
            po_k14 = json.load(plik)
        assert po_k14["13"] == po_k13["13"]
        assert po_k14["11"] == stare["11"]
        assert po_k14["12"] == stare["12"]
        assert po_k14["14"]["round"] == 14


def test_picki_sa_przycinane_do_10_najnowszych_kolejek():
    """Po zapisie kolejki 11 zostają tylko picki 2–11."""
    with tempfile.TemporaryDirectory() as katalog:
        picks_path = os.path.join(katalog, "best11_picks.json")
        next_path = os.path.join(katalog, "best11_next.json")
        with open(picks_path, "w", encoding="utf-8") as plik:
            json.dump({str(r): {"round": r} for r in range(1, 11)}, plik)
        zapisz_nastepny_sklad(_prognozy_testowe(), 11, next_path, picks_path)
        with open(picks_path, encoding="utf-8") as plik:
            zapisane = json.load(plik)
        assert set(zapisane) == {str(r) for r in range(2, 12)}


def test_pola_ui_sa_w_nastepnym_skladzie_i_historii():
    """Każdy zawodnik ma ID, rywali, liczbę meczów i bool kapitana."""
    with tempfile.TemporaryDirectory() as katalog:
        next_path = os.path.join(katalog, "best11_next.json")
        picks_path = os.path.join(katalog, "best11_picks.json")
        payload = zapisz_nastepny_sklad(
            _prognozy_testowe(), 13, next_path, picks_path
        )
        assert len(payload["players"]) == 11
        for player in payload["players"]:
            assert player["id"]
            assert player["opponents"]
            assert player["is_home_list"]
            assert isinstance(player["fixtures_count"], int)
            assert isinstance(player["is_captain"], bool)
        assert sum(player["is_captain"] for player in payload["players"]) == 1


def test_zrodlo_oceny_ma_kolejnosc_pick_csv_accuracy():
    """Ocena używa najpierw picku, potem CSV, a na końcu accuracy history."""
    with tempfile.TemporaryDirectory() as katalog:
        csv_path = os.path.join(katalog, "predictions.csv")
        league_path = os.path.join(katalog, "league_history.json")
        history_path = os.path.join(katalog, "best11_history.json")
        picks_path = os.path.join(katalog, "best11_picks.json")
        next_path = os.path.join(katalog, "best11_next.json")
        terminarz_path = os.path.join(katalog, "terminarz.txt")
        prognozy = _prognozy_testowe()
        with open(csv_path, "w", newline="", encoding="utf-8") as plik:
            writer = csv.DictWriter(plik, fieldnames=list(prognozy[0]) + ["round_number"])
            writer.writeheader()
            for row in prognozy:
                writer.writerow({**row, "round_number": 12})
        with open(league_path, "w", encoding="utf-8") as plik:
            json.dump({"rounds": []}, plik)
        with open(terminarz_path, "w", encoding="utf-8") as plik:
            plik.write("Kolejka 12\nA\t2 : 1\tB\t23 października,\n")
        fixtures_data = {"matches": {"12": [{"home": "A", "away": "B"}]}}

        # Najpierw jest zapisany pick, choć dostępny jest też CSV.
        zapisz_nastepny_sklad(prognozy, 12, next_path, picks_path)
        wpisy = aktualizuj_historie_best11(
            12, csv_path, [], [], league_path, history_path,
            fixtures_data=fixtures_data, terminarz_path=terminarz_path,
            picks_path=picks_path,
        )
        assert wpisy[-1]["zrodlo"] == "zapisany"

        # Bez picku używany jest CSV.
        with open(picks_path, "w", encoding="utf-8") as plik:
            json.dump({}, plik)
        wpisy = aktualizuj_historie_best11(
            12, csv_path, [], [], league_path, history_path,
            fixtures_data=fixtures_data, terminarz_path=terminarz_path,
            picks_path=picks_path,
        )
        assert wpisy[-1]["zrodlo"] == "csv"

        # Bez picku i CSV pozostaje przybliżone źródło accuracy history.
        os.remove(csv_path)
        wpisy = aktualizuj_historie_best11(
            12, None, [], [{
                "round": 12,
                "predictions": prognozy,
                "details": [{"player_id": "f1", "actual": 2}],
            }], league_path, history_path,
            fixtures_data=fixtures_data, terminarz_path=terminarz_path,
            picks_path=picks_path,
        )
        assert wpisy[-1]["zrodlo"] == "przyblizone"
        for player in wpisy[-1]["players"]:
            assert player["id"]
            assert "opponents" in player
            assert "is_home_list" in player
            assert isinstance(player["fixtures_count"], int)
            assert isinstance(player["is_captain"], bool)


if __name__ == "__main__":
    test_limity_pozycji_dla_kazdej_formacji()
    test_wybiera_najlepsza_formacje_na_przykladzie()
    test_kapitan_ma_najwyzsza_prognoze_i_mnoznik_x2()
    test_za_malo_graczy_zwraca_none()
    test_zapis_historii_jest_idempotentny()
    test_niekompletna_kolejka_nie_zapisuje_ani_nie_nadpisuje()
    test_kolejka_kompletna_wymaga_wynikow_dgw()
    test_nazwa_cmf_pochodzi_z_tabeli_ligi()
    test_historia_oznacza_brakujace_details_jako_przyblizone()
    test_pick_zapisuje_tylko_kolejke_prognozy_i_zachowuje_pozostale()
    test_picki_sa_przycinane_do_10_najnowszych_kolejek()
    test_pola_ui_sa_w_nastepnym_skladzie_i_historii()
    test_zrodlo_oceny_ma_kolejnosc_pick_csv_accuracy()
    print("Wszystkie testy Best11 przeszły")
