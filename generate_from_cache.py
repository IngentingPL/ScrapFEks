#!/usr/bin/env python3
"""
Generuje dashboard HTML z cache'owanych danych JSON.
Uruchom: python generate_from_cache.py
"""
import glob
import json
import os
import sys
from datetime import datetime

# Dodaj ścieżkę do scraper.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper import generate_dashboard_html


def find_latest_cache_file(output_dir):
    """Znajdź najnowszy plik fantasy_full_*.json w output/.

    Sortowanie po nazwie — ostatni alfabetycznie jest najnowszy, bo nazwa
    zawiera znacznik czasu (fantasy_full_YYYYMMDD_HHMMSS.json).
    """
    pattern = os.path.join(output_dir, "fantasy_full_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"Brak plików fantasy_full_*.json w {output_dir}. "
            f"Uruchom najpierw scraper.py, aby wygenerować dane."
        )
    return files[-1]


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "output")
    
    # Najnowszy plik JSON (dynamicznie, bez zahardkodowanej ścieżki)
    cache_file = find_latest_cache_file(output_dir)
    
    print(f"📂 Ładowanie danych z: {cache_file}")
    
    with open(cache_file, encoding="utf-8") as f:
        players = json.load(f)
    
    print(f"   Załadowano {len(players)} zawodników")
    
    # ---- Przygotuj summary_data ----
    summary_data = []
    for p in players:
        pts = p.get("total_points", 0) or 0
        if pts == 0:
            continue
        price = p.get("price", 0) or 0
        ppp = round(pts / price, 2) if price > 0 else 0
        
        # Forma: ostatnie 5 kolejek
        rounds = sorted(p.get("rounds", []), key=lambda r: r.get("round", 0))
        last5 = rounds[-5:] if rounds else []
        form = [{"r": r.get("round", 0), "pts": r.get("points", 0) if r.get("played") else 0, "p": bool(r.get("played"))} for r in last5]
        
        summary_data.append({
            "player_id": p.get("player_id"),
            "name": p.get("name", ""),
            "team": p.get("team", ""),
            "position": p.get("position", ""),
            "total_points": pts,
            "price": price,
            "points_per_price": ppp,
            "popularity_pct": p.get("popularity_pct", ""),
            "stats_url": p.get("stats_url", ""),
            "form": form,
            "xg_per90": p.get("xg_per90"),
            "shots_per90": p.get("shots_per90"),
            "shots_on_target_per90": p.get("shots_on_target_per90"),
            "key_passes_per90": p.get("key_passes_per90"),
            "crosses_per90": p.get("crosses_per90"),
            "crosses_accurate_per90": p.get("crosses_accurate_per90"),
        })
    summary_data.sort(key=lambda x: x.get("total_points", 0) or 0, reverse=True)
    print(f"   summary_data: {len(summary_data)} zawodników z punktami")
    
    # ---- Przygotuj tiers (puste - bez danych z drużyn) ----
    tiers = {}
    
    # ---- Pozostałe dane (puste/listy) ----
    teams_count = 1000
    league_captain_stats = []
    league_ownership_stats = []
    league_name = "discord-fmforumcmf"
    league_teams_count = 0
    league_rosters = {}
    league_teams_detail = []
    duets_data = []
    fixtures_data = {"rounds": [], "matches": {}}
    ekstra_stats = {"rows": []}
    fdr_data = {"teams": [], "gameweeks": []}
    transfers_data = {}
    predictions_data = []
    accuracy_history = []
    tuned_params = None
    league_history = {"rounds": []}
    # 📖 newsletter_data usunięte — zakładka Newsletter wyłączona, newsletter_history.json write-only

    # ---- Generuj HTML ----
    dashboard_file = os.path.join(output_dir, "dashboard.html")
    docs_file = os.path.join(script_dir, "docs", "index.html")
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    print(f"🎨 Generowanie dashboard HTML...")
    generate_dashboard_html(
        summary_data=summary_data,
        tiers=tiers,
        teams_count=teams_count,
        league_captain_stats=league_captain_stats,
        league_ownership_stats=league_ownership_stats,
        league_name=league_name,
        league_teams_count=league_teams_count,
        league_rosters=league_rosters,
        league_teams_detail=league_teams_detail,
        duets_data=duets_data,
        fixtures_data=fixtures_data,
        ekstra_stats=ekstra_stats,
        fdr_data=fdr_data,
        transfers_data=transfers_data,
        predictions_data=predictions_data,
        accuracy_history=accuracy_history,
        tuned_params=tuned_params,
        league_history=league_history,
        # 📖 newsletter_data usunięte — zakładka Newsletter wyłączona
        timestamp=timestamp,
        filename=dashboard_file,
    )
    
    print(f"💾 Zapisano do: {dashboard_file}")
    
    # Kopiuj do docs/
    with open(dashboard_file, encoding="utf-8") as src:
        content = src.read()
    with open(docs_file, "w", encoding="utf-8") as dst:
        dst.write(content)
    print(f"💾 Skopiowano do: {docs_file}")
    
    # ---- Weryfikacja ----
    print("\n🔍 Weryfikacja...")
    with open(dashboard_file, encoding="utf-8") as f:
        html = f.read()
    
    has_pos_map = "const POS_MAP" in html
    # Poprawne: 2 bloki script = theme toggle + main JS (nie duplikat!)
    script_count = html.count("<script>")
    has_dup_script = script_count > 2  # więcej niż 2 to dopiero duplikat
    
    print(f"   const POS_MAP: {'✅ OK' if has_pos_map else '❌ BRAK'}")
    print(f"   Duplikaty <script>: {'❌ TAK' if has_dup_script else '✅ OK'}")
    
    if has_pos_map and not has_dup_script:
        print("\n✅ Dashboard wygenerowany pomyślnie!")
    else:
        print("\n⚠️  Problemy z weryfikacją - sprawdź ręcznie")
        sys.exit(1)


if __name__ == "__main__":
    main()