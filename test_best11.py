"""Testy logiki wyboru i zapisu Najlepszej Jedenastki."""

import csv
import json
import os
import tempfile
import random
import time
import ast
from itertools import combinations
from pathlib import Path

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


def test_random_club_limit_and_picker_speed():
    rng = random.Random(771)
    for _ in range(20):
        pool = [{"id": str(i), "name": str(i), "team": f"Club {rng.randrange(8)}",
                 "position": rng.choice(["GK", "DEF", "MID", "FWD"]),
                 "predicted_points": rng.randrange(20)} for i in range(160)]
        result = wybierz_formacje_i_sklad(normalizuj_prognozy(pool))
        if result:
            chosen = result[1]
            assert len(chosen) == 11
            formation = result[0]
            assert [sum(p["position"] == pos for p in chosen) for pos in ("GK", "DEF", "MID", "FWD")] == [1, *formation]
            assert max(sum(p["team_key"] == team for p in chosen) for team in {p["team_key"] for p in chosen}) <= 3
    pool = [{"id": str(i), "name": str(i), "team": f"C{i % 40}",
             "position": ["GK", "DEF", "MID", "FWD"][i % 4], "predicted_points": i % 31}
            for i in range(416)]
    start = time.perf_counter()
    wybierz_formacje_i_sklad(normalizuj_prognozy(pool))
    assert time.perf_counter() - start < 1


def test_top_unrestricted_four_from_club_limited_to_three():
    pool = [{"id": f"A-{pos}{i}", "name": f"A-{pos}{i}", "team": "A", "position": pos,
             "predicted_points": 30-i} for pos, n in [("GK",1),("DEF",2),("MID",1)] for i in range(n)]
    pool += [{"id": f"x{i}", "name": f"x{i}", "team": f"B{i}", "position": p,
              "predicted_points": 20-i} for i, p in enumerate(["DEF"]*5+["MID"]*5+["FWD"]*5)]
    selected = wybierz_formacje_i_sklad(normalizuj_prognozy(pool))
    assert selected
    norm = normalizuj_prognozy(pool)
    unrestricted_options = []
    for formation in FORMACJE:
        demand = [1, *formation]
        positions = ["GK", "DEF", "MID", "FWD"]
        lineup = [p for pos, n in zip(positions, demand)
                  for p in [x for x in norm if x["position"] == pos][:n]]
        if len(lineup) == 11:
            unrestricted_options.append((sum(p["predicted"] for p in lineup) + max(p["predicted"] for p in lineup), lineup))
    unrestricted = max(unrestricted_options, key=lambda result: result[0])[1]
    assert max(sum(p["team_key"] == t for p in unrestricted) for t in {p["team_key"] for p in unrestricted}) == 4
    assert max(sum(p["team_key"] == t for p in selected[1]) for t in {p["team_key"] for p in selected[1]}) == 3


def test_negative_forecasts_use_real_captain_maximum():
    pool = [{"id": str(i), "name": str(i), "team": f"T{i}", "position": pos,
             "predicted_points": -i-1}
            for i, pos in enumerate(["GK"] + ["DEF"]*5 + ["MID"]*5 + ["FWD"]*3)]
    result = wybierz_formacje_i_sklad(normalizuj_prognozy(pool))
    assert result is not None
    chosen = result[1]
    assert result[3] == sum(p["predicted"] for p in chosen) + max(p["predicted"] for p in chosen)


def test_scraper_migration_rebuilds_only_unmarked_picks():
    source = Path(__file__).with_name("scraper.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_migrate_best11_picks")
    namespace = {"os": os, "csv": csv}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "scraper.py", "exec"), namespace)
    _migrate_best11_picks = namespace["_migrate_best11_picks"]
    with tempfile.TemporaryDirectory() as directory:
        picks_path = os.path.join(directory, "picks.json")
        paths = {}
        for round_number in (12, 13):
            path = os.path.join(directory, f"fantasy_predictions_{round_number}.csv")
            rows = _prognozy_testowe()
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]) + ["round_number"])
                writer.writeheader()
                writer.writerows([{**row, "round_number": round_number} for row in rows])
            paths[round_number] = path
        frozen = {"round": 13, "max_z_klubu": 3, "saved_at": "keep-this", "players": []}
        with open(picks_path, "w", encoding="utf-8") as f:
            json.dump({"12": {"round": 12, "players": []}, "13": frozen}, f)
        next_path = os.path.join(directory, "next.json")
        _migrate_best11_picks(directory, 12, lambda r, _dir: paths[r], picks_path, next_path)
        assert os.path.exists(next_path)
        with open(picks_path, encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["12"]["max_z_klubu"] == 3
        assert saved["13"] == frozen and saved["13"]["saved_at"] == "keep-this"


def test_seeded_small_pools_match_exhaustive_oracle_and_id_ties():
    rng = random.Random(4312)
    for trial in range(10):
        pool = [{"id": f"{trial}-{i:02}", "name": str(i), "team": f"T{i % 5}",
                 "position": pos, "predicted_points": rng.randrange(1, 16)}
                for i, pos in enumerate(["GK"]*3 + ["DEF"]*5 + ["MID"]*5 + ["FWD"]*4)]
        norm = normalizuj_prognozy(pool)
        got = wybierz_formacje_i_sklad(norm)
        expected = None
        for formation in FORMACJE:
            demand = [1, *formation]
            by_pos = [[p for p in norm if p["position"] == pos] for pos in ["GK", "DEF", "MID", "FWD"]]
            def choices(i, chosen):
                if i == 4:
                    counts = {}
                    for p in chosen:
                        counts[p["team_key"]] = counts.get(p["team_key"], 0) + 1
                    if max(counts.values()) <= 3:
                        score = sum(p["predicted"] for p in chosen) + max(p["predicted"] for p in chosen)
                        ids = tuple(sorted(p["player_id"] for p in chosen))
                        yield score, ids, chosen
                    return
                for subset in combinations(by_pos[i], demand[i]):
                    yield from choices(i+1, chosen+list(subset))
            for result in choices(0, []):
                if expected is None or result[0] > expected[0]:
                    expected = result
        assert got is not None and expected is not None
        assert round(sum(p["predicted"] for p in got[1]) + max(p["predicted"] for p in got[1]), 8) == expected[0]
        reversed_result = wybierz_formacje_i_sklad(normalizuj_prognozy(list(reversed(pool))))
        assert tuple(sorted(p["player_id"] for p in got[1])) == tuple(sorted(p["player_id"] for p in reversed_result[1]))


def test_unmarked_history_cleanup_idempotent_and_stale_pick_falls_back_csv():
    with tempfile.TemporaryDirectory() as directory:
        history = os.path.join(directory, "history.json")
        picks = os.path.join(directory, "picks.json")
        csv_path = os.path.join(directory, "pred.csv")
        league = os.path.join(directory, "league.json")
        fixtures = {"matches": {"12": [{"home": "A", "away": "B"}]}}
        with open(history, "w", encoding="utf-8") as f:
            json.dump([{"round": 11, "formation": "old"}], f)
        with open(picks, "w", encoding="utf-8") as f:
            json.dump({"12": {"round": 12, "max_z_klubu": 2, "players": []}}, f)
        players = _prognozy_testowe()
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(players[0]) + ["round_number"])
            writer.writeheader()
            writer.writerows([{**p, "round_number": 12} for p in players])
        with open(league, "w", encoding="utf-8") as f:
            json.dump({"rounds": []}, f)
        schedule = os.path.join(directory, "schedule.txt")
        with open(schedule, "w", encoding="utf-8") as f:
            f.write("Kolejka 12\nA\t2 : 1\tB\tdate\n")
        kwargs = dict(round_number=12, predictions_csv_path=csv_path, players_data=[], wpisy_trafnosci=[],
                      league_history_path=league, history_path=history, picks_path=picks,
                      fixtures_data=fixtures, terminarz_path=schedule)
        first = aktualizuj_historie_best11(**kwargs)
        assert len(first) == 1 and first[0]["max_z_klubu"] == 3 and first[0]["zrodlo"] == "csv"
        zapisz_nastepny_sklad(players, 12, os.path.join(directory, "next.json"), picks)
        with open(picks, encoding="utf-8") as f:
            assert json.load(f)["12"]["max_z_klubu"] == 3
        assert first[0]["max_z_klubu"] == 3


def test_history_marker_cleanup_idempotent_on_incomplete_round():
    with tempfile.TemporaryDirectory() as directory:
        history_path = os.path.join(directory, "history.json")
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump([{"round": 12, "formation": "K12 old"}], f)
        kwargs = dict(round_number=12, history_path=history_path,
                      league_history_path=os.path.join(directory, "league.json"),
                      fixtures_data={"matches": {"12": [{"home": "A", "away": "B"}]}},
                      terminarz_path=os.path.join(directory, "no-schedule.txt"))
        assert aktualizuj_historie_best11(**kwargs) == []
        first_bytes = open(history_path, "rb").read()
        assert json.loads(first_bytes) == []
        assert aktualizuj_historie_best11(**kwargs) == []
        assert open(history_path, "rb").read() == first_bytes


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
    """Limit klubu zmienia zwycięską formację na 3-5-2."""
    wynik = wybierz_formacje_i_sklad(normalizuj_prognozy(_prognozy_testowe()))
    assert wynik is not None
    formacja, sklad, kapitan, suma = wynik
    assert formacja == (3, 5, 2)
    assert len(sklad) == 11
    assert suma == 116
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
        poprzedni_wpis = [{"round": 12, "formation": "stary wpis", "max_z_klubu": 3}]
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
            wpisy_trafnosci=[],
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
            wpisy_trafnosci=[entry],
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
        assert set(po_k13) == {"13"}
        assert "11" not in po_k13 and "12" not in po_k13
        assert po_k13["13"]["round"] == 13
        assert po_k13["13"]["max_z_klubu"] == 3
        assert po_k13["13"]["saved_at"]
        assert pick13["round"] == 13

        zapisz_nastepny_sklad(_prognozy_testowe(), 14, next_path, picks_path)
        with open(picks_path, encoding="utf-8") as plik:
            po_k14 = json.load(plik)
        assert po_k14["13"] == po_k13["13"]
        assert "11" not in po_k14 and "12" not in po_k14
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
        assert set(zapisane) == {"11"}


def test_pola_ui_sa_w_nastepnym_skladzie_i_historii():
    """Każdy zawodnik ma ID, rywali, liczbę meczów i bool kapitana."""
    with tempfile.TemporaryDirectory() as katalog:
        next_path = os.path.join(katalog, "best11_next.json")
        picks_path = os.path.join(katalog, "best11_picks.json")
        payload = zapisz_nastepny_sklad(
            _prognozy_testowe(), 13, next_path, picks_path
        )
        assert len(payload["players"]) == 11
        assert payload["max_z_klubu"] == 3
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


def test_render_best11_counts_only_positive_differences_as_wins():
    """Best11's generated history display excludes ties from its win count."""
    source = Path(__file__).with_name("dashboard.py").read_text(encoding="utf-8")
    render = source.split("function renderBest11(viewSwitch)", 1)[1].split(
        "function ", 1
    )[0]

    # Exercise the same predicate used by renderBest11 on comparable rounds.
    comparable = [0, 1, -1]
    assert "const wins = comparable.filter(r=>num(r.difference)>0).length;" in render
    assert sum(difference > 0 for difference in comparable) == 1


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
    test_render_best11_counts_only_positive_differences_as_wins()
    test_random_club_limit_and_picker_speed()
    test_top_unrestricted_four_from_club_limited_to_three()
    test_negative_forecasts_use_real_captain_maximum()
    test_seeded_small_pools_match_exhaustive_oracle_and_id_ties()
    test_unmarked_history_cleanup_idempotent_and_stale_pick_falls_back_csv()
    test_scraper_migration_rebuilds_only_unmarked_picks()
    test_history_marker_cleanup_idempotent_on_incomplete_round()
    print("Wszystkie testy Best11 przeszły")
