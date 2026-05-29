#!/usr/bin/env python3
"""
Archiwizacja sezonu Fantasy Ekstraklasy
========================================
Przenosi dane sezonu do docs/archive/ i generuje statyczny HTML archiwum.

Użycie:
    python archive.py 2025-26
    python archive.py "2025-26 Wiosna"
    SEASON_NAME=2025-26 python archive.py

Autor: Wygenerowane przez Claude dla Piotra
"""

import os
import sys
import json
import shutil
import glob as glob_module
import re
from datetime import datetime


# ============================================================
# KONFIGURACJA
# ============================================================

# Nazwa sezonu - z argumentu lub zmiennej środowiskowej
SEASON_NAME = ""
if len(sys.argv) > 1:
    SEASON_NAME = sys.argv[1].strip()
elif os.environ.get("SEASON_NAME"):
    SEASON_NAME = os.environ.get("SEASON_NAME", "").strip()

# Walidacja SEASON_NAME
if not SEASON_NAME:
    print("❌ Błąd: SEASON_NAME jest wymagany!")
    print("   Użycie: python archive.py 2025-26")
    print("   Lub: SEASON_NAME=2025-26 python archive.py")
    sys.exit(1)

# Katalog wyjściowy
ARCHIVE_DIR = "docs/archive"
OUTPUT_DIR = "output"


# ============================================================
# GENEROWANIE INDEX ARCHIWUM
# ============================================================

def generate_archive_index(archive_dir: str = "docs/archive"):
    """
    Generuje stronę index.html z listą wszystkich archiwów sezonów.
    Skanuje katalog docs/archive/ w poszukiwaniu plików sezon-*.html.
    """
    # Sprawdź czy katalog istnieje
    if not os.path.exists(archive_dir):
        print(f"  ℹ️  Katalog archiwum nie istnieje: {archive_dir}")
        return False

    # Znajdź wszystkie pliki sezon-*.html
    pattern = os.path.join(archive_dir, "sezon-*.html")
    archive_files = glob_module.glob(pattern)

    if not archive_files:
        print(f"  ℹ️  Brak archiwów w katalogu: {archive_dir}")
        return False

    # Parsuj nazwy sezonów z plików
    archives = []
    for filepath in archive_files:
        filename = os.path.basename(filepath)
        # Wyciągnij nazwę sezonu: "sezon-2026-Wiosna.html" -> "2026 Wiosna"
        match = re.match(r"sezon-(.+)\.html$", filename)
        if match:
            season_name = match.group(1).strip().replace('-', ' ')
            archives.append({
                "name": season_name,
                "filename": filename,
            })

    # Sortuj po nazwie (od najnowszego)
    archives.sort(key=lambda x: x["name"], reverse=True)

    if not archives:
        print(f"  ℹ️  Nie znaleziono archiwów sezonów")
        return False

    # CSS dla strony index archiwum (ten sam co dashboard)
    index_css = """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { background: #131313; }
    body {
      min-height: 100vh;
      background: #131313;
      color: #ffffff;
      font-family: 'DM Sans', -apple-system, sans-serif;
      padding: 24px 16px;
    }
    .container { max-width: 800px; margin: 0 auto; padding: 0 16px; }
    .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
    .header h1 { font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }
    .header .sub { font-size: 12px; color: #949494; margin: 0; }
    .back-link {
      color: #3cffd0;
      text-decoration: none;
      font-size: 14px;
      font-weight: 600;
      margin-bottom: 20px;
      display: inline-block;
    }
    .back-link:hover { color: #3860be; }
    .archive-list { display: flex; flex-direction: column; gap: 12px; }
    .archive-item {
      background: #2d2d2d;
      border: 1px solid #3cffd0;
      border-radius: 12px;
      padding: 16px 20px;
      transition: all 0.2s;
    }
    .archive-item:hover {
      background: #3cffd0;
    }
    .archive-item:hover .archive-name {
      color: #131313;
    }
    .archive-item:hover .archive-arrow {
      color: #131313;
    }
    .archive-item a {
      text-decoration: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .archive-name {
      font-size: 16px;
      font-weight: 700;
      color: #ffffff;
    }
    .archive-arrow {
      font-size: 18px;
      color: #3cffd0;
    }
    .empty-msg { padding: 40px; text-align: center; color: #949494; }
    .footer { text-align: center; margin-top: 32px; color: #949494; font-size: 12px; }

    /* Light theme */
    html.theme-fantasy { background: #f5f5f5; }
    html.theme-fantasy body { background: #f5f5f5; color: #131313; }
    html.theme-fantasy .header h1 { color: #131313; }
    html.theme-fantasy .header .sub { color: #5a5a5a; }
    html.theme-fantasy .back-link { color: #309875; }
    html.theme-fantasy .back-link:hover { color: #3860be; }
    html.theme-fantasy .archive-item { background: #ffffff; border-color: #e0e0e0; }
    html.theme-fantasy .archive-item:hover { background: #309875; }
    html.theme-fantasy .archive-item:hover .archive-name { color: #ffffff; }
    html.theme-fantasy .archive-item:hover .archive-arrow { color: #ffffff; }
    html.theme-fantasy .archive-name { color: #131313; }
    html.theme-fantasy .archive-arrow { color: #309875; }
    html.theme-fantasy .footer { color: #5a5a5a; }
    """

    # Theme toggle JS
    theme_js = """
    function toggleTheme() {
      const html = document.documentElement;
      const btn = document.querySelector('.theme-toggle');
      if (html.classList.contains('theme-fantasy')) {
        html.classList.remove('theme-fantasy');
        btn.textContent = '☀️ Light';
        localStorage.setItem('theme', 'dark');
      } else {
        html.classList.add('theme-fantasy');
        btn.textContent = '🌙 Dark';
        localStorage.setItem('theme', 'light');
      }
    }
    (function() {
      const theme = localStorage.getItem('theme');
      const html = document.documentElement;
      const btn = document.querySelector('.theme-toggle');
      if (theme === 'light') {
        html.classList.add('theme-fantasy');
        btn.textContent = '🌙 Dark';
      } else {
        btn.textContent = '☀️ Light';
      }
    })();
    """

    # Generuj HTML
    archives_html = ""
    for arch in archives:
        archives_html += f'''
        <div class="archive-item">
          <a href="{arch['filename']}">
            <span class="archive-name">📁 Sezon {arch['name']}</span>
            <span class="archive-arrow">→</span>
          </a>
        </div>'''

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ScrapFEks – Archiwum</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{index_css}</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <h1>📁 Archiwum Sezonów</h1>
      <p class="sub">ScrapFEks · {timestamp}</p>
    </div>
    <button class="theme-toggle" onclick="toggleTheme()">☀️ Light</button>
  </div>
  <a href="../index.html" class="back-link">← Powrót do bieżącego sezonu</a>

  <div class="archive-list">
    {archives_html}
  </div>

  <div class="footer">ScrapFEks Archiwum · {timestamp}</div>
</div>
<script>{theme_js}</script>
</body>
</html>"""

    # Zapisz plik
    index_path = os.path.join(archive_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  📁 Index archiwum wygenerowany: {index_path} ({len(archives)} sezonów)")
    return True


# ============================================================
# GENEROWANIE ARCHIWUM SEZONU
# ============================================================

def generate_archive_html(
    season_name: str,
    players: list[dict],
    league_teams_detail: list[dict],
    league_history: dict,
    duets_data: list[dict],
    timestamp: str,
    filename: str,
):
    """
    Generuje HTML archiwum sezonu z pełną zakładką Zawodnicy (identyczna jak w dashboardzie).
    Zawiera zakładki: Zawodnicy, Liga CMF, Sezon.
    Zakładka Liga CMF zawiera widoki: Drużyny i Duety (identyczne jak w dashboardzie).
    """
    # Przygotuj dane dla JS - zawodnicy z formą (ostatnie 5 kolejek)
    # Oblicz formę dla każdego zawodnika (średnia z ostatnich 5 kolejek)
    players_with_form = []
    for p in players:
        player_copy = dict(p)
        rounds = p.get("rounds", [])
        # Weź ostatnie 5 kolejek z danymi
        last_5 = rounds[-5:] if len(rounds) >= 5 else rounds
        form_data = []
        for r in last_5:
            form_data.append({
                "r": r.get("round", 0),
                "pts": r.get("points", 0),
                "p": r.get("played", False)
            })
        player_copy["form"] = form_data
        # Oblicz points_per_price jeśli brak
        if "points_per_price" not in player_copy:
            price = player_copy.get("price", 0)
            pts = player_copy.get("total_points", 0)
            player_copy["points_per_price"] = round(pts / price, 1) if price > 0 else 0
        players_with_form.append(player_copy)
    
    players_json = json.dumps(players_with_form, ensure_ascii=False)
    league_teams_json = json.dumps(league_teams_detail, ensure_ascii=False)
    league_history_json = json.dumps(league_history or {"rounds": []}, ensure_ascii=False)
    duets_json = json.dumps(duets_data or [], ensure_ascii=False)

    # CSS dla archiwum - pełny zgodny z design.md i scraper.py
    # Kolory z design.md:
    # - Canvas Black: #131313 (tło)
    # - Jelly Mint: #3cffd0 (akcent)
    # - Verge Ultraviolet: #5200ff (akcent)
    # - Surface Slate: #2d2d2d (karty)
    # - Secondary Text: #949494 (metadane)
    archive_css = """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { background: #131313; }
    body {
      min-height: 100vh;
      background: #131313;
      color: #ffffff;
      font-family: 'DM Sans', -apple-system, sans-serif;
      padding: 24px 16px;
    }
    .container { max-width: 1400px; margin: 0 auto; padding: 0 16px; }
    .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }
    .header-left { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
    .header h1 { font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }
    .header .sub { font-size: 12px; color: #949494; margin: 0; }
    .archive-badge {
      background: #5200ff;
      color: #fff;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 700;
    }
    .back-link {
      color: #3cffd0;
      text-decoration: none;
      font-size: 14px;
      font-weight: 600;
      margin-bottom: 20px;
      display: inline-block;
    }
    .back-link:hover { color: #3860be; }
    .tabs { display: flex; gap: 4px; border-bottom: 1px solid #2d2d2d; flex-wrap: wrap; margin-bottom: 16px; }
    .tab {
      background: transparent; border: none; border-bottom: 2px solid transparent;
      color: #949494; padding: 10px 18px; font-size: 13px; font-weight: 600;
      cursor: pointer; border-radius: 8px 8px 0 0; transition: all 0.2s;
      font-family: inherit;
    }
    .tab.active { background: #2d2d2d; border-bottom-color: #3cffd0; color: #ffffff; }
    .tab:hover { color: #3860be; }
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    /* Filtry pozycji i scope - zgodne z scraper.py */
    .filters-row { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
    .pos-filters { display: flex; gap: 4px; }
    .pos-btn {
      background: transparent; border: 1px solid #3cffd0; color: #3cffd0;
      padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 600;
      cursor: pointer; transition: all 0.2s; font-family: inherit;
    }
    .pos-btn.active { border-color: transparent; color: #131313; }
    .pos-btn.active[data-pos="ALL"] { background: #3cffd0; }
    .pos-btn.active[data-pos="BR"] { background: #f59e0b; }
    .pos-btn.active[data-pos="OBR"] { background: #3b82f6; }
    .pos-btn.active[data-pos="POM"] { background: #10b981; }
    .pos-btn.active[data-pos="NAP"] { background: #ef4444; }
    .pos-btn:hover { opacity: 0.8; }
    
    /* Scope filters */
    .scope-filters { display: flex; gap: 4px; margin-left: auto; }
    .scope-btn {
      background: transparent; border: 1px solid #5200ff; color: #5200ff;
      padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 600;
      cursor: pointer; transition: all 0.2s; font-family: inherit;
    }
    .scope-btn.active { background: #5200ff; color: #ffffff; border-color: #5200ff; }
    .scope-btn:hover { opacity: 0.8; }

    /* Tabela danych */
    .data-table { background: #2d2d2d; border-radius: 12px; overflow: hidden; width: 100%; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    thead tr { background: #131313; }
    th { padding: 10px 14px; color: #949494; font-weight: 600; font-size: 11px; text-transform: uppercase; white-space: nowrap; }
    td { padding: 10px 14px; border-top: 1px solid #131313; white-space: nowrap; }
    .pos-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; color: #131313; }
    .pos-BR, .pos-1 { background: #f59e0b; }
    .pos-OBR, .pos-2 { background: #3b82f6; }
    .pos-POM, .pos-3 { background: #10b981; }
    .pos-NAP, .pos-4 { background: #ef4444; }
    .text-right { text-align: right; }
    .text-center { text-align: center; }
    .text-left { text-align: left; }
    .fw-700 { font-weight: 700; }
    .fw-600 { font-weight: 600; }
    .c-muted { color: #949494; }
    .c-dim { color: #64748b; }
    .empty-msg { padding: 40px; text-align: center; color: #949494; }

    /* Section title */
    .section-title { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
    .section-title h2 { font-size: 18px; font-weight: 700; margin: 0; }
    .section-title .line { flex: 1; height: 1px; background: #2d2d2d; }

    /* Sortowalne kolumny */
    .sortable { cursor: pointer; user-select: none; }
    .sortable:hover { color: #3cffd0 !important; }

    /* Diff badges */
    .diff-badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 12px; font-weight: 600; }
    .diff-pos { background: rgba(16, 185, 129, 0.2); color: #10b981; }
    .diff-neg { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
    .diff-zero { background: rgba(148, 163, 184, 0.2); color: #94a3b8; }

    /* Form chart */
    .form-chart { display: flex; align-items: flex-end; gap: 2px; height: 20px; }
    .form-chart.mini { height: 12px; }
    .form-bar { width: 4px; border-radius: 2px; min-height: 2px; position: relative; }
    .form-bar.not-played { opacity: 0.3; }
    .form-val { position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); font-size: 9px; color: #fff; opacity: 0; transition: opacity 0.2s; }
    .form-bar:hover .form-val { opacity: 1; }
    .form-rnd { position: absolute; top: 100%; left: 50%; transform: translateX(-50%); font-size: 8px; color: #64748b; }

    /* Bar chart for ownership */
    .bar-wrap { display: flex; align-items: center; gap: 6px; }
    .bar-bg { flex: 1; height: 6px; background: #1e293b; border-radius: 3px; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 3px; }
    .bar-val { font-size: 11px; color: #94a3b8; min-width: 36px; text-align: right; }

    /* Clickable cells */
    .clickable { cursor: pointer; }
    .clickable:hover { color: #3cffd0; }

    /* Detail panel */
    .detail-panel { background: #0f172a; padding: 12px; border-radius: 8px; }
    .detail-section { margin-bottom: 8px; }
    .ds-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; display: block; }
    .roster-chip { display: inline-flex; align-items: center; gap: 4px; background: #1e293b; padding: 4px 8px; border-radius: 4px; font-size: 12px; margin: 2px; }
    .rc-badge { font-size: 9px; padding: 1px 4px; border-radius: 3px; font-weight: 700; }
    .rc-cap { background: #fbbf24; color: #000; }
    .rc-res { background: #64748b; color: #fff; }
    .rc-xi { background: #3cffd0; color: #000; }

    /* Linki */
    .player-link { color: #3cffd0; text-decoration: none; }
    .player-link:hover { color: #3860be; }

    /* Highlight wiersza */
    .highlight { background: rgba(60, 255, 208, 0.1); }

    /* Team list */
    .team-list { display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }
    .team-list-item { background: #2d2d2d; border: 1px solid #3cffd0; border-radius: 8px; }
    .team-list-header { display: flex; align-items: center; gap: 12px; padding: 10px 16px; cursor: pointer; }
    .team-list-rank { font-size: 13px; font-weight: 800; color: #3cffd0; min-width: 32px; }
    .team-list-name { font-size: 14px; font-weight: 700; color: #ffffff; flex: 1; text-transform: capitalize; }
    .team-list-pts { font-size: 12px; color: #949494; font-weight: 600; }

    /* Footer */
    .footer { text-align: center; margin-top: 32px; color: #949494; font-size: 12px; }

    /* Season wrap */
    .season-wrap { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
    .season-chart svg { display: block; }

    /* View toggle */
    .view-toggle { display: flex; gap: 8px; margin-bottom: 16px; }
    .view-btn { padding: 6px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
    .view-btn.active { background: #3b82f6; color: #fff; }

    /* Captain badge */
    .captain-badge { background: #fbbf24; color: #000; padding: 1px 5px; border-radius: 3px; font-size: 10px; font-weight: 700; }

    /* Fantasy theme (light) */
    html.theme-fantasy { background: #f5f5f5; }
    html.theme-fantasy body { background: #f5f5f5; color: #131313; }
    html.theme-fantasy .header h1 { color: #131313; }
    html.theme-fantasy .header .sub { color: #5a5a5a; }
    html.theme-fantasy .archive-badge { background: #309875; }
    html.theme-fantasy .back-link { color: #309875; }
    html.theme-fantasy .back-link:hover { color: #3860be; }
    html.theme-fantasy .tabs { border-bottom-color: #e0e0e0; }
    html.theme-fantasy .tab { color: #5a5a5a; }
    html.theme-fantasy .tab.active { background: #ffffff; border-bottom-color: #309875; color: #131313; }
    html.theme-fantasy .tab:hover { color: #3860be; }
    html.theme-fantasy .pos-btn { border-color: #309875; color: #309875; }
    html.theme-fantasy .pos-btn.active[data-pos="ALL"] { background: #309875; color: #ffffff; }
    html.theme-fantasy .pos-btn.active[data-pos="BR"] { background: #f59e0b; color: #131313; }
    html.theme-fantasy .pos-btn.active[data-pos="OBR"] { background: #3b82f6; color: #ffffff; }
    html.theme-fantasy .pos-btn.active[data-pos="POM"] { background: #10b981; color: #ffffff; }
    html.theme-fantasy .pos-btn.active[data-pos="NAP"] { background: #ef4444; color: #ffffff; }
    html.theme-fantasy .scope-btn { border-color: #5200ff; color: #5200ff; }
    html.theme-fantasy .scope-btn.active { background: #5200ff; color: #ffffff; }
    html.theme-fantasy .data-table { background: #ffffff; }
    html.theme-fantasy table { background: #ffffff; }
    html.theme-fantasy thead tr { background: #f5f5f5; }
    html.theme-fantasy th { color: #5a5a5a; }
    html.theme-fantasy td { border-top-color: #e0e0e0; }
    html.theme-fantasy .c-muted { color: #5a5a5a; }
    html.theme-fantasy .c-dim { color: #949494; }
    html.theme-fantasy .section-title .line { background: #e0e0e0; }
    html.theme-fantasy .sortable:hover { color: #309875 !important; }
    html.theme-fantasy .player-link { color: #309875; }
    html.theme-fantasy .player-link:hover { color: #3860be; }
    html.theme-fantasy .team-list-item { border-color: #309875; }
    html.theme-fantasy .team-list-name { color: #131313; }
    html.theme-fantasy .team-list-pts { color: #5a5a5a; }
    html.theme-fantasy .footer { color: #5a5a5a; }
    html.theme-fantasy .detail-panel { background: #f5f5f5; }
    html.theme-fantasy .roster-chip { background: #e0e0e0; }
    html.theme-fantasy .bar-bg { background: #e0e0e0; }
    """

    # JS dla archiwum - pełna funkcjonalność zakładki Zawodnicy (identyczna jak w scraper.py)
    archive_js = f"""
    // Dane zawodników i drużyn
    const PLAYERS = {players_json};
    const LEAGUE_TEAMS = {league_teams_json};
    const LEAGUE_HISTORY = {league_history_json};
    
    // Mapowanie pozycji
    const POS_MAP = {{BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD','1':'GK','2':'DEF','3':'MID','4':'FWD'}};
    const POS_ID = {{'1':'BR','2':'OBR','3':'POM','4':'NAP',BR:'BR',OBR:'OBR',POM:'POM',NAP:'NAP',
      Bramkarz:'BR','Obrońca':'OBR',Pomocnik:'POM',Napastnik:'NAP'}};
    const DUETS_DATA = {duets_json};

    // Stan aplikacji
    let tab = 'players';
    let pos = 'ALL';
    let scope = 'all';
    let selectedTeam = '';
    let selectedDuet = '';
    let currentTeamsView = 'teams';
    
    // Konfiguracja sortowania
    const sorts = {{
      players: {{col:'total_points', dir:'desc'}},
      teams: {{col:'_pos_order', dir:'asc'}},
      teams_list: {{col:'total_pts', dir:'desc'}},
      duets_list: {{col:'total_pts', dir:'desc'}}
    }};

    // Funkcje pomocnicze
    function num(v) {{
      if (v === null || v === undefined || v === '') return 0;
      const n = typeof v === 'string' ? parseFloat(v) : v;
      return isNaN(n) ? 0 : n;
    }}
    
    function bar(val, max, color) {{
      const w = Math.min(val / max * 100, 100);
      return '<div class="bar-wrap"><div class="bar-bg"><div class="bar-fill" style="width:'+w+'%;background:'+color+'"></div></div><span class="bar-val">'+val.toFixed(1)+'%</span></div>';
    }}
    
    function posBadge(p) {{
      const k = POS_ID[p] || p;
      return '<span class="pos-badge pos-'+k+'">'+(POS_MAP[k]||POS_MAP[p]||p)+'</span>';
    }}
    
    function arrow(tabName, col) {{
      const s = sorts[tabName];
      return s.col === col ? (s.dir === 'desc' ? ' ▼' : ' ▲') : '';
    }}
    
    function filterPos(data) {{
      if (pos === 'ALL') return data;
      return data.filter(p => {{
        const pk = POS_ID[p.position] || POS_ID[p.position_id] || p.position;
        return pk === pos;
      }});
    }}
    
    function sortData(data, tabName) {{
      const s = sorts[tabName];
      return [...data].sort((a, b) => {{
        let av = a[s.col], bv = b[s.col];
        if (s.col === 'position' || s.col === 'position_id') {{
          const order = {{BR:1,OBR:2,POM:3,NAP:4,'1':1,'2':2,'3':3,'4':4,Bramkarz:1,'Obrońca':2,Pomocnik:3,Napastnik:4}};
          av = order[av] || 5; bv = order[bv] || 5;
        }} else if (s.col === 'name' || s.col === 'team') {{
          av = (av || '').toLowerCase(); bv = (bv || '').toLowerCase();
          if (av < bv) return s.dir === 'desc' ? 1 : -1;
          if (av > bv) return s.dir === 'desc' ? -1 : 1;
          return 0;
        }} else {{
          av = num(av); bv = num(bv);
        }}
        if (av < bv) return s.dir === 'desc' ? 1 : -1;
        if (av > bv) return s.dir === 'desc' ? -1 : 1;
        return 0;
      }});
    }}
    
    function formAvgNum(form) {{
      if (!form || !form.length) return 0;
      const played = form.filter(f => f.p !== false);
      if (!played.length) return 0;
      return played.reduce((s,f) => s + (f.pts||0), 0) / played.length;
    }}

    function diffBadge(pts, avg) {{
      if (!avg) return '<span class="diff-badge diff-zero">—</span>';
      const d = pts - avg;
      const cls = d > 0 ? 'diff-pos' : d < 0 ? 'diff-neg' : 'diff-zero';
      return '<span class="diff-badge '+cls+'">'+(d>0?'+':'')+d.toFixed(0)+'</span>';
    }}
    
    function nameCell(name, pid, style, prefix) {{
      const attr = pid ? ' data-pid="'+pid+'"' : '';
      return '<td class="clickable roster-trigger"'+attr+' style="cursor:pointer;'+(style||'')+'">'+(prefix||'')+name+' <span style="font-size:10px;color:#64748b">▸</span></td>';
    }}
    
    function formChart(form, mini) {{
      if (!form || !form.length) return '<span class="c-dim" style="font-size:11px">—</span>';
      const SCALE = 15;
      const MAX_H = mini ? 20 : 40;
      let h = '<div class="form-chart'+(mini ? ' mini' : '')+'">';
      form.forEach(f => {{
        const pts = f.pts || 0;
        const played = f.p !== false;
        const ht = Math.max(Math.abs(pts) / SCALE * MAX_H, 2);
        const c = !played ? '#334155' : pts >= 8 ? '#22d3ee' : pts >= 4 ? '#10b981' : pts >= 0 ? '#64748b' : '#ef4444';
        const np = !played ? ' not-played' : '';
        h += '<div class="form-bar'+np+'" style="height:'+ht+'px;background:'+c+'">';
        h += '<span class="form-val">'+(played ? pts : '—')+'</span>';
        h += '<span class="form-rnd">K'+f.r+'</span>';
        h += '</div>';
      }});
      h += '</div>';
      return h;
    }}
    
    function detailRow(pid, colspan) {{
      // W archiwum nie mamy danych ROSTERS, więc pokazujemy podstawowe info
      const p = PLAYERS.find(x => x.player_id == pid);
      if (!p) {{
        return '<tr class="detail-row"><td colspan="'+colspan+'"><div class="detail-panel"><span class="c-dim" style="font-size:12px">Brak szczegółowych danych</span></div></td></tr>';
      }}
      let h = '<tr class="detail-row"><td colspan="'+colspan+'"><div class="detail-panel">';
      h += '<div class="detail-section">';
      h += '<span class="ds-label">Forma (ostatnie 5 kolejek)</span>';
      h += formChart(p.form, false);
      h += '</div>';
      if (p.rounds && p.rounds.length) {{
        h += '<div class="detail-section" style="margin-top:12px">';
        h += '<span class="ds-label">Historia punktów</span>';
        h += '<div style="display:flex;flex-wrap:wrap;gap:8px;font-size:12px">';
        const last5 = p.rounds.slice(-5);
        last5.forEach(r => {{
          const pts = r.points || 0;
          const color = pts >= 8 ? '#22d3ee' : pts >= 4 ? '#10b981' : pts >= 0 ? '#64748b' : '#ef4444';
          h += '<span style="background:#1e293b;padding:4px 8px;border-radius:4px">K'+r.round+': <b style="color:'+color+'">'+pts+'</b></span>';
        }});
        h += '</div></div>';
      }}
      h += '</div></td></tr>';
      return h;
    }}
    
    function attachDetailClicks() {{
      document.querySelectorAll('.roster-trigger').forEach(td => {{
        td.onclick = function() {{
          const pid = this.dataset.pid || '';
          const row = this.closest('tr');
          const next = row.nextElementSibling;
          if (next && next.classList.contains('detail-row')) {{
            next.remove();
            return;
          }}
          document.querySelectorAll('.detail-row').forEach(r => r.remove());
          const cols = row.querySelectorAll('td').length;
          row.insertAdjacentHTML('afterend', detailRow(pid, cols));
        }};
      }});
    }}

    // Oblicz średnie punkty per pozycja — globalne
    const POS_AVGS = {{}};
    (function() {{
      const sums = {{}}, counts = {{}};
      PLAYERS.forEach(p => {{
        const pk = POS_ID[p.position] || p.position || '';
        const pts = p.total_points || 0;
        if (pts > 0 && pk) {{
          sums[pk] = (sums[pk] || 0) + pts;
          counts[pk] = (counts[pk] || 0) + 1;
        }}
      }});
      for (const k in sums) POS_AVGS[k] = sums[k] / counts[k];
    }})();

    // Oblicz średnie punkty per pozycja — liga
    const LEAGUE_POS_AVGS = {{}};
    (function() {{
      const seen = {{}}, sums = {{}}, counts = {{}};
      LEAGUE_TEAMS.forEach(t => {{
        if (t.players) t.players.forEach(p => {{
          const pid = p.pid || p.player_id;
          if (seen[pid]) return;
          seen[pid] = true;
          const pk = POS_ID[p.pos] || p.pos || '';
          const pts = p.pts || p.total_points || 0;
          if (pts > 0 && pk) {{
            sums[pk] = (sums[pk] || 0) + pts;
            counts[pk] = (counts[pk] || 0) + 1;
          }}
        }});
      }});
      for (const k in sums) LEAGUE_POS_AVGS[k] = sums[k] / counts[k];
    }})();
    
    // Funkcja renderPlayers - identyczna jak w scraper.py
    function renderPlayers() {{
      let data = [...PLAYERS];
      if (pos !== 'ALL') data = data.filter(p => (POS_ID[p.position] || p.position) === pos);
      if (!data.length) return '<div class="empty-msg">Brak danych</div>';
      
      const hasLeague = LEAGUE_TEAMS.length > 0 && Object.keys(LEAGUE_POS_AVGS).length > 0;
      
      let h = '<div class="section-title"><span style="font-size:22px">⚽</span><h2>Zawodnicy</h2><div class="line"></div></div>';
      h += '<div class="data-table"><table><thead><tr>';
      h += '<th class="text-left">#</th>';
      h += '<th class="text-left sortable" data-tab="players" data-col="name">Zawodnik'+arrow('players','name')+'</th>';
      h += '<th class="text-left sortable" data-tab="players" data-col="team">Drużyna'+arrow('players','team')+'</th>';
      h += '<th class="text-center sortable" data-tab="players" data-col="position">Poz'+arrow('players','position')+'</th>';
      h += '<th class="text-right sortable" data-tab="players" data-col="price">Cena'+arrow('players','price')+'</th>';
      h += '<th class="text-right sortable" data-tab="players" data-col="total_points">Punkty'+arrow('players','total_points')+'</th>';
      h += '<th class="text-center sortable" data-tab="players" data-col="_diff_global" title="Punkty zawodnika minus średnia punktów wszystkich grających na tej pozycji">±Avg'+arrow('players','_diff_global')+'</th>';
      if (hasLeague) {{
        h += '<th class="text-center sortable" data-tab="players" data-col="_diff_league" title="Punkty zawodnika minus średnia punktów graczy na tej pozycji w drużynach z Twojej ligi">±Liga'+arrow('players','_diff_league')+'</th>';
      }}
      h += '<th class="text-right sortable" data-tab="players" data-col="points_per_price">Pkt/Cena'+arrow('players','points_per_price')+'</th>';
      h += '<th class="text-center" style="min-width:80px">Forma</th>';
      h += '<th class="text-right sortable" data-tab="players" data-col="_form_avg" title="Średnia punktów z rozegranych meczów z ostatnich 5 kolejek">Średnia'+arrow('players','_form_avg')+'</th>';
      h += '<th class="text-right sortable" data-tab="players" data-col="popularity_pct" title="Oficjalny % popularności z API Fantasy Ekstraklasa">Pop.'+arrow('players','popularity_pct')+'</th>';
      h += '</tr></thead><tbody>';
      
      // Dodaj dane formy i diff do sortowania
      data.forEach(p => {{
        const f = p.form || [];
        const played = f.filter(x => x.p !== false);
        p._form_avg = played.length ? played.reduce((s,x) => s + (x.pts||0), 0) / played.length : 0;
        const pk = POS_ID[p.position] || p.position || '';
        const pts = p.total_points || 0;
        p._diff_global = (POS_AVGS[pk] && pts > 0) ? Math.round((pts - POS_AVGS[pk]) * 10) / 10 : 0;
        p._diff_league = (LEAGUE_POS_AVGS[pk] && pts > 0) ? Math.round((pts - LEAGUE_POS_AVGS[pk]) * 10) / 10 : 0;
      }});
      data = sortData(data, 'players');
      
      data.forEach((p, i) => {{
        const pts = p.total_points || 0, price = p.price || 0, ppp = p.points_per_price || 0;
        const ptsC = pts >= 35 ? '#22d3ee' : pts >= 25 ? '#e2e8f0' : '#94a3b8';
        const pppC = ppp >= 15 ? '#10b981' : ppp >= 10 ? '#e2e8f0' : '#94a3b8';
        const pk = POS_ID[p.position] || p.position || '';
        h += '<tr><td class="c-muted fw-600">'+(i+1)+'</td>';
        h += nameCell(p.name, p.player_id, 'font-weight:600');
        h += '<td class="c-muted" style="font-size:13px">'+p.team+'</td>';
        h += '<td class="text-center">'+posBadge(pk)+'</td>';
        h += '<td class="text-right c-muted">'+price.toFixed(1)+'M</td>';
        h += '<td class="text-right fw-700" style="color:'+ptsC+'">'+pts+'</td>';
        h += '<td class="text-center">'+diffBadge(pts, POS_AVGS[pk])+'</td>';
        if (hasLeague) {{
          h += '<td class="text-center">'+diffBadge(pts, LEAGUE_POS_AVGS[pk])+'</td>';
        }}
        h += '<td class="text-right fw-600" style="color:'+pppC+'">'+ppp.toFixed(1)+'</td>';
        h += '<td class="text-center">'+formChart(p.form, true)+'</td>';
        const favg = p._form_avg;
        const favgC = favg >= 6 ? '#22d3ee' : favg >= 3 ? '#10b981' : '#94a3b8';
        h += '<td class="text-right fw-600" style="color:'+favgC+'">'+(favg > 0 ? favg.toFixed(1) : '—')+'</td>';
        h += '<td class="text-right c-dim" style="font-size:13px">'+(p.popularity_pct || '—')+'</td>';
        h += '</tr>';
      }});
      h += '</tbody></table></div>';
      return h;
    }}
    """

    # Generuj HTML archiwum
    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ScrapFEks – Archiwum Sezonu {season_name}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{archive_css}</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="header-left">
      <h1>📁 Archiwum Sezonu {season_name}</h1>
      <span class="archive-badge">ARCHIWUM</span>
    </div>
    <p class="sub">ScrapFEks · {timestamp}</p>
  </div>
  <a href="../index.html" class="back-link">← Powrót do bieżącego sezonu</a>

  <div class="tabs">
    <button class="tab active" data-tab="players">👥 Zawodnicy</button>
    <button class="tab" data-tab="league">🏆 Liga CMF</button>
    <button class="tab" data-tab="season">📅 Sezon</button>
  </div>

  <!-- Zakładka Zawodnicy -->
  <div id="tab-players" class="tab-content active">
    <div class="filters-row">
      <div class="pos-filters">
        <button class="pos-btn active" data-pos="ALL">ALL</button>
        <button class="pos-btn" data-pos="BR">GK</button>
        <button class="pos-btn" data-pos="OBR">DEF</button>
        <button class="pos-btn" data-pos="POM">MID</button>
        <button class="pos-btn" data-pos="NAP">FWD</button>
      </div>
    </div>
    <div id="players-content"></div>
  </div>

  <!-- Zakładka Liga CMF -->
  <div id="tab-league" class="tab-content">
    <div id="league-content">
    </div>
  </div>

  <!-- Zakładka Sezon -->
  <div id="tab-season" class="tab-content">
    <div id="season-content">
    </div>
  </div>

  <div class="footer">ScrapFEks Archiwum · {timestamp}</div>
</div>

<script>{archive_js}</script>
<script>
// Funkcja render - główna funkcja renderująca zawartość zakładek
function render() {{
  // Renderuj zawartość zakładki Zawodnicy
  const playersContent = document.getElementById('players-content');
  if (playersContent) {{
    playersContent.innerHTML = tab === 'players' ? renderPlayers() : '';
  }}
  
  // Renderuj zawartość zakładki Liga CMF
  const leagueContent = document.getElementById('league-content');
  if (leagueContent) {{
    leagueContent.innerHTML = tab === 'league' ? renderTeams() : '';
  }}
  
  // Renderuj zawartość zakładki Sezon
  const seasonContent = document.getElementById('season-content');
  if (seasonContent) {{
    seasonContent.innerHTML = tab === 'season' ? renderSeason() : '';
  }}
  
  // Aktualizuj klasy aktywnych zakładek
  document.querySelectorAll('.tab-content').forEach(el => el.classList.toggle('active', el.id === 'tab-' + tab));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  
  // Aktualizuj aktywne filtry pozycji
  document.querySelectorAll('.pos-btn').forEach(b => b.classList.toggle('active', b.dataset.pos === pos));
  
  // Podłącz obsługę kliknięć w sortowalne nagłówki
  document.querySelectorAll('.sortable').forEach(th => {{
    th.onclick = () => {{
      const t = th.dataset.tab, col = th.dataset.col;
      if (sorts[t].col === col) sorts[t].dir = sorts[t].dir === 'desc' ? 'asc' : 'desc';
      else {{ sorts[t].col = col; sorts[t].dir = 'desc'; }}
      render();
    }};
  }});
  
  // Podłącz obsługę kliknięć w wiersze drużyn (expand/collapse)
  document.querySelectorAll('tr[data-teamslug]').forEach(el => {{
    el.onclick = (e) => {{
      if (e.target.closest('a')) return;
      const slug = el.dataset.teamslug;
      selectedTeam = selectedTeam === slug ? '' : slug;
      render();
    }};
  }});
  
  // Podłącz obsługę kliknięć w szczegóły zawodników
  attachDetailClicks();
}}

// Funkcja renderTeams - renderuje zakładkę Liga CMF
function renderTeams() {{
  if (!LEAGUE_TEAMS.length) return '<div class="empty-msg">Brak danych o drużynach ligi</div>';
  
  // Sortowanie drużyn
  const tls = sorts.teams_list;
  const sortedTeams = [...LEAGUE_TEAMS].sort((a, b) => {{
    let av, bv;
    if (tls.col === 'name') {{
      av = (a.display_name || a.slug || '').toLowerCase();
      bv = (b.display_name || b.slug || '').toLowerCase();
      if (av < bv) return tls.dir === 'desc' ? 1 : -1;
      if (av > bv) return tls.dir === 'desc' ? -1 : 1;
      return 0;
    }}
    av = num(a[tls.col]); bv = num(b[tls.col]);
    if (av < bv) return tls.dir === 'desc' ? 1 : -1;
    if (av > bv) return tls.dir === 'desc' ? -1 : 1;
    return 0;
  }});
  
  function tlArrow(col) {{
    return tls.col === col ? (tls.dir === 'desc' ? ' ▼' : ' ▲') : '';
  }}
  
  let h = '<div class="section-title"><span style="font-size:22px">📋</span><h2>Liga CMF</h2><div class="line"></div></div>';
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-center sortable" data-tab="teams_list" data-col="hockey_pos" style="width:50px">#'+tlArrow('hockey_pos')+'</th>';
  h += '<th class="text-left sortable" data-tab="teams_list" data-col="name">Drużyna'+tlArrow('name')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="autumn_pts">Jesień'+tlArrow('autumn_pts')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="spring_pts">Wiosna'+tlArrow('spring_pts')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="total_pts" style="font-size:13px;font-weight:800">SUMA'+tlArrow('total_pts')+'</th>';
  h += '<th class="text-center sortable" data-tab="teams_list" data-col="rank_change">Zmiana'+tlArrow('rank_change')+'</th>';
  h += '</tr></thead><tbody>';
  
  sortedTeams.forEach((t, i) => {{
    const pos = t.hockey_pos || (i + 1);
    const medal = pos === 1 ? '🥇' : pos === 2 ? '🥈' : pos === 3 ? '🥉' : pos;
    const tName = t.display_name || (t.slug ? t.slug.replace(/-/g,' ') : 'Drużyna');
    const isOpen = t.slug === selectedTeam;
    const hasPlayers = t.players && t.players.length > 0;
    
    let rowStyle = hasPlayers ? 'cursor:pointer' : '';
    
    h += '<tr'+(rowStyle ? ' style="'+rowStyle+'"' : '')+' data-teamslug="'+t.slug+'">';
    h += '<td class="text-center" style="font-size:'+(pos<=3?'18px':'14px')+'">' + medal + '</td>';
    h += '<td style="font-weight:600">' + tName + (hasPlayers ? ' <span style="font-size:10px;color:#475569">'+(isOpen?'▼':'▶')+'</span>' : '') + '</td>';
    h += '<td class="text-right" style="color:#94a3b8">' + (t.autumn_pts||0) + '</td>';
    h += '<td class="text-right" style="color:#94a3b8">' + (t.spring_pts||0) + '</td>';
    h += '<td class="text-right" style="font-weight:800;font-size:15px">' + (t.total_pts||0) + '</td>';
    
    const rc = t.rank_change || 0;
    let changeHtml = '';
    if (rc > 0) changeHtml = '<span style="color:#10b981">▲' + rc + '</span>';
    else if (rc < 0) changeHtml = '<span style="color:#ef4444">▼' + Math.abs(rc) + '</span>';
    else changeHtml = '<span style="color:#64748b">–</span>';
    h += '<td class="text-center">' + changeHtml + '</td>';
    h += '</tr>';
    
    // Rozwijany panel ze składem
    if (isOpen && hasPlayers) {{
      const POS_ORDER = {{BR:1,OBR:2,POM:3,NAP:4}};
      
      // Przygotuj dane zawodników
      t.players.forEach(p => {{
        const pk = POS_ID[p.pos] || p.pos || '';
        p._pk = pk;
        p._pos_order = POS_ORDER[pk] || 99;
        p._diff_global = (POS_AVGS[pk] && (p.pts||0) > 0) ? Math.round(((p.pts||0) - POS_AVGS[pk]) * 10) / 10 : 0;
        p._diff_league = (LEAGUE_POS_AVGS[pk] && (p.pts||0) > 0) ? Math.round(((p.pts||0) - LEAGUE_POS_AVGS[pk]) * 10) / 10 : 0;
        p._form_avg = formAvgNum(p.form);
      }});
      
      // Sortuj zawodników
      const s = sorts.teams;
      const sortedPlayers = [...t.players].sort((a,b) => {{
        let av = a[s.col], bv = b[s.col];
        if (typeof av === 'string') {{
          if (av < bv) return s.dir === 'desc' ? 1 : -1;
          if (av > bv) return s.dir === 'desc' ? -1 : 1;
          return 0;
        }}
        av = num(av); bv = num(bv);
        if (av < bv) return s.dir === 'desc' ? 1 : -1;
        if (av > bv) return s.dir === 'desc' ? -1 : 1;
        return 0;
      }});
      
      h += '<tr><td colspan="6" style="padding:0;background:#0f172a">';
      h += '<div class="data-table" style="padding:4px 12px 12px">';
      h += '<table><thead><tr>';
      h += '<th class="text-left">#</th>';
      h += '<th class="text-left sortable" data-tab="teams" data-col="name">Zawodnik'+arrow('teams','name')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_pos_order">Poz'+arrow('teams','_pos_order')+'</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="price">Cena'+arrow('teams','price')+'</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="pts">Punkty'+arrow('teams','pts')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_diff_global">±Avg'+arrow('teams','_diff_global')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_diff_league">±Liga'+arrow('teams','_diff_league')+'</th>';
      h += '<th class="text-center" style="min-width:80px">Forma</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="_form_avg">Średnia'+arrow('teams','_form_avg')+'</th>';
      h += '</tr></thead><tbody>';
      
      sortedPlayers.forEach((p, idx) => {{
        const pk = p._pk;
        const pts = p.pts || 0;
        const price = p.price || 0;
        let nameStyle = 'font-weight:600';
        if (p.C) nameStyle += ';color:#fbbf24';
        
        h += '<tr><td class="c-muted fw-600">'+(idx+1)+'</td>';
        h += nameCell(p.name, p.pid, nameStyle, p.C ? '<span class="captain-badge" style="margin-right:4px">C</span> ' : '');
        h += '<td class="text-center">'+posBadge(pk)+'</td>';
        h += '<td class="text-right c-muted">'+price.toFixed(1)+'M</td>';
        h += '<td class="text-right fw-700">'+pts+'</td>';
        h += '<td class="text-center">'+diffBadge(pts, POS_AVGS[pk])+'</td>';
        h += '<td class="text-center">'+diffBadge(pts, LEAGUE_POS_AVGS[pk])+'</td>';
        const favg = p._form_avg;
        const favgC = favg >= 6 ? '#22d3ee' : favg >= 3 ? '#10b981' : '#94a3b8';
        h += '<td class="text-center">'+formChart(p.form, true)+'</td>';
        h += '<td class="text-right fw-600" style="color:'+favgC+'">'+(favg > 0 ? favg.toFixed(1) : '—')+'</td>';
        h += '</tr>';
      }});
      
      h += '</tbody></table></div>';
      h += '</td></tr>';
    }}
  }});
  
  h += '</tbody></table></div>';
  return h;
}}

// Funkcja renderSeason - renderuje zakładkę Sezon
function renderSeason() {{
  if (!LEAGUE_HISTORY || !LEAGUE_HISTORY.rounds || LEAGUE_HISTORY.rounds.length === 0) {{
    return '<div class="empty-msg">Brak danych sezonu</div>';
  }}
  
  let h = '<div class="section-title"><span style="font-size:22px">📅</span><h2>Historia sezonu</h2><div class="line"></div></div>';
  h += '<div class="season-wrap">';
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-center">Kolejka</th>';
  h += '<th class="text-left">Gospodarz</th>';
  h += '<th class="text-center">Wynik</th>';
  h += '<th class="text-left">Gość</th>';
  h += '</tr></thead><tbody>';
  
  LEAGUE_HISTORY.rounds.forEach(r => {{
    h += '<tr>';
    h += '<td class="text-center fw-600">K'+r.round+'</td>';
    h += '<td>'+(r.home_team || '—')+'</td>';
    h += '<td class="text-center fw-700">'+(r.home_score || '-')+' : '+(r.away_score || '-')+'</td>';
    h += '<td>'+(r.away_team || '—')+'</td>';
    h += '</tr>';
  }});
  
  h += '</tbody></table></div>';
  h += '</div>';
  return h;
}}

// Obsługa zakładek
document.querySelectorAll('.tab').forEach(t => {{
  t.addEventListener('click', () => {{
    tab = t.dataset.tab;
    render();
  }});
}});

// Obsługa filtrów pozycji
document.querySelectorAll('.pos-btn').forEach(b => {{
  b.addEventListener('click', () => {{
    pos = b.dataset.pos;
    render();
  }});
}});

// Inicjalne renderowanie
render();
</script>
</body>
</html>"""

    # Zapisz plik archiwum
    os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else ".", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  📄 Wygenerowano archiwum HTML: {filename}")


# ============================================================
# ŁADOWANIE DANYCH
# ============================================================

def load_players_data() -> list[dict]:
    """Wczytuje dane zawodników z pliku JSON w output/."""
    # Znajdź najnowszy plik fantasy_full_*.json w output/
    # Sortuj po nazwie (alfabetycznie) - ostatni będzie najnowszy (格式: fantasy_full_YYYYMMDD_HHMMSS.json)
    pattern = os.path.join(OUTPUT_DIR, "fantasy_full_*.json")
    files = sorted(glob_module.glob(pattern))
    
    if not files:
        print(f"  ⚠️  Brak plików fantasy_full_*.json w {OUTPUT_DIR}")
        return []
    
    # Weź ostatni plik (najnowszy)
    latest_file = files[-1]
    print(f"  📂 Wczytuję dane zawodników z: {latest_file}")
    
    with open(latest_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_league_history() -> dict:
    """Wczytuje historię ligi z league_history.json."""
    # league_history.json jest w katalogu output/, nie w głównym katalogu
    history_file = os.path.join(OUTPUT_DIR, "league_history.json")
    if not os.path.exists(history_file):
        print(f"  ℹ️  Brak pliku {history_file}")
        return {"rounds": []}
    
    with open(history_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_league_teams_detail() -> list[dict]:
    """Wczytuje szczegóły drużyn ligi z output/."""
    # Dane league_teams nie są zapisywane jako osobny plik JSON w output/
    # Zwraca pustą listę - archiwum będzie działać bez danych ligi CMF
    print(f"  ℹ️  Dane ligi CMF (league_teams) nie są dostępne jako JSON - pomijam")
    return []


# ============================================================
# KOPIOWANIE PLIKÓW DO ARCHIWUM
# ============================================================

def copy_data_files_to_archive(season_name: str):
    """Kopiuje pliki danych do katalogu archiwum."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    
    # Kopia autumn_points.json
    if os.path.exists("autumn_points.json"):
        dest = f"{ARCHIVE_DIR}/autumn_points_{season_name}.json"
        shutil.copy("autumn_points.json", dest)
        print(f"   📄 Skopiowano autumn_points.json → {dest}")
    
    # Kopia league_history.json
    if os.path.exists("league_history.json"):
        dest = f"{ARCHIVE_DIR}/league_history_{season_name}.json"
        shutil.copy("league_history.json", dest)
        print(f"   📄 Skopiowano league_history.json → {dest}")
    
    # Kopia duets.json
    if os.path.exists("duets.json"):
        dest = f"{ARCHIVE_DIR}/duets_{season_name}.json"
        shutil.copy("duets.json", dest)
        print(f"   📄 Skopiowano duets.json → {dest}")
    
    # Kopia players z output/
    players = load_players_data()
    if players:
        dest = f"{ARCHIVE_DIR}/players_{season_name}.json"
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(players, f, ensure_ascii=False, indent=2)
        print(f"   📄 Skopiowano dane zawodników → {dest}")


# ============================================================
# RESETOWANIE DANYCH PO ARCHIWIZACJI
# ============================================================

def reset_data_after_archive(season_name: str):
    """
    Resetuje dane po archiwizacji sezonu.
    Uwaga: to jest opcjonalne i wymaga manualnego potwierdzenia.
    """
    print(f"\n⚠️  Reset danych po archiwizacji sezonu {season_name}")
    print("   Ta operacja usuwa/plikuje dane bieżącego sezonu.")
    print("   Nie jest to wykonywane automatycznie - do ręcznego uruchomienia.")
    
    # W obecnej wersji NIE resetujemy automatycznie
    # Użytkownik może ręcznie wyczyścić dane jeśli chce zacząć nowy sezon
    print("   ℹ️  Automatyczny reset wyłączony.")
    print("   ℹ️  Jeśli chcesz zresetować sezon, usuń ręcznie:")
    print("       - output/*.json (oprócz checkpointów)")
    print("       - autumn_points.json")
    print("       - league_history.json")
    print("       - duets.json")


# ============================================================
# MAIN
# ============================================================

def main():
    """Główna funkcja archiwizacji."""
    print(f"\n{'='*60}")
    print(f"📦 ARCHIWIZACJA SEZONU: {SEASON_NAME}")
    print(f"{'='*60}\n")

    # Ścieżka do archiwum – spacje zamienione na myślniki
    archive_html_path = f"{ARCHIVE_DIR}/sezon-{SEASON_NAME.replace(' ', '-')}.html"

    # Wczytaj dane
    print("📥 Wczytuję dane...")
    players = load_players_data()
    league_history = load_league_history()
    league_teams_detail = load_league_teams_detail()

    if not players:
        print("❌ Błąd: brak danych zawodników do archiwizacji!")
        print(f"   Upewnij się, że plik players_*.json istnieje w katalogu {OUTPUT_DIR}")
        sys.exit(1)

    print(f"   ✓ Załadowano {len(players)} zawodników")
    print(f"   ✓ Załadowano {len(league_teams_detail)} drużyn ligi")

    # Generuj archiwum HTML
    print("\n🎨 Generuję archiwum HTML...")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generate_archive_html(
        season_name=SEASON_NAME,
        players=players,
        league_teams_detail=league_teams_detail,
        league_history=league_history,
        timestamp=timestamp,
        filename=archive_html_path,
    )

    # Kopiuj pliki danych do archiwum
    print("\n📁 Kopiuję pliki danych do archiwum...")
    copy_data_files_to_archive(SEASON_NAME)

    # Opcjonalnie zresetuj dane (na razie wyłączone)
    reset_data_after_archive(SEASON_NAME)

    # Zaktualizuj index archiwum
    print("\n📑 Aktualizuję index archiwum...")
    generate_archive_index(ARCHIVE_DIR)

    print(f"\n{'='*60}")
    print(f"✅ Archiwizacja zakończona!")
    print(f"   📄 HTML: {archive_html_path}")
    print(f"   📁 Dane: {ARCHIVE_DIR}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()