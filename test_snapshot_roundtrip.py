#!/usr/bin/env python3
"""
Test round-trip snapshotu dashboardu.

Sprawdza, że:
1. Snapshot zapisany przez snapshot.py ma stałą strukturę i kolejność kluczy
   (schema_version, generated_at, inputs) — także w surowym tekście JSON.
2. HTML wygenerowany bezpośrednio ze słownika danych jest BAJT W BAJT
   identyczny z HTML wygenerowanym po round-tripie przez snapshot JSON.

Tylko biblioteka standardowa, bez sieci. Uruchom: python test_snapshot_roundtrip.py
"""
import json
import os
import tempfile

from snapshot import build_snapshot, save_dashboard_snapshot, load_dashboard_snapshot, SCHEMA_VERSION
from dashboard import generate_dashboard_html


def make_sample_inputs(filename: str) -> dict:
    """Mały, ale reprezentatywny zestaw 20 kluczy wejściowych dashboardu.

    Zawiera wszystkie typy używane przez dashboard.py: list[dict], dict,
    int, str, bool, list, None. Bez kluczy int i bez krotek — JSON ich
    nie toleruje (int → str, krotka → lista), patrz uwaga na końcu pliku.
    """
    return dict(
        # list[dict] — statystyki zawodników
        summary_data=[
            {
                "player_id": "p1",
                "name": "Jan Kowalski",
                "team": "Legia",
                "position": "FW",
                "price": 8.5,
                "points": 120,
                "points_per_price": 14.1,
                "form": [{"r": 10, "p": 8}, {"r": 11, "p": 12}],
                "ownership": 42,
            },
            {
                "player_id": "p2",
                "name": "Piotr Nowak",
                "team": "Lech",
                "position": "MF",
                "price": 6.0,
                "points": 90,
                "points_per_price": 15.0,
                "form": [{"r": 11, "p": 5}],
                "ownership": 15,
            },
        ],
        # dict — tier'y (top10/top100/all) z count/captains/ownership
        tiers={
            "top10": {"count": 10, "captains": [{"id": "p1", "count": 3}], "ownership": [{"id": "p1", "count": 4}]},
            "top100": {"count": 100, "captains": [{"id": "p2", "count": 1}], "ownership": []},
            "all": {"count": 200, "captains": [], "ownership": [{"id": "p2", "count": 9}]},
        },
        teams_count=10,  # int
        # list[dict] — statystyki kapitanów ligi
        league_captain_stats=[{"id": "p1", "name": "Jan Kowalski", "count": 5}],
        # list[dict] — ownership ligi
        league_ownership_stats=[{"id": "p2", "name": "Piotr Nowak", "count": 2}],
        league_name="discord-fmforumcmf",  # str
        league_teams_count=12,  # int
        # dict — rostery ligi: klucz = id zawodnika (str!), wartość = lista słowników
        league_rosters={
            "p1": [{"user": "Użytkownik A", "team": "Drużyna X", "pos": 1}],
            "p2": [],
        },
        # list[dict] — drużyny ligi
        league_teams_detail=[
            {"slug": "druzyna-x", "display_name": "Drużyna X", "total_pts": 55, "rank_change": 0},
            {"slug": "druzyna-y", "display_name": "Drużyna Y", "total_pts": 48, "rank_change": 1},
        ],
        # list[dict] — duety
        duets_data=[{"name": "Duet A", "users": ["Użytkownik A", "Użytkownik B"], "pts": 103}],
        # dict — terminarz (klucze matches to STR, bo JSON zamienia int na str)
        fixtures_data={
            "rounds": [10, 11],
            "matches": {"10": [{"home": "Legia", "away": "Lech", "date": "2026-01-10"}]},
            "teams": ["Legia", "Lech"],
            "abbrevs": {},
        },
        # dict — ekstra statystyki z API ekstraklasa.org
        ekstra_stats={"p1": {"xg": 3.2, "shots": 15}},
        # dict — FDR
        fdr_data={"teams": {"Legia": {"next": "home"}}, "gameweeks": [11]},
        # dict — transfery
        transfers_data={"transfers_in": [], "transfers_out": [{"player": "Nowak", "to": "Lech"}]},
        # list[dict] — prognozy
        predictions_data=[
            {"player_id": "p1", "name": "Jan Kowalski", "predicted": 9, "confidence": "wysoka", "fdr": 2, "xa90": 0.3, "xg90": 0.5, "dgw": False}
        ],
        prediction_round=11,  # int
        # list[dict] — historia trafności
        accuracy_history=[{"round": 10, "hits": 6, "total": 12}],
        tuned_params=None,  # None — może być puste
        # dict — historia ligi
        league_history={"rounds": [{"round": 10, "ranking": {"Drużyna X": 1}}]},
        filename=filename,  # str — ścieżka wyjściowa
    )


def test_snapshot_structure():
    """Struktura snapshotu: kolejność kluczy, wersja schematu, timestamp."""
    inputs = make_sample_inputs("ignored.html")
    snap = build_snapshot(inputs, "2026-01-01 12:00")
    assert list(snap.keys()) == ["schema_version", "generated_at", "inputs"], snap.keys()
    assert snap["schema_version"] == SCHEMA_VERSION == 1
    assert snap["generated_at"] == "2026-01-01 12:00"
    print("  OK Struktura build_snapshot: klucze, wersja i timestamp zgodne")


def test_snapshot_raw_key_order():
    """W surowym tekście JSON 'schema_version' ma być przed 'generated_at' przed 'inputs'."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "dashboard_snapshot.json")
        save_dashboard_snapshot(make_sample_inputs("x.html"), "2026-01-01 12:00", path=path)
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        i_sv = raw.index('"schema_version"')
        i_ga = raw.index('"generated_at"')
        i_in = raw.index('"inputs"')
        assert i_sv < i_ga < i_in, "Zła kolejność kluczy w surowym JSON"
        print("  OK Kolejność kluczy w JSON: schema_version < generated_at < inputs")


def test_direct_vs_snapshot_html_identical():
    """HTML ze słownika i HTML po round-tripie przez snapshot mają być identyczne."""
    with tempfile.TemporaryDirectory() as tmp:
        direct_path = os.path.join(tmp, "direct.html")
        snap_path = os.path.join(tmp, "dashboard_snapshot.json")
        from_snap_path = os.path.join(tmp, "from_snapshot.html")

        # A) build prosto ze słownika
        inputs = make_sample_inputs(direct_path)
        generate_dashboard_html(**inputs, timestamp="2026-01-01 12:00", has_archive=False)

        # B) build ze snapshotu (zapis → odczyt → generacja)
        save_dashboard_snapshot(make_sample_inputs("x.html"), "2026-01-01 12:00", path=snap_path)
        snapshot = load_dashboard_snapshot(snap_path)
        assert snapshot is not None, "Snapshot ma istnieć po zapisie"
        inputs2 = snapshot["inputs"]
        inputs2["filename"] = from_snap_path  # nadpisujemy ścieżkę wyjścia
        generate_dashboard_html(**inputs2, timestamp=snapshot["generated_at"], has_archive=False)

        # Porównanie bajtowe obu plików
        with open(direct_path, "rb") as f:
            direct_bytes = f.read()
        with open(from_snap_path, "rb") as f:
            from_snap_bytes = f.read()
        assert direct_bytes == from_snap_bytes, (
            f"HTML różni się po round-tripie ({len(direct_bytes)} vs {len(from_snap_bytes)} bajtów)"
        )
        print(f"  OK Round-trip: oba HTML identyczne bajt w bajt ({len(direct_bytes)} B)")


def test_load_missing_returns_none():
    """Brak pliku snapshotu → load_dashboard_snapshot zwraca None (nie crashuje)."""
    with tempfile.TemporaryDirectory() as tmp:
        result = load_dashboard_snapshot(os.path.join(tmp, "nie-ma.json"))
        assert result is None
        print("  OK Brak pliku snapshotu: load_dashboard_snapshot zwraca None")


def test_best11_inputs_optional():
    """Puste i uszkodzone dane Best11 nie blokują generatora ani tabel."""
    with tempfile.TemporaryDirectory() as tmp:
        cases = (
            ("empty_history", {"best11_next": None, "best11_history": []}),
            ("missing_next", {"best11_history": []}),
            # Starsze snapshoty nie zawierają jeszcze pól Best11.
            ("legacy", {}),
            ("missing_fields", {
                "best11_next": {"players": [{"name": "Best11 marker"}]},
                "best11_history": [{"round": 1}],
            }),
            ("null_values", {"best11_next": None, "best11_history": None}),
            ("empty_players", {
                "best11_next": {"round": 1, "players": []},
                "best11_history": [{"round": 1, "players": []}],
            }),
        )
        for suffix, extra in cases:
            inputs = make_sample_inputs(os.path.join(tmp, f"{suffix}.html"))
            inputs.update(extra)
            generate_dashboard_html(**inputs, timestamp="2026-01-01 12:00", has_archive=False)
            with open(inputs["filename"], encoding="utf-8") as html_file:
                html = html_file.read()
            assert "<table" in html.lower(), f"{suffix}: dashboard table missing"
            if suffix == "missing_fields":
                assert "Best11 marker" in html, "Malformed Best11 player table content missing"
        print("  OK Best11: puste, starsze i malformed dane zachowują HTML/tabele")


if __name__ == "__main__":
    print("Testy round-trip snapshotu dashboardu:\n")
    test_snapshot_structure()
    test_snapshot_raw_key_order()
    test_direct_vs_snapshot_html_identical()
    test_load_missing_returns_none()
    test_best11_inputs_optional()
    print("\nWszystkie testy przeszły — snapshot jest wiernym zapisem danych dashboardu")

# UWAGA o round-trip JSON (do przeglądu, bez wdrożenia):
# JSON zamienia klucze int → str oraz krotki → listy. Przeanalizowałem realne
# wejścia scrapera: fixtures_data["matches"] ma już klucze str (scraper formatuje
# przez str(round)), a tiers / league_rosters / predictions_data / fdr_data /
# ekstra_stats / league_history mają w praktyce klucze str i nie zawierają krotek.
# generate_dashboard_html serializuje większość pól przez json.dumps i czyta je
# w JS, więc zmiana int→str w kluczach byłaby jedynym realnym ryzykiem — ale
# takich kluczy w realnych danych nie ma. Jedyna niezgodność typów pojawiłaby się
# gdyby w przyszłości ktoś dodał klucze int — wówczas proponuję normalizację
# kluczy na str już na etapie build_snapshot() (jedno miejsce, łatwe do wdrożenia).
