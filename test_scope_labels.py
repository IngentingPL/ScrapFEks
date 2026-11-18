#!/usr/bin/env python3
"""
test_scope_labels.py — przyciski zakresu pokazują FAKTYCZNĄ liczbę drużyn
=========================================================================

Kontekst: gdy API /ranking-list padało (HTTP 500), scraper pobierał tylko
fragment rankingu (np. 200 z 1000). Snapshot powinien wtedy przenieść
faktyczne N (nie konfigurację TEAMS_TO_SCRAPE), a dashboard pokazać
zakres "Wszystkie (200)" — nie "Wszystkie (1000)".

Uruchomienie: pytest test_scope_labels.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard import generate_dashboard_html
from snapshot import build_snapshot, load_dashboard_snapshot, save_dashboard_snapshot
from test_snapshot_roundtrip import make_sample_inputs


def test_snapshot_przenosi_faktyczne_n():
    """teams_count w snapshotie = faktyczna liczba pobranych drużyn (tu: 200)."""
    with __import__("tempfile").TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "snap.json")
        inputs = make_sample_inputs(os.path.join(tmp, "ignored.html"))
        inputs["teams_count"] = 200  # scraper przekazał len(ranking_teams), nie konfig
        save_dashboard_snapshot(inputs, "2026-11-18 08:00", path=path)
        loaded = load_dashboard_snapshot(path)
        assert loaded["inputs"]["teams_count"] == 200


def test_dashboard_wyswietla_wszystkie_200():
    """Przycisk zakresu pokazuje 'Wszystkie (200)' — tak było w ucietym runie."""
    with __import__("tempfile").TemporaryDirectory() as tmp:
        inputs = make_sample_inputs(os.path.join(tmp, "scope.html"))
        inputs["teams_count"] = 200
        generate_dashboard_html(**inputs, timestamp="2026-11-18 08:00", has_archive=False)
        with open(inputs["filename"], encoding="utf-8") as f:
            html = f.read()
    assert "Wszystkie (200)" in html, "brak etykiety 'Wszystkie (200)'"
    assert "Wszystkie (1000)" not in html, "etykieta 'Wszystkie (1000)' mimo 200 drużyn"
    assert "Top 10" in html and "Top 100" in html


def test_dashboard_wyswietla_wszystkie_1000_przy_pelnym_rankingu():
    """Pełny ranking (N = 1000) → 'Wszystkie (1000)' bez regresji."""
    with __import__("tempfile").TemporaryDirectory() as tmp:
        inputs = make_sample_inputs(os.path.join(tmp, "scope1000.html"))
        inputs["teams_count"] = 1000
        inputs["tiers"] = dict(inputs["tiers"])  # nie ruszaj wspólnego sample
        inputs["tiers"]["all"] = dict(inputs["tiers"]["all"], count=1000)
        generate_dashboard_html(**inputs, timestamp="2026-11-18 08:00", has_archive=False)
        with open(inputs["filename"], encoding="utf-8") as f:
            html = f.read()
    assert "Wszystkie (1000)" in html
    assert "Wszystkie (200)" not in html


def test_build_snapshot_przyjmuje_n_z_inputs():
    """build_snapshot nie ignoruje teams_count z inputs (metadana trafia do JSON)."""
    inputs = make_sample_inputs("ignored.html")
    inputs["teams_count"] = 200
    snap = build_snapshot(inputs, "2026-11-18 08:00")
    assert snap["inputs"]["teams_count"] == 200
