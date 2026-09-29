#!/usr/bin/env python3
"""
duets.py — logika widoku Duety (Liga CMF)
==========================================

Parowanie drużyn i pseudonimy menedżerów żyją WYŁĄCZNIE w ręcznie
prowadzonym pliku `duets.json` (konfiguracja statyczna). Punkty drużyn
pochodzą z danych scrapera (już zsumowane w league_teams_detail.json /
league_history.json) — ten moduł jedynie je składa.

Dla każdego duetu:
  points      = punkty drużyny A + punkty drużyny B (stan bieżący)
  prev_points = to samo, ale stan sprzed jednej kolejki
  gain        = points - prev_points
  rank        = miejsce w rankingu 15 duetów po `points` malejąco
  rank_change = rank_poprzedniej_kolejki - rank  (dodatnie = awans)

Jeśli dla drużyny brakuje danych w danym momencie, duet dostaje
punkty=None i jest pomijany w rankingu (pusty stan w widoku).
"""
import json
import os

CONFIG_PATH = "duets.json"


def load_duets_config(config_path=CONFIG_PATH):
    """Wczytuje statyczną konfigurację parowania z JSON-a."""
    if not os.path.exists(config_path):
        print(f"  ⚠️  Brak pliku {config_path} — widok Duety będzie pusty")
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"  ⚠️  {config_path} nie zawiera listy — widok Duety będzie pusty")
            return []
        return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"  ⚠️  Błąd wczytywania {config_path}: {e}")
        return []


def _index_current_points(league_teams_detail):
    """slug -> aktualne punkty (skumulowane) drużyny."""
    idx = {}
    for t in league_teams_detail or []:
        slug = t.get("slug")
        if not slug:
            continue
        pts = t.get("total_pts")
        if pts is None:
            pts = t.get("pts")
        idx[slug] = pts
    return idx


def _index_history_points(league_history, round_no):
    """slug -> skumulowane punkty drużyny na koniec wskazanej kolejki."""
    idx = {}
    if not league_history:
        return idx
    for entry in league_history.get("rounds", []) or []:
        if entry.get("round") != round_no:
            continue
        for row in entry.get("standings", []) or []:
            slug = row.get("slug")
            if slug:
                idx[slug] = row.get("total_points")
    return idx


def build_duets_data(league_teams_detail, league_history, current_round, config_path=CONFIG_PATH):
    """
    Buduje listę duetów gotową do renderowania.

    Zwraca (duets_data, warnings) — warnings to lista komunikatów
    o duetach, dla których brakuje danych (pusty stan w widoku).
    """
    config = load_duets_config(config_path)
    warnings = []
    if not config:
        return [], warnings

    cur_pts = _index_current_points(league_teams_detail)
    # Poprzednia kolejka: stan sprzed jednej kolejki
    prev_round_no = (current_round - 1) if current_round else None
    prev_pts = _index_history_points(league_history, prev_round_no) if prev_round_no else {}

    rows = []
    for entry in config:
        s1 = entry.get("team1")
        s2 = entry.get("team2")
        managers = entry.get("managers", "")
        group_name = entry.get("group_name") or ""

        # Nazwy drużyn (do rozwijanej detalu)
        name_by_slug = {t.get("slug"): t.get("display_name") or (t.get("slug") or "").replace("-", " ")
                        for t in (league_teams_detail or [])}

        have_cur = s1 in cur_pts and s2 in cur_pts and cur_pts.get(s1) is not None and cur_pts.get(s2) is not None
        have_prev = s1 in prev_pts and s2 in prev_pts and prev_pts.get(s1) is not None and prev_pts.get(s2) is not None

        if not have_cur:
            warnings.append(
                f"duet „{managers}” ({s1} + {s2}) — brak aktualnych punktów (pusty stan)")

        points = (cur_pts.get(s1) or 0) + (cur_pts.get(s2) or 0) if have_cur else None
        prev = (prev_pts.get(s1) or 0) + (prev_pts.get(s2) or 0) if have_prev else None
        gain = (points - prev) if (points is not None and prev is not None) else None

        rows.append({
            "managers": managers,
            "group_name": group_name,
            "team1_slug": s1,
            "team2_slug": s2,
            "team1_name": name_by_slug.get(s1, s1),
            "team2_name": name_by_slug.get(s2, s2),
            "points": points,
            "prev_points": prev,
            "gain": gain,
            "rank": None,
            "rank_change": None,
        })

    # --- Ranking po `points` malejąco (tylko duety z danymi) ---
    scored = [r for r in rows if r["points"] is not None]
    scored.sort(key=lambda r: r["points"], reverse=True)
    for i, r in enumerate(scored):
        r["rank"] = i + 1

    # --- Ranking poprzedniej kolejki (po `prev_points` malejąco) ---
    prev_scored = [r for r in rows if r["prev_points"] is not None]
    prev_scored.sort(key=lambda r: r["prev_points"], reverse=True)
    prev_rank_by_key = {id(r): i + 1 for i, r in enumerate(prev_scored)}

    for r in rows:
        if r["rank"] is not None and id(r) in prev_rank_by_key:
            r["rank_change"] = prev_rank_by_key[id(r)] - r["rank"]
        else:
            r["rank_change"] = 0  # neutralny (brak danych porównawczych)

    # Kolejność wyświetlania: według rangi (bez danych na końcu)
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 999, r["managers"]))
    return rows, warnings
