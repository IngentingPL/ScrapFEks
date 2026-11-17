"""
test_network_retry.py — testy retry w network.py (E-01/E-03) i fetch_ranking_teams
==================================================================================

Scenariusze:
1. HTTP 500 -> 200 przy 2. próbie (odstęp 1s)
2. stałe 500 -> poddaje się po 3 próbach (brak pętli nieskończonej), zwraca odpowiedź
3. HTTP 429 z Retry-After (czeka wg nagłówka)
4. HTTP 429 z Retry-After > 10s (ograniczenie do 10s)
5. HTTP 429 bez Retry-After (rosnący odstęp 1s)
6. HTTP 404 — bez ponowienia
7. Timeout -> ponowienie (istniejące zachowanie)
8. stały Timeout -> None po 3 próbach
9. domyślny timeout 30s (E-03)
10. fetch_ranking_teams: stałe 500 -> 3 próby na partię, log statusu + treści,
    "⚠️ Ranking: pobrano 0 z 100"
11. fetch_ranking_teams: 500 -> 200 -> dane wczytane, "✅ Ranking: pobrano 1 z 100"

Uruchomienie: pytest test_network_retry.py
"""

import os
import sys
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
import requests

import network
import squads


def _resp(status=200, headers=None, text="", json_data=None):
    """Prosty mock requests.Response."""
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    r.text = text
    if json_data is None:
        r.json.side_effect = ValueError("brak jsona w mocku")
    else:
        r.json.return_value = json_data
    return r


# ============================================================
# network._request_with_retry
# ============================================================

def test_500_potem_200_druga_proba():
    responses = [_resp(500, text="oops"), _resp(200, json_data={"ok": True})]
    with patch.object(network.time, "sleep") as sleep_mock, \
         patch.object(network.requests, "get", side_effect=responses) as get_mock:
        resp = network._request_with_retry(requests.get, "http://x")
    assert resp is responses[1]
    assert get_mock.call_count == 2
    sleep_mock.assert_called_once_with(1)


def test_stale_500_poddaje_sie_po_3_probach():
    with patch.object(network.time, "sleep") as sleep_mock, \
         patch.object(network.requests, "get",
                      side_effect=lambda *a, **k: _resp(500, text="boom")) as get_mock:
        resp = network._request_with_retry(requests.get, "http://x")
    assert resp is not None and resp.status_code == 500  # odpowiedź, nie None
    assert get_mock.call_count == 3
    assert sleep_mock.call_args_list == [call(1), call(2)]  # 1s, 2s — bez snu po 3. próbie


def test_429_z_retry_after():
    responses = [_resp(429, headers={"Retry-After": "7"}), _resp(200, json_data={})]
    with patch.object(network.time, "sleep") as sleep_mock, \
         patch.object(network.requests, "get", side_effect=responses):
        resp = network._request_with_retry(requests.get, "http://x")
    assert resp.status_code == 200
    sleep_mock.assert_called_once_with(7)


def test_429_retry_after_max_10s():
    responses = [_resp(429, headers={"Retry-After": "60"}), _resp(200, json_data={})]
    with patch.object(network.time, "sleep") as sleep_mock, \
         patch.object(network.requests, "get", side_effect=responses):
        network._request_with_retry(requests.get, "http://x")
    sleep_mock.assert_called_once_with(10)


def test_429_bez_retry_after_backoff():
    responses = [_resp(429, headers={}), _resp(200, json_data={})]
    with patch.object(network.time, "sleep") as sleep_mock, \
         patch.object(network.requests, "get", side_effect=responses):
        network._request_with_retry(requests.get, "http://x")
    sleep_mock.assert_called_once_with(1)


def test_404_bez_ponowienia():
    with patch.object(network.time, "sleep") as sleep_mock, \
         patch.object(network.requests, "get",
                      side_effect=lambda *a, **k: _resp(404, text="Not Found")) as get_mock:
        resp = network._request_with_retry(requests.get, "http://x")
    assert resp is not None and resp.status_code == 404
    assert get_mock.call_count == 1  # żadnego ponowienia
    sleep_mock.assert_not_called()


def test_timeout_potem_200():
    responses = [requests.exceptions.ReadTimeout("t"), _resp(200, json_data={})]
    with patch.object(network.time, "sleep") as sleep_mock, \
         patch.object(network.requests, "get", side_effect=responses):
        resp = network._request_with_retry(requests.get, "http://x")
    assert resp.status_code == 200
    sleep_mock.assert_called_once_with(1)


def test_staly_timeout_zwraca_none():
    with patch.object(network.time, "sleep") as sleep_mock, \
         patch.object(network.requests, "get",
                      side_effect=requests.exceptions.ReadTimeout("t")):
        resp = network._request_with_retry(requests.get, "http://x")
    assert resp is None
    assert sleep_mock.call_args_list == [call(1), call(2)]


def test_domyslny_timeout_30s():
    with patch.object(network.requests, "get",
                      side_effect=lambda *a, **k: _resp(200, json_data={})) as get_mock:
        network._request_with_retry(requests.get, "http://x")
    assert get_mock.call_args.kwargs.get("timeout") == 30


def test_jawny_timeout_nie_nadpisany():
    with patch.object(network.requests, "get",
                      side_effect=lambda *a, **k: _resp(200, json_data={})) as get_mock:
        network._request_with_retry(requests.get, "http://x", timeout=15)
    assert get_mock.call_args.kwargs.get("timeout") == 15


# ============================================================
# squads.fetch_ranking_teams (wrapper + logi)
# ============================================================

def _team(slug):
    return {"slug": slug, "id": 1, "total_points": "100", "last_points": "10", "pos": 1}


def test_ranking_stale_500_trzy_proby_i_log_tresci(capsys):
    with patch.object(network.time, "sleep"), \
         patch.object(network.requests, "post",
                      side_effect=lambda *a, **k: _resp(500, text="Serwer padł " * 20)), \
         patch.object(squads.time, "sleep"):
        teams = squads.fetch_ranking_teams(None, 100)
    out = capsys.readouterr().out
    assert teams == []
    # 3 próby wrapper na jedną partię — brak pętli nieskończonej
    assert out.count("HTTP 500, próba 1/3") == 1
    assert out.count("HTTP 500, próba 2/3") == 1
    assert out.count("HTTP 500 po 3 próbach") == 1
    # status + fragment treści odpowiedzi (200 znaków), bez nagłówków
    assert "Błąd HTTP 500 przy start=0" in out
    assert "Serwer padł" in out
    assert "⚠️ Ranking: pobrano 0 z 100" in out


def test_ranking_500_potem_200_dane_wczytane(capsys):
    with patch.object(network.time, "sleep"), \
         patch.object(network.requests, "post",
                      side_effect=[_resp(500, text="err"),
                                   _resp(200, json_data={"data": [_team("druzyna-a")]}),
                                   _resp(200, json_data={"data": [_team("druzyna-b")]}),
                                   _resp(200, json_data={"data": [_team("druzyna-c")]}),
                                   _resp(200, json_data={"data": [_team("druzyna-d")]}),
                                   _resp(200, json_data={"data": [_team("druzyna-e")]})]), \
         patch.object(squads.time, "sleep"):
        teams = squads.fetch_ranking_teams(None, 500)
    assert len(teams) == 5
    assert teams[0]["slug"] == "druzyna-a"
    out = capsys.readouterr().out
    assert "⚠️ Ranking: pobrano 5 z 500" in out
    assert "✅ Ranking" not in out


def test_ranking_niepelny_zestaw_flaga_ostrozna(capsys):
    # 2 strony OK (200 drużyn) z count=1000 → ⚠️ (przypadek z runów 13-16.11)
    data_pages = [_resp(200, json_data={"data": [_team(f"d{i}") for i in range(100)]})] * 2
    with patch.object(network.time, "sleep"), \
         patch.object(network.requests, "post", side_effect=data_pages), \
         patch.object(squads.time, "sleep"):
        teams = squads.fetch_ranking_teams(None, 1000)
    assert len(teams) == 200
    out = capsys.readouterr().out
    assert "⚠️ Ranking: pobrano 200 z 1000" in out
