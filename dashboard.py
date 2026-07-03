"""dashboard.py - generowanie dashboardu HTML.

generate_dashboard_html() dostaje wszystkie dane jako parametry
i zwraca kompletny string HTML. Zero globalnego stanu, zero
operacji I/O - czysty transform danych → HTML.
"""
import json

def generate_dashboard_html(
    summary_data: list[dict],
    tiers: dict,
    teams_count: int,
    league_captain_stats: list[dict],
    league_ownership_stats: list[dict],
    league_name: str,
    league_teams_count: int,
    league_rosters: dict,
    league_teams_detail: list[dict],
    duets_data: list[dict],
    fixtures_data: dict,
    ekstra_stats: dict,
    fdr_data: dict,
    transfers_data: dict,
    predictions_data: list[dict],
    accuracy_history: list[dict],
    tuned_params: dict,
    league_history: dict,
    # 📖 newsletter_data usunięte z sygnatury — zakładka Newsletter wyłączona
    timestamp: str,
    filename: str,
    has_archive: bool = False,
):
    """Generuje interaktywny dashboard HTML z danymi Fantasy Ekstraklasa."""

    # Build DATA object for JS: { scope_key: { captains, ownership, label, count } }
    scopes_data = {}
    scope_buttons = []

    # Tier scopes (top10, top100, all)
    for key in ["top10", "top100", "all"]:
        tier = tiers.get(key)
        if not tier:
            continue
        count = tier["count"]
        label = f"Top {count}" if key != "all" else f"Wszystkie ({count})"
        scopes_data[key] = {
            "captains": tier["captains"][:50],
            "ownership": tier["ownership"],
            "label": label,
            "count": count,
        }
        emoji = "🏆" if key == "top10" else "🥈" if key == "top100" else "📊"
        scope_buttons.append((key, f"{emoji} Top {count}" if key != "all" else f"{emoji} Wszystkie ({count})"))

    # League scope
    has_league = league_teams_count > 0
    league_label = league_name.replace("-", " ").title() if league_name else ""
    if has_league:
        scopes_data["league"] = {
            "captains": league_captain_stats[:50],
            "ownership": league_ownership_stats,
            "label": league_label,
            "count": league_teams_count,
        }
        scope_buttons.append(("league", f"🏅 {league_label}"))

    data_json = json.dumps(scopes_data, ensure_ascii=False)
    players_json = json.dumps(summary_data, ensure_ascii=False)
    rosters_json = json.dumps(league_rosters, ensure_ascii=False)
    teams_detail_json = json.dumps(league_teams_detail, ensure_ascii=False)
    duets_data_json = json.dumps(duets_data or [], ensure_ascii=False)
    fixtures_json = json.dumps(fixtures_data, ensure_ascii=False)
    ekstra_stats_json = json.dumps(ekstra_stats, ensure_ascii=False)
    fdr_data_json = json.dumps(fdr_data, ensure_ascii=False)
    transfers_data_json = json.dumps(transfers_data or {}, ensure_ascii=False)
    predictions_json = json.dumps(predictions_data or [], ensure_ascii=False)
    accuracy_json = json.dumps(accuracy_history or [], ensure_ascii=False)
    tuned_params_json = json.dumps(tuned_params or None, ensure_ascii=False)
    league_history_json = json.dumps(league_history or {"rounds": []}, ensure_ascii=False)
    # 📖 newsletter_data usunięte — zakładka Newsletter wyłączona
    has_season = len((league_history or {}).get("rounds", [])) > 0
    has_fixtures = len(fixtures_data.get("rounds", [])) > 0
    has_transfers = bool((transfers_data or {}).get("transfers_in") or (transfers_data or {}).get("transfers_out"))
    has_predictions = len(predictions_data or []) > 0
    has_accuracy = len(accuracy_history or []) > 0
    # Sprawdź czy istnieje katalog archiwum z plikami sezon-*.html (dostarczane jako parametr)

    # For stat cards
    all_tier = tiers.get("all", tiers.get("top100", tiers.get("top10", {})))
    all_owns = all_tier.get("ownership", []) if all_tier else []
    top_owned = all_owns[0] if all_owns else {}
    best_ppp = max(summary_data, key=lambda x: x.get("points_per_price", 0)) if summary_data else {}

    # Default scope
    default_scope = "top10" if "top10" in scopes_data else ("top100" if "top100" in scopes_data else "league")

    # Build scope toggle HTML
    scope_toggle_html = ""
    if len(scope_buttons) > 1:
        btns = ""
        for key, label in scope_buttons:
            btns += f"<button class='scope-btn' data-scope='{key}'>{label}</button>"
        scope_toggle_html = f"<div class='scope-toggle'>{btns}</div>"

    html = f'''<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fantasy Ekstraklasa Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
/* ============================================================
   MOTYW CIEMNY (domyślny) — oparty na design.md
   ============================================================ */
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ background: #131313; }}
body {{
  min-height: 100vh;
  background: #131313;
  color: #ffffff;
  font-family: 'DM Sans', -apple-system, sans-serif;
  padding: 24px 16px;
}}
.container {{ max-width: 1400px; margin: 0 auto; padding: 0 16px; }}
@media (max-width: 768px) {{ .container {{ max-width: 100%; padding: 0 12px; }} }}
@media (min-width: 2000px) {{ .container {{ max-width: 1600px; }} }}

/* Header + Theme Toggle */
.header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }}
.header-left {{ display: flex; align-items: center; gap: 14px; }}
.logo {{ width: 48px; height: 48px; border-radius: 10px; object-fit: contain; }}
.header h1 {{ font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }}
.header .sub {{ font-size: 12px; color: #949494; margin: 0; }}

/* Theme Toggle Button */
.theme-toggle {{
  background: #2d2d2d;
  border: 1px solid #3cffd0;
  border-radius: 24px;
  color: #3cffd0;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.2s;
}}
.theme-toggle:hover {{ background: #3cffd0; color: #131313; }}

/* Stat Cards */
.stats-row {{ display: flex; gap: 12px; margin-top: 16px; overflow-x: auto; padding-bottom: 4px; flex-wrap: wrap; }}
.stat-card {{
  background: #2d2d2d;
  border: 1px solid #3cffd0;
  border-radius: 20px;
  padding: 16px 20px;
  flex: 1 1 calc(25% - 12px); min-width: 140px; max-width: 250px;
}}
.stat-card .val {{ font-size: 24px; font-weight: 800; }}
.stat-card .label {{ font-size: 11px; color: #949494; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.8px; }}
.stat-card .sub {{ font-size: 11px; color: #949494; margin-top: 4px; }}
.accent-cyan {{ border-left: 3px solid #3cffd0; }}
.accent-cyan .val {{ color: #3cffd0; }}
.accent-gold {{ border-left: 3px solid #fbbf24; }}
.accent-gold .val {{ color: #fbbf24; }}
.accent-green {{ border-left: 3px solid #10b981; }}
.accent-green .val {{ color: #10b981; }}
.accent-purple {{ border-left: 3px solid #5200ff; }}
.accent-purple .val {{ color: #5200ff; }}

/* Tabs */
.tabs {{ display: flex; gap: 4px; border-bottom: 1px solid #2d2d2d; flex-wrap: wrap; }}
.tab {{
  background: transparent; border: none; border-bottom: 2px solid transparent;
  color: #949494; padding: 10px 18px; font-size: 13px; font-weight: 600;
  cursor: pointer; border-radius: 8px 8px 0 0; transition: all 0.2s;
  font-family: inherit;
}}
.tab.active {{ background: #2d2d2d; border-bottom-color: #3cffd0; color: #ffffff; }}
.tab:hover {{ color: #3860be; }}

/* Filters */
.filters-row {{ display: flex; gap: 8px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
.pos-filters {{ display: flex; gap: 4px; align-items: center; }}
.pos-btn {{
  background: transparent; border: 1px solid #2d2d2d; color: #949494;
  padding: 4px 10px; font-size: 11px; font-weight: 700; cursor: pointer;
  border-radius: 6px; font-family: inherit; transition: all 0.15s;
}}
.pos-btn.active {{ border-color: transparent; color: #131313; }}
.pos-btn.active[data-pos="ALL"] {{ background: #3cffd0; }}
.pos-btn.active[data-pos="BR"] {{ background: #f59e0b; }}
.pos-btn.active[data-pos="OBR"] {{ background: #3b82f6; }}
.pos-btn.active[data-pos="POM"] {{ background: #10b981; }}
.pos-btn.active[data-pos="NAP"] {{ background: #ef4444; }}
.scope-toggle {{ display: flex; gap: 0; border-radius: 8px; overflow: hidden; border: 1px solid #2d2d2d; }}
.scope-btn {{
  background: transparent; border: none; color: #949494;
  padding: 6px 14px; font-size: 12px; font-weight: 600; cursor: pointer;
  font-family: inherit; transition: all 0.15s;
}}
.scope-btn.active {{ background: #3cffd0; color: #131313; }}

/* Section Title */
.section-title {{ display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }}
.section-title h2 {{ font-size: 16px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: #ffffff; }}
.section-title .line {{ flex: 1; height: 1px; background: linear-gradient(90deg, #2d2d2d, transparent); }}

/* Data Table */
.data-table {{ background: #2d2d2d; border-radius: 12px; overflow: hidden; width: 100%; overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
thead tr {{ background: #131313; }}
th {{ padding: 10px 14px; color: #949494; font-weight: 600; font-size: 11px; text-transform: uppercase; white-space: nowrap; }}
th.sortable {{ cursor: pointer; user-select: none; }}
th.sortable:hover {{ color: #ffffff; }}
th.sortable[title] {{ cursor: help; border-bottom: 1px dashed #2d2d2d; }}
td {{ padding: 10px 14px; border-top: 1px solid #131313; white-space: nowrap; }}
tr.highlight {{ background: rgba(251,191,36,0.06); }}

/* Badge pozycji */
.pos-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; color: #131313; }}
.pos-BR, .pos-1 {{ background: #f59e0b; }}
.pos-OBR, .pos-2 {{ background: #3b82f6; }}
.pos-POM, .pos-3 {{ background: #10b981; }}
.pos-NAP, .pos-4 {{ background: #ef4444; }}

/* Kapitan */
.captain-badge {{ display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; background: linear-gradient(135deg, #fbbf24, #f59e0b); color: #131313; font-size: 11px; font-weight: 800; }}

/* Bar */
.bar-wrap {{ display: flex; align-items: center; gap: 8px; }}
.bar-bg {{ width: 80px; height: 6px; background: #131313; border-radius: 3px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.6s ease; }}
.bar-val {{ font-size: 13px; color: #949494; min-width: 38px; text-align: right; }}

/* Tab Content */
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.footer {{ text-align: center; margin-top: 32px; color: #949494; font-size: 12px; }}
.text-right {{ text-align: right; }}
.text-center {{ text-align: center; }}
.text-left {{ text-align: left; }}
.fw-700 {{ font-weight: 700; }}
.fw-600 {{ font-weight: 600; }}
.c-muted {{ color: #949494; }}
.c-dim {{ color: #949494; }}
.empty-msg {{ padding: 40px; text-align: center; color: #949494; }}
.clickable {{ cursor: pointer; }}
.clickable:hover {{ color: #3860be; }}

/* ============================================================
   MOTYW JASNY (theme-fantasy) — aktywowany klasą html.theme-fantasy
   ============================================================ */
html.theme-fantasy {{ background: #f5f5f5; }}
html.theme-fantasy body {{ background: #f5f5f5; color: #131313; }}

html.theme-fantasy .header-left h1 {{ color: #131313; }}
html.theme-fantasy .header .sub {{ color: #5a5a5a; }}
html.theme-fantasy .theme-toggle {{ background: #ffffff; border-color: #309875; color: #309875; }}
html.theme-fantasy .theme-toggle:hover {{ background: #309875; color: #ffffff; }}

html.theme-fantasy .stat-card {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .stat-card .val {{ color: #131313; }}
html.theme-fantasy .stat-card .label {{ color: #5a5a5a; }}
html.theme-fantasy .stat-card .sub {{ color: #5a5a5a; }}

html.theme-fantasy .tab {{ color: #5a5a5a; }}
html.theme-fantasy .tab.active {{ background: #ffffff; border-bottom-color: #309875; color: #131313; }}
html.theme-fantasy .tab:hover {{ color: #3860be; }}

html.theme-fantasy .pos-btn {{ border-color: #e0e0e0; color: #5a5a5a; }}
html.theme-fantasy .pos-btn.active {{ color: #ffffff; }}
html.theme-fantasy .scope-btn {{ color: #5a5a5a; }}
html.theme-fantasy .scope-btn.active {{ background: #309875; }}

html.theme-fantasy .section-title h2 {{ color: #131313; }}
html.theme-fantasy .section-title .line {{ background: linear-gradient(90deg, #e0e0e0, transparent); }}

html.theme-fantasy .data-table {{ background: #ffffff; border: 1px solid #e0e0e0; }}
html.theme-fantasy thead tr {{ background: #f5f5f5; }}
html.theme-fantasy th {{ color: #5a5a5a; }}
html.theme-fantasy th.sortable:hover {{ color: #131313; }}
html.theme-fantasy td {{ border-top-color: #e0e0e0; }}
html.theme-fantasy tr.highlight {{ background: rgba(48,152,117,0.06); }}

html.theme-fantasy .pos-badge {{ color: #131313; }}
html.theme-fantasy .captain-badge {{ color: #131313; }}
html.theme-fantasy .bar-bg {{ background: #e0e0e0; }}
html.theme-fantasy .bar-val {{ color: #5a5a5a; }}

html.theme-fantasy .footer {{ color: #5a5a5a; }}
html.theme-fantasy .c-muted {{ color: #5a5a5a; }}
html.theme-fantasy .c-dim {{ color: #5a5a5a; }}
html.theme-fantasy .empty-msg {{ color: #5a5a5a; }}
html.theme-fantasy .clickable:hover {{ color: #3860be; }}

/* Więcej komponentów dla obu motywów */
.roster-chip {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #2d2d2d;
  border: 1px solid #3cffd0;
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
  color: #ffffff;
}}
html.theme-fantasy .roster-chip {{ background: #ffffff; border-color: #e0e0e0; color: #131313; }}

.roster-chip .rc-badge {{ font-size: 9px; font-weight: 800; border-radius: 3px; padding: 1px 4px; }}
.rc-cap {{ background: #fbbf24; color: #131313; }}
.rc-res {{ background: #475569; color: #ffffff; }}
.rc-xi {{ background: #3cffd0; color: #131313; }}

.form-panel {{ background: #131313; border: 1px solid #2d2d2d; border-radius: 8px; padding: 12px 16px; display: flex; align-items: flex-end; gap: 16px; flex-wrap: wrap; }}
html.theme-fantasy .form-panel {{ background: #f5f5f5; border-color: #e0e0e0; }}

.form-chart {{ display: inline-flex; align-items: flex-end; gap: 3px; height: 48px; vertical-align: middle; }}
.form-chart.mini {{ height: 24px; gap: 2px; }}
.form-chart.mini .form-bar {{ width: 8px; }}
.form-chart.mini .form-val {{ font-size: 8px; top: -12px; color: #949494; font-weight: 500; }}
.form-chart.mini .form-rnd {{ display: none; }}
.form-bar {{ width: 14px; border-radius: 3px 3px 0 0; min-height: 2px; position: relative; display: inline-flex; flex-direction: column; align-items: center; justify-content: flex-start; }}
.form-bar .form-val {{ position: absolute; top: -16px; font-size: 10px; color: #ffffff; font-weight: 600; white-space: nowrap; }}
.form-bar .form-rnd {{ position: absolute; bottom: -16px; font-size: 9px; color: #949494; white-space: nowrap; }}
.form-bar.not-played {{ opacity: 0.35; border: 1px dashed #475569; background: transparent !important; }}
.form-avg {{ display: flex; flex-direction: column; align-items: center; margin-left: 8px; }}
.form-avg .fa-val {{ font-size: 20px; font-weight: 800; color: #3cffd0; }}
.form-avg .fa-lbl {{ font-size: 10px; color: #949494; text-transform: uppercase; letter-spacing: 0.5px; }}
html.theme-fantasy .form-avg .fa-val {{ color: #309875; }}
html.theme-fantasy .form-avg .fa-lbl {{ color: #5a5a5a; }}

.detail-row td {{ padding: 0 !important; border-top: none !important; }}
.detail-panel {{ background: #131313; border: 1px solid #2d2d2d; border-radius: 8px; padding: 12px 16px; margin: 4px 0 8px; display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-start; }}
html.theme-fantasy .detail-panel {{ background: #f5f5f5; border-color: #e0e0e0; }}

.detail-section {{ display: flex; flex-direction: column; gap: 4px; }}
.detail-section .ds-label {{ font-size: 10px; color: #949494; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }}
html.theme-fantasy .detail-section .ds-label {{ color: #5a5a5a; }}

.team-list {{ display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }}
.team-list-item {{ background: #2d2d2d; border: 1px solid #3cffd0; border-radius: 8px; }}
.team-list-item.active {{ border-color: #3cffd0; }}
html.theme-fantasy .team-list-item {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .team-list-item.active {{ border-color: #309875; }}

.team-list-header {{ display: flex; align-items: center; gap: 12px; padding: 10px 16px; cursor: pointer; transition: background 0.15s; }}
.team-list-header:hover {{ background: #3cffd0; }}
html.theme-fantasy .team-list-header:hover {{ background: #309875; }}
.team-list-rank {{ font-size: 13px; font-weight: 800; color: #3cffd0; min-width: 32px; }}
.team-list-name {{ font-size: 14px; font-weight: 700; color: #ffffff; flex: 1; text-transform: capitalize; }}
.team-list-pts {{ font-size: 12px; color: #949494; font-weight: 600; }}
.team-list-count {{ font-size: 11px; color: #949494; }}
html.theme-fantasy .team-list-rank {{ color: #309875; }}
html.theme-fantasy .team-list-name {{ color: #131313; }}
html.theme-fantasy .team-list-pts {{ color: #5a5a5a; }}
html.theme-fantasy .team-list-count {{ color: #5a5a5a; }}
html.theme-fantasy .team-stat {{ color: #5a5a5a; }}
html.theme-fantasy .team-stat b {{ color: #131313; }}
html.theme-fantasy .team-list-arrow {{ color: #949494; }}
html.theme-fantasy .diff-pos {{ background: rgba(16,185,129,0.1); }}
html.theme-fantasy .diff-neg {{ background: rgba(239,68,68,0.1); }}
html.theme-fantasy .diff-zero {{ background: rgba(100,116,139,0.1); }}

/* Fixture Ticker - Light Theme */
html.theme-fantasy .ft-table th {{ color: #5a5a5a; border-bottom-color: #e0e0e0; }}
html.theme-fantasy .ft-table td {{ border-bottom-color: #e0e0e0; }}
html.theme-fantasy .ft-table td.ft-team {{ color: #131313; }}
html.theme-fantasy .ft-table td.ft-team:hover {{ color: #309875; }}
html.theme-fantasy .ft-cell {{ background: #f5f5f5; color: #131313; }}
html.theme-fantasy .ft-cell .ft-ha {{ opacity: 0.7; }}
html.theme-fantasy .ft-cell-team {{ color: #131313; }}
html.theme-fantasy .ft-cell-team .ft-ha {{ opacity: 0.7; }}
html.theme-fantasy .ft-val {{ background: #e0e0e0; color: #131313; }}
html.theme-fantasy .ft-legend {{ color: #5a5a5a; }}
html.theme-fantasy .ft-legend-swatch {{ border: 1px solid #e0e0e0; }}

/* Rating Modal - Light Theme */
html.theme-fantasy .ft-modal-bg {{ background: rgba(0,0,0,0.4); }}
html.theme-fantasy .ft-modal {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .ft-modal h3 {{ color: #131313; }}
html.theme-fantasy .ft-modal-close {{ color: #5a5a5a; }}
html.theme-fantasy .ft-modal-close:hover {{ color: #131313; }}

/* FDR Tiles - Light Theme */
html.theme-fantasy .fdr-table th {{ color: #5a5a5a; border-bottom-color: #e0e0e0; }}
html.theme-fantasy .fdr-table td {{ border-bottom-color: #e0e0e0; }}
html.theme-fantasy .fdr-legend {{ color: #5a5a5a; }}
html.theme-fantasy .fdr-cell-team {{ color: #131313; }}
html.theme-fantasy .fdr-cell-team .fdr-ha {{ opacity: 0.7; }}
html.theme-fantasy .fdr-mini {{ background: #e0e0e0; color: #131313; }}

/* Fixture Planner - Light Theme */
html.theme-fantasy .fp-section {{ border-top-color: #e0e0e0; }}
html.theme-fantasy .fp-controls label {{ color: #5a5a5a; }}
html.theme-fantasy .fp-controls select {{ background: #ffffff; border-color: #e0e0e0; color: #131313; }}
html.theme-fantasy .fp-mode-btns {{ border-color: #e0e0e0; }}
html.theme-fantasy .fp-mode-btn {{ color: #5a5a5a; }}
html.theme-fantasy .fp-mode-btn.active {{ background: #309875; color: #ffffff; }}
html.theme-fantasy .fp-table th {{ color: #5a5a5a; border-bottom-color: #e0e0e0; }}
html.theme-fantasy .fp-table th:hover {{ color: #131313; }}
html.theme-fantasy .fp-table th.fp-sorted {{ color: #309875; }}
html.theme-fantasy .fp-table td {{ border-bottom-color: #e0e0e0; }}
html.theme-fantasy .fp-table td.fp-team-cell {{ color: #131313; }}
html.theme-fantasy .fp-table td.fp-team-cell:hover {{ color: #309875; }}
html.theme-fantasy .fp-table td.fp-team-cell.fp-selected {{ background: rgba(48,152,117,0.1); color: #309875; }}
html.theme-fantasy .fp-tile {{ background: #f5f5f5; }}
html.theme-fantasy .fp-rotation {{ background: #ffffff; border-color: #e0e0e0; color: #131313; }}
html.theme-fantasy .fp-rotation .fp-rot-label {{ color: #5a5a5a; }}
html.theme-fantasy .fp-summary {{ background: #ffffff; border-color: #e0e0e0; color: #131313; }}

/* Transfers Tab - Light Theme */
html.theme-fantasy .transfers-header h3 {{ color: #131313; }}
html.theme-fantasy .tr-gw-badge {{ background: #f5f5f5; border-color: #e0e0e0; color: #5a5a5a; }}

/* Predictions Tab - Light Theme */
html.theme-fantasy .pred-val {{ background: #f5f5f5; color: #131313; }}
html.theme-fantasy .pred-fdr-tile {{ background: #e0e0e0; color: #131313; }}
html.theme-fantasy .pred-fdr-used {{ background: rgba(0,0,0,0.05); }}
html.theme-fantasy .pred-legend {{ background: #f5f5f5; color: #5a5a5a; }}
html.theme-fantasy .pred-legend b {{ color: #131313; }}

/* Season Tracker - Light Theme */
html.theme-fantasy .season-wrap {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .season-btn {{ background: transparent; border: 1px solid #e0e0e0; color: #5a5a5a; }}
html.theme-fantasy .season-btn.active {{ background: #309875; color: #ffffff; }}
html.theme-fantasy .season-tooltip {{ background: #ffffff; border-color: #e0e0e0; color: #131313; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
html.theme-fantasy .season-legend-item {{ color: #5a5a5a; }}
html.theme-fantasy .trend-up {{ color: #10b981; }}
html.theme-fantasy .trend-down {{ color: #ef4444; }}
html.theme-fantasy .trend-flat {{ color: #949494; }}

/* Compare Tab - Light Theme */
html.theme-fantasy .cmp-search-input {{ background: #ffffff; border-color: #e0e0e0; color: #131313; }}
html.theme-fantasy .cmp-search-input:focus {{ border-color: #309875; }}
html.theme-fantasy .cmp-search-input::placeholder {{ color: #949494; }}
html.theme-fantasy .cmp-autocomplete {{ background: #ffffff; border-color: #e0e0e0; box-shadow: 0 8px 24px rgba(0,0,0,0.15); }}
html.theme-fantasy .cmp-ac-item {{ color: #131313; }}
html.theme-fantasy .cmp-ac-item:hover {{ background: #f5f5f5; }}
html.theme-fantasy .cmp-clear-btn {{ background: #e0e0e0; color: #5a5a5a; }}
html.theme-fantasy .cmp-chip {{ background: #f5f5f5; border-color: #e0e0e0; color: #131313; }}
html.theme-fantasy .cmp-table {{ background: #ffffff; }}
html.theme-fantasy .cmp-table th {{ background: #f5f5f5; color: #5a5a5a; border-bottom-color: #e0e0e0; }}
html.theme-fantasy .cmp-table td {{ color: #131313; border-top-color: #e0e0e0; }}
html.theme-fantasy .cmp-rot-wrap {{ background: #ffffff; border-color: #e0e0e0; }}
html.theme-fantasy .cmp-fdr-table {{ color: #131313; }}
html.theme-fantasy .cmp-fdr-table th {{ color: #5a5a5a; border-bottom-color: #e0e0e0; }}

.team-list-arrow {{ font-size: 10px; color: #64748b; margin-left: 4px; }}
.diff-badge {{
  display: inline-block; font-size: 12px; font-weight: 700; border-radius: 4px;
  padding: 2px 8px; min-width: 48px; text-align: center;
}}
.diff-pos {{ background: rgba(16,185,129,0.15); color: #10b981; }}
.diff-neg {{ background: rgba(239,68,68,0.15); color: #ef4444; }}
.diff-zero {{ background: rgba(100,116,139,0.15); color: #94a3b8; }}
.team-header {{
  display: flex; align-items: center; gap: 16px; margin-bottom: 16px; flex-wrap: wrap;
}}
.team-stat {{ font-size: 13px; color: #94a3b8; }}
.team-stat b {{ color: #e2e8f0; }}
/* Fixture Ticker */
.ft-table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.ft-table th {{ padding: 6px 4px; text-align: center; font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #334155; }}
.ft-table th.ft-round {{ min-width: 80px; }}
.ft-table td {{ padding: 5px 4px; text-align: center; border-bottom: 1px solid #1e293b; }}
.ft-table td.ft-team {{ text-align: left; font-weight: 700; white-space: nowrap; padding-left: 8px; cursor: pointer; }}
.ft-table td.ft-team:hover {{ color: #22d3ee; }}
.ft-cell {{ border-radius: 4px; padding: 4px 6px; font-weight: 600; font-size: 12px; display: inline-block; min-width: 52px; text-align: center; }}
.ft-cell .ft-ha {{ font-size: 10px; font-weight: 400; opacity: 0.7; }}
.ft-cell-dual {{ display: flex; flex-direction: column; align-items: center; gap: 2px; min-width: 68px; }}
.ft-cell-team {{ font-size: 11px; font-weight: 600; color: #e2e8f0; white-space: nowrap; }}
.ft-cell-team .ft-ha {{ font-size: 10px; font-weight: 400; opacity: 0.7; }}
.ft-cell-vals {{ display: flex; gap: 2px; }}
.ft-val {{ border-radius: 3px; padding: 2px 5px; font-weight: 700; font-size: 10px; min-width: 28px; text-align: center; }}
.ft-legend {{ display: flex; gap: 12px; align-items: center; margin-bottom: 12px; font-size: 12px; color: #94a3b8; flex-wrap: wrap; }}
.ft-legend-item {{ display: flex; align-items: center; gap: 4px; }}
.ft-legend-swatch {{ width: 16px; height: 16px; border-radius: 3px; }}
/* Rating modal */
.ft-modal-bg {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); z-index: 1000; display: flex; align-items: center; justify-content: center; }}
.ft-modal {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px 32px; min-width: 340px; max-width: 90vw; position: relative; }}
.ft-modal h3 {{ margin: 0 0 16px; font-size: 18px; }}
.ft-modal-close {{ position: absolute; top: 12px; right: 16px; background: none; border: none; color: #94a3b8; font-size: 20px; cursor: pointer; }}
.ft-modal-close:hover {{ color: #e2e8f0; }}
/* FDR tiles */
.fdr-table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.fdr-table th {{ padding: 8px 6px; text-align: center; font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #334155; }}
.fdr-table td {{ padding: 5px 4px; text-align: center; border-bottom: 1px solid #1e293b; }}
.fdr-table td.fdr-team {{ text-align: left; font-weight: 700; white-space: nowrap; padding-left: 8px; }}
.fdr-sum {{ font-weight: 800; font-size: 15px; }}
.fdr-legend {{ display: flex; gap: 8px; align-items: center; margin-bottom: 14px; font-size: 12px; color: #94a3b8; flex-wrap: wrap; }}
.fdr-legend-item {{ display: flex; align-items: center; gap: 5px; }}
.fdr-legend-swatch {{ width: 20px; height: 20px; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }}
.fdr-cell {{ display: flex; flex-direction: column; align-items: center; gap: 3px; min-width: 80px; }}
.fdr-cell-team {{ font-size: 12px; font-weight: 600; color: #e2e8f0; white-space: nowrap; }}
.fdr-cell-team .fdr-ha {{ font-size: 10px; font-weight: 400; opacity: 0.7; }}
.fdr-cell-vals {{ display: flex; gap: 3px; }}
.fdr-mini {{ border-radius: 4px; padding: 2px 6px; font-size: 12px; font-weight: 700; min-width: 36px; text-align: center; display: inline-flex; align-items: center; gap: 2px; }}
.fdr-mini .fdr-lbl {{ font-size: 8px; font-weight: 600; opacity: 0.8; letter-spacing: 0.3px; }}
/* Fixture Planner */
.fp-section {{ margin-top: 32px; border-top: 2px solid #334155; padding-top: 24px; }}
.fp-controls {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }}
.fp-controls label {{ font-size: 12px; color: #94a3b8; font-weight: 600; }}
.fp-controls select {{ background: #0f172a; border: 1px solid #334155; color: #e2e8f0; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-family: inherit; cursor: pointer; }}
.fp-mode-btns {{ display: flex; gap: 0; border-radius: 8px; overflow: hidden; border: 1px solid #334155; }}
.fp-mode-btn {{ background: transparent; border: none; color: #64748b; padding: 5px 12px; font-size: 11px; font-weight: 700; cursor: pointer; font-family: inherit; transition: all 0.15s; }}
.fp-mode-btn.active {{ background: #22d3ee; color: #0f172a; }}
.fp-table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.fp-table th {{ padding: 8px 6px; text-align: center; font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #334155; cursor: pointer; user-select: none; }}
.fp-table th:hover {{ color: #e2e8f0; }}
.fp-table th.fp-sorted {{ color: #22d3ee; }}
.fp-table td {{ padding: 5px 4px; text-align: center; border-bottom: 1px solid #1e293b; }}
.fp-table td.fp-team-cell {{ text-align: left; font-weight: 700; white-space: nowrap; padding-left: 8px; cursor: pointer; }}
.fp-table td.fp-team-cell:hover {{ color: #22d3ee; }}
.fp-table td.fp-team-cell.fp-selected {{ background: rgba(34,211,238,0.12); color: #22d3ee; }}
.fp-tile {{ border-radius: 4px; padding: 4px 6px; font-weight: 600; font-size: 11px; display: inline-block; min-width: 56px; text-align: center; }}
.fp-tile .fp-ha {{ font-size: 9px; font-weight: 400; opacity: 0.7; }}
.fp-avg-cell {{ font-weight: 800; font-size: 14px; }}
.fp-rotation {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px 16px; margin-top: 12px; font-size: 13px; color: #e2e8f0; line-height: 1.6; }}
.fp-rotation .fp-rot-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 6px; }}
.fp-summary {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 14px 18px; margin-top: 16px; font-size: 13px; line-height: 2; color: #e2e8f0; }}
.fp-summary-line {{ display: flex; align-items: center; gap: 6px; }}
/* Transfers tab */
.transfers-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
@media (max-width: 768px) {{ .transfers-grid {{ grid-template-columns: 1fr; }} }}
.transfers-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }}
.transfers-header h3 {{ font-size: 14px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase; }}
.tr-filters-row {{ display: flex; gap: 8px; margin-bottom: 14px; align-items: center; flex-wrap: wrap; }}
.tr-gw-badge {{ background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 4px 12px; font-size: 12px; color: #94a3b8; font-weight: 600; }}
.price-up {{ color: #10b981; font-size: 11px; font-weight: 700; }}
.price-down {{ color: #ef4444; font-size: 11px; font-weight: 700; }}
.price-neutral {{ color: #64748b; font-size: 11px; }}
/* Predictions tab */
.pred-val {{
  font-size: 18px; font-weight: 800; padding: 4px 10px; border-radius: 6px;
  display: inline-block; min-width: 48px; text-align: center;
}}
.pred-fdr-tile {{
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 12px; font-weight: 700; min-width: 32px; text-align: center;
}}
.pred-fdr-used {{
  font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 4px;
  display: inline-block; background: rgba(255,255,255,0.05);
}}
.pred-confidence {{
  display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 10px;
  border-radius: 10px; letter-spacing: 0.3px;
}}
.pred-conf-high {{ background: rgba(16,185,129,0.2); color: #10b981; }}
.pred-conf-medium {{ background: rgba(251,191,36,0.2); color: #fbbf24; }}
.pred-conf-low {{ background: rgba(239,68,68,0.2); color: #ef4444; }}
.pred-conf-insufficient {{ background: rgba(100,116,139,0.2); color: #94a3b8; }}
.pred-conf-unavailable {{ background: rgba(239,68,68,0.15); color: #ef4444; }}
.pred-legend {{
  background: #1e293b; border-radius: 8px; padding: 12px 16px;
  margin-bottom: 16px; font-size: 12px; color: #94a3b8; line-height: 1.8;
}}
.pred-legend b {{ color: #e2e8f0; }}
.pred-filters {{ display: flex; gap: 8px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
/* --- Season tracker --- */
.season-wrap {{ background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
.season-controls {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
.season-btn {{
  background: transparent; border: 1px solid #334155; color: #64748b;
  padding: 5px 14px; font-size: 12px; font-weight: 600; cursor: pointer;
  border-radius: 6px; font-family: inherit; transition: all 0.15s;
}}
.season-btn.active {{ background: #22d3ee; color: #0f172a; border-color: transparent; }}
.season-chart {{ position: relative; width: 100%; overflow-x: auto; }}
.season-chart svg {{ display: block; }}
.season-tooltip {{
  position: absolute; pointer-events: none; background: #0f172a; border: 1px solid #334155;
  border-radius: 8px; padding: 8px 12px; font-size: 12px; color: #e2e8f0;
  white-space: nowrap; z-index: 10; opacity: 0; transition: opacity 0.15s;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}}
.season-tooltip.visible {{ opacity: 1; }}
.season-legend {{ display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 12px; }}
.season-legend-item {{
  display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
  color: #94a3b8; cursor: pointer; user-select: none; transition: opacity 0.2s;
}}
.season-legend-item.hidden {{ opacity: 0.3; text-decoration: line-through; }}
.season-legend-item .swatch {{ width: 14px; height: 3px; border-radius: 2px; }}
.season-table {{ margin-top: 20px; }}
.trend-up {{ color: #10b981; }}
.trend-down {{ color: #ef4444; }}
.trend-flat {{ color: #64748b; }}
/* ============================================================
   📖 PORÓWNYWARKA ZAWODNIKÓW — style
   Sekcje: wybór, karty, tabela statystyk, wykres formy, FDR
   ============================================================ */
.cmp-search-wrap {{
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 20px;
}}
.cmp-search-box {{
  position: relative; flex: 1; min-width: 200px;
}}
.cmp-search-input {{
  width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid #334155;
  background: #0f172a; color: #e2e8f0; font-size: 14px; font-family: inherit;
  outline: none; transition: border-color 0.2s;
}}
.cmp-search-input:focus {{ border-color: #22d3ee; }}
.cmp-search-input::placeholder {{ color: #64748b; }}
/* 📖 Autouzupełnianie — lista podpowiedzi pod polem wyszukiwania */
.cmp-autocomplete {{
  position: absolute; top: 100%; left: 0; right: 0; z-index: 100;
  background: #1e293b; border: 1px solid #334155; border-radius: 8px;
  max-height: 220px; overflow-y: auto; display: none; margin-top: 4px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}}
.cmp-autocomplete.visible {{ display: block; }}
.cmp-ac-item {{
  padding: 8px 14px; cursor: pointer; font-size: 13px; display: flex;
  align-items: center; gap: 8px; transition: background 0.1s;
}}
.cmp-ac-item:hover {{ background: #334155; }}
.cmp-ac-item .cmp-ac-team {{ color: #64748b; font-size: 11px; }}
.cmp-clear-btn {{
  background: #334155; border: none; color: #94a3b8; padding: 8px 16px;
  border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer;
  font-family: inherit; transition: all 0.15s;
}}
.cmp-clear-btn:hover {{ background: #475569; color: #e2e8f0; }}
.cmp-selected-chips {{
  display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px;
}}
.cmp-chip {{
  display: inline-flex; align-items: center; gap: 6px; background: #1e293b;
  border: 1px solid #334155; border-radius: 20px; padding: 4px 12px 4px 8px;
  font-size: 13px; color: #e2e8f0; animation: cmpChipIn 0.2s ease;
}}
@keyframes cmpChipIn {{
  from {{ opacity: 0; transform: scale(0.9); }}
  to {{ opacity: 1; transform: scale(1); }}
}}
.cmp-chip-remove {{
  background: none; border: none; color: #64748b; cursor: pointer;
  font-size: 16px; line-height: 1; padding: 0 2px; transition: color 0.15s;
}}
.cmp-chip-remove:hover {{ color: #ef4444; }}
/* 📖 Karty zawodników — obok siebie, responsywne */
.cmp-cards {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px; margin-bottom: 24px;
}}
.cmp-card {{
  background: #1e293b; border-radius: 12px; padding: 20px;
  border-top: 3px solid #22d3ee; animation: cmpChipIn 0.3s ease;
}}
.cmp-card:nth-child(2) {{ border-top-color: #fbbf24; }}
.cmp-card:nth-child(3) {{ border-top-color: #a78bfa; }}
.cmp-card-name {{ font-size: 16px; font-weight: 800; margin-bottom: 4px; }}
.cmp-card-meta {{ font-size: 12px; color: #94a3b8; margin-bottom: 12px; }}
.cmp-card-stats {{ display: flex; flex-direction: column; gap: 6px; }}
.cmp-card-stat {{
  display: flex; justify-content: space-between; font-size: 13px;
  padding: 4px 0; border-bottom: 1px solid #0f172a;
}}
.cmp-card-stat .cmp-stat-label {{ color: #64748b; }}
.cmp-card-stat .cmp-stat-val {{ font-weight: 700; color: #e2e8f0; }}
/* 📖 Tabela porównania — podświetlenie najlepszej wartości */
.cmp-table {{ background: #1e293b; border-radius: 12px; overflow: hidden; margin-bottom: 24px; overflow-x: auto; }}
.cmp-table table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
.cmp-table th {{ padding: 10px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; color: #64748b; font-weight: 600; background: #0f172a; }}
.cmp-table td {{ padding: 10px 14px; border-top: 1px solid #0f172a; text-align: center; }}
.cmp-table td:first-child {{ text-align: left; color: #94a3b8; font-weight: 600; font-size: 12px; }}
.cmp-table td.cmp-best {{ background: rgba(16,185,129,0.12); color: #10b981; font-weight: 800; }}
/* 📖 Wykres formy — SVG, jedna linia per zawodnik */
.cmp-chart-wrap {{
  background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 24px;
}}
.cmp-chart-title {{ font-size: 14px; font-weight: 700; margin-bottom: 12px; color: #e2e8f0; }}
.cmp-chart-legend {{
  display: flex; gap: 16px; margin-bottom: 12px; font-size: 12px; flex-wrap: wrap;
}}
.cmp-chart-legend-item {{ display: flex; align-items: center; gap: 6px; color: #94a3b8; }}
.cmp-chart-legend-swatch {{ width: 16px; height: 3px; border-radius: 2px; }}
.cmp-chart svg {{ display: block; width: 100%; }}
/* 📖 Siatka FDR — kolorowe kafelki jak w zakładce Terminarz */
.cmp-fdr-wrap {{
  background: #1e293b; border-radius: 12px; padding: 20px; overflow-x: auto;
}}
.cmp-fdr-title {{ font-size: 14px; font-weight: 700; margin-bottom: 12px; color: #e2e8f0; }}
.cmp-fdr-table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.cmp-fdr-table th {{ padding: 8px 10px; font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; border-bottom: 2px solid #334155; }}
.cmp-fdr-table td {{ padding: 6px 10px; text-align: center; border-bottom: 1px solid #0f172a; }}
.cmp-fdr-cell {{
  display: inline-flex; align-items: center; gap: 4px; border-radius: 4px;
  padding: 3px 8px; font-weight: 700; font-size: 12px;
}}
.cmp-fdr-cell .cmp-fdr-ha {{ font-size: 9px; font-weight: 400; opacity: 0.7; }}
.cmp-empty {{
  text-align: center; padding: 60px 20px; color: #64748b; font-size: 15px;
}}
.cmp-empty-icon {{ font-size: 48px; margin-bottom: 12px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="header-left">
      <img src="logo.PNG" alt="ScrapFEks" class="logo">
      <div>
        <h1>Fantasy Ekstraklasa</h1>
        <p class="sub">Dashboard · {timestamp}</p>
      </div>
    </div>
    <button class="theme-toggle" onclick="toggleTheme()">☀️ Light</button>
  </div>
  <div class="stats-row">
    <div class="stat-card accent-cyan">
      <div class="val">{teams_count}</div>
      <div class="label">Top drużyn</div>
    </div>
    <div class="stat-card accent-green">
      <div class="val">{top_owned.get('squad_pct', '—')}</div>
      <div class="label">Top owned</div>
      <div class="sub">{top_owned.get('name', '—')}</div>
    </div>
    <div class="stat-card accent-purple">
      <div class="val">{best_ppp.get('points_per_price', 0):.1f}</div>
      <div class="label">Najlepszy PPP</div>
      <div class="sub">{best_ppp.get('name', '—')} · {best_ppp.get('price', 0):.1f}M</div>
    </div>
    {"<div class='stat-card accent-cyan'><div class='val'>" + str(league_teams_count) + "</div><div class='label'>Liga</div><div class='sub'>" + league_label + "</div></div>" if has_league else ""}
  </div>

  <div style="margin-top: 24px;">
    <div class="tabs">
      <button class="tab active" data-tab="players">⚽ Zawodnicy</button>
      {"<button class='tab' data-tab='teams'>📋 Liga CMF</button>" if has_league else ""}
      {"<button class='tab' data-tab='fixtures'>📅 Terminarz</button>" if has_fixtures else ""}
      {"<button class='tab' data-tab='transfers'>🔄 Transfery</button>" if has_transfers else ""}
      {"<button class='tab' data-tab='predictions'>🔮 Prognoza</button>" if has_predictions else ""}
      {"<button class='tab' data-tab='accuracy'>📊 Trafność</button>" if has_accuracy else ""}
      {"<button class='tab' data-tab='season'>📈 Sezon</button>" if has_season else ""}
      <button class="tab" data-tab="compare">⚖️ Porównanie</button>
      {"<a href='archive/index.html' class='tab' style='text-decoration:none'>📁 Archiwum</a>" if has_archive else "<span class='tab' style='opacity:0.4;pointer-events:none;cursor:default'>📁 Archiwum</span>"}
    </div>
    <div class="filters-row" style="margin-top: 12px;">
      {scope_toggle_html}
      <div class="pos-filters" style="margin-left:auto;">
        <button class="pos-btn active" data-pos="ALL">ALL</button>
        <button class="pos-btn" data-pos="BR">GK</button>
        <button class="pos-btn" data-pos="OBR">DEF</button>
        <button class="pos-btn" data-pos="POM">MID</button>
        <button class="pos-btn" data-pos="NAP">FWD</button>
      </div>
    </div>
    <div id="tab-players" class="tab-content active"></div>
    <div id="tab-teams" class="tab-content"></div>
    <div id="tab-fixtures" class="tab-content"></div>
    <div id="tab-transfers" class="tab-content"></div>
    <div id="tab-predictions" class="tab-content"></div>
    <div id="tab-accuracy" class="tab-content"></div>
    <div id="tab-season" class="tab-content"></div>
    <div id="tab-compare" class="tab-content"></div>
  </div>
  <div class="footer">Fantasy Ekstraklasa Dashboard · {timestamp}</div>
</div>

// __JS_PLACEHOLDER__

<script>
const DATA = {data_json};
const PLAYERS = {players_json};
const ROSTERS = {rosters_json};
const LEAGUE_TEAMS = {teams_detail_json};
const DUETS_DATA = {duets_data_json};
const FIXTURES = {fixtures_json};
const EKSTRA_STATS = {ekstra_stats_json};
const FDR_DATA = {fdr_data_json};
const TRANSFERS_DATA = {transfers_data_json};
const PREDICTIONS = {predictions_json};
const ACCURACY_HISTORY = {accuracy_json};
const TUNED_PARAMS = {tuned_params_json};
const LEAGUE_HISTORY = {league_history_json};
 const POS_MAP = {{BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD','1':'GK','2':'DEF','3':'MID','4':'FWD'}};
const POS_ID = {{'1':'BR','2':'OBR','3':'POM','4':'NAP',BR:'BR',OBR:'OBR',POM:'POM',NAP:'NAP',
  Bramkarz:'BR','Obrońca':'OBR',Pomocnik:'POM',Napastnik:'NAP'}};

let tab = 'players', pos = 'ALL', scope = '{{default_scope}}';
let selectedTeam = '';
let selectedDuet = '';
let currentTeamsView = 'teams';
// 📖 Stan porównywarki — tablica player_id wybranych zawodników (max 3)
let cmpSelected = [];
let sorts = {{
  players: {{col:'total_points', dir:'desc'}},
  teams: {{col:'_pos_order', dir:'asc'}},
  teams_list: {{col:'total_pts', dir:'desc'}},
  duets_list: {{col:'total_pts', dir:'desc'}},
}};

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
function arrow(tab, col) {{
  const s = sorts[tab];
  return s.col === col ? (s.dir === 'desc' ? ' ▼' : ' ▲') : '';
}}
function filterPos(data) {{
  if (pos === 'ALL') return data;
  return data.filter(p => {{
    const pk = POS_ID[p.position] || POS_ID[p.position_id] || p.position;
    return pk === pos;
  }});
}}
function sortData(data, tab) {{
  const s = sorts[tab];
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

// Detail panel — kliknięcie na zawodnika pokazuje formę + drużyny z ligi
function nameCell(name, pid, style, prefix) {{
  const attr = pid ? ' data-pid="'+pid+'"' : '';
  return '<td class="clickable roster-trigger"'+attr+' style="cursor:pointer;'+(style||'')+'">'+( prefix||'')+name+' <span style="font-size:10px;color:#64748b">▸</span></td>';
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

function formAvg(form) {{
  if (!form || !form.length) return '—';
  const played = form.filter(f => f.p !== false);
  if (!played.length) return '—';
  const avg = played.reduce((s,f) => s + (f.pts||0), 0) / played.length;
  return avg.toFixed(1);
}}

function formAvgNum(form) {{
  if (!form || !form.length) return 0;
  const played = form.filter(f => f.p !== false);
  if (!played.length) return 0;
  return played.reduce((s,f) => s + (f.pts||0), 0) / played.length;
}}

function detailRow(pid, colspan) {{
  const r = ROSTERS[pid];
  if (!r || !r.length) {{
    return '<tr class="detail-row"><td colspan="'+colspan+'"><div class="detail-panel"><span class="c-dim" style="font-size:12px">Brak danych o drużynach ligowych</span></div></td></tr>';
  }}
  const sorted = [...r].sort((a,b) => (a.pos||999) - (b.pos||999));
  let chips = '';
  sorted.forEach(t => {{
    let badge = '';
    if (t.C) badge = '<span class="rc-badge rc-cap">C</span>';
    else if (t.R) badge = '<span class="rc-badge rc-res">RES</span>';
    else badge = '<span class="rc-badge rc-xi">XI</span>';
    const slug = t.team.replace(/-/g,' ');
    const posLabel = t.pos ? '<span style="color:#64748b;font-size:10px;margin-right:2px">#'+t.pos+'</span>' : '';
    chips += '<span class="roster-chip">'+posLabel+slug+' '+badge+'</span>';
  }});
  let h = '<tr class="detail-row"><td colspan="'+colspan+'"><div class="detail-panel">';
  h += '<div class="detail-section">';
  h += '<span class="ds-label">Drużyny w lidze ('+r.length+')</span>';
  h += '<div style="display:flex;flex-wrap:wrap;gap:4px">'+chips+'</div>';
  h += '</div></div></td></tr>';
  return h;
}}

function renderPlayers() {{
  let data = [...PLAYERS];
  if (pos !== 'ALL') data = data.filter(p => (POS_ID[p.position] || p.position) === pos);
  if (!data.length) return '<div class="empty-msg">Brak danych</div>';

  // Buduj lookup ownership z aktualnego scope — dopasowanie po player_id
  const scopeData = DATA[scope] || {{}};
  const ownData = scopeData.ownership || [];
  const ownMap = {{}};
  ownData.forEach(o => {{ ownMap[o.player_id] = o; }});
  const hasOwn = ownData.length > 0;
  const hasLeague = LEAGUE_TEAMS.length > 0 && Object.keys(LEAGUE_POS_AVGS).length > 0;
  const scopeLabel = scopeData.label || scope;

  let h = '<div class="section-title"><span style="font-size:22px">⚽</span><h2>Zawodnicy'+(hasOwn ? ' — ownership: '+scopeLabel : '')+'</h2><div class="line"></div></div>';
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
  h += '<th class="text-right sortable" data-tab="players" data-col="_form_avg" title="Średnia punktów z rozegranych meczów z ostatnich 5 kolejek uwzględnionych w formie">Średnia'+arrow('players','_form_avg')+'</th>';
  h += '<th class="text-right sortable" data-tab="players" data-col="popularity_pct" title="Oficjalny % popularności z API Fantasy Ekstraklasa — procent WSZYSTKICH graczy fantasy, którzy mają tego zawodnika w składzie">Pop.'+arrow('players','popularity_pct')+'</th>';
  if (hasOwn) {{
    h += '<th class="text-right sortable" data-tab="players" data-col="_own_squad" style="min-width:100px" title="% drużyn z wybranego zakresu (Top 10/100/Wszystkie/Liga), które mają tego zawodnika w składzie">W składzie'+arrow('players','_own_squad')+'</th>';
    h += '<th class="text-right sortable" data-tab="players" data-col="_own_starting" style="min-width:100px" title="% drużyn z wybranego zakresu, które mają tego zawodnika w Starting XI (nie na ławce)">Start XI'+arrow('players','_own_starting')+'</th>';
    h += '<th class="text-right sortable" data-tab="players" data-col="_own_captain" style="min-width:100px" title="% drużyn z wybranego zakresu, które mają tego zawodnika jako kapitana">Kapitan'+arrow('players','_own_captain')+'</th>';
  }}
  h += '</tr></thead><tbody>';

  // Dodaj dane ownership, formę i diff do sortowania
  data.forEach(p => {{
    const o = ownMap[p.player_id];
    p._own_squad = o ? num(o.squad_pct) : 0;
    p._own_starting = o ? num(o.starting_pct) : 0;
    p._own_captain = o ? num(o.captain_pct) : 0;
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
    h += '<td class="text-right c-dim" style="font-size:13px">'+p.popularity_pct+'</td>';
    if (hasOwn) {{
      const sq = p._own_squad, st = p._own_starting, cp = p._own_captain;
      h += '<td>'+(sq > 0 ? bar(sq, 100, '#10b981') : '<span class="c-dim" style="font-size:12px">—</span>')+'</td>';
      h += '<td>'+(st > 0 ? bar(st, 100, '#3b82f6') : '<span class="c-dim" style="font-size:12px">—</span>')+'</td>';
      h += '<td>'+(cp > 0 ? bar(cp, 40, '#fbbf24') : '<span class="c-dim" style="font-size:12px">—</span>')+'</td>';
    }}
    h += '</tr>';
  }});
  h += '</tbody></table></div>';
  return h;
}}

// Oblicz średnie punkty per pozycja — globalne (wykluczając <=0)
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

// Oblicz średnie punkty per pozycja — liga (z drużyn ligowych, wykluczając <=0)
const LEAGUE_POS_AVGS = {{}};
(function() {{
  const seen = {{}}, sums = {{}}, counts = {{}};
  LEAGUE_TEAMS.forEach(t => {{
    t.players.forEach(p => {{
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

function diffBadge(pts, avg) {{
  if (!avg) return '<span class="diff-badge diff-zero">—</span>';
  const d = pts - avg;
  const cls = d > 0 ? 'diff-pos' : d < 0 ? 'diff-neg' : 'diff-zero';
  return '<span class="diff-badge '+cls+'">'+(d>0?'+':'')+d.toFixed(0)+'</span>';
}}

function renderDuets() {{
  if (!DUETS_DATA.length) return '<div class="empty-msg">Brak danych o duetach</div>';

  // Zmienne motywu dla kolorów (dark/light)
  const isLight = document.documentElement.classList.contains('theme-fantasy');
  const bgPanel = isLight ? '#f5f5f5' : '#0f172a';
  const cMuted = isLight ? '#5a5a5a' : '#94a3b8';
  const cLabel = isLight ? '#949494' : '#64748b';

  const dls = sorts.duets_list;
  function dlArrow(col) {{
    return dls.col === col ? (dls.dir === 'desc' ? ' ▼' : ' ▲') : '';
  }}

  const sortedDuets = [...DUETS_DATA].sort((a, b) => {{
    let av = a[dls.col], bv = b[dls.col];
    if (typeof av === 'string') {{
      if (av < bv) return dls.dir === 'desc' ? 1 : -1;
      if (av > bv) return dls.dir === 'desc' ? -1 : 1;
      return 0;
    }}
    av = num(av); bv = num(bv);
    if (av < bv) return dls.dir === 'desc' ? 1 : -1;
    if (av > bv) return dls.dir === 'desc' ? -1 : 1;
    return 0;
  }});

  let h = '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-center" style="width:50px">#</th>';
  h += '<th class="text-left sortable" data-tab="duets_list" data-col="duet_name">Duet'+dlArrow('duet_name')+'</th>';
  h += '<th class="text-left">Gracze</th>';
  h += '<th class="text-right sortable" data-tab="duets_list" data-col="autumn_pts">Jesień'+dlArrow('autumn_pts')+'</th>';
  h += '<th class="text-right sortable" data-tab="duets_list" data-col="spring_pts">Wiosna'+dlArrow('spring_pts')+'</th>';
  h += '<th class="text-right sortable" data-tab="duets_list" data-col="total_pts" style="font-size:13px;font-weight:800">SUMA'+dlArrow('total_pts')+'</th>';
  h += '<th class="text-center sortable" data-tab="duets_list" data-col="rank_change">Zmiana'+dlArrow('rank_change')+'</th>';
  h += '</tr></thead><tbody>';

  sortedDuets.forEach((d, i) => {{
    const pos = i + 1;
    const medal = pos === 1 ? '🥇' : pos === 2 ? '🥈' : pos === 3 ? '🥉' : pos;
    const isOpen = d.duet_name === selectedDuet;

    h += '<tr style="cursor:pointer" data-duetname="'+encodeURIComponent(d.duet_name)+'">';
    h += '<td class="text-center" style="font-size:'+(pos<=3?'18px':'14px')+'">'+medal+'</td>';
    h += '<td style="font-weight:600">'+d.duet_name+' <span style="font-size:10px;color:#475569">'+(isOpen?'▼':'▶')+'</span></td>';
    h += '<td style="font-size:12px;color:#94a3b8">'+d.players+'</td>';
    h += '<td class="text-right" style="color:#94a3b8">'+(d.autumn_pts||0)+'</td>';
    h += '<td class="text-right" style="color:#94a3b8">'+(d.spring_pts||0)+'</td>';
    h += '<td class="text-right" style="font-weight:800;font-size:15px">'+(d.total_pts||0)+'</td>';

    const rc = d.rank_change || 0;
    let changeHtml = '';
    if (rc > 0) changeHtml = '<span style="color:#10b981">▲'+rc+'</span>';
    else if (rc < 0) changeHtml = '<span style="color:#ef4444">▼'+Math.abs(rc)+'</span>';
    else changeHtml = '<span style="color:#64748b">–</span>';
    h += '<td class="text-center">'+changeHtml+'</td>';
    h += '</tr>';

    if (isOpen) {{
      h += '<tr><td colspan="7" style="padding:8px 16px;background:#0f172a">';
      h += '<div style="font-size:13px;line-height:1.8">';
      const t1sum = (d.team1_autumn||0) + (d.team1_spring||0);
      const t2sum = (d.team2_autumn||0) + (d.team2_spring||0);
      h += '<div style="display:flex;justify-content:space-between;max-width:500px">';
      h += '<span style="font-weight:600">'+d.team1_name+'</span>';
      h += '<span style="color:#94a3b8">'+d.team1_autumn+' + '+d.team1_spring+' = <b>'+t1sum+'</b></span>';
      h += '</div>';
      h += '<div style="display:flex;justify-content:space-between;max-width:500px">';
      h += '<span style="font-weight:600">'+d.team2_name+'</span>';
      h += '<span style="color:#94a3b8">'+d.team2_autumn+' + '+d.team2_spring+' = <b>'+t2sum+'</b></span>';
      h += '</div>';
      h += '</div>';
      h += '</td></tr>';
    }}
  }});

  h += '</tbody></table></div>';
  return h;
}}

function renderTeams() {{
  if (!LEAGUE_TEAMS.length) return '<div class="empty-msg">Brak danych o drużynach ligi</div>';

  // Zmienne motywu dla kolorów (dark/light)
  const isLight = document.documentElement.classList.contains('theme-fantasy');
  const bgBtn = isLight ? '#ffffff' : '#1e293b';
  const bgPanel = isLight ? '#f5f5f5' : '#0f172a';
  const cMuted = isLight ? '#5a5a5a' : '#94a3b8';

  let h = '<div class="section-title"><span style="font-size:22px">📋</span><h2>Liga CMF</h2><div class="line"></div></div>';

  // View toggle
  h += '<div class="view-toggle" style="display:flex;gap:8px;margin-bottom:16px">';
  h += '<button class="view-btn'+(currentTeamsView==='teams'?' active':'')+'" data-view="teams" style="padding:6px 16px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:600;background:'+(currentTeamsView==='teams'?'#3b82f6':bgBtn)+';color:'+(currentTeamsView==='teams'?'#fff':cMuted)+'">👥 Drużyny</button>';
  h += '<button class="view-btn'+(currentTeamsView==='duets'?' active':'')+'" data-view="duets" style="padding:6px 16px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:600;background:'+(currentTeamsView==='duets'?'#3b82f6':bgBtn)+';color:'+(currentTeamsView==='duets'?'#fff':cMuted)+'">👫 Duety</button>';
  h += '</div>';

  if (currentTeamsView === 'duets') return h + renderDuets();

  // Helpers for squad table
  const POS_ORDER = {{BR:1,OBR:2,POM:3,NAP:4}};
  const NCOLS = 10;

  // Build player ownership map: pid -> number of teams owning that player
  const playerOwnerCount = {{}};
  const totalTeams = LEAGUE_TEAMS.length;
  LEAGUE_TEAMS.forEach(team => {{
    if (team.players) team.players.forEach(p => {{
      playerOwnerCount[p.pid] = (playerOwnerCount[p.pid] || 0) + 1;
    }});
  }});

  function sortGroup(arr) {{
    const s = sorts.teams;
    return [...arr].sort((a,b) => {{
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
  }}

  function renderSquadRow(p, idx) {{
    const pk = p._pk;
    const pts = p.pts || 0;
    const price = p.price || 0;
    let nameStyle = 'font-weight:600';
    if (p.C) nameStyle += ';color:#fbbf24';
    let r = '<tr><td class="c-muted fw-600">'+(idx+1)+'</td>';
    r += nameCell(p.name, p.pid, nameStyle, p.C ? '<span class="captain-badge" style="margin-right:4px">C</span> ' : '');
    r += '<td class="text-center">'+posBadge(pk)+'</td>';
    r += '<td class="text-right c-muted">'+price.toFixed(1)+'M</td>';
    r += '<td class="text-right fw-700">'+pts+'</td>';
    r += '<td class="text-center">'+diffBadge(pts, POS_AVGS[pk])+'</td>';
    r += '<td class="text-center">'+diffBadge(pts, LEAGUE_POS_AVGS[pk])+'</td>';
    const favg = p._form_avg;
    const favgC = favg >= 6 ? '#22d3ee' : favg >= 3 ? '#10b981' : '#94a3b8';
    r += '<td class="text-center">'+formChart(p.form, true)+'</td>';
    r += '<td class="text-right fw-600" style="color:'+favgC+'">'+(favg > 0 ? favg.toFixed(1) : '—')+'</td>';
    const imp = p._imp != null ? p._imp : 100;
    const impColor = imp >= 70 ? '#10b981' : imp >= 30 ? '#eab308' : '#ef4444';
    r += '<td class="text-center fw-600" style="color:'+impColor+'">'+imp+'%</td>';
    r += '</tr>';
    return r;
  }}

  // Sort teams by selected column
  const tls = sorts.teams_list;
  const sortedTeams = [...LEAGUE_TEAMS].sort((a, b) => {{
    let av, bv;
    if (tls.col === 'name') {{
      av = (a.display_name || a.slug.replace(/-/g,' ')).toLowerCase();
      bv = (b.display_name || b.slug.replace(/-/g,' ')).toLowerCase();
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

  // Hockey-style table with expandable squads
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-center sortable" data-tab="teams_list" data-col="hockey_pos" style="width:50px">#'+tlArrow('hockey_pos')+'</th>';
  h += '<th class="text-left sortable" data-tab="teams_list" data-col="name">Drużyna'+tlArrow('name')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="autumn_pts">Jesień'+tlArrow('autumn_pts')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="best_gw_autumn" style="font-size:11px;color:#64748b">🔥 J'+tlArrow('best_gw_autumn')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="spring_pts">Wiosna'+tlArrow('spring_pts')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="best_gw_spring" style="font-size:11px;color:#64748b">🔥 W'+tlArrow('best_gw_spring')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="total_pts" style="font-size:13px;font-weight:800">SUMA'+tlArrow('total_pts')+'</th>';
  h += '<th class="text-center sortable" data-tab="teams_list" data-col="rank_change">Zmiana'+tlArrow('rank_change')+'</th>';
  h += '</tr></thead><tbody>';

  sortedTeams.forEach((t, i) => {{
    const pos = t.hockey_pos || (i + 1);
    const medal = pos === 1 ? '🥇' : pos === 2 ? '🥈' : pos === 3 ? '🥉' : pos;
    const tName = t.display_name || t.slug.replace(/-/g,' ');
    const isMyTeam = tName.toLowerCase() === 'tokusatsu soccer';
    const dimRow = t.autumn_only;
    const isOpen = t.slug === selectedTeam;
    const hasPlayers = t.players && t.players.length > 0;

    let rowCls = isMyTeam ? 'highlight' : '';
    let rowStyle = '';
    if (dimRow) rowStyle = 'opacity:0.45';
    if (hasPlayers) rowStyle += (rowStyle ? ';' : '') + 'cursor:pointer';

    h += '<tr'+(rowCls ? ' class="'+rowCls+'"' : '')+(rowStyle ? ' style="'+rowStyle+'"' : '')+' data-teamslug="'+t.slug+'">';
    h += '<td class="text-center" style="font-size:'+(pos<=3?'18px':'14px')+'">' + medal + '</td>';
    h += '<td style="font-weight:600">' + tName + (dimRow ? ' <span style="font-size:10px;color:#64748b">(nie gra)</span>' : '') + (hasPlayers ? ' <span style="font-size:10px;color:#475569">'+(isOpen?'▼':'▶')+'</span>' : '') + '</td>';
    h += '<td class="text-right" style="color:#94a3b8">' + (t.autumn_pts||0) + '</td>';
    h += '<td class="text-right" style="color:#64748b;font-size:12px">' + (t.best_gw_autumn > 0 ? t.best_gw_autumn : '—') + '</td>';
    h += '<td class="text-right" style="color:#94a3b8">' + (t.spring_pts||0) + '</td>';
    h += '<td class="text-right" style="color:#64748b;font-size:12px">' + (t.best_gw_spring > 0 ? t.best_gw_spring : '—') + '</td>';
    h += '<td class="text-right" style="font-weight:800;font-size:15px">' + (t.total_pts||0) + '</td>';

    const rc = t.rank_change || 0;
    let changeHtml = '';
    if (rc > 0) changeHtml = '<span style="color:#10b981">▲' + rc + '</span>';
    else if (rc < 0) changeHtml = '<span style="color:#ef4444">▼' + Math.abs(rc) + '</span>';
    else changeHtml = '<span style="color:#64748b">–</span>';
    h += '<td class="text-center">' + changeHtml + '</td>';
    h += '</tr>';

    // Expandable squad panel
    if (isOpen && hasPlayers) {{
      t.players.forEach(p => {{
        const pk = POS_ID[p.pos] || p.pos || '';
        p._pk = pk;
        p._pos_order = POS_ORDER[pk] || 99;
        p._diff_global = (POS_AVGS[pk] && (p.pts||0) > 0) ? Math.round(((p.pts||0) - POS_AVGS[pk]) * 10) / 10 : 0;
        p._diff_league = (LEAGUE_POS_AVGS[pk] && (p.pts||0) > 0) ? Math.round(((p.pts||0) - LEAGUE_POS_AVGS[pk]) * 10) / 10 : 0;
        p._form_avg = formAvgNum(p.form);
        const ownersExcl = (playerOwnerCount[p.pid] || 1) - 1;
        p._imp = totalTeams > 1 ? Math.round(((totalTeams - 1 - ownersExcl) / (totalTeams - 1)) * 100) : 100;
      }});

      h += '<tr><td colspan="8" style="padding:0;background:#0f172a">';
      h += '<div class="data-table" style="padding:4px 12px 12px">';
      h += '<table><thead><tr>';
      h += '<th class="text-left">#</th>';
      h += '<th class="text-left sortable" data-tab="teams" data-col="name">Zawodnik'+arrow('teams','name')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_pos_order">Poz'+arrow('teams','_pos_order')+'</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="price">Cena'+arrow('teams','price')+'</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="pts">Punkty'+arrow('teams','pts')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_diff_global" title="Punkty zawodnika minus średnia punktów wszystkich grających na tej pozycji">±Avg'+arrow('teams','_diff_global')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_diff_league" title="Punkty zawodnika minus średnia punktów graczy na tej pozycji w drużynach z Twojej ligi">±Liga'+arrow('teams','_diff_league')+'</th>';
      h += '<th class="text-center" style="min-width:80px">Forma</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="_form_avg" title="Średnia punktów z rozegranych meczów (ostatnie 5 kolejek przed obecną)">Średnia'+arrow('teams','_form_avg')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_imp" title="Differential ownership — im wyższy %, tym mniej managerów w lidze posiada tego zawodnika">Imp'+arrow('teams','_imp')+'</th>';
      h += '</tr></thead><tbody>';

      const starters = sortGroup(t.players.filter(p => !p.R));
      const reserves = sortGroup(t.players.filter(p => p.R));

      starters.forEach((p, idx) => {{ h += renderSquadRow(p, idx); }});
      if (reserves.length) {{
        h += '<tr><td colspan="'+NCOLS+'" style="padding:6px 0;border-top:1px dashed #334155"><span class="c-dim" style="font-size:11px;text-transform:uppercase;letter-spacing:1px">Ławka rezerwowych</span></td></tr>';
        reserves.forEach((p, idx) => {{ h += renderSquadRow(p, starters.length + idx); }});
      }}

      // Podsumowanie
      const totalPts = starters.reduce((s,p) => s + (p.pts||0), 0);
      const totalDiffG = t.players.reduce((s,p) => s + (p._diff_global||0), 0);
      const totalDiffL = t.players.reduce((s,p) => s + (p._diff_league||0), 0);
      h += '<tr style="border-top:2px solid #334155"><td colspan="4" class="fw-700" style="text-align:right;padding-top:10px">Razem:</td>';
      h += '<td class="text-right fw-700" style="padding-top:10px">'+totalPts+'</td>';
      const gCls = totalDiffG > 0 ? 'diff-pos' : totalDiffG < 0 ? 'diff-neg' : 'diff-zero';
      const lCls = totalDiffL > 0 ? 'diff-pos' : totalDiffL < 0 ? 'diff-neg' : 'diff-zero';
      h += '<td class="text-center" style="padding-top:10px"><span class="diff-badge '+gCls+'">'+(totalDiffG>0?'+':'')+totalDiffG.toFixed(0)+'</span></td>';
      h += '<td class="text-center" style="padding-top:10px"><span class="diff-badge '+lCls+'">'+(totalDiffL>0?'+':'')+totalDiffL.toFixed(0)+'</span></td>';
      const avgImp = t.players.length > 0 ? Math.round(t.players.reduce((s,p) => s + (p._imp||0), 0) / t.players.length) : 0;
      const avgImpColor = avgImp >= 70 ? '#10b981' : avgImp >= 30 ? '#eab308' : '#ef4444';
      h += '<td colspan="2"></td><td class="text-center fw-700" style="padding-top:10px;color:'+avgImpColor+'">Ø '+avgImp+'%</td></tr>';

      h += '</tbody></table></div>';
      h += '</td></tr>';
    }}
  }});

  h += '</tbody></table></div>';
  return h;
}}

// ============ FDR (Fixture Difficulty Rating) ============
const FDR_COLORS = {{
  1: {{bg:'#375523', fg:'#ffffff'}},
  2: {{bg:'#01FC7A', fg:'#000000'}},
  3: {{bg:'#E7E7E7', fg:'#000000'}},
  4: {{bg:'#FF1751', fg:'#ffffff'}},
  5: {{bg:'#80072D', fg:'#ffffff'}},
}};
const FDR_LABELS = {{1:'Bardzo łatwy', 2:'Łatwy', 3:'Średni', 4:'Trudny', 5:'Bardzo trudny'}};
let fdrSort = 'alpha'; // 'alpha' | 'def' | 'atk'

function fdrShowModal(team) {{
  const st = EKSTRA_STATS[team];
  const str = (FDR_DATA.team_strengths || {{}})[team];
  const abbr = FIXTURES.abbrevs[team] || team.substring(0,3).toUpperCase();
  const old = document.getElementById("ftModal");
  if (old) old.remove();
  const wrap = document.createElement("div");
  wrap.className = "ft-modal-bg";
  wrap.id = "ftModal";
  const gf = st ? st.gf : '?';
  const ga = st ? st.ga : '?';
  let strengthHtml = '';
  if (str) {{
    strengthHtml = '<div style="margin-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:8px">'
      +'<div style="text-align:center;background:#0f172a;border-radius:8px;padding:8px"><div style="font-size:10px;color:#64748b;text-transform:uppercase">Atak (D)</div><div style="font-size:20px;font-weight:800;color:#22d3ee">'+str.attack_h+'</div></div>'
      +'<div style="text-align:center;background:#0f172a;border-radius:8px;padding:8px"><div style="font-size:10px;color:#64748b;text-transform:uppercase">Atak (W)</div><div style="font-size:20px;font-weight:800;color:#22d3ee">'+str.attack_a+'</div></div>'
      +'<div style="text-align:center;background:#0f172a;border-radius:8px;padding:8px"><div style="font-size:10px;color:#64748b;text-transform:uppercase">Obrona (D)</div><div style="font-size:20px;font-weight:800;color:#f87171">'+str.defense_h+'</div></div>'
      +'<div style="text-align:center;background:#0f172a;border-radius:8px;padding:8px"><div style="font-size:10px;color:#64748b;text-transform:uppercase">Obrona (W)</div><div style="font-size:20px;font-weight:800;color:#f87171">'+str.defense_a+'</div></div>'
      +'</div>';
  }}
  wrap.innerHTML = '<div class="ft-modal"><button class="ft-modal-close" id="ftClose">✕</button>'
    +'<h3>'+abbr+' — '+team+'</h3>'
    +'<div style="display:flex;gap:24px;margin:16px 0">'
    +'<div style="flex:1;text-align:center"><div style="font-size:12px;color:#94a3b8;margin-bottom:4px">Strzelone (GF)</div><div style="font-size:28px;font-weight:800;color:#22d3ee">'+gf+'</div></div>'
    +'<div style="flex:1;text-align:center"><div style="font-size:12px;color:#94a3b8;margin-bottom:4px">Stracone (GA)</div><div style="font-size:28px;font-weight:800;color:#f87171">'+ga+'</div></div>'
    +'</div>'
    +strengthHtml
    +'<div style="font-size:11px;color:#64748b;text-align:center;margin-top:12px">Siła >1.0 = powyżej średniej ligowej &nbsp;|&nbsp; Dane z 90minut.pl</div>'
    +'</div>';
  document.body.appendChild(wrap);
  document.getElementById("ftClose").onclick = function() {{ wrap.remove(); }};
  wrap.onclick = function(e) {{ if (e.target === wrap) wrap.remove(); }};
}}

function renderFixtures() {{
  const fdrTeams = FDR_DATA.teams || [];
  const gws = FDR_DATA.gameweeks || [];
  if (!gws.length) return '<div class="empty-msg">Brak danych terminarza — sprawdź terminarz.txt i dane z 90minut.pl</div>';

  // Sortowanie
  let teams = [...fdrTeams];
  if (fdrSort === 'def') {{
    teams.sort((a,b) => a.total_def - b.total_def);
  }} else if (fdrSort === 'atk') {{
    teams.sort((a,b) => a.total_atk - b.total_atk);
  }} else {{
    teams.sort((a,b) => a.name.localeCompare(b.name, 'pl'));
  }}

  let h = '<div class="section-title"><span style="font-size:22px">📅</span><h2>Terminarz — trudność meczów</h2><div class="line"></div></div>';

  // Legenda
  h += '<div class="fdr-legend">';
  [1,2,3,4,5].forEach(r => {{
    const c = FDR_COLORS[r];
    h += '<span class="fdr-legend-item"><span class="fdr-legend-swatch" style="background:'+c.bg+';color:'+c.fg+'">'+r+'</span><span style="color:#94a3b8">'+FDR_LABELS[r]+'</span></span>';
  }});
  h += '</div>';

  h += '<div style="margin-bottom:10px;font-size:11px;color:#64748b;line-height:1.6">';
  h += '<span style="color:#22d3ee;font-weight:600">ATK</span> = siła ataku rywala (ważne dla obrońców/GK — zielony = słaby atak rywala) &nbsp;|&nbsp; ';
  h += '<span style="color:#f87171;font-weight:600">DEF</span> = siła obrony rywala (ważne dla napastników/pomocników — zielony = słaba obrona rywala)';
  h += '</div>';

  // Sort toggle
  h += '<div style="margin-bottom:12px;font-size:12px">';
  h += '<span class="c-dim">Sortuj: </span>';
  h += '<button class="scope-btn fdr-sort-btn" data-fdrsort="alpha" style="font-size:11px;padding:3px 10px">A-Z</button> ';
  h += '<button class="scope-btn fdr-sort-btn" data-fdrsort="def" style="font-size:11px;padding:3px 10px">Najłatwiejszy dla ataku ↑</button> ';
  h += '<button class="scope-btn fdr-sort-btn" data-fdrsort="atk" style="font-size:11px;padding:3px 10px">Najłatwiejszy dla obrony ↑</button>';
  h += '</div>';

  // Tabela
  h += '<div class="data-table" style="overflow-x:auto"><table class="fdr-table"><thead><tr>';
  h += '<th style="text-align:left;min-width:100px">Drużyna</th>';
  h += '<th style="min-width:56px">Σ ATK</th>';
  h += '<th style="min-width:56px">Σ DEF</th>';
  gws.forEach(gw => {{ h += '<th style="min-width:100px">K'+gw+'</th>'; }});
  h += '</tr></thead><tbody>';

  teams.forEach((team, ti) => {{
    h += '<tr>';
    h += '<td class="fdr-team fdr-team-click" data-fdrteam="'+ti+'" style="text-align:left;font-weight:700;white-space:nowrap;padding-left:8px;cursor:pointer">';
    h += '<span style="font-size:11px;color:#64748b;margin-right:3px">'+(ti+1)+'</span> '+team.short+'</td>';

    // Σ ATK
    const avgAtk = gws.length ? (team.total_atk / gws.length) : 3;
    const atkColor = avgAtk <= 2 ? '#10b981' : avgAtk <= 3 ? '#94a3b8' : '#ef4444';
    h += '<td><span class="fdr-sum" style="color:'+atkColor+'">'+team.total_atk+'</span></td>';

    // Σ DEF
    const avgDef = gws.length ? (team.total_def / gws.length) : 3;
    const defColor = avgDef <= 2 ? '#10b981' : avgDef <= 3 ? '#94a3b8' : '#ef4444';
    h += '<td><span class="fdr-sum" style="color:'+defColor+'">'+team.total_def+'</span></td>';

    // Dual ATK/DEF tiles per gameweek
    team.fixtures.forEach(f => {{
      if (!f.opponent) {{
        h += '<td>—</td>';
        return;
      }}
      const cA = FDR_COLORS[f.atk] || FDR_COLORS[3];
      const cD = FDR_COLORS[f.def] || FDR_COLORS[3];
      const ha = f.home ? 'D' : 'W';
      h += '<td title="'+f.opponent+' ('+(f.home ? 'dom' : 'wyjazd')+') '+f.date+'">';
      h += '<div class="fdr-cell">';
      h += '<div class="fdr-cell-team">'+f.opponent_short+' <span class="fdr-ha">('+ha+')</span></div>';
      h += '<div class="fdr-cell-vals">';
      h += '<span class="fdr-mini" style="background:'+cA.bg+';color:'+cA.fg+'"><span class="fdr-lbl">ATK</span>'+f.atk+'</span>';
      h += '<span class="fdr-mini" style="background:'+cD.bg+';color:'+cD.fg+'"><span class="fdr-lbl">DEF</span>'+f.def+'</span>';
      h += '</div></div></td>';
    }});

    h += '</tr>';
  }});

  h += '</tbody></table></div>';
  window._fdrTeams = teams;

  // 📋 Fixture Planner — sekcja dodana POD istniejącą siatką FDR
  h += renderFixturePlanner();

  return h;
}}

// ============ Fixture Planner ============
// 📖 LEKCJA: Fixture Planner pomaga planować transfery na kilka kolejek do przodu.
// Pokazuje które drużyny mają najłatwiejszy terminarz w wybranym zakresie,
// co pomaga w decyzjach transferowych — kupujesz zawodników z łatwym kalendarzem.

let fpMode = 'mix';        // 'atk' | 'def' | 'mix' — perspektywa pozycyjna
let fpSortCol = 'avg';     // kolumna sortowania: 'team','avg','sum','easy','hard' lub 'gwNN'
let fpSortDir = 'asc';     // kierunek sortowania
let fpGwFrom = 0;           // gameweek start (0 = auto)
let fpGwTo = 0;             // gameweek end (0 = auto)
let fpSelected = [];         // max 2 drużyny do rotation pair

function fpGetFdr(fixture, mode) {{
  // 📖 ATK mode: patrzymy na DEF rywala (słaba obrona = łatwo strzelić)
  // DEF mode: patrzymy na ATK rywala (słaby atak = mało stracimy)
  // MIX: średnia obu
  if (!fixture || !fixture.opponent) return 3;
  if (mode === 'atk') return fixture.def;
  if (mode === 'def') return fixture.atk;
  return Math.round((fixture.atk + fixture.def) / 2);
}}

function renderFixturePlanner() {{
  const fdrTeams = FDR_DATA.teams || [];
  const gws = FDR_DATA.gameweeks || [];
  if (!gws.length || !fdrTeams.length) return '';

  // Ustaw domyślne zakresy jeśli jeszcze nie ustawione
  if (fpGwFrom === 0) fpGwFrom = gws[0];
  if (fpGwTo === 0) fpGwTo = gws[gws.length - 1];

  // Waliduj zakres
  if (fpGwFrom < gws[0]) fpGwFrom = gws[0];
  if (fpGwTo > gws[gws.length - 1]) fpGwTo = gws[gws.length - 1];
  if (fpGwFrom > fpGwTo) fpGwFrom = fpGwTo;

  const selectedGws = gws.filter(g => g >= fpGwFrom && g <= fpGwTo);
  if (!selectedGws.length) return '';

  let h = '<div class="fp-section">';
  h += '<div class="section-title"><span style="font-size:22px">📋</span><h2>Fixture Planner</h2><div class="line"></div></div>';
  h += '<div style="margin-bottom:12px;font-size:12px;color:#64748b;line-height:1.6">';
  h += 'Planuj transfery na kilka kolejek do przodu. Wybierz zakres i perspektywę pozycyjną, aby znaleźć drużyny z najłatwiejszym terminarzem.';
  h += '</div>';

  // Kontrolki: zakres kolejek + tryb pozycyjny
  h += '<div class="fp-controls">';
  h += '<label>Od kolejki:</label>';
  h += '<select class="fp-gw-from">';
  gws.forEach(g => {{ h += '<option value="'+g+'"'+(g===fpGwFrom?' selected':'')+'>K'+g+'</option>'; }});
  h += '</select>';
  h += '<label>Do kolejki:</label>';
  h += '<select class="fp-gw-to">';
  gws.forEach(g => {{ h += '<option value="'+g+'"'+(g===fpGwTo?' selected':'')+'>K'+g+'</option>'; }});
  h += '</select>';

  // 📖 Tryb pozycyjny: ATK (dla napastników/pomocników), DEF (dla obrońców/bramkarzy), MIX (średnia)
  h += '<div class="fp-mode-btns">';
  h += '<button class="fp-mode-btn'+(fpMode==='atk'?' active':'')+'" data-fpmode="atk">ATK</button>';
  h += '<button class="fp-mode-btn'+(fpMode==='def'?' active':'')+'" data-fpmode="def">DEF</button>';
  h += '<button class="fp-mode-btn'+(fpMode==='mix'?' active':'')+'" data-fpmode="mix">MIX</button>';
  h += '</div>';
  h += '</div>';

  // Oblicz dane planera dla każdej drużyny
  const planData = fdrTeams.map(team => {{
    const fixturesInRange = selectedGws.map(gw => {{
      const f = team.fixtures.find(fx => fx.gw === gw);
      return f || null;
    }});
    const fdrValues = fixturesInRange.map(f => fpGetFdr(f, fpMode));
    const sum = fdrValues.reduce((a, b) => a + b, 0);
    const avg = fdrValues.length ? sum / fdrValues.length : 3;
    const easy = fdrValues.filter(v => v <= 2).length;
    const hard = fdrValues.filter(v => v >= 4).length;
    return {{
      name: team.name,
      short: team.short,
      fixtures: fixturesInRange,
      fdrValues: fdrValues,
      sum: sum,
      avg: avg,
      easy: easy,
      hard: hard,
    }};
  }});

  // Sortowanie
  const sortFns = {{
    'team': (a, b) => a.name.localeCompare(b.name, 'pl'),
    'avg': (a, b) => a.avg - b.avg,
    'sum': (a, b) => a.sum - b.sum,
    'easy': (a, b) => b.easy - a.easy,
    'hard': (a, b) => a.hard - b.hard,
  }};
  // Sortowanie po kolumnie kolejki: gwNN
  let sortFn = sortFns[fpSortCol];
  if (!sortFn && fpSortCol.startsWith('gw')) {{
    const gwIdx = selectedGws.indexOf(parseInt(fpSortCol.substring(2)));
    if (gwIdx >= 0) sortFn = (a, b) => a.fdrValues[gwIdx] - b.fdrValues[gwIdx];
  }}
  if (!sortFn) sortFn = sortFns['avg'];
  planData.sort((a, b) => {{
    const v = sortFn(a, b);
    return fpSortDir === 'desc' ? -v : v;
  }});

  // Nagłówek sortowania — helper
  function thClass(col) {{ return fpSortCol === col ? ' fp-sorted' : ''; }}
  function thArrow(col) {{ return fpSortCol === col ? (fpSortDir === 'asc' ? ' ↑' : ' ↓') : ''; }}

  // Tabela planera
  h += '<div class="data-table" style="overflow-x:auto"><table class="fp-table"><thead><tr>';
  h += '<th class="fp-sort'+thClass('team')+'" data-fpcol="team" style="text-align:left;min-width:80px">Drużyna'+thArrow('team')+'</th>';
  selectedGws.forEach(gw => {{
    h += '<th class="fp-sort'+thClass('gw'+gw)+'" data-fpcol="gw'+gw+'" style="min-width:68px">K'+gw+thArrow('gw'+gw)+'</th>';
  }});
  h += '<th class="fp-sort'+thClass('sum')+'" data-fpcol="sum" style="min-width:52px">Σ FDR'+thArrow('sum')+'</th>';
  h += '<th class="fp-sort'+thClass('avg')+'" data-fpcol="avg" style="min-width:52px">Śr.'+thArrow('avg')+'</th>';
  h += '<th class="fp-sort'+thClass('easy')+'" data-fpcol="easy" style="min-width:52px">Łatwych'+thArrow('easy')+'</th>';
  h += '<th class="fp-sort'+thClass('hard')+'" data-fpcol="hard" style="min-width:52px">Trudnych'+thArrow('hard')+'</th>';
  h += '</tr></thead><tbody>';

  planData.forEach((team, ti) => {{
    const isSelected = fpSelected.includes(team.name);
    h += '<tr>';
    h += '<td class="fp-team-cell'+(isSelected ? ' fp-selected' : '')+'" data-fpteam="'+team.name+'">';
    h += '<span style="font-size:11px;color:#64748b;margin-right:3px">'+(ti+1)+'</span> '+team.short+'</td>';

    // Kafelki FDR per kolejka
    team.fixtures.forEach((f, fi) => {{
      if (!f || !f.opponent) {{
        h += '<td>—</td>';
        return;
      }}
      const fdr = team.fdrValues[fi];
      const c = FDR_COLORS[fdr] || FDR_COLORS[3];
      const ha = f.home ? 'D' : 'W';
      h += '<td title="'+f.opponent+' ('+(f.home?'dom':'wyjazd')+') '+f.date+'">';
      h += '<span class="fp-tile" style="background:'+c.bg+';color:'+c.fg+'">'+f.opponent_short+' <span class="fp-ha">('+ha+')</span></span>';
      h += '</td>';
    }});

    // Suma FDR
    h += '<td><span class="fdr-sum" style="color:'+(team.avg<=2.5?'#10b981':team.avg<=3.5?'#94a3b8':'#ef4444')+'">'+team.sum+'</span></td>';

    // Średnia FDR (kolorowana)
    const avgColor = team.avg < 2.5 ? '#10b981' : team.avg > 3.5 ? '#ef4444' : '#94a3b8';
    h += '<td><span class="fp-avg-cell" style="color:'+avgColor+'">'+team.avg.toFixed(1)+'</span></td>';

    // Łatwych / Trudnych
    h += '<td style="color:#10b981;font-weight:700">'+team.easy+'</td>';
    h += '<td style="color:#ef4444;font-weight:700">'+team.hard+'</td>';

    h += '</tr>';
  }});

  h += '</tbody></table></div>';

  // 📖 LEKCJA: "Rotation pair" — dwie drużyny z uzupełniającymi się terminarzami.
  // Jeśli Lech ma trudny mecz w K28 ale Pogoń łatwy, i odwrotnie w K29 —
  // to świetna para do rotacji obrońców/bramkarzy. Zawsze masz kogoś z łatwym meczem.
  if (fpSelected.length === 2) {{
    const t1 = planData.find(t => t.name === fpSelected[0]);
    const t2 = planData.find(t => t.name === fpSelected[1]);
    if (t1 && t2) {{
      let bothEasy = 0;   // obie łatwy — marnowanie slota
      let coverage = 0;   // przynajmniej jedna łatwy
      const totalGws = selectedGws.length;
      for (let i = 0; i < totalGws; i++) {{
        const e1 = t1.fdrValues[i] <= 2;
        const e2 = t2.fdrValues[i] <= 2;
        if (e1 && e2) bothEasy++;
        if (e1 || e2) coverage++;
      }}
      h += '<div class="fp-rotation">';
      h += '<div class="fp-rot-label">🔄 Rotation Pair: '+t1.short+' + '+t2.short+'</div>';
      h += '<div>Pokrycie: <b style="color:#22d3ee">'+coverage+'/'+totalGws+'</b> kolejek (przynajmniej jedna drużyna z łatwym meczem)</div>';
      h += '<div>Marnowanie: <b style="color:#fbbf24">'+bothEasy+'/'+totalGws+'</b> kolejek (obie mają łatwy mecz jednocześnie)</div>';
      const score = totalGws > 0 ? Math.round(coverage / totalGws * 100) : 0;
      const scoreColor = score >= 80 ? '#10b981' : score >= 50 ? '#fbbf24' : '#ef4444';
      h += '<div style="margin-top:6px">Wynik rotacji: <b style="color:'+scoreColor+'">'+score+'%</b></div>';
      h += '</div>';
    }}
  }} else if (fpSelected.length === 1) {{
    h += '<div class="fp-rotation"><div class="fp-rot-label">🔄 Rotation Pair</div>';
    h += '<div style="color:#64748b">Kliknij drugą drużynę, aby zobaczyć wynik rotacji</div></div>';
  }}

  // 📖 Szybki widok "Najlepsze drużyny na X kolejek" — podsumowanie
  // Sortujemy osobno wg ATK (DEF rywali), DEF (ATK rywali), i ogólnie najtrudniejsze
  const atkRanked = fdrTeams.map(team => {{
    const vals = selectedGws.map(gw => {{
      const f = team.fixtures.find(fx => fx.gw === gw);
      return fpGetFdr(f, 'atk');
    }});
    return {{ short: team.short, avg: vals.reduce((a,b)=>a+b,0) / (vals.length||1) }};
  }}).sort((a,b) => a.avg - b.avg);

  const defRanked = fdrTeams.map(team => {{
    const vals = selectedGws.map(gw => {{
      const f = team.fixtures.find(fx => fx.gw === gw);
      return fpGetFdr(f, 'def');
    }});
    return {{ short: team.short, avg: vals.reduce((a,b)=>a+b,0) / (vals.length||1) }};
  }}).sort((a,b) => a.avg - b.avg);

  const hardRanked = [...atkRanked].sort((a,b) => b.avg - a.avg);

  // Najlepsza para rotacyjna — brute-force po wszystkich parach
  let bestPair = {{ t1: '', t2: '', coverage: 0 }};
  for (let i = 0; i < planData.length; i++) {{
    for (let j = i + 1; j < planData.length; j++) {{
      let cov = 0;
      for (let k = 0; k < selectedGws.length; k++) {{
        if (planData[i].fdrValues[k] <= 2 || planData[j].fdrValues[k] <= 2) cov++;
      }}
      if (cov > bestPair.coverage) {{
        bestPair = {{ t1: planData[i].short, t2: planData[j].short, coverage: cov }};
      }}
    }}
  }}

  h += '<div class="fp-summary">';
  h += '<div class="fp-summary-line"><span>🟢</span> <b>Najłatwiejszy (ATK):</b> ';
  h += atkRanked.slice(0,3).map(t => t.short+' (śr. '+t.avg.toFixed(1)+')').join(' — ');
  h += '</div>';
  h += '<div class="fp-summary-line"><span>🟢</span> <b>Najłatwiejszy (DEF):</b> ';
  h += defRanked.slice(0,3).map(t => t.short+' (śr. '+t.avg.toFixed(1)+')').join(' — ');
  h += '</div>';
  h += '<div class="fp-summary-line"><span>🔴</span> <b>Najtrudniejszy:</b> ';
  h += hardRanked.slice(0,3).map(t => t.short+' (śr. '+t.avg.toFixed(1)+')').join(' — ');
  h += '</div>';
  if (bestPair.t1) {{
    h += '<div class="fp-summary-line"><span>🔄</span> <b>Najlepsza para rotacyjna:</b> ';
    h += bestPair.t1+' + '+bestPair.t2+' (pokrycie '+bestPair.coverage+'/'+selectedGws.length+')';
    h += '</div>';
  }}
  h += '</div>';

  h += '</div>';  // end fp-section
  return h;
}}

// ============ Transfers Tab ============
let trPos = 'ALL';
let predPos = 'ALL';
if (!sorts.predictions) sorts.predictions = {{col:'predicted_points', dir:'desc'}};

function priceChangeHtml(pc) {{
  if (!pc) return '';
  const v = parseFloat(pc) || 0;
  if (v > 0) return ' <span class="price-up">↑ +' + v.toFixed(1) + 'M</span>';
  if (v < 0) return ' <span class="price-down">↓ ' + v.toFixed(1) + 'M</span>';
  return '';
}}

function renderTransfersTable(list, totalTeams, title, color) {{
  if (!list || !list.length) return '<div class="empty-msg" style="padding:24px">Brak danych</div>';

  const filtered = trPos === 'ALL' ? list : list.filter(p => {{
    const pk = POS_ID[p.position] || p.position || '';
    return pk === trPos;
  }});

  if (!filtered.length) return '<div class="empty-msg" style="padding:24px">Brak zawodników dla wybranej pozycji</div>';

  let h = '<div class="transfers-header"><span style="font-size:18px">'+title.split(' ')[0]+'</span>';
  h += '<h3 style="color:'+color+'">'+title.split(' ').slice(1).join(' ')+'</h3></div>';
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-left">#</th>';
  h += '<th class="text-left">Zawodnik</th>';
  h += '<th class="text-center">Poz</th>';
  h += '<th class="text-left" style="max-width:120px">Drużyna</th>';
  h += '<th class="text-right">Cena</th>';
  h += '<th style="min-width:120px">Drużyn</th>';
  h += '</tr></thead><tbody>';

  filtered.forEach((p, i) => {{
    const pk = POS_ID[p.position] || p.position || '';
    const pct = p.pct || 0;
    const barW = Math.min(pct, 100);
    const priceChg = priceChangeHtml(p.price_change);
    h += '<tr>';
    h += '<td class="c-muted fw-600">' + (i + 1) + '</td>';
    h += '<td class="fw-600">' + p.name + priceChg + '</td>';
    h += '<td class="text-center">' + posBadge(pk) + '</td>';
    h += '<td class="c-muted" style="font-size:12px;max-width:120px;white-space:normal">' + (p.team || '—') + '</td>';
    h += '<td class="text-right c-muted">' + (p.price ? p.price.toFixed(1) + 'M' : '—') + '</td>';
    h += '<td><div class="bar-wrap"><div class="bar-bg" style="width:80px"><div class="bar-fill" style="width:' + barW + '%;background:' + color + '"></div></div>';
    h += '<span class="bar-val">' + p.count + ' (' + pct.toFixed(1) + '%)</span></div></td>';
    h += '</tr>';
  }});
  h += '</tbody></table></div>';
  return h;
}}

function renderTransfers() {{
  const td = TRANSFERS_DATA;
  if (!td || (!td.transfers_in && !td.transfers_out)) {{
    return '<div class="empty-msg">Brak danych transferowych — upewnij się że liga prywatna jest skonfigurowana i rozegrano co najmniej 2 kolejki</div>';
  }}

  const gw = td.gameweek || '?';
  const prevGw = td.prev_gameweek || (gw - 1);
  const leagueCount = td.league_teams_count || 0;
  const tin = td.transfers_in || [];
  const tout = td.transfers_out || [];

  let h = '<div class="section-title"><span style="font-size:22px">🔄</span><h2>Transfery — K' + prevGw + ' → K' + gw + '</h2><div class="line"></div></div>';

  // Filters row
  h += '<div class="tr-filters-row">';
  h += '<div class="pos-filters">';
  ['ALL','BR','OBR','POM','NAP'].forEach(p => {{
    const labels = {{ALL:'ALL',BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD'}};
    const active = trPos === p ? ' active' : '';
    h += '<button class="pos-btn tr-pos-btn' + active + '" data-trpos="' + p + '" data-pos="' + p + '">' + labels[p] + '</button>';
  }});
  h += '</div>';
  h += '<span class="tr-gw-badge" style="margin-left:auto">K' + prevGw + ' → K' + gw + ' · ' + leagueCount + ' drużyn</span>';
  h += '</div>';

  // Two tables side by side
  h += '<div class="transfers-grid">';
  h += '<div>' + renderTransfersTable(tin, leagueCount, '🟢 Najpopularniejsze kupna', '#10b981') + '</div>';
  h += '<div>' + renderTransfersTable(tout, leagueCount, '🔴 Najpopularniejsze sprzedaże', '#ef4444') + '</div>';
  h += '</div>';

  return h;
}}

function renderPredictions() {{
  if (!PREDICTIONS || !PREDICTIONS.length) return '<div class="empty-msg">Brak danych prognoz — sprawdź czy predictor.py jest dostępny i dane FDR zostały obliczone</div>';

  let data = [...PREDICTIONS].filter(p => p.predicted_points !== null && p.predicted_points !== undefined);
  if (predPos !== 'ALL') data = data.filter(p => (POS_ID[p.position] || p.position) === predPos);
  if (!data.length) return '<div class="empty-msg">Brak prognoz dla wybranej pozycji</div>';

  // Sort
  const s = sorts.predictions;
  data.sort((a, b) => {{
    // Niedostępni zawodnicy ZAWSZE na końcu, niezależnie od sortowania
    if (a.unavailable && !b.unavailable) return 1;
    if (!a.unavailable && b.unavailable) return -1;
    if (a.unavailable && b.unavailable) {{
      // Wśród niedostępnych sortuj alfabetycznie
      const an = (a.name || '').toLowerCase();
      const bn = (b.name || '').toLowerCase();
      return an < bn ? -1 : an > bn ? 1 : 0;
    }}
    let av = a[s.col], bv = b[s.col];
    if (s.col === 'name' || s.col === 'team' || s.col === 'next_opponent') {{
      av = (av || '').toLowerCase(); bv = (bv || '').toLowerCase();
      if (av < bv) return s.dir === 'desc' ? 1 : -1;
      if (av > bv) return s.dir === 'desc' ? -1 : 1;
      return 0;
    }}
    av = num(av); bv = num(bv);
    if (av < bv) return s.dir === 'desc' ? 1 : -1;
    if (av > bv) return s.dir === 'desc' ? -1 : 1;
    return 0;
  }});

  function predArrow(col) {{
    return s.col === col ? (s.dir === 'desc' ? ' ▼' : ' ▲') : '';
  }}

  // Prediction value gradient: high = green, medium = yellow, low = gray
  function predGradient(val) {{
    if (val >= 8) return 'background:rgba(16,185,129,0.25);color:#10b981';
    if (val >= 6) return 'background:rgba(34,211,238,0.2);color:#22d3ee';
    if (val >= 4) return 'background:rgba(251,191,36,0.2);color:#fbbf24';
    if (val >= 2) return 'background:rgba(148,163,184,0.15);color:#94a3b8';
    return 'background:rgba(100,116,139,0.1);color:#64748b';
  }}

  function fdrTile(val) {{
    const c = FDR_COLORS[val] || FDR_COLORS[3];
    return '<span class="pred-fdr-tile" style="background:'+c.bg+';color:'+c.fg+'">'+val+'</span>';
  }}

  function fdrUsedLabel(position, fdr_mod) {{
    const pk = POS_ID[position] || position;
    let label = 'MIX';
    if (pk === 'NAP') label = 'DEF';
    else if (pk === 'OBR' || pk === 'BR') label = 'ATK';
    const color = fdr_mod > 1.0 ? '#10b981' : fdr_mod < 1.0 ? '#ef4444' : '#94a3b8';
    return '<span class="pred-fdr-used" style="color:'+color+'">'+label+' ×'+fdr_mod.toFixed(2)+'</span>';
  }}

  function confidenceBadge(conf) {{
    const map = {{
      high: {{emoji:'🟢', label:'high', cls:'pred-conf-high'}},
      medium: {{emoji:'🟡', label:'medium', cls:'pred-conf-medium'}},
      low: {{emoji:'🔴', label:'low', cls:'pred-conf-low'}},
      insufficient_data: {{emoji:'⚪', label:'insuf.', cls:'pred-conf-insufficient'}},
      unavailable: {{emoji:'⛔', label:'niedostępny', cls:'pred-conf-unavailable'}},
    }};
    const m = map[conf] || map.low;
    return '<span class="pred-confidence '+m.cls+'">'+m.emoji+' '+m.label+'</span>';
  }}

  let h = '<div class="section-title"><span style="font-size:22px">🔮</span><h2>Prognoza punktów — następna kolejka</h2><div class="line"></div></div>';

  // Legend
  h += '<div class="pred-legend">';
  h += '<b>NAP</b> / <b>POM</b> → FDR DEF rywala (słabsza obrona = wyższa prognoza) &nbsp;|&nbsp; ';
  h += '<b>BR</b> / <b>OBR</b> → FDR ATK rywala (słabszy atak = wyższa prognoza)';
  h += '</div>';

  // Position filters
  h += '<div class="pred-filters">';
  h += '<div class="pos-filters">';
  ['ALL','BR','OBR','POM','NAP'].forEach(p => {{
    const labels = {{ALL:'ALL',BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD'}};
    const active = predPos === p ? ' active' : '';
    h += '<button class="pos-btn pred-pos-btn'+active+'" data-predpos="'+p+'" data-pos="'+p+'">'+labels[p]+'</button>';
  }});
  h += '</div>';
  h += '<span style="margin-left:auto;font-size:12px;color:#64748b">'+data.length+' zawodników</span>';
  h += '</div>';

  // Table
  h += '<div class="data-table"><table><thead><tr>';
  h += '<th class="text-left">#</th>';
  h += '<th class="text-left sortable" data-tab="predictions" data-col="name">Zawodnik'+predArrow('name')+'</th>';
  h += '<th class="text-center sortable" data-tab="predictions" data-col="position">Poz'+predArrow('position')+'</th>';
  h += '<th class="text-left sortable" data-tab="predictions" data-col="team">Drużyna'+predArrow('team')+'</th>';
  h += '<th class="text-center">Rywal</th>';
  h += '<th class="text-center">D/W</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="predicted_points">Prognoza'+predArrow('predicted_points')+'</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="base_avg">Śr. pkt'+predArrow('base_avg')+'</th>';
  h += '<th class="text-center">FDR ATK</th>';
  h += '<th class="text-center">FDR DEF</th>';
  h += '<th class="text-center">Użyty FDR</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="avg_minutes">Śr. min'+predArrow('avg_minutes')+'</th>';
  h += '<th class="text-center sortable" data-tab="predictions" data-col="confidence">Pewność'+predArrow('confidence')+'</th>';
  h += '</tr></thead><tbody>';

  data.forEach((p, i) => {{
    const pred = p.predicted_points || 0;
    const pk = POS_ID[p.position] || p.position || '';
    const oppFdrAtk = p.fdr_atk_opponent || 3;
    const oppFdrDef = p.fdr_def_opponent || 3;
    const fdrMod = p.fdr_modifier || 1.0;
    const avgMin = p.avg_minutes || 0;
    const baseAvg = p.base_avg || 0;
    const detail = p.detail || '';
    const isUnavailable = p.unavailable === true;
    const unavailableReason = p.availability_reason || '';

    // Wiersz dla niedostępnego zawodnika — przyciemniony, z markerem
    const rowStyle = isUnavailable ? ' style="opacity:0.55"' : '';
    h += '<tr'+rowStyle+'>';
    h += '<td class="c-muted fw-600">'+(i+1)+'</td>';
    h += '<td class="fw-600" title="'+detail.replace(/"/g,'&quot;')+'">'+p.name+(isUnavailable ? ' <span style="font-size:11px;color:#ef4444">⛔ '+unavailableReason+'</span>' : '')+'</td>';
    h += '<td class="text-center">'+posBadge(pk)+'</td>';
    h += '<td class="c-muted" style="font-size:13px">'+p.team+'</td>';

    // Rywal z FDR kolorem (używamy wyższego FDR)
    const oppName = p.opponent_short || p.next_opponent || '';
    const oppFdr = Math.max(oppFdrAtk, oppFdrDef);
    const oppC = FDR_COLORS[oppFdr] || FDR_COLORS[3];
    h += '<td class="text-center"><span class="pred-fdr-tile" style="background:'+oppC.bg+';color:'+oppC.fg+';font-size:11px;padding:3px 8px">'+oppName+'</span></td>';

    // Dom/Wyjazd
    h += '<td class="text-center">'+(p.is_home ? '🏠' : '✈️')+'</td>';

    // Prognoza — pogrubiona, gradient; dla niedostępnych: "—"
    if (isUnavailable) {{
      h += '<td class="text-right"><span class="pred-val" style="color:#64748b;font-style:italic">—</span></td>';
    }} else {{
      h += '<td class="text-right"><span class="pred-val" style="'+predGradient(pred)+'">'+pred.toFixed(1)+'</span></td>';
    }}

    // Średnia ważona
    const avgC = baseAvg >= 6 ? '#22d3ee' : baseAvg >= 3 ? '#10b981' : '#94a3b8';
    h += '<td class="text-right fw-600" style="color:'+avgC+'">'+baseAvg.toFixed(1)+'</td>';

    // FDR ATK/DEF rywala
    h += '<td class="text-center">'+fdrTile(oppFdrAtk)+'</td>';
    h += '<td class="text-center">'+fdrTile(oppFdrDef)+'</td>';

    // Użyty FDR
    h += '<td class="text-center">'+fdrUsedLabel(p.position, fdrMod)+'</td>';

    // Średnie minuty
    h += '<td class="text-right c-muted">'+Math.round(avgMin)+'&prime;</td>';

    // Pewność
    h += '<td class="text-center">'+confidenceBadge(p.confidence)+'</td>';

    h += '</tr>';
  }});

  h += '</tbody></table></div>';
  return h;
}}

function renderAccuracy() {{
  if (!ACCURACY_HISTORY || !ACCURACY_HISTORY.length) return '<div class="empty-msg">Brak danych trafności — uruchom scraper przynajmniej dwa razy, aby porównać prognozy z rzeczywistością</div>';

  const latest = ACCURACY_HISTORY[ACCURACY_HISTORY.length - 1];
  let h = '';

  // === STAT CARDS ===
  const maeByPos = latest.mae_by_pos || {{}};
  const posNames = Object.keys(maeByPos);
  let bestPos = '—';
  let bestPosVal = Infinity;
  posNames.forEach(p => {{ if (maeByPos[p] < bestPosVal) {{ bestPosVal = maeByPos[p]; bestPos = p; }} }});

  h += '<div class="stats-row">';
  h += '<div class="stat-card accent-cyan"><div class="val">' + latest.mae + ' pkt</div><div class="label">MAE ogólne</div><div class="sub">Średni błąd prognozy</div></div>';
  h += '<div class="stat-card accent-green"><div class="val">' + Math.round(latest.hit_rate * 100) + '%</div><div class="label">Hit rate</div><div class="sub">Błąd &lt; 3 pkt</div></div>';
  h += '<div class="stat-card accent-gold"><div class="val">' + bestPos + ' — ' + bestPosVal + '</div><div class="label">Najlepsza pozycja</div><div class="sub">Najniższy MAE</div></div>';
  h += '<div class="stat-card accent-purple"><div class="val">' + latest.top10_mae + ' pkt</div><div class="label">Top 10 MAE</div><div class="sub">Trafność liderów</div></div>';
  h += '</div>';

  // === MAE TREND CHART (SVG) ===
  if (ACCURACY_HISTORY.length >= 1) {{
    const W = 700, H = 250, PAD = 50, PADR = 30, PADT = 20, PADB = 40;
    const chartW = W - PAD - PADR, chartH = H - PADT - PADB;

    // Zbierz dane
    const rounds = ACCURACY_HISTORY.map(a => a.round);
    const allVals = [];
    ACCURACY_HISTORY.forEach(a => {{
      allVals.push(a.mae);
      ['BR','OBR','POM','NAP'].forEach(p => {{ if (a.mae_by_pos && a.mae_by_pos[p] !== undefined) allVals.push(a.mae_by_pos[p]); }});
    }});
    const minR = Math.min(...rounds), maxR = Math.max(...rounds);
    const maxV = Math.max(...allVals, 1);
    const rangeR = Math.max(maxR - minR, 1);

    const x = r => PAD + ((r - minR) / rangeR) * chartW;
    const y = v => PADT + chartH - (v / maxV) * chartH;

    let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;max-width:700px;height:auto;display:block;margin:20px auto;">';

    // Grid lines
    for (let i = 0; i <= 4; i++) {{
      const yy = PADT + (chartH / 4) * i;
      const val = (maxV * (4 - i) / 4).toFixed(1);
      svg += '<line x1="' + PAD + '" y1="' + yy + '" x2="' + (W - PADR) + '" y2="' + yy + '" stroke="#334155" stroke-width="1"/>';
      svg += '<text x="' + (PAD - 8) + '" y="' + (yy + 4) + '" text-anchor="end" fill="#64748b" font-size="11">' + val + '</text>';
    }}

    // X axis labels
    rounds.forEach(r => {{
      svg += '<text x="' + x(r) + '" y="' + (H - 8) + '" text-anchor="middle" fill="#64748b" font-size="11">K' + r + '</text>';
    }});

    // Position lines
    const posColors = {{BR:'#f59e0b', OBR:'#3b82f6', POM:'#10b981', NAP:'#ef4444'}};
    ['BR','OBR','POM','NAP'].forEach(pos => {{
      const pts = [];
      ACCURACY_HISTORY.forEach(a => {{
        if (a.mae_by_pos && a.mae_by_pos[pos] !== undefined) pts.push({{r: a.round, v: a.mae_by_pos[pos]}});
      }});
      if (pts.length > 1) {{
        const d = pts.map((p, i) => (i === 0 ? 'M' : 'L') + x(p.r) + ',' + y(p.v)).join(' ');
        svg += '<path d="' + d + '" fill="none" stroke="' + posColors[pos] + '" stroke-width="1.5" opacity="0.6"/>';
      }} else if (pts.length === 1) {{
        svg += '<circle cx="' + x(pts[0].r) + '" cy="' + y(pts[0].v) + '" r="4" fill="' + posColors[pos] + '" opacity="0.6"/>';
      }}
    }});

    // Overall MAE line (thick, white)
    if (ACCURACY_HISTORY.length > 1) {{
      const d = ACCURACY_HISTORY.map((a, i) => (i === 0 ? 'M' : 'L') + x(a.round) + ',' + y(a.mae)).join(' ');
      svg += '<path d="' + d + '" fill="none" stroke="#e2e8f0" stroke-width="2.5"/>';
    }}
    // Dots for overall MAE
    ACCURACY_HISTORY.forEach(a => {{
      svg += '<circle cx="' + x(a.round) + '" cy="' + y(a.mae) + '" r="4" fill="#e2e8f0"/>';
    }});

    svg += '</svg>';

    // Legend
    let legend = '<div style="display:flex;gap:16px;justify-content:center;flex-wrap:wrap;margin-bottom:16px;">';
    legend += '<span style="color:#e2e8f0;font-weight:700;font-size:12px;">━━ MAE ogólne</span>';
    Object.entries(posColors).forEach(([p, c]) => {{
      legend += '<span style="color:' + c + ';font-size:12px;">━ ' + p + '</span>';
    }});
    legend += '</div>';

    h += '<div class="section-title" style="margin-top:24px;"><h2>Trend MAE</h2><div class="line"></div></div>';
    h += '<div class="data-table" style="padding:16px;">' + svg + legend + '</div>';
  }}

  // === DETAIL TABLE (latest round) ===
  const details = latest.details || [];
  if (details.length) {{
    h += '<div class="section-title" style="margin-top:24px;"><h2>Szczegóły — Kolejka ' + latest.round + '</h2><div class="line"></div></div>';

    if (!sorts.accuracy) sorts.accuracy = {{col:'abs_error', dir:'asc'}};
    const s = sorts.accuracy;
    let sorted = [...details];
    sorted.forEach(d => {{ d.abs_error = Math.abs(d.error); }});
    sorted.sort((a, b) => {{
      let va = a[s.col], vb = b[s.col];
      if (typeof va === 'string') {{ va = va.toLowerCase(); vb = (vb||'').toLowerCase(); }}
      if (va < vb) return s.dir === 'asc' ? -1 : 1;
      if (va > vb) return s.dir === 'asc' ? 1 : -1;
      return 0;
    }});

    function accArrow(col) {{
      if (s.col !== col) return '';
      return s.dir === 'desc' ? ' ▼' : ' ▲';
    }}

    h += '<div class="data-table"><table><thead><tr>';
    h += '<th class="text-left sortable" data-tab="accuracy" data-col="name">Zawodnik' + accArrow('name') + '</th>';
    h += '<th class="text-center sortable" data-tab="accuracy" data-col="position">Poz' + accArrow('position') + '</th>';
    h += '<th class="text-left sortable" data-tab="accuracy" data-col="team">Drużyna' + accArrow('team') + '</th>';
    h += '<th class="text-right sortable" data-tab="accuracy" data-col="predicted">Prognoza' + accArrow('predicted') + '</th>';
    h += '<th class="text-right sortable" data-tab="accuracy" data-col="actual">Rzeczywistość' + accArrow('actual') + '</th>';
    h += '<th class="text-right sortable" data-tab="accuracy" data-col="abs_error">Błąd' + accArrow('abs_error') + '</th>';
    h += '</tr></thead><tbody>';

    sorted.forEach(d => {{
      const absErr = Math.abs(d.error);
      let errColor = '#ef4444';
      if (absErr < 2) errColor = '#10b981';
      else if (absErr < 4) errColor = '#94a3b8';

      const posClass = 'pos-' + (d.position || '');
      h += '<tr>';
      h += '<td class="text-left">' + (d.name || '') + '</td>';
      h += '<td class="text-center"><span class="pos-badge ' + posClass + '">' + (d.position || '') + '</span></td>';
      h += '<td class="text-left c-muted">' + (d.team || '') + '</td>';
      h += '<td class="text-right">' + (d.predicted != null ? d.predicted.toFixed(1) : '—') + '</td>';
      h += '<td class="text-right">' + (d.actual != null ? d.actual : '—') + '</td>';
      h += '<td class="text-right" style="color:' + errColor + ';font-weight:700;">' + absErr.toFixed(1) + '</td>';
      h += '</tr>';
    }});

    h += '</tbody></table></div>';
  }}

  // === AUTO-TUNING SECTION ===
  // Sekcja pokazuje status i wyniki auto-tunera parametrów predictora
  h += '<div class="section-title" style="margin-top:32px;"><h2>🔧 Auto-tuning</h2><div class="line"></div></div>';
  h += '<div class="data-table" style="padding:20px;">';

  if (!TUNED_PARAMS) {{
    // Tuning jeszcze nie miał wystarczająco danych — zbieramy historię
    const totalRounds = ACCURACY_HISTORY ? ACCURACY_HISTORY.length : 0;
    h += '<div style="text-align:center;padding:16px 0;">';
    h += '<div style="font-size:32px;margin-bottom:8px;">⏳</div>';
    h += '<div style="color:#94a3b8;font-size:14px;">Zbiera dane (' + totalRounds + '/4 kolejek)</div>';
    h += '<div style="color:#64748b;font-size:12px;margin-top:4px;">Auto-tuning uruchomi się automatycznie po zebraniu min. 4 kolejek historii trafności</div>';
    h += '</div>';
  }} else {{
    // Tuning został wykonany — pokazuj wyniki
    const tp = TUNED_PARAMS;

    // Domyślne wartości predictora (przed tuningiem)
    const defaults = {{
      decay: 0.85,
      fdr_strength: 1.0,
      home_away_bonus: 0.05,
    }};

    // Status: aktywny
    h += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;">';
    h += '<span style="background:#10b981;color:#fff;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:700;">✅ Aktywny</span>';
    h += '<span style="color:#94a3b8;font-size:13px;">' + tp.rounds_used + ' kolejek · ostatni tuning: ' + (tp.last_tuned || '—') + '</span>';
    h += '</div>';

    // Tabela porównawcza parametrów
    h += '<table style="width:100%;border-collapse:collapse;margin-bottom:20px;">';
    h += '<thead><tr>';
    h += '<th style="text-align:left;padding:8px 12px;border-bottom:1px solid #334155;color:#64748b;font-size:12px;font-weight:600;">PARAMETR</th>';
    h += '<th style="text-align:right;padding:8px 12px;border-bottom:1px solid #334155;color:#64748b;font-size:12px;font-weight:600;">DOMYŚLNA</th>';
    h += '<th style="text-align:right;padding:8px 12px;border-bottom:1px solid #334155;color:#64748b;font-size:12px;font-weight:600;">WYTUNOWANA</th>';
    h += '<th style="text-align:right;padding:8px 12px;border-bottom:1px solid #334155;color:#64748b;font-size:12px;font-weight:600;">ZMIANA</th>';
    h += '</tr></thead><tbody>';

    function tuneRow(label, key, fmt) {{
      const defVal = defaults[key];
      const tunedVal = tp[key];
      if (tunedVal === undefined || tunedVal === null) return '';
      const diff = tunedVal - defVal;
      const diffStr = diff > 0.001 ? '+' + fmt(diff) : diff < -0.001 ? fmt(diff) : '—';
      const diffColor = Math.abs(diff) > 0.001 ? '#f59e0b' : '#64748b';
      return '<tr>'
        + '<td style="padding:8px 12px;color:#e2e8f0;font-size:13px;">' + label + '</td>'
        + '<td style="text-align:right;padding:8px 12px;color:#64748b;font-size:13px;">' + fmt(defVal) + '</td>'
        + '<td style="text-align:right;padding:8px 12px;color:#e2e8f0;font-weight:700;font-size:13px;">' + fmt(tunedVal) + '</td>'
        + '<td style="text-align:right;padding:8px 12px;color:' + diffColor + ';font-size:13px;">' + diffStr + '</td>'
        + '</tr>';
    }}

    const f2 = v => (Math.round(v * 100) / 100).toFixed(2);
    h += tuneRow('Decay (zanik wag)', 'decay', f2);
    h += tuneRow('FDR Strength (siła FDR)', 'fdr_strength', f2);
    h += tuneRow('Home/Away Bonus', 'home_away_bonus', f2);

    h += '</tbody></table>';

    // Poprawa MAE
    if (tp.mae_before != null && tp.mae_after != null) {{
      const improved = tp.mae_after < tp.mae_before;
      const arrow = improved ? '↓' : '↑';
      const color = improved ? '#10b981' : '#ef4444';
      const sign = improved ? '' : '+';
      h += '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">';
      h += '<div style="background:#1e293b;border-radius:8px;padding:12px 20px;">';
      h += '<div style="color:#64748b;font-size:11px;font-weight:600;margin-bottom:4px;">POPRAWA MAE</div>';
      h += '<div style="font-size:18px;font-weight:700;">';
      h += '<span style="color:#94a3b8;">' + tp.mae_before.toFixed(1) + '</span>';
      h += ' <span style="color:#64748b;font-size:14px;">→</span> ';
      h += '<span style="color:#e2e8f0;">' + tp.mae_after.toFixed(1) + '</span>';
      const pct = tp.improvement_pct != null ? tp.improvement_pct : 0;
      h += ' <span style="color:' + color + ';font-size:14px;">(' + arrow + Math.abs(pct).toFixed(1) + '%)</span>';
      h += '</div>';
      h += '</div>';
      h += '</div>';
    }}
  }}

  h += '</div>';  // end data-table

  return h;
}}

// ========== SEASON TRACKER ==========
// Stan widoku sezonu — przechowywany poza renderSeason(), bo render() czyści DOM
let seasonView = 'positions';  // 'positions' lub 'points'
let seasonFilter = 'all';     // 'all', 'top5', 'bottom5'
let seasonHidden = {{}};       // {{teamName: true}} — ukryte linie

// Paleta kolorów czytelna na ciemnym tle
const SEASON_COLORS = [
  '#22d3ee','#f59e0b','#10b981','#a78bfa','#f472b6','#fb923c',
  '#38bdf8','#facc15','#4ade80','#c084fc','#fb7185','#fdba74',
  '#67e8f9','#fde047','#86efac','#d8b4fe','#fda4af','#fed7aa',
];

function renderSeason() {{
  const rounds = (LEAGUE_HISTORY.rounds || []);
  if (rounds.length < 1) {{
    return '<div class="empty-msg">Zbieranie danych — wykres pojawi się po 2+ kolejkach</div>';
  }}

  // Zbierz wszystkie drużyny (unikalne nazwy)
  const teamSet = new Set();
  rounds.forEach(r => (r.standings || []).forEach(s => teamSet.add(s.team)));
  const allTeams = [...teamSet];

  // Przypisz kolory
  const teamColor = {{}};
  allTeams.forEach((t, i) => teamColor[t] = SEASON_COLORS[i % SEASON_COLORS.length]);

  // Ostatnia kolejka — aktualne pozycje do filtrowania
  const lastRound = rounds[rounds.length - 1];
  const lastStandings = {{}};
  (lastRound.standings || []).forEach(s => lastStandings[s.team] = s);

  // Filtruj drużyny wg przełącznika
  let visibleTeams = allTeams;
  if (seasonFilter === 'top5') {{
    visibleTeams = allTeams.filter(t => lastStandings[t] && lastStandings[t].position <= 5);
  }} else if (seasonFilter === 'bottom5') {{
    const sorted = allTeams.filter(t => lastStandings[t]).sort((a, b) => lastStandings[b].position - lastStandings[a].position);
    visibleTeams = sorted.slice(0, 5);
  }}

  // Wymiary wykresu SVG
  const marginL = 44, marginR = 20, marginT = 20, marginB = 36;
  const numRounds = rounds.length;
  // Szerokość punktu danych: min 60px, dopasuj do ekranu
  const ptW = Math.max(60, Math.min(100, (900 - marginL - marginR) / Math.max(numRounds - 1, 1)));
  const chartW = marginL + marginR + ptW * Math.max(numRounds - 1, 1);
  const chartH = 320;
  const plotW = chartW - marginL - marginR;
  const plotH = chartH - marginT - marginB;

  // Zakres osi Y
  let yMin, yMax;
  if (seasonView === 'positions') {{
    // Pozycje: 1..maxPos (odwrócone — 1 na górze)
    const maxPos = allTeams.length || 1;
    yMin = 1;
    yMax = maxPos;
  }} else {{
    // Punkty łącznie: 0..max
    let maxPts = 0;
    rounds.forEach(r => (r.standings || []).forEach(s => {{ if (s.total_points > maxPts) maxPts = s.total_points; }}));
    yMin = 0;
    yMax = maxPts || 100;
  }}

  // Funkcje mapowania
  const xScale = (idx) => marginL + (numRounds > 1 ? idx / (numRounds - 1) * plotW : plotW / 2);
  const yScale = (val) => {{
    if (seasonView === 'positions') {{
      // Odwrócona oś — pozycja 1 na górze
      return marginT + (val - yMin) / (yMax - yMin) * plotH;
    }} else {{
      // Punkty rosnąco w górę
      return marginT + plotH - (val - yMin) / (yMax - yMin || 1) * plotH;
    }}
  }};

  // Buduj SVG
  let svg = '<svg width="' + chartW + '" height="' + chartH + '" xmlns="http://www.w3.org/2000/svg">';

  // Siatka i etykiety osi Y
  const yTicks = seasonView === 'positions'
    ? Array.from({{length: Math.min(yMax, 10)}}, (_, i) => i + 1)
    : (() => {{
        const step = Math.ceil(yMax / 6 / 10) * 10 || 10;
        const ticks = [];
        for (let v = 0; v <= yMax; v += step) ticks.push(v);
        return ticks;
      }})();

  yTicks.forEach(v => {{
    const y = yScale(v);
    svg += '<line x1="' + marginL + '" y1="' + y + '" x2="' + (chartW - marginR) + '" y2="' + y + '" stroke="#1e293b" stroke-width="1"/>';
    svg += '<text x="' + (marginL - 8) + '" y="' + (y + 4) + '" text-anchor="end" fill="#64748b" font-size="11" font-family="DM Sans,sans-serif">' + v + '</text>';
  }});

  // Etykiety osi X — numery kolejek
  rounds.forEach((r, i) => {{
    const x = xScale(i);
    svg += '<text x="' + x + '" y="' + (chartH - 8) + '" text-anchor="middle" fill="#64748b" font-size="11" font-family="DM Sans,sans-serif">' + r.round + '</text>';
  }});

  // Linie drużyn
  // Budujemy dane per drużyna: [{{x, y, round, team, position, total_points}}]
  const teamLines = {{}};
  visibleTeams.forEach(team => {{
    teamLines[team] = [];
    rounds.forEach((r, ri) => {{
      const s = (r.standings || []).find(s => s.team === team);
      if (s) {{
        const val = seasonView === 'positions' ? s.position : s.total_points;
        teamLines[team].push({{
          x: xScale(ri), y: yScale(val),
          round: r.round, team: team,
          position: s.position, total_points: s.total_points, round_points: s.round_points || 0,
        }});
      }}
    }});
  }});

  // Rysuj linie i punkty
  visibleTeams.forEach(team => {{
    if (seasonHidden[team]) return;
    const pts = teamLines[team];
    if (pts.length < 1) return;
    const color = teamColor[team];
    // Grubsza linia dla własnej drużyny (slug zawierający 'tokusatsu' lub pozycja 1)
    const isOwn = team.toLowerCase().includes('tokusatsu');
    const sw = isOwn ? 3 : 1.5;
    const opacity = isOwn ? 1 : 0.85;

    // Polyline
    const points = pts.map(p => p.x + ',' + p.y).join(' ');
    svg += '<polyline points="' + points + '" fill="none" stroke="' + color + '" stroke-width="' + sw + '" stroke-opacity="' + opacity + '" stroke-linejoin="round" stroke-linecap="round"/>';

    // Punkty danych (klikalne kółka)
    pts.forEach((p, pi) => {{
      svg += '<circle cx="' + p.x + '" cy="' + p.y + '" r="' + (isOwn ? 5 : 3.5) + '" fill="' + color + '" stroke="#0f172a" stroke-width="1.5"'
        + ' data-season-pt="1"'
        + ' data-tip="Kolejka ' + p.round + ': ' + p.team + ' — poz. ' + p.position + ' (' + p.total_points + ' pkt)"'
        + ' style="cursor:pointer" />';
    }});
  }});

  svg += '</svg>';

  // === Buduj HTML ===
  let h = '<div class="section-title"><span style="font-size:22px">📈</span><h2>Sezon — historia ligi</h2><div class="line"></div></div>';

  // Kontrolki
  h += '<div class="season-controls">';
  h += '<button class="season-btn' + (seasonView === 'positions' ? ' active' : '') + '" data-sview="positions">Pozycje</button>';
  h += '<button class="season-btn' + (seasonView === 'points' ? ' active' : '') + '" data-sview="points">Punkty łącznie</button>';
  h += '<span style="width:16px"></span>';
  h += '<button class="season-btn' + (seasonFilter === 'all' ? ' active' : '') + '" data-sfilter="all">Wszystkie</button>';
  h += '<button class="season-btn' + (seasonFilter === 'top5' ? ' active' : '') + '" data-sfilter="top5">Top 5</button>';
  h += '<button class="season-btn' + (seasonFilter === 'bottom5' ? ' active' : '') + '" data-sfilter="bottom5">Dolne 5</button>';
  h += '</div>';

  // Wykres
  h += '<div class="season-wrap">';
  h += '<div class="season-chart" id="seasonChart">';
  h += svg;
  h += '<div class="season-tooltip" id="seasonTooltip"></div>';
  h += '</div>';

  // Legenda
  h += '<div class="season-legend">';
  visibleTeams.forEach(team => {{
    const color = teamColor[team];
    const cls = seasonHidden[team] ? ' hidden' : '';
    h += '<span class="season-legend-item' + cls + '" data-steam="' + team.replace(/"/g, '&quot;') + '">';
    h += '<span class="swatch" style="background:' + color + '"></span>' + team;
    h += '</span>';
  }});
  h += '</div>';
  h += '</div>';  // season-wrap

  // === Tabela szczegółów ===
  if (lastRound && lastRound.standings && lastRound.standings.length > 0) {{
    h += '<div class="season-table"><div class="data-table"><table>';
    h += '<thead><tr>';
    h += '<th class="text-left">Drużyna</th><th class="text-center">Poz.</th><th class="text-right">Punkty</th>';
    h += '<th class="text-right">Średnia/kol.</th><th class="text-right">Najlepsza kol.</th><th class="text-right">Najgorsza kol.</th>';
    h += '<th class="text-center">Trend</th>';
    h += '</tr></thead><tbody>';

    // Oblicz statystyki per drużyna
    const teamStats = [];
    allTeams.forEach(team => {{
      const roundData = [];
      rounds.forEach(r => {{
        const s = (r.standings || []).find(s => s.team === team);
        if (s) roundData.push({{ round: r.round, pts: s.round_points || 0, pos: s.position, total: s.total_points }});
      }});
      if (roundData.length === 0) return;

      const last = roundData[roundData.length - 1];
      const totalPts = last.total;
      const avg = roundData.length > 0 ? (totalPts / roundData.length) : 0;

      // Najlepsza/najgorsza kolejka (po round_points)
      let bestRound = roundData[0], worstRound = roundData[0];
      roundData.forEach(rd => {{
        if (rd.pts > bestRound.pts) bestRound = rd;
        if (rd.pts < worstRound.pts) worstRound = rd;
      }});

      // Trend — zmiana pozycji w ostatnich 3 kolejkach
      let trend = 0;
      if (roundData.length >= 2) {{
        const recent = roundData.slice(-3);
        trend = recent[0].pos - recent[recent.length - 1].pos;
      }}

      teamStats.push({{
        team, position: last.pos, totalPts, avg,
        bestRound: bestRound.pts + ' (K' + bestRound.round + ')',
        worstRound: worstRound.pts + ' (K' + worstRound.round + ')',
        trend,
      }});
    }});

    // Sortuj po pozycji
    teamStats.sort((a, b) => a.position - b.position);

    teamStats.forEach(ts => {{
      const trendHtml = ts.trend > 0
        ? '<span class="trend-up">▲' + ts.trend + '</span>'
        : ts.trend < 0
          ? '<span class="trend-down">▼' + Math.abs(ts.trend) + '</span>'
          : '<span class="trend-flat">●</span>';
      const color = teamColor[ts.team] || '#e2e8f0';
      h += '<tr>';
      h += '<td class="text-left" style="color:' + color + ';font-weight:600">' + ts.team + '</td>';
      h += '<td class="text-center fw-700">' + ts.position + '</td>';
      h += '<td class="text-right fw-600">' + ts.totalPts + '</td>';
      h += '<td class="text-right">' + ts.avg.toFixed(1) + '</td>';
      h += '<td class="text-right" style="color:#10b981">' + ts.bestRound + '</td>';
      h += '<td class="text-right" style="color:#ef4444">' + ts.worstRound + '</td>';
      h += '<td class="text-center">' + trendHtml + '</td>';
      h += '</tr>';
    }});

    h += '</tbody></table></div></div>';
  }}

  return h;
}}

function attachSeasonHandlers() {{
  // Przełączniki widoku i filtra
  document.querySelectorAll('[data-sview]').forEach(btn => {{
    btn.onclick = () => {{ seasonView = btn.dataset.sview; render(); }};
  }});
  document.querySelectorAll('[data-sfilter]').forEach(btn => {{
    btn.onclick = () => {{ seasonFilter = btn.dataset.sfilter; render(); }};
  }});
  // Legenda — klik ukrywa/pokazuje linię
  document.querySelectorAll('.season-legend-item').forEach(item => {{
    item.onclick = () => {{
      const team = item.dataset.steam;
      seasonHidden[team] = !seasonHidden[team];
      render();
    }};
  }});
  // Tooltip na punktach wykresu
  const chart = document.getElementById('seasonChart');
  const tip = document.getElementById('seasonTooltip');
  if (chart && tip) {{
    chart.addEventListener('mouseover', (e) => {{
      const el = e.target.closest('[data-season-pt]');
      if (el) {{
        tip.textContent = el.dataset.tip;
        tip.classList.add('visible');
        const rect = chart.getBoundingClientRect();
        const cx = parseFloat(el.getAttribute('cx'));
        const cy = parseFloat(el.getAttribute('cy'));
        tip.style.left = (cx + 12) + 'px';
        tip.style.top = (cy - 10) + 'px';
      }}
    }});
    chart.addEventListener('mouseout', (e) => {{
      if (e.target.closest('[data-season-pt]')) {{
        tip.classList.remove('visible');
      }}
    }});
  }}
}}

// ============================================================
// 📖 PORÓWNYWARKA ZAWODNIKÓW
// Pozwala wybrać 2-3 graczy i porównać ich obok siebie:
// karty, tabela statystyk, wykres formy (SVG), siatka FDR.
// ============================================================

// 📖 Kolory przypisane do pozycji w kartach — stałe, czytelne
const CMP_COLORS = ['#22d3ee', '#fbbf24', '#a78bfa'];

function cmpAddPlayer(id) {{
  if (cmpSelected.length >= 3) return;
  if (cmpSelected.includes(id)) return;
  cmpSelected.push(id);
  render();
}}
function cmpRemovePlayer(id) {{
  cmpSelected = cmpSelected.filter(x => x !== id);
  render();
}}
function cmpClear() {{
  cmpSelected = [];
  render();
}}

function renderComparison() {{
  // 📖 Łączymy dane z PLAYERS i PREDICTIONS — PLAYERS mają formę i cenę,
  // PREDICTIONS mają prognozę, FDR, średnią minut itp.
  const allPlayers = PLAYERS.map(p => {{
    const pred = PREDICTIONS.find(pr => pr.player_id === p.player_id) || {{}};
    return {{...p, ...pred, _src: p}};
  }});

  let h = '<div class="section-title"><span style="font-size:22px">⚖️</span><h2>Porównanie zawodników</h2><div class="line"></div></div>';

  // --- Pole wyszukiwania ---
  h += '<div class="cmp-search-wrap">';
  h += '<div class="cmp-search-box">';
  h += '<input class="cmp-search-input" id="cmpSearchInput" type="text" placeholder="Wpisz imię zawodnika… (min 2, max 3)" autocomplete="off">';
  h += '<div class="cmp-autocomplete" id="cmpAutocomplete"></div>';
  h += '</div>';
  h += '<button class="cmp-clear-btn" onclick="cmpClear()">Wyczyść</button>';
  h += '</div>';

  // --- Chipy wybranych zawodników ---
  if (cmpSelected.length) {{
    h += '<div class="cmp-selected-chips">';
    cmpSelected.forEach((id, i) => {{
      const p = allPlayers.find(x => x.player_id === id);
      if (!p) return;
      const pk = POS_ID[p.position] || p.position || '';
      h += '<div class="cmp-chip" style="border-color:'+CMP_COLORS[i]+'">';
      h += posBadge(p.position) + ' <strong>' + p.name + '</strong> <span style="color:#64748b;font-size:11px">(' + p.team + ')</span>';
      h += '<button class="cmp-chip-remove" onclick="cmpRemovePlayer('+id+')">×</button>';
      h += '</div>';
    }});
    h += '</div>';
  }}

  // Jeśli mniej niż 2 zawodników — pokaż instrukcję
  if (cmpSelected.length < 2) {{
    h += '<div class="cmp-empty"><div class="cmp-empty-icon">⚖️</div>';
    h += 'Wybierz <strong>2 lub 3</strong> zawodników aby zobaczyć porównanie.<br>';
    h += '<span style="font-size:13px;color:#475569">Zacznij wpisywać nazwisko w polu powyżej.</span></div>';
    return h;
  }}

  // --- Zbierz dane wybranych graczy ---
  const selected = cmpSelected.map((id, i) => {{
    const p = allPlayers.find(x => x.player_id === id);
    return p ? {{...p, _color: CMP_COLORS[i]}} : null;
  }}).filter(Boolean);

  if (selected.length < 2) return h + '<div class="cmp-empty">Nie znaleziono danych dla wybranych zawodników.</div>';

  // === SEKCJA A: Karty zawodników ===
  h += '<div class="cmp-cards">';
  selected.forEach((p, i) => {{
    const pk = POS_ID[p.position] || p.position || '';
    const played = (p.form || []).filter(f => f.p);
    const formAvg = played.length ? (played.reduce((s,f) => s + f.pts, 0) / played.length).toFixed(1) : '—';
    const predPts = p.predicted_points != null ? p.predicted_points.toFixed(1) : '—';
    // 📖 Następny rywal z FDR — szukamy w FDR_DATA
    const teamFdr = (FDR_DATA.teams || []).find(t => t.name === p.team);
    const nextFix = teamFdr ? (teamFdr.fixtures || [])[0] : null;
    const nextOpp = nextFix ? nextFix.opponent_short : (p.next_opponent || '—');
    const nextFdrAtk = nextFix ? nextFix.atk : (p.fdr_atk_opponent || 3);
    const nextFdrDef = nextFix ? nextFix.def : (p.fdr_def_opponent || 3);
    // 📖 FDR uśredniony do jednej wartości (zależy od pozycji)
    const isAttacker = (pk === 'NAP' || pk === 'POM');
    const mainFdr = isAttacker ? nextFdrDef : nextFdrAtk;
    const fdrC = FDR_COLORS[mainFdr] || FDR_COLORS[3];
    const isHome = nextFix ? nextFix.home : p.is_home;
    const haLabel = isHome ? '(D)' : '(W)';

    h += '<div class="cmp-card" style="border-top-color:'+CMP_COLORS[i]+'">';
    h += '<div class="cmp-card-name">' + p.name + '</div>';
    h += '<div class="cmp-card-meta">' + posBadge(p.position) + ' · ' + p.team + '</div>';
    h += '<div class="cmp-card-stats">';
    h += '<div class="cmp-card-stat"><span class="cmp-stat-label">Cena</span><span class="cmp-stat-val">' + (p.price || 0).toFixed(1) + 'M</span></div>';
    h += '<div class="cmp-card-stat"><span class="cmp-stat-label">Łączne pkt</span><span class="cmp-stat-val">' + (p.total_points || 0) + '</span></div>';
    h += '<div class="cmp-card-stat"><span class="cmp-stat-label">Średnia (forma)</span><span class="cmp-stat-val">' + formAvg + '</span></div>';
    h += '<div class="cmp-card-stat"><span class="cmp-stat-label">Prognoza</span><span class="cmp-stat-val" style="color:#22d3ee">' + predPts + '</span></div>';
    h += '<div class="cmp-card-stat"><span class="cmp-stat-label">Następny rywal</span><span class="cmp-stat-val">';
    h += '<span class="cmp-fdr-cell" style="background:'+fdrC.bg+';color:'+fdrC.fg+'">' + nextOpp + ' <span class="cmp-fdr-ha">' + haLabel + '</span></span>';
    h += '</span></div>';
    h += '</div></div>';
  }});
  h += '</div>';

  // === SEKCJA B: Tabela statystyk ===
  // 📖 Definicje wierszy: [label, getter, mode]
  // mode: 'higher'=wyższe lepsze, 'lower'=niższe lepsze, 'neutral'=bez podświetlenia
  const rows = [
    ['Łączne pkt', p => p.total_points || 0, 'higher'],
    ['Cena', p => p.price || 0, 'lower'],
    ['Pkt/Cena', p => p.points_per_price || 0, 'higher'],
    ['Średnia (forma)', p => {{ const played = (p.form||[]).filter(f=>f.p); return played.length ? played.reduce((s,f)=>s+f.pts,0)/played.length : 0; }}, 'higher'],
    ['Prognoza', p => p.predicted_points || 0, 'higher'],
    ['Śr. minut', p => p.avg_minutes || 0, 'higher'],
    ['Popularność', p => parseFloat((p.popularity_pct||'0').replace('%','')) || 0, 'neutral'],
    ['Pewność prognozy', p => ({{high:3,medium:2,low:1}})[p.confidence] || 0, 'higher'],
  ];

  h += '<div class="cmp-table"><table>';
  h += '<thead><tr><th style="text-align:left">Statystyka</th>';
  selected.forEach((p,i) => {{ h += '<th style="color:'+CMP_COLORS[i]+'">' + p.name.split(' ').pop() + '</th>'; }});
  h += '</tr></thead><tbody>';

  rows.forEach(([label, getter, mode]) => {{
    const vals = selected.map(p => getter(p));
    // 📖 Znajdź najlepszą wartość — zależy od mode
    let bestIdx = -1;
    if (mode !== 'neutral') {{
      let best = mode === 'lower' ? Infinity : -Infinity;
      vals.forEach((v, i) => {{
        if ((mode === 'higher' && v > best) || (mode === 'lower' && v < best)) {{ best = v; bestIdx = i; }}
      }});
      // Jeśli remis — podświetl wszystkie z najlepszą wartością
    }}
    h += '<tr><td>' + label + '</td>';
    vals.forEach((v, i) => {{
      let display = v;
      // Formatowanie
      if (label === 'Cena') display = v.toFixed(1) + 'M';
      else if (label === 'Pkt/Cena' || label === 'Średnia (forma)' || label === 'Prognoza' || label === 'Śr. minut') display = v.toFixed(1);
      else if (label === 'Popularność') display = v.toFixed(0) + '%';
      else if (label === 'Pewność prognozy') display = ['—','Low','Medium','High'][v] || '—';
      const isBest = bestIdx !== -1 && v === vals[bestIdx] && mode !== 'neutral';
      h += '<td' + (isBest ? ' class="cmp-best"' : '') + '>' + display + '</td>';
    }});
    h += '</tr>';
  }});
  h += '</tbody></table></div>';

  // === SEKCJA C: Wykres formy (SVG) ===
  // 📖 Zbieramy punkty z formy, rysujemy linie SVG bez zewnętrznych bibliotek
  h += '<div class="cmp-chart-wrap">';
  h += '<div class="cmp-chart-title">📈 Forma — ostatnie kolejki</div>';
  h += '<div class="cmp-chart-legend">';
  selected.forEach((p,i) => {{
    h += '<div class="cmp-chart-legend-item"><span class="cmp-chart-legend-swatch" style="background:'+CMP_COLORS[i]+'"></span>' + p.name.split(' ').pop() + '</div>';
  }});
  h += '</div>';

  // Zbierz wszystkie unikalne kolejki
  const allRounds = new Set();
  selected.forEach(p => (p.form || []).forEach(f => allRounds.add(f.r)));
  const rounds = [...allRounds].sort((a,b) => a - b);

  if (rounds.length >= 2) {{
    const svgW = 500, svgH = 180, padL = 40, padR = 20, padT = 20, padB = 30;
    const chartW = svgW - padL - padR, chartH = svgH - padT - padB;
    let maxPts = 0;
    selected.forEach(p => (p.form||[]).forEach(f => {{ if (f.p && f.pts > maxPts) maxPts = f.pts; }}));
    if (maxPts === 0) maxPts = 10;
    maxPts = Math.ceil(maxPts * 1.15); // 📖 Trochę marginesu na górze

    const xScale = (idx) => padL + (idx / (rounds.length - 1)) * chartW;
    const yScale = (pts) => padT + chartH - (pts / maxPts) * chartH;

    h += '<div class="cmp-chart"><svg viewBox="0 0 '+svgW+' '+svgH+'" preserveAspectRatio="xMidYMid meet">';

    // Siatka Y
    for (let g = 0; g <= 4; g++) {{
      const yVal = Math.round(maxPts / 4 * g);
      const y = yScale(yVal);
      h += '<line x1="'+padL+'" y1="'+y+'" x2="'+(svgW-padR)+'" y2="'+y+'" stroke="#334155" stroke-width="0.5"/>';
      h += '<text x="'+(padL-6)+'" y="'+(y+4)+'" fill="#64748b" font-size="10" text-anchor="end">'+yVal+'</text>';
    }}

    // Etykiety X (numery kolejek)
    rounds.forEach((r, idx) => {{
      h += '<text x="'+xScale(idx)+'" y="'+(svgH-6)+'" fill="#64748b" font-size="10" text-anchor="middle">'+r+'</text>';
    }});

    // Linie per gracz
    selected.forEach((p, pi) => {{
      const form = p.form || [];
      const points = [];
      rounds.forEach((r, idx) => {{
        const f = form.find(ff => ff.r === r);
        if (f && f.p) points.push({{x: xScale(idx), y: yScale(f.pts), pts: f.pts}});
      }});
      if (points.length < 2) return;
      // 📖 Polyline — łączna linia z punktami
      const lineStr = points.map(pt => pt.x+','+pt.y).join(' ');
      h += '<polyline points="'+lineStr+'" fill="none" stroke="'+CMP_COLORS[pi]+'" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>';
      // Kropki
      points.forEach(pt => {{
        h += '<circle cx="'+pt.x+'" cy="'+pt.y+'" r="4" fill="'+CMP_COLORS[pi]+'" stroke="#1e293b" stroke-width="2"/>';
        h += '<text x="'+pt.x+'" y="'+(pt.y-8)+'" fill="'+CMP_COLORS[pi]+'" font-size="9" font-weight="700" text-anchor="middle">'+pt.pts+'</text>';
      }});
    }});

    h += '</svg></div>';
  }} else {{
    h += '<div style="color:#64748b;text-align:center;padding:20px">Za mało danych o formie.</div>';
  }}
  h += '</div>';

  // === SEKCJA D: FDR następne kolejki ===
  const fdrTeams = FDR_DATA.teams || [];
  const fdrGws = FDR_DATA.gameweeks || [];
  if (fdrGws.length) {{
    h += '<div class="cmp-fdr-wrap">';
    h += '<div class="cmp-fdr-title">📅 Trudność najbliższych meczów (FDR)</div>';
    h += '<div class="cmp-fdr-table"><table><thead><tr><th style="text-align:left">Kolejka</th>';
    selected.forEach((p,i) => {{ h += '<th style="color:'+CMP_COLORS[i]+'">' + p.name.split(' ').pop() + ' (' + (fdrTeams.find(t=>t.name===p.team)||{{}}).short + ')</th>'; }});
    h += '</tr></thead><tbody>';

    fdrGws.forEach(gw => {{
      h += '<tr><td style="text-align:left;font-weight:700;color:#94a3b8">' + gw + '</td>';
      selected.forEach((p, pi) => {{
        const teamFdr = fdrTeams.find(t => t.name === p.team);
        const fix = teamFdr ? (teamFdr.fixtures || []).find(f => f.gw === gw) : null;
        if (fix) {{
          const pk = POS_ID[p.position] || p.position || '';
          const isAtk = (pk === 'NAP' || pk === 'POM');
          const mainFdr = isAtk ? fix.def : fix.atk;
          const c = FDR_COLORS[mainFdr] || FDR_COLORS[3];
          const ha = fix.home ? '(D)' : '(W)';
          h += '<td><span class="cmp-fdr-cell" style="background:'+c.bg+';color:'+c.fg+'">' + fix.opponent_short + ' <span class="cmp-fdr-ha">' + ha + '</span></span></td>';
        }} else {{
          h += '<td style="color:#475569">—</td>';
        }}
      }});
      h += '</tr>';
    }});
    h += '</tbody></table></div></div>';
  }}

  return h;
}}

function render() {{
  document.getElementById('tab-players').innerHTML = tab === 'players' ? renderPlayers() : '';
  document.getElementById('tab-teams').innerHTML = tab === 'teams' ? renderTeams() : '';
  const ftEl = document.getElementById('tab-fixtures');
  if (ftEl) ftEl.innerHTML = tab === 'fixtures' ? renderFixtures() : '';
  const trEl = document.getElementById('tab-transfers');
  if (trEl) trEl.innerHTML = tab === 'transfers' ? renderTransfers() : '';
  const prEl = document.getElementById('tab-predictions');
  if (prEl) prEl.innerHTML = tab === 'predictions' ? renderPredictions() : '';
  const acEl = document.getElementById('tab-accuracy');
  if (acEl) acEl.innerHTML = tab === 'accuracy' ? renderAccuracy() : '';
  const seEl = document.getElementById('tab-season');
  if (seEl) seEl.innerHTML = tab === 'season' ? renderSeason() : '';
  const cmpEl = document.getElementById('tab-compare');
  if (cmpEl) cmpEl.innerHTML = tab === 'compare' ? renderComparison() : '';
  document.querySelectorAll('.tab-content').forEach(el => el.classList.toggle('active', el.id === 'tab-'+tab));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.pos-btn').forEach(b => b.classList.toggle('active', b.dataset.pos === pos));
  document.querySelectorAll('.scope-btn:not(.fdr-sort-btn)').forEach(b => b.classList.toggle('active', b.dataset.scope === scope));
  const fr = document.querySelector('.filters-row');
  if (fr) fr.style.display = (tab === 'players') ? 'flex' : 'none';
  // Transfers position filter handlers
  document.querySelectorAll('.tr-pos-btn').forEach(b => {{
    b.classList.toggle('active', b.dataset.trpos === trPos);
    b.onclick = () => {{ trPos = b.dataset.trpos; render(); }};
  }});
  // Predictions position filter handlers
  document.querySelectorAll('.pred-pos-btn').forEach(b => {{
    b.classList.toggle('active', b.dataset.predpos === predPos);
    b.onclick = () => {{ predPos = b.dataset.predpos; render(); }};
  }});
  // Sortable click handlers
  document.querySelectorAll('.sortable').forEach(th => {{
    th.onclick = () => {{
      const t = th.dataset.tab, col = th.dataset.col;
      if (sorts[t].col === col) sorts[t].dir = sorts[t].dir === 'desc' ? 'asc' : 'desc';
      else {{ sorts[t].col = col; sorts[t].dir = 'desc'; }}
      render();
    }};
  }});
  // Attach detail click handlers (form + roster)
  attachDetailClicks();
  // Season tab handlers (tooltip, legend, view toggle)
  if (tab === 'season') attachSeasonHandlers();
  // Team row click handlers (expand/collapse squad)
  document.querySelectorAll('tr[data-teamslug]').forEach(el => {{
    el.onclick = (e) => {{
      if (e.target.closest('a')) return;
      const slug = el.dataset.teamslug;
      selectedTeam = selectedTeam === slug ? '' : slug;
      render();
    }};
  }});
  // Duet row click handlers (expand/collapse)
  document.querySelectorAll('tr[data-duetname]').forEach(el => {{
    el.onclick = () => {{
      const name = decodeURIComponent(el.dataset.duetname);
      selectedDuet = selectedDuet === name ? '' : name;
      render();
    }};
  }});
  // View toggle (Drużyny / Duety)
  document.querySelectorAll('.view-btn').forEach(btn => {{
    btn.onclick = () => {{
      currentTeamsView = btn.dataset.view;
      render();
    }};
  }});
  // FDR sort handlers
  document.querySelectorAll('.fdr-sort-btn').forEach(b => {{
    b.classList.toggle('active', b.dataset.fdrsort === fdrSort);
    b.onclick = () => {{ fdrSort = b.dataset.fdrsort; render(); }};
  }});
  // FDR team click → show stats modal
  document.querySelectorAll('.fdr-team-click').forEach(td => {{
    td.onclick = () => {{
      const teams = window._fdrTeams || [];
      const t = teams[parseInt(td.dataset.fdrteam)];
      if (t) fdrShowModal(t.name);
    }};
  }});
  // Fixture Planner handlers
  const fpFrom = document.querySelector('.fp-gw-from');
  const fpTo = document.querySelector('.fp-gw-to');
  if (fpFrom) fpFrom.onchange = () => {{ fpGwFrom = parseInt(fpFrom.value); render(); }};
  if (fpTo) fpTo.onchange = () => {{ fpGwTo = parseInt(fpTo.value); render(); }};
  document.querySelectorAll('.fp-mode-btn').forEach(b => {{
    b.onclick = () => {{ fpMode = b.dataset.fpmode; render(); }};
  }});
  document.querySelectorAll('.fp-sort').forEach(th => {{
    th.onclick = () => {{
      const col = th.dataset.fpcol;
      if (fpSortCol === col) fpSortDir = fpSortDir === 'asc' ? 'desc' : 'asc';
      else {{ fpSortCol = col; fpSortDir = col === 'team' ? 'asc' : 'asc'; }}
      render();
    }};
  }});
  // 📖 Klik na drużynę w planerze — zaznacza do rotation pair (max 2)
  document.querySelectorAll('.fp-team-cell').forEach(td => {{
    td.onclick = () => {{
      const name = td.dataset.fpteam;
      const idx = fpSelected.indexOf(name);
      if (idx >= 0) {{ fpSelected.splice(idx, 1); }}
      else if (fpSelected.length < 2) {{ fpSelected.push(name); }}
      else {{ fpSelected = [name]; }}
      render();
    }};
  }});
  // 📖 Autouzupełnianie w porównywarce — nasłuchuje na wpisywanie tekstu
  // i wyświetla listę pasujących zawodników
  const cmpInput = document.getElementById('cmpSearchInput');
  const cmpAc = document.getElementById('cmpAutocomplete');
  if (cmpInput && cmpAc) {{
    cmpInput.value = '';
    cmpInput.oninput = () => {{
      const q = cmpInput.value.trim().toLowerCase();
      if (q.length < 2) {{ cmpAc.classList.remove('visible'); cmpAc.innerHTML = ''; return; }}
      // 📖 Szukamy w PLAYERS — filtrujemy po nazwisku, drużynie
      const matches = PLAYERS.filter(p =>
        !cmpSelected.includes(p.player_id) &&
        (p.name.toLowerCase().includes(q) || p.team.toLowerCase().includes(q))
      ).slice(0, 8);
      if (!matches.length) {{ cmpAc.classList.remove('visible'); cmpAc.innerHTML = ''; return; }}
      let acH = '';
      matches.forEach(p => {{
        acH += '<div class="cmp-ac-item" data-cmpid="'+p.player_id+'">';
        acH += posBadge(p.position) + ' <strong>' + p.name + '</strong>';
        acH += '<span class="cmp-ac-team">' + p.team + ' · ' + (p.price||0).toFixed(1) + 'M · ' + (p.total_points||0) + 'pkt</span>';
        acH += '</div>';
      }});
      cmpAc.innerHTML = acH;
      cmpAc.classList.add('visible');
      // Klik na element listy
      cmpAc.querySelectorAll('.cmp-ac-item').forEach(el => {{
        el.onclick = () => {{
          cmpAddPlayer(parseInt(el.dataset.cmpid));
          cmpAc.classList.remove('visible');
          cmpAc.innerHTML = '';
        }};
      }});
    }};
    // Zamknij autocomplete po kliknięciu poza
    document.addEventListener('click', (e) => {{
      if (!e.target.closest('.cmp-search-box')) {{
        cmpAc.classList.remove('visible');
      }}
    }});
  }}
}}

document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => {{ tab = t.dataset.tab; render(); }}));
document.querySelectorAll('.pos-btn').forEach(b => b.addEventListener('click', () => {{ pos = b.dataset.pos; render(); }}));
document.querySelectorAll('.scope-btn').forEach(b => b.addEventListener('click', () => {{ scope = b.dataset.scope; render(); }}));
render();
</script>
</body>
</html>'''

    # Theme toggle JS - z <script> bo wstawiamy w miejsce placeholderu
    theme_js = """<script>
    // Toggle z localStorage
    function toggleTheme() {
      const html = document.documentElement;
      const btn = document.querySelector('.theme-toggle');
      const isLight = html.classList.contains('theme-fantasy');
      if (isLight) {
        html.classList.remove('theme-fantasy');
        btn.textContent = '☀️ Light';
        localStorage.setItem('theme', 'dark');
      } else {
        html.classList.add('theme-fantasy');
        btn.textContent = '🌙 Dark';
        localStorage.setItem('theme', 'light');
      }
    }
    // Przywróć motyw po załadowaniu
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
    </script>"""

    # Wstaw theme JS w placeholder (replace all occurrences)
    html = html.replace('// __JS_PLACEHOLDER__', theme_js, 1)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📊 Dashboard: {filename}")
