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
    timestamp: str,
    filename: str,
):
    """
    Generuje uproszczony HTML archiwum sezonu.
    Zawiera tylko zakładki: Zawodnicy, Liga CMF, Sezon.
    """
    # Przygotuj dane dla JS
    players_json = json.dumps(players[:200], ensure_ascii=False)  # Limit do 200 zawodników
    league_teams_json = json.dumps(league_teams_detail, ensure_ascii=False)
    league_history_json = json.dumps(league_history or {"rounds": []}, ensure_ascii=False)

    # CSS dla archiwum (uproszczony)
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
    .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
    .header-left { display: flex; align-items: center; gap: 14px; }
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
    .c-muted { color: #949494; }
    .empty-msg { padding: 40px; text-align: center; color: #949494; }
    .team-list { display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }
    .team-list-item { background: #2d2d2d; border: 1px solid #3cffd0; border-radius: 8px; }
    .team-list-header { display: flex; align-items: center; gap: 12px; padding: 10px 16px; cursor: pointer; }
    .team-list-rank { font-size: 13px; font-weight: 800; color: #3cffd0; min-width: 32px; }
    .team-list-name { font-size: 14px; font-weight: 700; color: #ffffff; flex: 1; text-transform: capitalize; }
    .team-list-pts { font-size: 12px; color: #949494; font-weight: 600; }
    .footer { text-align: center; margin-top: 32px; color: #949494; font-size: 12px; }
    .season-wrap { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
    .season-chart svg { display: block; }

    /* Dodatkowe style dla pełnej tabeli drużyn */
    .section-title { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
    .section-title h2 { font-size: 18px; font-weight: 700; margin: 0; }
    .section-title .line { flex: 1; height: 1px; background: #2d2d2d; }
    .view-toggle { display: flex; gap: 8px; margin-bottom: 16px; }
    .view-btn { padding: 6px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
    .view-btn.active { background: #3b82f6; color: #fff; }
    .sortable { cursor: pointer; }
    .sortable:hover { color: #3cffd0 !important; }
    .highlight { background: rgba(60, 255, 208, 0.1); }
    .captain-badge { background: #fbbf24; color: #000; padding: 1px 5px; border-radius: 3px; font-size: 10px; font-weight: 700; }
    .diff-badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 12px; font-weight: 600; }
    .diff-pos { background: rgba(16, 185, 129, 0.2); color: #10b981; }
    .diff-neg { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
    .diff-zero { background: rgba(148, 163, 184, 0.2); color: #94a3b8; }
    .form-chart { display: flex; align-items: flex-end; gap: 2px; height: 20px; }
    .form-chart.mini { height: 12px; }
    .form-bar { width: 4px; border-radius: 2px; min-height: 2px; }
    .form-bar.not-played { opacity: 0.3; }
    .player-link { color: #3cffd0; text-decoration: none; }
    .player-link:hover { color: #3860be; }
    .c-dim { color: #64748b; }
    """

    # JS dla archiwum (uproszczony)
    archive_js = f"""
    const PLAYERS = {players_json};
    const LEAGUE_TEAMS = {league_teams_json};
    const LEAGUE_HISTORY = {league_history_json};
    const POS_MAP = {{BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD','1':'GK','2':'DEF','3':'MID','4':'FWD'}};
    const POS_ID = {{'1':'BR','2':'OBR','3':'POM','4':'NAP',BR:'BR',OBR:'OBR',POM:'POM',NAP:'NAP'}};
    const DUETS_DATA = [];  // Archiwum nie zawiera danych o duetach

    // Średnie punkty per pozycja — globalne (z wszystkich zawodników)
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

    // Średnie punkty per pozycja — liga (z drużyn ligowych)
    const LEAGUE_POS_AVGS = {{}};
    (function() {{
      const seen = {{}}, sums = {{}}, counts = {{}};
      LEAGUE_TEAMS.forEach(t => {{
        if (t.players) t.players.forEach(p => {{
          const pid = p.pid;
          if (seen[pid]) return;
          seen[pid] = true;
          const pk = POS_ID[p.pos] || p.pos || '';
          const pts = p.pts || 0;
          if (pts > 0 && pk) {{
            sums[pk] = (sums[pk] || 0) + pts;
            counts[pk] = (counts[pk] || 0) + 1;
          }}
        }});
      }});
      for (const k in sums) LEAGUE_POS_AVGS[k] = sums[k] / counts[k];
    }})();

    // Stan dla renderTeams
    let currentTeamsView = 'teams';
    let selectedTeam = null;
    const sorts = {{
      teams: {{col: 'pts', dir: 'desc'}},
      teams_list: {{col: 'total_pts', dir: 'desc'}},
      duets: {{col: 'total_pts', dir: 'desc'}},
      duets_list: {{col: 'total_pts', dir: 'desc'}}
    }};

    // Funkcje pomocnicze
    function num(v) {{ return parseFloat(String(v).replace(/[^0-9.-]/g,'')) || 0; }}
    function arrow(tab, col) {{ return sorts[tab].col === col ? (sorts[tab].dir === 'desc' ? ' ▼' : ' ▲') : ''; }}
    function formAvgNum(f) {{ if (!f || !f.length) return 0; const played = f.filter(x => x.p !== false); return played.length ? played.reduce((s,x) => s + (x.pts||0), 0) / played.length : 0; }}

    function diffBadge(pts, avg) {{
      if (!avg) return '<span class="diff-badge diff-zero">—</span>';
      const d = pts - avg;
      const cls = d > 0 ? 'diff-pos' : d < 0 ? 'diff-neg' : 'diff-zero';
      return '<span class="diff-badge '+cls+'">'+(d>0?'+':'')+d.toFixed(0)+'</span>';
    }}

    function nameCell(name, pid, style, prefix) {{
      return '<td style="'+style+'">'+prefix+'<a href="#" class="player-link" data-pid="'+pid+'">'+name+'</a></td>';
    }}

    function formChart(f, mini) {{
      if (!f || !f.length) return '<span style="color:#64748b">—</span>';
      let h = '<div class="form-chart'+(mini?' mini':'')+'">';
      f.forEach(ff => {{
        const pts = ff.pts || 0;
        const played = ff.p !== false;
        const color = !played ? '#334155' : pts >= 8 ? '#22d3ee' : pts >= 4 ? '#10b981' : pts >= 0 ? '#64748b' : '#ef4444';
        const height = Math.max(Math.abs(pts) / 15 * (mini?12:20), 2);
        h += '<div class="form-bar'+(played?'':' not-played')+'" style="height:'+height+'px;background:'+color+'"></div>';
      }});
      return h + '</div>';
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
    <div class="data-table">
      <table>
        <thead>
          <tr>
            <th class="sortable" data-col="name">Zawodnik</th>
            <th>Drużyna</th>
            <th class="text-center">Pozycja</th>
            <th class="text-right sortable" data-col="total_points">Punkty</th>
            <th class="text-right sortable" data-col="price">Cena</th>
            <th class="text-right">Średnia</th>
          </tr>
        </thead>
        <tbody id="players-body">
        </tbody>
      </table>
    </div>
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
// Obsługa zakładek
document.querySelectorAll('.tab').forEach(tab => {{
  tab.addEventListener('click', () => {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  }});
}});

// Renderuj zawodników
const playersBody = document.getElementById('players-body');
PLAYERS.slice(0, 100).forEach(p => {{
  const pos = POS_ID[p.position] || p.position || '';
  const posClass = 'pos-' + (pos === 'BR' ? '1' : pos === 'OBR' ? '2' : pos === 'POM' ? '3' : pos === 'NAP' ? '4' : '');
  const posLabel = POS_MAP[pos] || pos;
  const avg = POS_AVGS[pos] || 0;
  const row = document.createElement('tr');
  row.innerHTML = `
    ${{nameCell(p.name, p.player_id, '', '')}}
    <td>${{p.team || ''}}</td>
    <td class="text-center"><span class="pos-badge ${{posClass}}">${{posLabel}}</span></td>
    <td class="text-right fw-700">${{p.total_points || 0}}</td>
    <td class="text-right">${{(p.price || 0).toFixed(2)}}</td>
    <td class="text-right c-muted">${{diffBadge(p.total_points / 15, avg)}}</td>
  `;
  playersBody.appendChild(row);
}});

// Renderuj ligę CMF
const leagueContent = document.getElementById('league-content');
if (LEAGUE_TEAMS && LEAGUE_TEAMS.length > 0) {{
  let html = '<div class="team-list">';
  LEAGUE_TEAMS.forEach((t, i) => {{
    html += `
      <div class="team-list-item">
        <div class="team-list-header">
          <span class="team-list-rank">${{i + 1}}</span>
          <span class="team-list-name">${{t.team_name || t.slug || 'Drużyna'}}</span>
          <span class="team-list-pts">${{t.total_points || 0}} pkt</span>
        </div>
      </div>`;
  }});
  html += '</div>';
  leagueContent.innerHTML = html;
}} else {{
  leagueContent.innerHTML = '<div class="empty-msg">Brak danych ligi CMF</div>';
}}

// Renderuj sezon
const seasonContent = document.getElementById('season-content');
if (LEAGUE_HISTORY && LEAGUE_HISTORY.rounds && LEAGUE_HISTORY.rounds.length > 0) {{
  let html = '<div class="season-wrap">';
  html += '<h3>Historia sezonu</h3>';
  html += '<div class="season-chart">';
  LEAGUE_HISTORY.rounds.forEach(r => {{
    html += `<div style="padding: 8px; border-bottom: 1px solid #2d2d2d;">
      <strong>Kolejka ${{r.round}}</strong>: ${{r.home_team}} ${{r.home_score || '-'}} - ${{r.away_score || '-'}} ${{r.away_team}}
    </div>`;
  }});
  html += '</div></div>';
  seasonContent.innerHTML = html;
}} else {{
  seasonContent.innerHTML = '<div class="empty-msg">Brak danych sezonu</div>';
}}
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
    # Znajdź najnowszy plik players_*.json w output/
    pattern = os.path.join(OUTPUT_DIR, "players_*.json")
    files = glob_module.glob(pattern)
    
    if not files:
        print(f"  ⚠️  Brak plików players_*.json w {OUTPUT_DIR}")
        return []
    
    # Weź najnowszy plik
    latest_file = max(files, key=os.path.getmtime)
    print(f"  📂 Wczytuję dane z: {latest_file}")
    
    with open(latest_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_league_history() -> dict:
    """Wczytuje historię ligi z league_history.json."""
    history_file = "league_history.json"
    if not os.path.exists(history_file):
        print(f"  ℹ️  Brak pliku {history_file}")
        return {"rounds": []}
    
    with open(history_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_league_teams_detail() -> list[dict]:
    """Wczytuje szczegóły drużyn ligi z output/."""
    # Szukaj pliku z danymi ligi - sprawdź różne możliwe nazwy
    possible_files = [
        os.path.join(OUTPUT_DIR, "league_teams_detail.json"),
        os.path.join(OUTPUT_DIR, "league_teams_detail_latest.json"),
    ]
    
    for f in possible_files:
        if os.path.exists(f):
            print(f"  📂 Wczytuję dane ligi z: {f}")
            with open(f, "r", encoding="utf-8") as fp:
                return json.load(fp)
    
    # Fallback: spróbuj znaleźć dowolny pasujący plik
    pattern = os.path.join(OUTPUT_DIR, "league_teams*.json")
    files = glob_module.glob(pattern)
    if files:
        latest = max(files, key=os.path.getmtime)
        print(f"  📂 Wczytuję dane ligi z: {latest}")
        with open(latest, "r", encoding="utf-8") as fp:
            return json.load(fp)
    
    print(f"  ℹ️  Brak plików league_teams w {OUTPUT_DIR}")
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