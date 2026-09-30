"""dashboard.py - generowanie dashboardu HTML.

generate_dashboard_html() dostaje wszystkie dane jako parametry
i zwraca kompletny string HTML. Zero globalnego stanu, zero
operacji I/O - czysty transform danych → HTML.
"""
import json

# Etykieta bieżącego sezonu — pokazywana w mastheadzie i na landing page.
# Zmienia się raz w roku (sezon piłkarski przecina lata kalendarzowe).
SEASON_LABEL = "Sezon 2026/27"

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

    # Lider ligi CMF — pierwsza drużyna (dane już posortowane wg total_pts)
    league_leader = league_teams_detail[0] if league_teams_detail else None
    leader_name = league_leader.get("display_name") or \
                  league_leader.get("slug", "").replace("-", " ").title() \
                  if league_leader else "—"
    leader_pts = league_leader.get("total_pts", 0) if league_leader else 0

    # --- Dane pomocnicze dla landing page i KPI (Koncepcja C) ---
    # Wszystko to czyste, read-only wyprowadzenia z danych już przekazanych do szablonu —
    # nie modyfikuje żadnej logiki scrapera/pipeline'u.

    # Przewaga lidera (lider - druga drużyna w tabeli sumarycznej jesień+wiosna)
    leader_margin = 0
    if len(league_teams_detail) >= 2:
        leader_margin = (league_teams_detail[0].get("total_pts", 0) or 0) - \
                        (league_teams_detail[1].get("total_pts", 0) or 0)

    # Top owned — uzupełnij o drużynę i pozycję (lookup w summary_data po player_id)
    top_owned_team = ""
    top_owned_pos = ""
    if top_owned and top_owned.get("player_id") is not None:
        top_owned_pid = str(top_owned.get("player_id"))
        _tp = next((p for p in summary_data if str(p.get("player_id")) == top_owned_pid), None)
        if _tp:
            top_owned_team = _tp.get("team", "")
            top_owned_pos = _tp.get("position", "")

    # Skrót pozycji dla KPI (polskie pełne nazwy / kody numeryczne → krótki kod)
    _POS_SHORT = {"Bramkarz": "GK", "Obrońca": "DEF", "Pomocnik": "MID", "Napastnik": "FWD",
                  "1": "GK", "2": "DEF", "3": "MID", "4": "FWD",
                  "BR": "GK", "OBR": "DEF", "POM": "MID", "NAP": "FWD"}
    top_owned_pos_short = _POS_SHORT.get(top_owned_pos, "") if top_owned_pos else ""

    # Bieżąca kolejka (najwyższy numer rozegranej kolejki z formy zawodników)
    current_round_label = ""
    if summary_data:
        _played_rounds = [f.get("r", 0) for p in summary_data for f in (p.get("form") or []) if f.get("p")]
        if _played_rounds:
            current_round_label = str(max(_played_rounds))

    # Gracz kolejki — najwyższy wynik w ostatniej rozegranej kolejce (best-effort)
    round_star = None
    if summary_data and current_round_label:
        _last_r = int(current_round_label)
        _best = None
        for p in summary_data:
            for f in (p.get("form") or []):
                if f.get("p") and f.get("r") == _last_r:
                    _pts = f.get("pts", 0) or 0
                    if _best is None or _pts > _best["pts"]:
                        _best = {"name": p.get("name", ""), "pts": _pts}
        round_star = _best

    # Średnia punktów ligi / kolejkę (z ostatniej rundy league_history)
    league_avg_round = None
    if (league_history or {}).get("rounds"):
        _lr = league_history["rounds"][-1]
        _sts = _lr.get("standings") or []
        _vals = [s.get("round_points") for s in _sts if s.get("round_points") is not None]
        if _vals:
            league_avg_round = round(sum(_vals) / len(_vals), 1)

    # Default scope
    default_scope = "top10" if "top10" in scopes_data else ("top100" if "top100" in scopes_data else "league")

    # Build scope toggle HTML (Koncepcja C: segment .seg + przyciski .seg-btn)
    scope_toggle_html = ""
    if len(scope_buttons) > 1:
        btns = ""
        for key, label in scope_buttons:
            active_cls = " active" if key == default_scope else ""
            btns += f"<button class='seg-btn scope-btn{active_cls}' data-scope='{key}'>{label}</button>"
        scope_toggle_html = f"<div class='seg' role='group' aria-label='Zakres'><span class='seg-label'>Zakres</span>{btns}</div>"

    html = f'''<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fantasy Ekstraklasa Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
/* ============================================================
   KONCEPCJA C — zunifikowany system tokenów (The Verge x ScrapFEks)
   Źródło wyglądu: redesign-mockups/concept-c-dark.html + concept-c-light.html
   Motyw jasny = podmiana wartości w bloku html.theme-fantasy, reszta bez zmian.
   ============================================================ */
/*==TOKENS:START==*/
:root{{
  --canvas:#131313;
  --surface:#2d2d2d;
  --surface-inset:#191919;
  --surface-sunken:#0e0e0e;
  --surface-hover:#333333;
  --border:#3d3d3d;
  --border-strong:#575757;
  --border-accent:#3cffd0;
  --text:#ffffff;
  --text-muted:#a0a0a0;
  --text-dim:#9c9c9c;
  --text-inverse:#131313;
  --accent:#3cffd0;
  --accent-deep:#309875;
  --link-hover:#3860be;
  --focus:#1eaedb;
  --violet:#5200ff;
  --violet-soft:#8b5cf6;
  --gold:#fbbf24;
  --medal-silver:#d4d4d4;
  --bronze:#f08a2c;
  --pink:#f472b6;
  --pos-gk:#f59e0b;
  --pos-def:#3b82f6;
  --pos-mid:#10b981;
  --pos-fwd:#ef4444;
  --fdr-1:#2fbf71;
  --fdr-2:#8fcf3c;
  --fdr-3:#e8b923;
  --fdr-4:#f08a2c;
  --fdr-5:#e5484d;
  --fdr-ink:#131313;
  --up:#17cca0;
  --down:#ff9e9e;
  --flat:#ababab;
  --conf-high:#17cca0;
  --conf-med:#e8b923;
  --conf-low:#ff9e9e;
  --tint-accent:rgba(60,255,208,.14);
  --tint-up:rgba(23,204,160,.14);
  --tint-down:rgba(255,158,158,.16);
  --tint-gold:rgba(251,191,36,.14);
  --tint-violet:rgba(139,92,246,.16);
  --tint-soft:rgba(255,255,255,.05);
  --tint-row:rgba(255,255,255,.035);
  --overlay:rgba(0,0,0,.6);
  --series-1:#3cffd0;
  --series-2:#fbbf24;
  --series-3:#f472b6;
  --series-4:#8b5cf6;
  --series-5:#38c8ff;
  --series-6:#fb923c;
  --series-7:#4ade80;
  --series-8:#f87171;
  --series-9:#e879f9;
  --series-10:#60a5fa;
  --series-11:#facc15;
  --series-12:#2dd4bf;
}}
html.theme-fantasy{{
  --canvas:#f5f5f5;
  --surface:#ffffff;
  --surface-inset:#f0f0f0;
  --surface-sunken:#ededed;
  --surface-hover:#eeeeee;
  --border:#e0e0e0;
  --border-strong:#808080;
  --border-accent:#0a6e4e;
  --text:#131313;
  --text-muted:#5a5a5a;
  --text-dim:#666666;
  --text-inverse:#ffffff;
  --accent:#0a6e4e;
  --accent-deep:#075f45;
  --link-hover:#3860be;
  --focus:#0284c7;
  --violet:#5200ff;
  --violet-soft:#7c3aed;
  --gold:#8a5a06;
  --medal-silver:#666666;
  --bronze:#c2410c;
  --pink:#db2777;
  --pos-gk:#b45309;
  --pos-def:#1d4ed8;
  --pos-mid:#047857;
  --pos-fwd:#c1121f;
  --fdr-1:#2fbf71;
  --fdr-2:#8fcf3c;
  --fdr-3:#e8b923;
  --fdr-4:#f08a2c;
  --fdr-5:#e5484d;
  --fdr-ink:#131313;
  --up:#0a7342;
  --down:#b91c1c;
  --flat:#666666;
  --conf-high:#0a7342;
  --conf-med:#8a5a06;
  --conf-low:#b91c1c;
  --tint-accent:rgba(10,110,78,.10);
  --tint-up:rgba(10,115,66,.10);
  --tint-down:rgba(185,28,28,.10);
  --tint-gold:rgba(138,90,6,.12);
  --tint-violet:rgba(124,58,237,.12);
  --tint-soft:rgba(19,19,19,.05);
  --tint-row:rgba(19,19,19,.04);
  --overlay:rgba(0,0,0,.5);
  --series-1:#0a6e4e;
  --series-2:#b45309;
  --series-3:#c026d3;
  --series-4:#6d28d9;
  --series-5:#0369a1;
  --series-6:#ea580c;
  --series-7:#15803d;
  --series-8:#b91c1c;
  --series-9:#a21caf;
  --series-10:#2563eb;
  --series-11:#a16207;
  --series-12:#0f766e;
}}
/*==TOKENS:END==*/

*{{margin:0;padding:0;box-sizing:border-box}}
html{{background:var(--canvas);scroll-behavior:smooth}}
body{{
  min-height:100vh;background:var(--canvas);color:var(--text);
  font-family:'DM Sans',-apple-system,BlinkMacSystemFont,sans-serif;
  font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased;padding-bottom:40px;
}}
.mono{{font-family:'JetBrains Mono',ui-monospace,Menlo,monospace}}
.shell{{max-width:1400px;margin:0 auto;padding:0 20px}}
@media (max-width:768px){{.shell{{padding:0 12px}}}}
@media (min-width:2000px){{.shell{{max-width:1600px}}}}
button,input,select{{font-family:inherit;color:inherit}}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}}
a{{color:var(--text);text-decoration:none;transition:color .15s}}
a:hover{{color:var(--link-hover)}}

/* ===== MASTHEAD ===== */
.masthead{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:22px 0 14px;flex-wrap:wrap}}
.brand{{display:flex;align-items:center;gap:14px;cursor:pointer;background:none;border:0;text-align:left}}
.logo{{width:52px;height:52px;border-radius:12px;border:1px solid var(--border);background:var(--surface);display:flex;align-items:center;justify-content:center;overflow:hidden;flex:0 0 auto}}
.logo img{{width:100%;height:100%;object-fit:contain}}
.brand strong{{display:block;font-size:22px;font-weight:800;letter-spacing:-.6px;line-height:1.1}}
.brand .sub{{display:block;font-size:10px;letter-spacing:1.4px;color:var(--text-muted);margin-top:3px;text-transform:uppercase}}
.mast-right{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.pill-tag{{display:inline-block;background:var(--accent);color:var(--text-inverse);border-radius:20px;padding:6px 14px;font-size:11px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;font-family:'JetBrains Mono',monospace}}
.ghost-link{{border:1px solid var(--border-accent);color:var(--accent);border-radius:40px;padding:9px 18px;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;transition:background .15s,color .15s;min-height:44px;display:inline-flex;align-items:center;background:transparent;cursor:pointer}}
.ghost-link:hover{{background:var(--accent);color:var(--text-inverse)}}

/* ===== 4 KARTY NAGŁÓDKA (KPI) ===== */
.kpi-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:6px}}
.kpi{{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:16px 18px;min-width:0}}
.kpi-label{{display:flex;align-items:center;gap:8px;font-size:10px;letter-spacing:1.6px;text-transform:uppercase;color:var(--text-muted);font-family:'JetBrains Mono',monospace}}
.kpi-mark{{width:9px;height:9px;flex:0 0 auto;background:var(--accent)}}
.kpi-mark.gold{{background:var(--gold)}}
.kpi-mark.violet{{background:var(--violet-soft)}}
.kpi-val{{font-size:30px;font-weight:800;letter-spacing:-1.2px;margin-top:8px;line-height:1}}
.kpi-sub{{font-size:12px;color:var(--text-muted);margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.kpi-lead{{background:var(--accent);border-color:var(--accent);color:var(--text-inverse)}}
.kpi-lead .kpi-label,.kpi-lead .kpi-sub{{color:var(--text-inverse)}}
.kpi-lead .kpi-mark{{background:var(--text-inverse)}}
@media (max-width:900px){{.kpi-row{{grid-template-columns:repeat(2,1fr)}}}}
@media (max-width:400px){{.kpi-row{{grid-template-columns:1fr}}}}

/* ===== PASEK ZAKŁADEK ===== */
.tabbar{{position:sticky;top:0;z-index:60;background:var(--canvas);border-bottom:1px solid var(--border);margin-top:22px}}
.tabs{{display:flex;gap:0;overflow-x:auto;scrollbar-width:none;-ms-overflow-style:none}}
.tabs::-webkit-scrollbar{{display:none}}
.tab{{flex:0 0 auto;display:inline-flex;align-items:center;gap:7px;min-height:52px;padding:0 16px;background:none;border:0;border-bottom:3px solid transparent;color:var(--text-muted);font-size:12px;font-weight:700;letter-spacing:.9px;text-transform:uppercase;cursor:pointer;white-space:nowrap;transition:color .15s,border-color .15s,background .15s}}
.tab .tab-idx{{font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:500;color:var(--text-dim);letter-spacing:.5px}}
.tab:hover{{color:var(--text);background:var(--tint-row)}}
.tab.active{{color:var(--text);border-bottom-color:var(--accent);background:var(--surface-inset)}}
.tab.active .tab-idx{{color:var(--text-muted)}}
.tab-link{{text-decoration:none}}

/* ===== SEGMENTY / FILTRY ===== */
.toolbar{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:20px 0 18px}}
.seg{{display:flex;gap:6px;flex-wrap:wrap;align-items:center}}
.seg-label{{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--text-dim);font-family:'JetBrains Mono',monospace;margin-right:2px}}
.seg-btn{{background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:20px;padding:0 16px;min-height:44px;font-size:12px;font-weight:700;cursor:pointer;transition:background .15s,color .15s,border-color .15s;letter-spacing:.3px}}
.seg-btn:hover{{color:var(--text);border-color:var(--border-strong);background:var(--surface)}}
.seg-btn.active{{background:var(--accent);border-color:var(--accent);color:var(--text-inverse)}}
.pos-btn.active{{background:var(--accent);border-color:var(--accent);color:var(--text-inverse)}}
.pos-btn[data-pos="BR"].active{{background:var(--pos-gk);border-color:var(--pos-gk)}}
.pos-btn[data-pos="OBR"].active{{background:var(--pos-def);border-color:var(--pos-def)}}
.pos-btn[data-pos="POM"].active{{background:var(--pos-mid);border-color:var(--pos-mid)}}
.pos-btn[data-pos="NAP"].active{{background:var(--pos-fwd);border-color:var(--pos-fwd)}}
.seg-push{{margin-left:auto}}
.field{{display:flex;align-items:center;gap:8px}}
.field label{{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--text-dim);font-family:'JetBrains Mono',monospace}}
.input,select.input{{background:var(--surface-sunken);border:1px solid var(--border-strong);color:var(--text);border-radius:4px;padding:11px 12px;font-size:13px;min-height:44px;transition:border-color .15s}}
.input::placeholder{{color:var(--text-dim)}}
.input:focus{{border-color:var(--accent);outline:none}}
select.input{{cursor:pointer;padding-right:26px}}
.search-wrap{{position:relative;flex:1;min-width:200px;max-width:340px}}
.search-wrap .input{{width:100%}}

/* ===== WIDOKI / SEKCJE ===== */
.view{{display:none;padding-bottom:8px}}
.view.active{{display:block;animation:fade .28s ease}}
@keyframes fade{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:none}}}}
.sec{{display:flex;align-items:center;gap:12px;margin:34px 0 16px}}
.sec h2,.sec h3{{font-size:13px;font-weight:700;letter-spacing:2px;text-transform:uppercase;white-space:nowrap}}
.sec .rule{{flex:1;height:1px;background:var(--border)}}
.sec .sec-note{{font-size:11px;color:var(--text-muted);letter-spacing:.6px;white-space:normal;text-align:right}}
.page-title{{font-size:clamp(26px,4vw,40px);font-weight:800;letter-spacing:-1.4px;line-height:1.05;margin:30px 0 6px}}
.page-sub{{font-size:13px;color:var(--text-muted);margin-bottom:6px}}
.page-sub .mono{{font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--accent)}}
.panel{{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:20px}}
.lede{{font-size:15px;color:var(--text-muted);max-width:74ch;line-height:1.65}}
.lede b{{color:var(--text);font-weight:700}}
.hint{{font-size:12px;color:var(--text-dim);margin-top:4px}}
.hint.warn{{color:var(--conf-low)}}
.row-count{{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:1.4px;text-transform:uppercase;color:var(--text-dim);margin-bottom:10px}}

/* ===== TABELA — jedna gęstość ===== */
.tscroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.dt{{width:100%;border-collapse:collapse;font-size:13px;table-layout:auto}}
.dt thead th{{background:var(--surface-inset);color:var(--text-muted);font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;letter-spacing:1.1px;text-transform:uppercase;padding:12px 12px;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-bottom:1px solid var(--border)}}
.dt thead th.sortable{{cursor:pointer;user-select:none;transition:color .15s}}
.dt thead th.sortable:hover{{color:var(--text)}}
.dt thead th.sorted{{color:var(--accent)}}
.dt thead th.sorted .sarr{{font-size:9px}}
.dt thead th.text-right{{text-align:right}}
.dt thead th.text-center{{text-align:center}}
.dt thead th.text-left{{text-align:left}}
.dt td{{padding:11px 12px;border-top:1px solid var(--border);white-space:nowrap;vertical-align:middle}}
.dt .clip{{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.dt td[colspan]{{white-space:normal;overflow:visible;text-overflow:clip}}
.dt tbody tr:first-child td{{border-top:0}}
.dt tbody tr:hover td{{background:var(--tint-row)}}
.dt .num{{text-align:right;font-variant-numeric:tabular-nums}}
.dt .center{{text-align:center}}
.dt .strong{{font-weight:700}}
.dt .muted{{color:var(--text-muted)}}
.rank{{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-muted);font-weight:700}}
.medal{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;font-size:11px;font-weight:800;background:var(--surface-inset);border:1px solid var(--border)}}
.medal.m1{{background:var(--gold);color:var(--text-inverse);border-color:var(--gold)}}
.medal.m2{{background:var(--medal-silver);color:var(--text-inverse);border-color:var(--medal-silver)}}
.medal.m3{{background:var(--bronze);color:var(--text-inverse);border-color:var(--bronze)}}

/* badge pozycji */
.badge-pos{{display:inline-block;padding:3px 9px;border-radius:4px;font-size:10px;font-weight:800;letter-spacing:.8px;color:var(--text-inverse);text-transform:uppercase;min-width:42px;text-align:center}}
.pos-GK{{background:var(--pos-gk)}}
.pos-DEF{{background:var(--pos-def)}}
.pos-MID{{background:var(--pos-mid)}}
.pos-FWD{{background:var(--pos-fwd)}}

.delta{{display:inline-block;min-width:46px;text-align:center;padding:2px 7px;border-radius:4px;font-size:12px;font-weight:700;font-variant-numeric:tabular-nums}}
.d-up{{background:var(--tint-up);color:var(--up)}}
.d-down{{background:var(--tint-down);color:var(--down)}}
.d-flat{{background:var(--tint-soft);color:var(--flat)}}
.chg{{font-size:13px;font-weight:700}}
.chg-up{{color:var(--up)}}
.chg-down{{color:var(--down)}}
.chg-flat{{color:var(--flat)}}

.bar{{display:inline-flex;align-items:center;gap:8px}}
.bar-track{{width:74px;height:6px;border-radius:3px;background:var(--surface-inset);overflow:hidden;border:1px solid var(--border)}}
.bar-fill{{display:block;height:100%;background:var(--accent)}}
.bar-fill.neg{{background:var(--down)}}
.bar-val{{font-size:12px;color:var(--text-muted);font-variant-numeric:tabular-nums;min-width:52px}}

.mini{{display:inline-flex;align-items:flex-end;gap:3px;height:26px}}
.mini i{{display:block;width:9px;min-height:2px;background:var(--accent);border-radius:2px 2px 0 0;opacity:.9}}
.mini i.zero{{background:var(--border-strong);height:3px!important;opacity:.7}}

/* FDR 1-5 */
.fdr{{display:inline-flex;align-items:center;justify-content:center;min-width:26px;height:22px;padding:0 6px;border-radius:4px;font-size:11px;font-weight:800;color:var(--fdr-ink);font-variant-numeric:tabular-nums}}
.fdr-1{{background:var(--fdr-1)}}
.fdr-2{{background:var(--fdr-2)}}
.fdr-3{{background:var(--fdr-3)}}
.fdr-4{{background:var(--fdr-4)}}
.fdr-5{{background:var(--fdr-5)}}
.legend{{display:flex;gap:8px 16px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--text-muted);margin-bottom:16px}}
.legend .li{{display:inline-flex;align-items:center;gap:7px}}
.legend .fdr{{min-width:22px;height:20px}}

.opp{{display:inline-flex;flex-direction:column;align-items:center;gap:3px;min-width:78px;max-width:100%}}
.opp .o-code{{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:.6px;display:flex;align-items:center;gap:5px;min-width:0;max-width:100%}}
.opp .o-nm{{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.opp .hw{{flex-shrink:0}}
.hw{{display:inline-block;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:800;letter-spacing:.6px;background:var(--tint-soft);color:var(--text-muted);border:1px solid var(--border)}}
.hw.d{{background:var(--tint-accent);color:var(--accent);border-color:transparent}}

.conf{{display:inline-block;padding:3px 10px;border-radius:12px;font-size:10px;font-weight:800;letter-spacing:.8px;text-transform:uppercase}}
.conf-high{{background:var(--tint-up);color:var(--conf-high)}}
.conf-medium{{background:var(--tint-gold);color:var(--conf-med)}}
.conf-low{{background:var(--tint-down);color:var(--conf-low)}}
.pot{{display:inline-block;padding:3px 9px;border-radius:4px;font-size:12px;font-weight:800;font-variant-numeric:tabular-nums}}
.pot-hi{{background:var(--tint-up);color:var(--up)}}
.pot-mid{{background:var(--tint-gold);color:var(--conf-med)}}
.pot-lo{{background:var(--tint-down);color:var(--down)}}
.pred-val{{display:inline-block;min-width:52px;text-align:center;background:var(--surface-inset);border:1px solid var(--border-strong);border-radius:6px;padding:5px 9px;font-size:15px;font-weight:800;font-variant-numeric:tabular-nums}}
.occ{{font-weight:800;font-variant-numeric:tabular-nums}}
.occ-hi{{color:var(--accent)}}
.occ-mid{{color:var(--gold)}}
.occ-lo{{color:var(--text-muted)}}
.used{{display:inline-block;background:var(--tint-soft);border:1px solid var(--border);border-radius:4px;padding:3px 8px;font-size:11px;font-weight:700;letter-spacing:.4px}}

/* ===== LANDING ===== */
.hero{{display:grid;grid-template-columns:1.15fr .85fr;gap:28px;align-items:stretch;margin-top:26px}}
.hero-kicker{{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:2.4px;text-transform:uppercase;color:var(--accent);margin-bottom:16px}}
.hero h1{{font-size:clamp(34px,5.2vw,64px);font-weight:800;letter-spacing:-2.4px;line-height:.98}}
.hero h1 em{{font-style:normal;color:var(--accent)}}
.hero .lede{{margin-top:18px}}
.hero-cta{{display:flex;gap:10px;margin-top:26px;flex-wrap:wrap}}
.btn-primary,.btn-ghost{{display:inline-flex;align-items:center;gap:8px;min-height:48px;padding:0 26px;border-radius:24px;font-size:13px;font-weight:700;letter-spacing:.6px;cursor:pointer;border:1px solid transparent;transition:background .15s,color .15s,border-color .15s}}
.btn-primary{{background:var(--accent);color:var(--text-inverse)}}
.btn-primary:hover{{background:var(--text);color:var(--text-inverse)}}
.btn-ghost{{background:transparent;border-color:var(--border-accent);color:var(--accent)}}
.btn-ghost:hover{{background:var(--accent);color:var(--text-inverse)}}
.fact-strip{{display:flex;gap:0;flex-wrap:wrap;border:1px solid var(--border);border-radius:20px;background:var(--surface-inset);margin-top:24px;overflow:hidden}}
.fact{{flex:1 1 180px;padding:14px 18px;border-right:1px solid var(--border);min-width:0}}
.fact:last-child{{border-right:0}}
.fact .fk{{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.6px;text-transform:uppercase;color:var(--text-dim)}}
.fact .fv{{font-size:15px;font-weight:700;margin-top:5px}}
.entry-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:14px}}
.entry{{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:20px;display:flex;flex-direction:column;gap:8px;cursor:pointer;text-align:left;min-height:172px;transition:border-color .15s,background .15s;color:var(--text)}}
.entry:hover{{border-color:var(--border-strong);background:var(--surface-hover);color:var(--text)}}
.entry .e-num{{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:1.6px;color:var(--text-dim);text-transform:uppercase}}
.entry .e-val{{font-size:34px;font-weight:800;letter-spacing:-1.6px;line-height:1}}
.entry .e-name{{font-size:14px;font-weight:700}}
.entry .e-desc{{font-size:12px;color:var(--text-muted);line-height:1.5;margin-top:auto}}
.entry .e-go{{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--accent);margin-top:8px}}
.entry-feature{{background:var(--accent);border-color:var(--accent);color:var(--text-inverse)}}
.entry-feature .e-num,.entry-feature .e-desc,.entry-feature .e-go{{color:var(--text-inverse)}}
.entry-feature:hover{{background:var(--text);border-color:var(--text);color:var(--text-inverse)}}
.entry-feature:hover .e-num,.entry-feature:hover .e-desc,.entry-feature:hover .e-go{{color:var(--text-inverse)}}
@media (max-width:1000px){{.hero{{grid-template-columns:1fr}}.entry-grid{{grid-template-columns:repeat(2,1fr)}}}}
@media (max-width:520px){{.entry-grid{{grid-template-columns:1fr}}}}

/* ===== TERMINARZ ===== */
.planner-intro{{font-size:14px;color:var(--text-muted);line-height:1.65;max-width:82ch;margin-bottom:18px}}
.planner-intro b{{color:var(--text)}}
.fp-controls{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:18px}}
.insights{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:18px}}
.insight{{background:var(--surface-inset);border:1px solid var(--border);border-radius:20px;padding:16px 18px}}
.insight h4{{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--text-muted);font-weight:700;margin-bottom:12px}}
.insight ol{{list-style:none;display:flex;flex-direction:column;gap:8px}}
.insight li{{display:flex;align-items:center;gap:8px;font-size:13px}}
.insight .ii{{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text-dim);width:14px}}
.insight .iv{{margin-left:auto;font-weight:700;font-variant-numeric:tabular-nums}}
.rot-pair{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;font-weight:700}}
.rot-pct{{margin-left:auto;background:var(--accent);color:var(--text-inverse);border-radius:12px;padding:2px 9px;font-size:11px;font-weight:800}}
.rot-note{{font-size:11px;color:var(--text-muted);margin-top:10px;line-height:1.5;font-weight:400}}
@media (max-width:1100px){{.insights{{grid-template-columns:repeat(2,1fr)}}}}
@media (max-width:560px){{.insights{{grid-template-columns:1fr}}}}

/* ===== TRANSFERY ===== */
.transfer-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media (max-width:900px){{.transfer-grid{{grid-template-columns:1fr}}}}
.list-head{{display:flex;align-items:baseline;gap:10px;margin-bottom:14px;flex-wrap:wrap}}
.list-head h3{{font-size:14px;font-weight:800;letter-spacing:1.4px;text-transform:uppercase}}
.list-head .lh-note{{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:1.4px;text-transform:uppercase;color:var(--text-dim)}}
.list-head.buy h3{{color:var(--up)}}
.list-head.sell h3{{color:var(--down)}}
.gw-badge{{display:inline-flex;align-items:center;background:var(--surface-inset);border:1px solid var(--border-strong);border-radius:20px;padding:9px 16px;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--text);min-height:44px}}

/* ===== PROGNOZA ===== */
.method{{background:var(--surface-inset);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:16px;padding:16px 20px;margin:18px 0;font-size:13px;line-height:1.75;color:var(--text-muted)}}
.method b{{color:var(--text);font-weight:700}}
.method .m-row{{display:block}}
.method code{{font-family:'JetBrains Mono',monospace;font-size:12px;background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:2px 7px;color:var(--accent)}}

/* ===== SEZON ===== */
.chart-card{{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:20px}}
.chart-card svg{{display:block;width:100%;height:auto}}
.chart-legend{{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:16px}}
.chart-legend .cli{{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--text-muted)}}
.chart-legend .csw{{width:16px;height:4px;border-radius:2px}}
.dot{{width:8px;height:8px;border-radius:2px;display:inline-block}}
.axis{{stroke:var(--border);stroke-width:1}}
.gridline{{stroke:var(--border);stroke-width:1;stroke-dasharray:2 5}}
.axis-txt{{fill:var(--text-dim);font-family:'JetBrains Mono',monospace;font-size:11px}}
.grid-txt{{fill:var(--text-dim);font-family:'JetBrains Mono',monospace;font-size:10px}}

/* ===== SEZON — warstwa wykresu (linie "Pozycje" + słupki "Punkty łącznie") ===== */
/* Najechanie na linię/słupek albo na pozycję w legendzie — reszta przygasza */
.season-chart .steam{{transition:opacity .18s ease}}
.season-chart.has-focus .steam{{opacity:.14}}
.season-chart.has-focus .steam.is-focus{{opacity:1}}
/* Linie: kolor drużyny przez zmienną --lc (var() nie działa w atrybucie stroke) */
.season-chart .sline{{fill:none;stroke:var(--lc,var(--text-dim));stroke-opacity:.92;stroke-width:var(--lw,2px);stroke-linejoin:round;stroke-linecap:round;transition:stroke-width .18s,stroke-opacity .18s}}
.season-chart.has-focus .steam.is-focus .sline{{stroke-width:calc(var(--lw,2px) + 1.8px);stroke-opacity:1}}
.season-chart .shit{{fill:none;stroke:transparent;stroke-width:16;pointer-events:stroke}}
.season-chart .sdot{{fill:var(--lc,var(--text-dim));stroke:var(--surface);stroke-width:1.5}}
/* Słupki klasyfikacji */
.season-chart .sband{{fill:transparent;pointer-events:all}}
.season-chart .steam.is-focus .sband{{fill:var(--tint-soft)}}
.season-chart .steam.is-own .sband{{fill:var(--tint-accent)}}
.season-chart .strack{{fill:var(--surface-inset)}}
.season-chart .sbar{{fill:var(--lc,var(--text-dim))}}
.season-chart .srow-name{{font-size:12.5px;font-weight:600;fill:var(--text)}}
.season-chart .steam.is-own .srow-name{{font-weight:800}}
.season-chart .sval{{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;fill:var(--text-muted)}}
.season-chart .steam.is-own .sval{{fill:var(--text)}}
.season-chart .srank{{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;fill:var(--text-dim)}}
.season-chart .srank.top1{{fill:var(--gold)}}
.season-chart .sgrid{{stroke:var(--border-strong);stroke-width:1;stroke-opacity:.45;stroke-dasharray:2 5}}
.season-chart .sband-lbl{{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;fill:var(--text-dim)}}
/* Legenda sezonu — klik = ukrycie, najechanie = podświetlenie na wykresie */
.chart-legend .cli.is-focus{{color:var(--text)}}
.chart-legend .cli.is-own{{color:var(--text);font-weight:700}}

/* ===== PORÓWNANIE ===== */
.chips{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:14px 0 6px;min-height:44px}}
.chip{{display:inline-flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:5px 8px 5px 6px;font-size:13px;animation:chipin .18s ease}}
@keyframes chipin{{from{{opacity:0;transform:scale(.92)}}to{{opacity:1;transform:none}}}}
.chip .chip-meta{{color:var(--text-muted);font-size:11px}}
.chip-x{{background:none;border:0;color:var(--text-muted);font-size:15px;line-height:1;cursor:pointer;width:36px;height:36px;border-radius:50%;transition:color .15s,background .15s}}
.chip-x:hover{{color:var(--down);background:var(--tint-down)}}
.chip-btn{{background:none;border:0;padding:0;cursor:pointer;display:inline-flex;align-items:center;gap:8px;color:inherit;font:inherit}}
.clear-btn{{background:var(--surface-sunken);border:1px solid var(--border-strong);color:var(--text-muted);border-radius:20px;min-height:44px;padding:0 18px;font-size:12px;font-weight:700;cursor:pointer;transition:color .15s,border-color .15s}}
.clear-btn:hover{{color:var(--text);border-color:var(--accent)}}
.ac{{position:absolute;top:100%;left:0;right:0;z-index:80;background:var(--surface);border:1px solid var(--border-strong);border-radius:12px;margin-top:6px;overflow:hidden;display:none}}
.ac.open{{display:block}}
.ac button{{display:flex;width:100%;gap:10px;align-items:center;background:none;border:0;border-top:1px solid var(--border);padding:12px 14px;font-size:13px;cursor:pointer;text-align:left;min-height:48px;color:var(--text)}}
.ac button:first-child{{border-top:0}}
.ac button:hover{{background:var(--surface-hover)}}
.ac .ac-team{{color:var(--text-muted);font-size:11px;margin-left:auto}}
.cmp-cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin-bottom:20px}}
.cmp-card{{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:18px 20px;position:relative;overflow:hidden}}
.cmp-card .cc-bar{{position:absolute;top:0;left:0;right:0;height:4px}}
.cmp-card .cc-pos{{margin-bottom:10px}}
.cmp-card .cc-name{{font-size:17px;font-weight:800;letter-spacing:-.4px}}
.cmp-card .cc-team{{font-size:12px;color:var(--text-muted);margin-top:3px}}
.ccmp-stat{{display:flex;justify-content:space-between;gap:12px;font-size:13px;padding:9px 0;border-top:1px solid var(--border);align-items:center}}
.ccmp-stat .cs-k{{color:var(--text-muted)}}
.ccmp-stat .cs-v{{font-weight:700;display:inline-flex;align-items:center;gap:6px}}
.cmp-table td.best{{background:var(--tint-accent);color:var(--accent);font-weight:800}}
.cmp-table td.metric{{text-align:left;color:var(--text-muted);font-size:12px;font-weight:700;letter-spacing:.4px;white-space:nowrap}}
.cmp-empty{{text-align:center;padding:56px 20px;color:var(--text-muted);font-size:15px;background:var(--surface-inset);border:1px dashed var(--border-strong);border-radius:20px}}
.cmp-empty strong{{display:block;color:var(--text);font-size:18px;margin-bottom:8px}}

/* ===== ARCHIWUM ===== */
.arc-badge{{display:inline-flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--gold);color:var(--gold);border-radius:20px;padding:8px 16px;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase}}
.season-item{{display:flex;align-items:center;gap:16px;background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:20px 22px;cursor:pointer;transition:border-color .15s,background .15s;width:100%;text-align:left;color:var(--text);min-height:76px}}
.season-item:hover{{border-color:var(--accent);background:var(--surface-hover)}}
.season-item .si-t{{display:block;font-size:17px;font-weight:800;letter-spacing:-.3px}}
.season-item .si-m{{display:block;font-size:12px;color:var(--text-muted);margin-top:4px}}
.season-item .si-go{{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.4px;color:var(--accent);text-transform:uppercase}}
.back-link{{display:inline-flex;align-items:center;gap:8px;min-height:44px;font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1.4px;text-transform:uppercase;color:var(--text-muted)}}
.back-link:hover{{color:var(--link-hover)}}
.subtabs{{display:flex;gap:6px;flex-wrap:wrap;margin:16px 0 6px}}
.empty-note{{padding:34px;text-align:center;color:var(--text-muted);font-size:14px}}
.footer{{text-align:center;margin-top:44px;padding-top:20px;border-top:1px solid var(--border);color:var(--text-dim);font-size:11px;letter-spacing:1.2px;text-transform:uppercase;font-family:'JetBrains Mono',monospace}}
.detail-row > td{{background:var(--surface-inset)!important;padding:0!important;border-top:0!important}}
.detail-in{{padding:16px 18px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.detail-tag{{display:inline-flex;align-items:center;gap:7px;background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:6px 13px;font-size:12px}}
.detail-tag .dt-pts{{color:var(--accent);font-weight:800;font-variant-numeric:tabular-nums}}
.detail-tag .dt-nm{{font-weight:600}}
.expand-btn{{background:none;border:0;color:var(--text-muted);cursor:pointer;font-size:11px;width:28px;height:36px;transition:transform .15s,color .15s;padding:0}}
.expand-btn:hover{{color:var(--accent)}}
.expand-btn.open{{transform:rotate(90deg);color:var(--accent)}}
.team-cell{{display:inline-flex;align-items:center;gap:8px;max-width:100%;min-width:0}}
.team-name{{font-weight:700;display:inline-block;max-width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}

/* ===== UTILITIES — wspólne dla renderów zakładek (mapowane na tokeny) ===== */
.text-right{{text-align:right}}
.text-center{{text-align:center}}
.text-left{{text-align:left}}
.fw-700{{font-weight:700}}
.fw-600{{font-weight:600}}
.c-muted{{color:var(--text-muted)}}
.c-dim{{color:var(--text-dim)}}
.empty-msg{{padding:40px;text-align:center;color:var(--text-muted);font-size:14px}}
.highlight{{background:var(--tint-accent)}}
.price-up{{color:var(--up);font-size:11px;font-weight:700}}
.price-down{{color:var(--down);font-size:11px;font-weight:700}}
.season-chart{{position:relative;width:100%;overflow-x:auto}}
.season-tooltip{{position:absolute;pointer-events:none;background:var(--surface-sunken);border:1px solid var(--border-strong);border-radius:8px;padding:8px 12px;font-size:12px;color:var(--text);white-space:nowrap;z-index:10;opacity:0;transition:opacity .15s}}
.season-tooltip.visible{{opacity:1}}
.season-legend-item{{cursor:pointer}}
.season-legend-item.hidden{{opacity:0.3;text-decoration:line-through}}
/* Dotyk: domyślna wysokość pozycji legendy (~18px) jest poniżej minimum WCAG 2.5.8 —
   na telefonach podbijamy do 28px, żeby dało się trafić palcem.
   Nazwy drużyn w słupkach: w wąskiej kolumnie (150px) zmniejszamy krój, żeby się mieściły */
@media (max-width:768px){{
  .season-legend-item{{min-height:28px;padding:5px 0}}
  .season-chart .srow-name{{font-size:11px}}
}}

/* ===== MODAL statystyk drużyny (FDR) ===== */
.ft-modal-bg{{position:fixed;top:0;left:0;width:100%;height:100%;background:var(--overlay);z-index:1000;display:flex;align-items:center;justify-content:center}}
.ft-modal{{background:var(--surface);border:1px solid var(--border-strong);border-radius:20px;padding:24px 32px;min-width:340px;max-width:90vw;position:relative;color:var(--text)}}
.ft-modal h3{{margin:0 0 16px;font-size:18px}}
.ft-modal-close{{position:absolute;top:12px;right:16px;background:none;border:none;color:var(--text-muted);font-size:20px;cursor:pointer}}
.ft-modal-close:hover{{color:var(--text)}}

/* ===== FIXTURE PLANNER — stany ===== */
.fp-section{{margin-top:32px;border-top:1px solid var(--border);padding-top:24px}}
.fp-team-cell{{cursor:pointer}}
.fp-team-cell .team-name{{transition:color .15s}}
.fp-team-cell:hover .team-name{{color:var(--link-hover)}}
.fp-team-cell.fp-selected .team-name{{color:var(--accent)}}
.dt thead th.fp-sorted{{color:var(--accent)}}
.roster-trigger{{cursor:pointer}}
.roster-trigger .team-name{{transition:color .15s}}
.roster-trigger:hover .team-name{{color:var(--link-hover)}}
.name-cell{{display:inline-flex;align-items:center;gap:6px;min-width:0}}
.name-caret{{font-size:10px;color:var(--text-dim);line-height:1;flex:0 0 auto}}

/* ===== ODZNAKI ROSTER (C / RES / XI) w panelu szczegółów ===== */
.rc-badge{{font-size:9px;font-weight:800;border-radius:3px;padding:1px 5px;letter-spacing:.4px}}
.rc-cap{{background:var(--gold);color:var(--text-inverse)}}
.rc-res{{background:var(--surface-sunken);color:var(--text-muted);border:1px solid var(--border-strong)}}
.rc-xi{{background:var(--accent);color:var(--text-inverse)}}

@media (max-width:768px){{
  .tab{{padding:0 13px;font-size:11px}}
  .dt{{font-size:12px}}
  .dt td{{padding:10px}}
  .page-title{{letter-spacing:-1px}}
  .sec{{flex-wrap:wrap}}
  .sec .sec-note{{text-align:left}}
  .fact{{border-right:0;border-bottom:1px solid var(--border)}}
}}

</style>
</head>
<body>
<div class="shell">

  <!-- ============ MASTHEAD ============ -->
  <header class="masthead">
    <button class="brand" data-go="landing" aria-label="Strona główna">
      <span class="logo"><img src="logo.PNG" alt="ScrapFEks"></span>
      <span class="brand-txt">
        <strong>Fantasy Ekstraklasa</strong>
        <span class="sub mono">ScrapFEks · dashboard · {timestamp}</span>
      </span>
    </button>
    <div class="mast-right">
      <span class="pill-tag">{SEASON_LABEL}</span>
      <button class="ghost-link" data-go="landing" aria-label="Wróć na stronę główną">Strona główna</button>
      <button class="ghost-link theme-toggle" onclick="toggleTheme()" aria-label="Przełącz motyw">☀️ Light</button>
      {"<a class='ghost-link' href='archive/index.html'>Archiwum</a>" if has_archive else ""}
    </div>
  </header>

  <!-- ============ 4 KARTY KPI (zawsze widoczne) ============ -->
  <div class="kpi-row">
    <div class="kpi kpi-lead">
      <div class="kpi-label"><span class="kpi-mark"></span>Lider ligi</div>
      <div class="kpi-val">{leader_pts}</div>
      <div class="kpi-sub">{leader_name}{' · przewaga +' + str(leader_margin) + ' pkt' if leader_margin > 0 else ''}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label"><span class="kpi-mark"></span>Top owned</div>
      <div class="kpi-val">{top_owned.get('squad_pct', '—')}</div>
      <div class="kpi-sub">{top_owned.get('name', '—')}{' · ' + top_owned_pos_short if top_owned_pos_short else ''}{' · ' + top_owned_team if top_owned_team else ''}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label"><span class="kpi-mark gold"></span>Najlepszy PPP</div>
      <div class="kpi-val">{best_ppp.get('points_per_price', 0):.1f}</div>
      <div class="kpi-sub">{best_ppp.get('name', '—')} · {best_ppp.get('price', 0):.1f}M</div>
    </div>
    {"<div class='kpi'><div class='kpi-label'><span class='kpi-mark violet'></span>Liga</div><div class='kpi-val'>" + str(league_teams_count) + "</div><div class='kpi-sub'>" + league_label + " · drużyn</div></div>" if has_league else ""}
  </div>

  <!-- ============ PASEK ZAKŁADEK ============ -->
  <nav class="tabbar" aria-label="Nawigacja dashboardu">
    <div class="tabs">
      <button class="tab" data-go="players"><span class="tab-idx">01</span>Zawodnicy</button>
      {"<button class='tab' data-go='teams'><span class='tab-idx'>02</span>Liga CMF</button>" if has_league else ""}
      {"<button class='tab' data-go='fixtures'><span class='tab-idx'>03</span>Terminarz</button>" if has_fixtures else ""}
      {"<button class='tab' data-go='transfers'><span class='tab-idx'>04</span>Transfery</button>" if has_transfers else ""}
      {"<button class='tab' data-go='predictions'><span class='tab-idx'>05</span>Prognoza</button>" if has_predictions else ""}
      {"<button class='tab' data-go='accuracy'><span class='tab-idx'>06</span>Trafność</button>" if has_accuracy else ""}
      {"<button class='tab' data-go='season'><span class='tab-idx'>07</span>Sezon</button>" if has_season else ""}
      <button class="tab" data-go="compare"><span class="tab-idx">08</span>Porównanie</button>
      {"<a class='tab tab-link' href='archive/index.html'><span class='tab-idx'>09</span>Archiwum</a>" if has_archive else "<span class='tab' style='opacity:0.4;pointer-events:none;cursor:default'><span class='tab-idx'>09</span>Archiwum</span>"}
    </div>
  </nav>

  <main>

  <!-- ============ LANDING ============ -->
  <section id="v-landing" class="view active" aria-label="Start">
    <div class="hero">
      <div>
        <div class="hero-kicker">{SEASON_LABEL}{' · kolejka ' + current_round_label if current_round_label else ''} · dane {timestamp}</div>
        <h1>Dashboard ligi Discord Forum CMF.<br><em>Tabele, analizy, prognozy.</em></h1>
        <div class="hero-cta">
          <button class="btn-primary" data-go="players">Wejdź w zawodników →</button>
          <button class="btn-ghost" data-go="fixtures">Zobacz trudność meczów</button>
        </div>
        <div class="fact-strip">
          {"<div class='fact'><div class='fk'>Ostatnia kolejka</div><div class='fv'>K" + current_round_label + "</div></div>" if current_round_label else ""}
          {"<div class='fact'><div class='fk'>Gracz kolejki</div><div class='fv'>" + (round_star['name'] if round_star else '') + " · " + (str(round_star['pts']) if round_star else '') + " pkt</div></div>" if round_star else ""}
          {"<div class='fact'><div class='fk'>Średnia ligi / kol.</div><div class='fv'>" + str(league_avg_round) + " pkt</div></div>" if league_avg_round is not None else ""}
        </div>
      </div>
      <div class="entry-grid" style="grid-template-columns:1fr 1fr;align-content:start">
        <button class="entry entry-feature" data-go="teams">
          <span class="e-num">01 · Lider ligi</span>
          <span class="e-val">{leader_pts}</span>
          <span class="e-name">{leader_name}</span>
          <span class="e-desc">Pełna tabela CMF: jesień + wiosna, medale, rozwijane składy i ruchy pozycji.</span>
          <span class="e-go">Otwórz ligę →</span>
        </button>
        <button class="entry" data-go="players">
          <span class="e-num">02 · Top owned</span>
          <span class="e-val">{top_owned.get('squad_pct', '—')}</span>
          <span class="e-name">{top_owned.get('name', '—')}</span>
          <span class="e-desc">Kto trzyma go w składzie, w jedenastce i kto oddał mu opaskę kapitana.</span>
          <span class="e-go">Właściciele →</span>
        </button>
        <button class="entry" data-go="players">
          <span class="e-num">03 · Najlepszy PPP</span>
          <span class="e-val">{best_ppp.get('points_per_price', 0):.1f}</span>
          <span class="e-name">{best_ppp.get('name', '—')} · {best_ppp.get('price', 0):.1f}M</span>
          <span class="e-desc">Sortuj po Pkt/Cena i szukaj okazji, zanim zrobi to reszta ligi.</span>
          <span class="e-go">Szukaj okazji →</span>
        </button>
        {"<button class='entry' data-go='teams'><span class='e-num'>04 · Liga</span><span class='e-val'>" + str(league_teams_count) + "</span><span class='e-name'>" + league_label + "</span><span class='e-desc'>Trzydzieści drużyn, jedna tabela i widok duetów obok.</span><span class='e-go'>Zobacz wszystkich →</span></button>" if has_league else ""}
      </div>
    </div>

    <div class="sec"><h2>Wejdź w szczegóły</h2><span class="rule"></span>
      <span class="sec-note">Dziewięć powodów, żeby zostać na dłużej</span></div>
    <div class="entry-grid">
      <button class="entry" data-go="players">
        <span class="e-num">01 · Zawodnicy</span>
        <span class="e-name" style="font-size:18px">15 kolumn, wszystkie sortowalne</span>
        <span class="e-desc">Zakresy Top 10 / Top 100 / Wszystkie / liga, filtry pozycji, wyszukiwarka i forma z ostatnich kolejek.</span>
        <span class="e-go">Otwórz →</span>
      </button>
      {"<button class='entry' data-go='teams'><span class='e-num'>02 · Liga CMF</span><span class='e-name' style='font-size:18px'>Drużyny i duety</span><span class='e-desc'>Jesień, wiosna, suma, zmiana, medale na podium i rozwijany skład drużyny.</span><span class='e-go'>Otwórz →</span></button>" if has_league else ""}
      {"<button class='entry' data-go='fixtures'><span class='e-num'>03 · Terminarz</span><span class='e-name' style='font-size:18px'>Trudność meczów + Fixture Planner</span><span class='e-desc'>Skala 1–5 dla ataku i obrony, sortowanie po łatwości i para rotacyjna na wybrany zakres kolejek.</span><span class='e-go'>Otwórz →</span></button>" if has_fixtures else ""}
      {"<button class='entry' data-go='transfers'><span class='e-num'>04 · Transfery</span><span class='e-name' style='font-size:18px'>Kupna i sprzedaże</span><span class='e-desc'>Dwie listy top 15 z liczbą drużyn, udziałem procentowym i paskiem postępu.</span><span class='e-go'>Otwórz →</span></button>" if has_transfers else ""}
      {"<button class='entry' data-go='predictions'><span class='e-num'>05 · Prognoza</span><span class='e-name' style='font-size:18px'>17 kolumn na następną kolejkę</span><span class='e-desc'>Potencjał z percentyli, użyty FDR, xA/90, xG/90 i pewność prognozy.</span><span class='e-go'>Otwórz →</span></button>" if has_predictions else ""}
      {"<button class='entry' data-go='accuracy'><span class='e-num'>06 · Trafność</span><span class='e-name' style='font-size:18px'>MAE, hit rate i auto-tuning</span><span class='e-desc'>Karty metryk, wykres trendu MAE, szczegóły kolejki i status auto-tunera.</span><span class='e-go'>Otwórz →</span></button>" if has_accuracy else ""}
      {"<button class='entry' data-go='season'><span class='e-num'>07 · Sezon</span><span class='e-name' style='font-size:18px'>Historia ligi: pozycje i punkty</span><span class='e-desc'>Pozycje albo punkty łącznie, zakresy Top 5 / Dolne 5 i tabela z trendem.</span><span class='e-go'>Otwórz →</span></button>" if has_season else ""}
      <button class="entry" data-go="compare">
        <span class="e-num">08 · Porównanie</span>
        <span class="e-name" style="font-size:18px">Do trzech zawodników obok siebie</span>
        <span class="e-desc">Karty, tabela z wygranym w każdym wierszu, forma i FDR najbliższych meczów.</span>
        <span class="e-go">Otwórz →</span>
      </button>
      {"<a class='entry' href='archive/index.html' style='text-decoration:none'><span class='e-num'>09 · Archiwum</span><span class='e-name' style='font-size:18px'>Zamknięte sezony</span><span class='e-desc'>Poprzednie sezony w trybie tylko do odczytu.</span><span class='e-go'>Otwórz →</span></a>" if has_archive else ""}
    </div>
  </section>

  <!-- ============ WIDOKI ZAKŁADEK ============ -->
  <section id="v-players" class="view" aria-label="Zawodnicy">
    <div class="sec" style="margin-top:26px"><h2>Zawodnicy</h2><span class="rule"></span>
      <span class="sec-note">Kliknij nagłówek, żeby posortować</span></div>
    <div class="toolbar">
      {scope_toggle_html}
      <div class="seg seg-push" id="players-pos" role="group" aria-label="Pozycja">
        <span class="seg-label">Poz</span>
        <button class="seg-btn pos-btn active" data-pos="ALL">ALL</button>
        <button class="seg-btn pos-btn" data-pos="BR">GK</button>
        <button class="seg-btn pos-btn" data-pos="OBR">DEF</button>
        <button class="seg-btn pos-btn" data-pos="POM">MID</button>
        <button class="seg-btn pos-btn" data-pos="NAP">FWD</button>
      </div>
      <div class="search-wrap">
        <input class="input" id="players-q" type="search" placeholder="Szukaj zawodnika lub drużyny (min. 2 znaki)…" aria-label="Szukaj zawodnika">
      </div>
    </div>
    <div id="tab-players"></div>
  </section>
  <section id="v-teams" class="view" aria-label="Liga CMF">
    <div class="sec" style="margin-top:26px"><h2>Liga CMF</h2><span class="rule"></span>
      <span class="sec-note">Tabela sumaryczna: jesień + wiosna</span></div>
    <div class="toolbar">
      <div class="seg" id="league-view" role="group" aria-label="Widok">
        <span class="seg-label">Widok</span>
        <button class="seg-btn active" data-lview="teams">Drużyny</button>
        <button class="seg-btn" data-lview="duets">Duety</button>
      </div>
      <span class="hint">Kliknij strzałkę przy wierszu, żeby rozwinąć szczegóły.</span>
    </div>
    <div id="tab-teams"></div>
  </section>
  <section id="v-fixtures" class="view" aria-label="Terminarz"><div id="tab-fixtures"></div></section>
  <section id="v-transfers" class="view" aria-label="Transfery"><div id="tab-transfers"></div></section>
  <section id="v-predictions" class="view" aria-label="Prognoza"><div id="tab-predictions"></div></section>
  <section id="v-accuracy" class="view" aria-label="Trafność"><div id="tab-accuracy"></div></section>
  <section id="v-season" class="view" aria-label="Sezon"><div id="tab-season"></div></section>
  <section id="v-compare" class="view" aria-label="Porównanie"><div id="tab-compare"></div></section>
  </main>

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

// 📖 Normalizacja nazw drużyn — usuwa znaki diakrytyczne, mapuje polskie litery,
// lowercase, trim. Używana do bezpiecznego porównywania nazw drużyn z FDR_DATA.
function normalizeTeamNameJS(s) {{
  if (!s) return '';
  return s.normalize('NFKD')
          .replace(/[\u0300-\u036f]/g, '')
          .replace(/ł/g, 'l')
          .replace(/Ł/g, 'L')
          .toLowerCase()
          .trim();
}}

let tab = 'players', pos = 'ALL', scope = '{default_scope}';
let playersQ = '';
let selectedTeam = '';
let selectedDuet = '';
let currentTeamsView = 'teams';
// 📖 Stan porównywarki — tablica player_id wybranych zawodników (max 3)
let cmpSelected = [];
let sorts = {{
  players: {{col:'total_points', dir:'desc'}},
  teams: {{col:'_pos_order', dir:'asc'}},
  teams_list: {{col:'total_pts', dir:'desc'}},
  duets_list: {{col:'points', dir:'desc'}},
}};

function num(v) {{
  if (v === null || v === undefined || v === '') return 0;
  const n = typeof v === 'string' ? parseFloat(v) : v;
  return isNaN(n) ? 0 : n;
}}
function bar(val, max, color) {{
  const w = Math.min(val / max * 100, 100);
  return '<span class="bar"><span class="bar-track"><span class="bar-fill" style="width:'+w+'%;background:'+color+'"></span></span><span class="bar-val">'+val.toFixed(1)+'%</span></span>';
}}
function posBadge(p) {{
  const k = POS_ID[p] || p;
  const short = POS_MAP[k] || POS_MAP[p] || p;
  return '<span class="badge-pos pos-'+short+'">'+short+'</span>';
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

// Detail panel — kliknięcie na zawodnika pokazuje drużyny z ligi
function nameCell(name, pid, style, prefix) {{
  const attr = pid ? ' data-pid="'+pid+'"' : '';
  return '<td class="roster-trigger"'+attr+' style="cursor:pointer;'+(style||'')+'"><span class="name-cell">'+( prefix||'')+'<span class="team-name">'+name+'</span><span class="name-caret">▸</span></span></td>';
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
  const vals = form.map(f => f.pts || 0);
  const max = Math.max.apply(null, vals.concat([1]));
  const title = 'Ostatnie ' + form.length + ' kolejek: ' + form.map(f => 'K' + f.r + ': ' + (f.p !== false ? (f.pts || 0) : '—')).join(' · ');
  let h = '<span class="mini" title="' + title + '">';
  form.forEach(f => {{
    const pts = f.pts || 0;
    const played = f.p !== false;
    const ht = Math.max(3, Math.round(Math.max(pts, 0) / max * 24));
    const cls = (!played || pts <= 0) ? 'zero' : '';
    h += '<i class="' + cls + '" style="height:' + ht + 'px"></i>';
  }});
  h += '</span>';
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
    return '<tr class="detail-row"><td colspan="'+colspan+'"><div class="detail-in"><span class="c-dim" style="font-size:12px">Brak danych o drużynach ligowych</span></div></td></tr>';
  }}
  const sorted = [...r].sort((a,b) => (a.pos||999) - (b.pos||999));
  let chips = '';
  sorted.forEach(t => {{
    let badge = '';
    if (t.C) badge = '<span class="rc-badge rc-cap">C</span>';
    else if (t.R) badge = '<span class="rc-badge rc-res">RES</span>';
    else badge = '<span class="rc-badge rc-xi">XI</span>';
    const slug = t.team.replace(/-/g,' ');
    const posLabel = t.pos ? '<span class="rank" style="margin-right:2px">#'+t.pos+'</span>' : '';
    chips += '<span class="detail-tag">'+posLabel+'<span class="dt-nm">'+slug+'</span> '+badge+'</span>';
  }});
  let h = '<tr class="detail-row"><td colspan="'+colspan+'"><div class="detail-in">';
  h += '<span class="seg-label" style="margin-right:6px">Drużyny w lidze ('+r.length+')</span>'+chips;
  h += '</div></td></tr>';
  return h;
}}

function renderPlayers() {{
  let data = [...PLAYERS];
  if (pos !== 'ALL') data = data.filter(p => (POS_ID[p.position] || p.position) === pos);
  if (playersQ && playersQ.length >= 2) {{
    const q = playersQ.toLowerCase();
    data = data.filter(p => (p.name || '').toLowerCase().indexOf(q) >= 0 || (p.team || '').toLowerCase().indexOf(q) >= 0);
  }}
  if (!data.length) return '<div class="empty-msg">Brak danych</div>';

  // Buduj lookup ownership z aktualnego scope — dopasowanie po player_id
  const scopeData = DATA[scope] || {{}};
  const ownData = scopeData.ownership || [];
  const ownMap = {{}};
  ownData.forEach(o => {{ ownMap[o.player_id] = o; }});
  const hasOwn = ownData.length > 0;
  const hasLeague = LEAGUE_TEAMS.length > 0 && Object.keys(LEAGUE_POS_AVGS).length > 0;
  const scopeLabel = scopeData.label || scope;

  let h = '<div class="row-count">' + data.length + ' zawodników · zakres: ' + scopeLabel + ' · pozycja: ' + pos + '</div>';
  h += '<div class="panel" style="padding:0;overflow:hidden"><div class="tscroll"><table class="dt"><thead><tr>';
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
    const ptsC = pts >= 35 ? 'var(--accent)' : pts >= 25 ? 'var(--text)' : 'var(--text-muted)';
    const pppC = ppp >= 15 ? 'var(--up)' : ppp >= 10 ? 'var(--text)' : 'var(--text-muted)';
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
    const favgC = favg >= 6 ? 'var(--accent)' : favg >= 3 ? 'var(--up)' : 'var(--text-muted)';
    h += '<td class="text-right fw-600" style="color:'+favgC+'">'+(favg > 0 ? favg.toFixed(1) : '—')+'</td>';
    h += '<td class="text-right c-dim" style="font-size:13px">'+p.popularity_pct+'</td>';
    if (hasOwn) {{
      const sq = p._own_squad, st = p._own_starting, cp = p._own_captain;
      h += '<td>'+(sq > 0 ? bar(sq, 100, 'var(--up)') : '<span class="c-dim" style="font-size:12px">—</span>')+'</td>';
      h += '<td>'+(st > 0 ? bar(st, 100, 'var(--accent)') : '<span class="c-dim" style="font-size:12px">—</span>')+'</td>';
      h += '<td>'+(cp > 0 ? bar(cp, 40, 'var(--gold)') : '<span class="c-dim" style="font-size:12px">—</span>')+'</td>';
    }}
    h += '</tr>';
  }});
  h += '</tbody></table></div></div>';
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
  if (!avg) return '<span class="delta d-flat">—</span>';
  const d = pts - avg;
  const cls = d > 0 ? 'd-up' : d < 0 ? 'd-down' : 'd-flat';
  return '<span class="delta '+cls+'">'+(d>0?'+':'')+d.toFixed(0)+'</span>';
}}

function renderDuets() {{
  if (!DUETS_DATA.length) return '<div class="empty-msg">Brak duetów — dodaj pary drużyn w pliku konfiguracyjnym duets.json</div>';

  const dls = sorts.duets_list;
  function dlArrow(col) {{
    return dls.col === col ? (dls.dir === 'desc' ? ' ▼' : ' ▲') : '';
  }}

  const sortedDuets = [...DUETS_DATA].sort((a, b) => {{
    let av = a[dls.col], bv = b[dls.col];
    if (typeof av === 'string' || typeof bv === 'string') {{
      av = av == null ? '' : String(av);
      bv = bv == null ? '' : String(bv);
      if (av < bv) return dls.dir === 'desc' ? 1 : -1;
      if (av > bv) return dls.dir === 'desc' ? -1 : 1;
      return 0;
    }}
    av = num(av); bv = num(bv);
    if (av < bv) return dls.dir === 'desc' ? 1 : -1;
    if (av > bv) return dls.dir === 'desc' ? -1 : 1;
    return 0;
  }});

  // Numer ostatniej rozegranej kolejki — czytany z realnej historii ligi
  const _rounds = (LEAGUE_HISTORY && LEAGUE_HISTORY.rounds ? LEAGUE_HISTORY.rounds : []).map(r => r.round || 0);
  const lastRound = _rounds.length ? Math.max.apply(null, _rounds) : 0;

  let h = '<div class="row-count">' + sortedDuets.length + ' duetów' + (lastRound ? ' · kolejka ' + lastRound : '') + '</div>';
  h += '<div class="panel" style="padding:0;overflow:hidden"><div class="tscroll"><table class="dt"><thead><tr>';
  h += '<th class="text-center sortable" data-tab="duets_list" data-col="rank">#'+dlArrow('rank')+'</th>';
  h += '<th class="text-left sortable" data-tab="duets_list" data-col="managers">Duet'+dlArrow('managers')+'</th>';
  h += '<th class="text-left sortable c-dim" data-tab="duets_list" data-col="group_name">Grupa'+dlArrow('group_name')+'</th>';
  h += '<th class="text-right sortable" data-tab="duets_list" data-col="points">Punkty'+dlArrow('points')+'</th>';
  h += '<th class="text-right sortable c-dim" data-tab="duets_list" data-col="prev_points">Poprzednia'+dlArrow('prev_points')+'</th>';
  h += '<th class="text-right sortable" data-tab="duets_list" data-col="gain">Zysk'+dlArrow('gain')+'</th>';
  h += '<th class="text-center sortable" data-tab="duets_list" data-col="rank_change">Zmiana'+dlArrow('rank_change')+'</th>';
  h += '</tr></thead><tbody>';

  sortedDuets.forEach((d, i) => {{
    // Prawdziwe miejsce z danych (null gdy brak) — nie mylić z pozycją wiersza
    const pos = (d.rank === null || d.rank === undefined) ? (i + 1) : d.rank;
    const isOpen = d.managers === selectedDuet;
    const hasData = d.points !== null && d.points !== undefined;
    const hasPrev = d.prev_points !== null && d.prev_points !== undefined;

    h += '<tr style="cursor:pointer" data-duet="'+encodeURIComponent(d.managers)+'">';
    h += '<td class="text-center">'+(pos <= 3 ? '<span class="medal m'+pos+'">'+pos+'</span>' : '<span class="rank">'+pos+'</span>')+'</td>';
    h += '<td><span class="team-cell"><button class="expand-btn'+(isOpen?' open':'')+'" aria-label="Rozwiń duet">▶</button><span class="team-name">'+d.managers+'</span></span></td>';
    h += '<td class="text-left c-muted" style="font-size:12px">'+(d.group_name ? d.group_name : '<span class="c-muted">—</span>')+'</td>';

    // Pusty stan: brak danych = kreska, nigdy 0
    h += '<td class="text-right fw-700" style="font-size:15px">'+(hasData ? d.points : '—')+'</td>';
    h += '<td class="text-right c-muted">'+(hasPrev ? d.prev_points : '—')+'</td>';

    // Zysk za ostatnią kolejkę — pill w kolorach --up / --down / neutralny
    let gainHtml = '<span class="delta d-flat">—</span>';
    if (d.gain !== null && d.gain !== undefined) {{
      if (d.gain > 0) gainHtml = '<span class="delta d-up">+'+d.gain+'</span>';
      else if (d.gain < 0) gainHtml = '<span class="delta d-down">'+d.gain+'</span>';
      else gainHtml = '<span class="delta d-flat">0</span>';
    }}
    h += '<td class="text-right">'+gainHtml+'</td>';

    const rc = d.rank_change || 0;
    let changeHtml = '';
    if (rc > 0) changeHtml = '<span class="chg chg-up">▲'+rc+'</span>';
    else if (rc < 0) changeHtml = '<span class="chg chg-down">▼'+Math.abs(rc)+'</span>';
    else changeHtml = '<span class="chg chg-flat">—</span>';
    h += '<td class="text-center">'+changeHtml+'</td>';
    h += '</tr>';

    if (isOpen) {{
      h += '<tr class="detail-row"><td colspan="7"><div class="detail-in">';
      h += '<span class="detail-tag"><span class="dt-nm">'+d.team1_name+'</span></span>';
      h += '<span class="detail-tag"><span class="dt-nm">'+d.team2_name+'</span></span>';
      h += '<span class="detail-tag"><span class="dt-nm">Suma duetu</span><span class="dt-pts">'+(hasData ? d.points + ' pkt' : '—')+'</span></span>';
      h += '<span class="detail-tag"><span class="dt-nm">Poprzednia kolejka</span><span class="dt-pts">'+(hasPrev ? d.prev_points + ' pkt' : '—')+'</span></span>';
      h += '</div></td></tr>';
    }}
  }});

  h += '</tbody></table></div></div>';
  return h;
}}

function renderTeams() {{
  if (!LEAGUE_TEAMS.length) return '<div class="empty-msg">Brak danych o drużynach ligi</div>';

  if (currentTeamsView === 'duets') return renderDuets();

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
    if (p.C) nameStyle += ';color:var(--gold)';
    let r = '<tr><td class="c-muted fw-600">'+(idx+1)+'</td>';
    r += nameCell(p.name, p.pid, nameStyle, p.C ? '<span class="rc-badge rc-cap" style="margin-right:4px">C</span> ' : '');
    r += '<td class="text-center">'+posBadge(pk)+'</td>';
    r += '<td class="text-right c-muted">'+price.toFixed(1)+'M</td>';
    r += '<td class="text-right fw-700">'+pts+'</td>';
    r += '<td class="text-center">'+diffBadge(pts, POS_AVGS[pk])+'</td>';
    r += '<td class="text-center">'+diffBadge(pts, LEAGUE_POS_AVGS[pk])+'</td>';
    const favg = p._form_avg;
    const favgC = favg >= 6 ? 'var(--accent)' : favg >= 3 ? 'var(--up)' : 'var(--text-muted)';
    r += '<td class="text-center">'+formChart(p.form, true)+'</td>';
    r += '<td class="text-right fw-600" style="color:'+favgC+'">'+(favg > 0 ? favg.toFixed(1) : '—')+'</td>';
    const imp = p._imp != null ? p._imp : 100;
    const impColor = imp >= 70 ? 'var(--up)' : imp >= 30 ? 'var(--gold)' : 'var(--down)';
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
  let h = '<div class="row-count">' + sortedTeams.length + ' drużyn · jesień + wiosna</div>';
  h += '<div class="panel" style="padding:0;overflow:hidden"><div class="tscroll"><table class="dt"><thead><tr>';
  h += '<th class="text-center sortable" data-tab="teams_list" data-col="hockey_pos">#'+tlArrow('hockey_pos')+'</th>';
  h += '<th class="text-left sortable" data-tab="teams_list" data-col="name">Drużyna'+tlArrow('name')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="autumn_pts">Jesień'+tlArrow('autumn_pts')+'</th>';
  h += '<th class="text-right sortable c-dim" data-tab="teams_list" data-col="best_gw_autumn">🔥 J'+tlArrow('best_gw_autumn')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="spring_pts">Wiosna'+tlArrow('spring_pts')+'</th>';
  h += '<th class="text-right sortable c-dim" data-tab="teams_list" data-col="best_gw_spring">🔥 W'+tlArrow('best_gw_spring')+'</th>';
  h += '<th class="text-right sortable" data-tab="teams_list" data-col="total_pts">SUMA'+tlArrow('total_pts')+'</th>';
  h += '<th class="text-center sortable" data-tab="teams_list" data-col="rank_change">Zmiana'+tlArrow('rank_change')+'</th>';
  h += '</tr></thead><tbody>';

  sortedTeams.forEach((t, i) => {{
    const pos = t.hockey_pos || (i + 1);
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
    h += '<td class="text-center">' + (pos <= 3 ? '<span class="medal m'+pos+'">'+pos+'</span>' : '<span class="rank">'+pos+'</span>') + '</td>';
    h += '<td><span class="team-cell">' + (hasPlayers ? '<button class="expand-btn'+(isOpen?' open':'')+'" aria-label="Rozwiń skład">▶</button>' : '') + '<span class="team-name">' + tName + '</span>' + (dimRow ? ' <span class="c-dim" style="font-size:10px">(nie gra)</span>' : '') + '</span></td>';
    h += '<td class="text-right c-muted">' + (t.autumn_pts||0) + '</td>';
    h += '<td class="text-right c-dim" style="font-size:12px">' + (t.best_gw_autumn > 0 ? t.best_gw_autumn : '—') + '</td>';
    h += '<td class="text-right c-muted">' + (t.spring_pts||0) + '</td>';
    h += '<td class="text-right c-dim" style="font-size:12px">' + (t.best_gw_spring > 0 ? t.best_gw_spring : '—') + '</td>';
    h += '<td class="text-right fw-700" style="font-size:15px">' + (t.total_pts||0) + '</td>';

    const rc = t.rank_change || 0;
    let changeHtml = '';
    if (rc > 0) changeHtml = '<span class="chg chg-up">▲' + rc + '</span>';
    else if (rc < 0) changeHtml = '<span class="chg chg-down">▼' + Math.abs(rc) + '</span>';
    else changeHtml = '<span class="chg chg-flat">—</span>';
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

      h += '<tr class="detail-row"><td colspan="8"><div style="padding:16px 18px"><div class="tscroll"><table class="dt"><thead><tr>';
      h += '<th class="text-left">#</th>';
      h += '<th class="text-left sortable" data-tab="teams" data-col="name">Zawodnik'+arrow('teams','name')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_pos_order">Poz'+arrow('teams','_pos_order')+'</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="price">Cena'+arrow('teams','price')+'</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="pts">Punkty'+arrow('teams','pts')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_diff_global" title="Punkty zawodnika minus średnia punktów wszystkich grających na tej pozycji">±Avg'+arrow('teams','_diff_global')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_diff_league" title="Punkty zawodnika minus średnia punktów graczy na tej pozycji w drużynach z Twojej ligi">±Liga'+arrow('teams','_diff_league')+'</th>';
      h += '<th class="text-center">Forma</th>';
      h += '<th class="text-right sortable" data-tab="teams" data-col="_form_avg" title="Średnia punktów z rozegranych meczów (ostatnie 5 kolejek przed obecną)">Średnia'+arrow('teams','_form_avg')+'</th>';
      h += '<th class="text-center sortable" data-tab="teams" data-col="_imp" title="Differential ownership — im wyższy %, tym mniej managerów w lidze posiada tego zawodnika">Imp'+arrow('teams','_imp')+'</th>';
      h += '</tr></thead><tbody>';

      const starters = sortGroup(t.players.filter(p => !p.R));
      const reserves = sortGroup(t.players.filter(p => p.R));

      starters.forEach((p, idx) => {{ h += renderSquadRow(p, idx); }});
      if (reserves.length) {{
        h += '<tr><td colspan="'+NCOLS+'" style="padding:6px 0;border-top:1px dashed var(--border-strong)"><span class="c-dim" style="font-size:11px;text-transform:uppercase;letter-spacing:1px">Ławka rezerwowych</span></td></tr>';
        reserves.forEach((p, idx) => {{ h += renderSquadRow(p, starters.length + idx); }});
      }}

      // Podsumowanie
      const totalPts = starters.reduce((s,p) => s + (p.pts||0), 0);
      const totalDiffG = t.players.reduce((s,p) => s + (p._diff_global||0), 0);
      const totalDiffL = t.players.reduce((s,p) => s + (p._diff_league||0), 0);
      h += '<tr style="border-top:2px solid var(--border-strong)"><td colspan="4" class="fw-700" style="text-align:right;padding-top:10px">Razem:</td>';
      h += '<td class="text-right fw-700" style="padding-top:10px">'+totalPts+'</td>';
      const gCls = totalDiffG > 0 ? 'd-up' : totalDiffG < 0 ? 'd-down' : 'd-flat';
      const lCls = totalDiffL > 0 ? 'd-up' : totalDiffL < 0 ? 'd-down' : 'd-flat';
      h += '<td class="text-center" style="padding-top:10px"><span class="delta '+gCls+'">'+(totalDiffG>0?'+':'')+totalDiffG.toFixed(0)+'</span></td>';
      h += '<td class="text-center" style="padding-top:10px"><span class="delta '+lCls+'">'+(totalDiffL>0?'+':'')+totalDiffL.toFixed(0)+'</span></td>';
      const avgImp = t.players.length > 0 ? Math.round(t.players.reduce((s,p) => s + (p._imp||0), 0) / t.players.length) : 0;
      const avgImpColor = avgImp >= 70 ? 'var(--up)' : avgImp >= 30 ? 'var(--gold)' : 'var(--down)';
      h += '<td colspan="2"></td><td class="text-center fw-700" style="padding-top:10px;color:'+avgImpColor+'">Ø '+avgImp+'%</td></tr>';

      h += '</tbody></table></div></div></td></tr>';
    }}
  }});

  h += '</tbody></table></div></div>';
  return h;
}}

// ============ FDR (Fixture Difficulty Rating) ============
// Skala trudności 1-5 używa tokenów Concept C (zielony → czerwony, tusz zawsze ciemny).
const FDR_COLORS = {{
  1: {{bg:'var(--fdr-1)', fg:'var(--fdr-ink)'}},
  2: {{bg:'var(--fdr-2)', fg:'var(--fdr-ink)'}},
  3: {{bg:'var(--fdr-3)', fg:'var(--fdr-ink)'}},
  4: {{bg:'var(--fdr-4)', fg:'var(--fdr-ink)'}},
  5: {{bg:'var(--fdr-5)', fg:'var(--fdr-ink)'}},
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
      +'<div style="text-align:center;background:var(--surface-inset);border-radius:8px;padding:8px"><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase">Atak (D)</div><div style="font-size:20px;font-weight:800;color:var(--accent)">'+str.attack_h+'</div></div>'
      +'<div style="text-align:center;background:var(--surface-inset);border-radius:8px;padding:8px"><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase">Atak (W)</div><div style="font-size:20px;font-weight:800;color:var(--accent)">'+str.attack_a+'</div></div>'
      +'<div style="text-align:center;background:var(--surface-inset);border-radius:8px;padding:8px"><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase">Obrona (D)</div><div style="font-size:20px;font-weight:800;color:var(--down)">'+str.defense_h+'</div></div>'
      +'<div style="text-align:center;background:var(--surface-inset);border-radius:8px;padding:8px"><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase">Obrona (W)</div><div style="font-size:20px;font-weight:800;color:var(--down)">'+str.defense_a+'</div></div>'
      +'</div>';
  }}
  wrap.innerHTML = '<div class="ft-modal"><button class="ft-modal-close" id="ftClose">✕</button>'
    +'<h3>'+abbr+' — '+team+'</h3>'
    +'<div style="display:flex;gap:24px;margin:16px 0">'
    +'<div style="flex:1;text-align:center"><div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">Strzelone (GF)</div><div style="font-size:28px;font-weight:800;color:var(--accent)">'+gf+'</div></div>'
    +'<div style="flex:1;text-align:center"><div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">Stracone (GA)</div><div style="font-size:28px;font-weight:800;color:var(--down)">'+ga+'</div></div>'
    +'</div>'
    +strengthHtml
    +'<div style="font-size:11px;color:var(--text-dim);text-align:center;margin-top:12px">Siła >1.0 = powyżej średniej ligowej &nbsp;|&nbsp; Dane z 90minut.pl</div>'
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

  let h = '<div class="sec" style="margin-top:26px"><h2>Trudność meczów</h2><span class="rule"></span>'
    + '<span class="sec-note">ATK = siła ataku rywala (dla DEF/GK) · DEF = siła obrony rywala (dla FWD/MID)</span></div>';

  // Legenda
  h += '<div class="legend">';
  [1,2,3,4,5].forEach(r => {{
    h += '<span class="li"><span class="fdr fdr-'+r+'">'+r+'</span>'+FDR_LABELS[r]+'</span>';
  }});
  h += '<span class="li" style="margin-left:auto">Ta sama skala działa w Prognozie i Porównaniu.</span>';
  h += '</div>';

  // Sort toggle
  h += '<div class="toolbar"><div class="seg" id="fix-sort" role="group" aria-label="Sortowanie">';
  h += '<span class="seg-label">Sortuj</span>';
  h += '<button class="seg-btn fdr-sort-btn" data-fdrsort="alpha">A–Z</button>';
  h += '<button class="seg-btn fdr-sort-btn" data-fdrsort="def">Najłatwiejszy dla ataku</button>';
  h += '<button class="seg-btn fdr-sort-btn" data-fdrsort="atk">Najłatwiejszy dla obrony</button>';
  h += '</div></div>';

  // Tabela
  h += '<div class="panel" style="padding:0;overflow:hidden"><div class="tscroll"><table class="dt"><thead><tr>';
  h += '<th class="text-left">Drużyna</th>';
  h += '<th class="text-right">Σ ATK</th>';
  h += '<th class="text-right">Σ DEF</th>';
  gws.forEach(gw => {{ h += '<th class="text-center">K'+gw+'</th>'; }});
  h += '</tr></thead><tbody>';

  teams.forEach((team, ti) => {{
    h += '<tr>';
    h += '<td class="fdr-team-click" data-fdrteam="'+ti+'" style="cursor:pointer"><span class="team-name">'+team.short+'</span></td>';

    // Σ ATK
    const avgAtk = gws.length ? (team.total_atk / gws.length) : 3;
    const atkColor = avgAtk <= 2 ? 'var(--up)' : avgAtk <= 3 ? 'var(--text-muted)' : 'var(--down)';
    h += '<td class="text-right fw-700" style="color:'+atkColor+'">'+team.total_atk+'</td>';

    // Σ DEF
    const avgDef = gws.length ? (team.total_def / gws.length) : 3;
    const defColor = avgDef <= 2 ? 'var(--up)' : avgDef <= 3 ? 'var(--text-muted)' : 'var(--down)';
    h += '<td class="text-right fw-700" style="color:'+defColor+'">'+team.total_def+'</td>';

    // Dual ATK/DEF tiles per gameweek
    team.fixtures.forEach(f => {{
      if (!f.opponent) {{
        h += '<td class="text-center">—</td>';
        return;
      }}
      const ha = f.home ? 'D' : 'W';
      h += '<td class="text-center" title="'+f.opponent+' ('+(f.home ? 'dom' : 'wyjazd')+') '+f.date+'">';
      h += '<span class="opp"><span class="o-code"><span class="o-nm">'+f.opponent_short+'</span><span class="hw'+(f.home?' d':'')+'">'+ha+'</span></span>';
      h += '<span style="display:flex;gap:3px">';
      h += '<span class="fdr fdr-'+f.atk+'" title="ATK">A'+f.atk+'</span>';
      h += '<span class="fdr fdr-'+f.def+'" title="DEF">D'+f.def+'</span>';
      h += '</span></span></td>';
    }});

    h += '</tr>';
  }});

  h += '</tbody></table></div></div>';
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
  h += '<div class="sec"><h2>Fixture Planner</h2><span class="rule"></span>'
    + '<span class="sec-note">18 drużyn Ekstraklasy · zakres kolejek</span></div>';
  h += '<p class="planner-intro">Wybierz zakres kolejek i tryb trudności. <b>ATK</b> ma znaczenie dla bramkarzy i obrońców (liczy się siła ataku rywala), <b>DEF</b> dla pomocników i napastników (siła obrony rywala), <b>MIX</b> uśrednia oba. Kafelki 1–5 używają tej samej zielono-czerwonej skali, co reszta dashboardu.</p>';

  // Kontrolki: zakres kolejek + tryb pozycyjny
  h += '<div class="fp-controls">';
  h += '<div class="field"><label for="fp-from">Od</label><select class="input fp-gw-from" id="fp-from">';
  gws.forEach(g => {{ h += '<option value="'+g+'"'+(g===fpGwFrom?' selected':'')+'>K'+g+'</option>'; }});
  h += '</select></div>';
  h += '<div class="field"><label for="fp-to">Do</label><select class="input fp-gw-to" id="fp-to">';
  gws.forEach(g => {{ h += '<option value="'+g+'"'+(g===fpGwTo?' selected':'')+'>K'+g+'</option>'; }});
  h += '</select></div>';

  // 📖 Tryb pozycyjny: ATK (dla napastników/pomocników), DEF (dla obrońców/bramkarzy), MIX (średnia)
  h += '<div class="seg" id="fp-mode" role="group" aria-label="Tryb">';
  h += '<span class="seg-label">Tryb</span>';
  h += '<button class="seg-btn fp-mode-btn'+(fpMode==='atk'?' active':'')+'" data-fpmode="atk">ATK</button>';
  h += '<button class="seg-btn fp-mode-btn'+(fpMode==='def'?' active':'')+'" data-fpmode="def">DEF</button>';
  h += '<button class="seg-btn fp-mode-btn'+(fpMode==='mix'?' active':'')+'" data-fpmode="mix">MIX</button>';
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
  h += '<div class="panel" style="padding:0;overflow:hidden"><div class="tscroll"><table class="dt"><thead><tr>';
  h += '<th class="text-left sortable fp-sort'+thClass('team')+'" data-fpcol="team">Drużyna'+thArrow('team')+'</th>';
  selectedGws.forEach(gw => {{
    h += '<th class="text-center sortable fp-sort'+thClass('gw'+gw)+'" data-fpcol="gw'+gw+'">K'+gw+thArrow('gw'+gw)+'</th>';
  }});
  h += '<th class="text-right sortable fp-sort'+thClass('sum')+'" data-fpcol="sum">Σ FDR'+thArrow('sum')+'</th>';
  h += '<th class="text-right sortable fp-sort'+thClass('avg')+'" data-fpcol="avg">Śr.'+thArrow('avg')+'</th>';
  h += '<th class="text-right sortable fp-sort'+thClass('easy')+'" data-fpcol="easy">Łatwych'+thArrow('easy')+'</th>';
  h += '<th class="text-right sortable fp-sort'+thClass('hard')+'" data-fpcol="hard">Trudnych'+thArrow('hard')+'</th>';
  h += '</tr></thead><tbody>';

  planData.forEach((team, ti) => {{
    const isSelected = fpSelected.includes(team.name);
    h += '<tr>';
    h += '<td class="fp-team-cell'+(isSelected ? ' fp-selected' : '')+'" data-fpteam="'+team.name+'" style="cursor:pointer"><span class="team-name">'+team.short+'</span></td>';

    // Kafelki FDR per kolejka
    team.fixtures.forEach((f, fi) => {{
      if (!f || !f.opponent) {{
        h += '<td class="text-center">—</td>';
        return;
      }}
      const fdr = team.fdrValues[fi];
      const ha = f.home ? 'D' : 'W';
      h += '<td class="text-center" title="'+f.opponent+' ('+(f.home?'dom':'wyjazd')+') '+f.date+'">';
      h += '<span class="opp"><span class="o-code"><span class="o-nm">'+f.opponent_short+'</span><span class="hw'+(f.home?' d':'')+'">'+ha+'</span></span><span class="fdr fdr-'+fdr+'">'+fdr+'</span></span>';
      h += '</td>';
    }});

    // Suma FDR
    const sumColor = team.avg <= 2.5 ? 'var(--up)' : team.avg <= 3.5 ? 'var(--text-muted)' : 'var(--down)';
    h += '<td class="text-right fw-700" style="color:'+sumColor+'">'+team.sum+'</td>';

    // Średnia FDR (kolorowana)
    const avgColor = team.avg < 2.5 ? 'var(--up)' : team.avg > 3.5 ? 'var(--down)' : 'var(--text-muted)';
    h += '<td class="text-right fw-700" style="color:'+avgColor+'">'+team.avg.toFixed(1)+'</td>';

    // Łatwych / Trudnych
    h += '<td class="text-right fw-700" style="color:var(--up)">'+team.easy+'</td>';
    h += '<td class="text-right fw-700" style="color:var(--down)">'+team.hard+'</td>';

    h += '</tr>';
  }});

  h += '</tbody></table></div></div>';

  // 📖 Szybki widok "Najlepsze drużyny na X kolejek" — podsumowanie (insights)
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

  const insightList = (list) => list.slice(0,3).map((t, i) =>
    '<li><span class="ii">0'+(i+1)+'</span>'+t.short+'<span class="iv">'+t.avg.toFixed(1)+'</span></li>'
  ).join('');

  h += '<div class="insights">';
  h += '<div class="insight"><h4>Najłatwiejszy (ATK)</h4><ol>'+insightList(atkRanked)+'</ol></div>';
  h += '<div class="insight"><h4>Najłatwiejszy (DEF)</h4><ol>'+insightList(defRanked)+'</ol></div>';
  h += '<div class="insight"><h4>Najtrudniejszy</h4><ol>'+insightList(hardRanked)+'</ol></div>';
  h += '<div class="insight"><h4>Najlepsza para rotacyjna</h4>';
  if (bestPair.t1) {{
    const bestPct = selectedGws.length > 0 ? Math.round(bestPair.coverage / selectedGws.length * 100) : 0;
    h += '<div class="rot-pair">'+bestPair.t1+' <span class="c-dim">+</span> '+bestPair.t2+'<span class="rot-pct">'+bestPct+'%</span></div>';
  }}
  if (fpSelected.length === 2) {{
    const s1 = planData.find(t => t.name === fpSelected[0]);
    const s2 = planData.find(t => t.name === fpSelected[1]);
    if (s1 && s2) {{
      let cov = 0;
      for (let i = 0; i < selectedGws.length; i++) {{
        if (s1.fdrValues[i] <= 2 || s2.fdrValues[i] <= 2) cov++;
      }}
      h += '<div class="rot-note">Wybrana para '+s1.short+' + '+s2.short+': pokrycie '+cov+'/'+selectedGws.length+' kolejek.</div>';
    }}
  }} else if (fpSelected.length === 1) {{
    h += '<div class="rot-note">Kliknij drugą drużynę, aby zobaczyć wynik rotacji.</div>';
  }} else {{
    h += '<div class="rot-note">Kliknij dwie drużyny w tabeli, aby sprawdzić rotację.</div>';
  }}
  h += '</div>';
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

  let h = '<div class="list-head '+(title.indexOf('kupna')>=0?'buy':'sell')+'"><h3>'+title+'</h3><span class="lh-note">Top 15</span></div>';
  h += '<div class="tscroll"><table class="dt"><thead><tr>';
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
    h += '<td><span class="bar"><span class="bar-track" style="width:80px"><span class="bar-fill" style="width:' + barW + '%;background:' + color + '"></span></span>';
    h += '<span class="bar-val">' + p.count + ' (' + pct.toFixed(1) + '%)</span></span></td>';
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

  let h = '<div class="sec" style="margin-top:26px"><h2>Transfery</h2><span class="rule"></span>'
    + '<span class="sec-note">Kto wchodzi, kto wychodzi · K' + prevGw + ' → K' + gw + '</span></div>';

  // Toolbar
  h += '<div class="toolbar">';
  h += '<div class="seg" id="tr-pos" role="group" aria-label="Pozycja">';
  h += '<span class="seg-label">Poz</span>';
  ['ALL','BR','OBR','POM','NAP'].forEach(p => {{
    const labels = {{ALL:'ALL',BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD'}};
    const active = trPos === p ? ' active' : '';
    h += '<button class="seg-btn pos-btn tr-pos-btn' + active + '" data-trpos="' + p + '" data-pos="' + p + '">' + labels[p] + '</button>';
  }});
  h += '</div>';
  h += '<span class="gw-badge" style="margin-left:auto">K' + prevGw + ' → K' + gw + ' · ' + leagueCount + ' drużyn</span>';
  h += '</div>';

  // Two tables side by side
  h += '<div class="transfer-grid">';
  h += '<div class="panel">' + renderTransfersTable(tin, leagueCount, 'Najpopularniejsze kupna', 'var(--up)') + '</div>';
  h += '<div class="panel">' + renderTransfersTable(tout, leagueCount, 'Najpopularniejsze sprzedaże', 'var(--down)') + '</div>';
  h += '</div>';

  return h;
}}

function renderPredictions() {{
  if (!PREDICTIONS || !PREDICTIONS.length) return '<div class="empty-msg">Brak danych prognoz — sprawdź czy predictor.py jest dostępny i dane FDR zostały obliczone</div>';

  let data = [...PREDICTIONS].filter(p => p.predicted_points !== null && p.predicted_points !== undefined);
  if (predPos !== 'ALL') data = data.filter(p => (POS_ID[p.position] || p.position) === predPos);
  if (!data.length) return '<div class="empty-msg">Brak prognoz dla wybranej pozycji</div>';
  const hasRealPredictions = data.some(p => !p.unavailable);
  if (!hasRealPredictions) return '<div class="empty-msg">Brak prognoz — potrzebne minimum 2 rozegrane kolejki</div>';

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
    if (val >= 8) return 'background:var(--tint-up);color:var(--up)';
    if (val >= 6) return 'background:var(--tint-accent);color:var(--accent)';
    if (val >= 4) return 'background:var(--tint-gold);color:var(--conf-med)';
    if (val >= 2) return 'background:var(--tint-soft);color:var(--text-muted)';
    return 'background:var(--tint-soft);color:var(--text-dim)';
  }}

  // Percentyle 0-100 — analogiczny gradient do predGradient
  function potentialGradient(val) {{
    if (val >= 80) return 'background:var(--tint-up);color:var(--up)';
    if (val >= 60) return 'background:var(--tint-accent);color:var(--accent)';
    if (val >= 40) return 'background:var(--tint-gold);color:var(--conf-med)';
    if (val >= 20) return 'background:var(--tint-soft);color:var(--text-muted)';
    return 'background:var(--tint-soft);color:var(--text-dim)';
  }}

  function fdrTile(val) {{
    return '<span class="fdr fdr-'+val+'">'+val+'</span>';
  }}

  function fdrUsedLabel(position, fdr_mod) {{
    const pk = POS_ID[position] || position;
    let label = 'MIX';
    if (pk === 'NAP') label = 'DEF';
    else if (pk === 'OBR' || pk === 'BR') label = 'ATK';
    const color = fdr_mod > 1.0 ? 'var(--up)' : fdr_mod < 1.0 ? 'var(--down)' : 'var(--text-muted)';
    return '<span class="used" style="color:'+color+'">'+label+' ×'+fdr_mod.toFixed(2)+'</span>';
  }}

  // Kolumna adaptacyjna "Aktywność" — wzorowana na fdrUsedLabel
  function activityLabel(position, shots, chances, csRate, gcPer90) {{
    const pk = POS_ID[position] || position;
    // NAP/POM: strzały/90, w tooltipie szanse stworzone/90
    if (pk === 'NAP' || pk === 'POM') {{
      const s = shots != null ? shots.toFixed(1) : '—';
      const cc = chances != null ? chances.toFixed(1) : '—';
      return '<span title="' + cc + ' szans stworzonych">' + s + '</span>';
    }}
    // OBR/BR: czyste konta/90, w tooltipie stracone/90
    if (pk === 'OBR' || pk === 'BR') {{
      const cs = csRate != null ? csRate.toFixed(1) : '—';
      const gc = gcPer90 != null ? gcPer90.toFixed(1) : '—';
      return '<span title="' + gc + ' straconych/90">' + cs + '</span>';
    }}
    return '—';
  }}

  function confidenceBadge(conf) {{
    const map = {{
      high: {{label:'Wysoka', cls:'conf-high'}},
      medium: {{label:'Średnia', cls:'conf-medium'}},
      low: {{label:'Niska', cls:'conf-low'}},
      insufficient_data: {{label:'insuf.', cls:'conf-medium'}},
      unavailable: {{label:'niedostępny', cls:'conf-low'}},
    }};
    const m = map[conf] || map.low;
    return '<span class="conf '+m.cls+'">'+m.label+'</span>';
  }}

   let h = '<div class="page-title">Prognoza Punktów — Następna Kolejka</div>';
   h += '<div class="page-sub"><span class="mono">Powered by <a href="https://arturkarpinski.com/ekstraklasa-scouting/" target="_blank" rel="noopener">Ekstraklasa Scouting</a></span></div>';

  // Metoda
   h += '<div class="method">';
   h += '<span class="m-row"><b>Jak czytać FDR:</b> NAP/POM dostaje <code>FDR DEF</code> rywala, BR/OBR dostaje <code>FDR ATK</code> rywala.</span>';
   h += '<span class="m-row"><b>Potencjał</b> = średnia percentyli pozycyjnych zawodnika (0–100).</span>';
   h += '<span class="m-row"><b>Wzory punktacji:</b> <code>BR = obrony + CS</code> · <code>OBR = CS + stracone + xG + xA + szanse</code> · <code>POM/NAP = strzały + szanse</code></span>';
   h += '<span class="m-row">Skala trudności 1–5 (zielony → czerwony) jest identyczna jak w Terminarzu i Porównaniu.</span>';
   h += '</div>';

  // Position filters
  h += '<div class="toolbar">';
  h += '<div class="seg" id="pred-pos" role="group" aria-label="Pozycja">';
  h += '<span class="seg-label">Poz</span>';
  ['ALL','BR','OBR','POM','NAP'].forEach(p => {{
    const labels = {{ALL:'ALL',BR:'GK',OBR:'DEF',POM:'MID',NAP:'FWD'}};
    const active = predPos === p ? ' active' : '';
    h += '<button class="seg-btn pos-btn pred-pos-btn'+active+'" data-predpos="'+p+'" data-pos="'+p+'">'+labels[p]+'</button>';
  }});
  h += '</div>';
  h += '<span class="row-count" style="margin-left:auto;margin-bottom:0">'+data.length+' zawodników</span>';
  h += '</div>';

  // Table
  h += '<div class="panel" style="padding:0;overflow:hidden"><div class="tscroll"><table class="dt"><thead><tr>';
  h += '<th class="text-left">#</th>';
  h += '<th class="text-left sortable" data-tab="predictions" data-col="name">Zawodnik'+predArrow('name')+'</th>';
  h += '<th class="text-center sortable" data-tab="predictions" data-col="position">Poz'+predArrow('position')+'</th>';
  h += '<th class="text-left sortable" data-tab="predictions" data-col="team">Drużyna'+predArrow('team')+'</th>';
   h += '<th class="text-center sortable" data-tab="predictions" data-col="next_opponent">Rywal'+predArrow('next_opponent')+'</th>';
  h += '<th class="text-center">D/W</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="predicted_points">Prognoza'+predArrow('predicted_points')+'</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="base_avg">Śr. pkt'+predArrow('base_avg')+'</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="karpinski_rating">Ocena'+predArrow('karpinski_rating')+'</th>';
   h += '<th class="text-center sortable" data-tab="predictions" data-col="fdr_atk_opponent">FDR ATK'+predArrow('fdr_atk_opponent')+'</th>';
   h += '<th class="text-center sortable" data-tab="predictions" data-col="fdr_def_opponent">FDR DEF'+predArrow('fdr_def_opponent')+'</th>';
   h += '<th class="text-center sortable" data-tab="predictions" data-col="used_fdr_value">Użyty FDR'+predArrow('used_fdr_value')+'</th>';
   h += '<th class="text-center sortable" data-tab="predictions" data-col="potential_value">Potencjał'+predArrow('potential_value')+'</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="avg_minutes">Śr. min'+predArrow('avg_minutes')+'</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="xa_per_90">xA/90'+predArrow('xa_per_90')+'</th>';
  h += '<th class="text-right sortable" data-tab="predictions" data-col="xg_per_90">xG/90'+predArrow('xg_per_90')+'</th>';

   h += '<th class="text-center sortable" data-tab="predictions" data-col="confidence_rank">Pewność'+predArrow('confidence_rank')+'</th>';
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
    h += '<td class="fw-600" title="'+detail.replace(/"/g,'&quot;')+'">'+(p.karpinski_slug ? '<a href="https://arturkarpinski.com/ekstraklasa-scouting/#sel='+p.karpinski_slug+'" target="_blank" rel="noopener" style="color:inherit;text-decoration:none;border-bottom:1px dotted var(--text-dim)" title="Profil na ekstraklasa-scouting">'+p.name+'</a>' : p.name)+(isUnavailable ? ' <span style="font-size:11px;color:var(--down)">⛔ '+unavailableReason+'</span>' : '')+'</td>';
    h += '<td class="text-center">'+posBadge(pk)+'</td>';
    h += '<td class="c-muted" style="font-size:13px">'+p.team+'</td>';

    // Rywal z FDR kolorem (używamy wyższego FDR)
    const oppName = p.opponent_short || p.next_opponent || '';
    const oppFdr = Math.max(oppFdrAtk, oppFdrDef);
    h += '<td class="text-center"><span class="opp"><span class="o-code"><span class="o-nm">'+oppName+'</span></span><span class="fdr fdr-'+oppFdr+'">'+oppFdr+'</span></span></td>';

    // Dom/Wyjazd
    h += '<td class="text-center"><span class="hw'+(p.is_home?' d':'')+'">'+(p.is_home?'D':'W')+'</span></td>';

    // Prognoza — pogrubiona, gradient; dla niedostępnych: "—"
    if (isUnavailable) {{
      h += '<td class="text-right"><span class="pred-val" style="color:var(--text-dim);font-style:italic">—</span></td>';
    }} else {{
      h += '<td class="text-right"><span class="pred-val" style="'+predGradient(pred)+'">'+pred.toFixed(1)+'</span></td>';
    }}

    // Średnia ważona
    const avgC = baseAvg >= 6 ? 'var(--accent)' : baseAvg >= 3 ? 'var(--up)' : 'var(--text-muted)';
    h += '<td class="text-right fw-600" style="color:'+avgC+'">'+baseAvg.toFixed(1)+'</td>';

    // Ocena Karpińskiego (1-10)
    const karpRating = p.karpinski_rating;
    h += '<td class="text-right c-muted">'+(karpRating != null ? karpRating.toFixed(1) : '—')+'</td>';

    // FDR ATK/DEF rywala
    h += '<td class="text-center">'+fdrTile(oppFdrAtk)+'</td>';
    h += '<td class="text-center">'+fdrTile(oppFdrDef)+'</td>';

    // Użyty FDR
    h += '<td class="text-center">'+fdrUsedLabel(p.position, fdrMod)+'</td>';

    // Potencjał — średnia percentyli pozycyjnych (0-100), tooltip z rozbiciem na percentyle składowe
    function pctStr(val) {{ return val != null ? Math.round(val) : '—'; }}
    let potTooltip;
    if (pk === 'BR') {{
      potTooltip = 'obrony: ' + pctStr(p.percentile_goals_prevented) + ' percentyl, czyste konta: ' + pctStr(p.percentile_clean_sheet) + ' percentyl';
    }} else if (pk === 'OBR') {{
      potTooltip = 'CS: ' + pctStr(p.percentile_clean_sheet) + ' pc, stracone: ' + pctStr(p.percentile_goals_conceded) + ' pc (odwr.), xG: ' + pctStr(p.percentile_xg) + ' pc, xA: ' + pctStr(p.percentile_xa) + ' pc, szanse: ' + pctStr(p.percentile_chances_created) + ' pc';
    }} else {{
      potTooltip = 'strzały: ' + pctStr(p.percentile_shots) + ' percentyl, szanse: ' + pctStr(p.percentile_chances_created) + ' percentyl';
    }}
    const potVal = p.potential_value;
    h += '<td class="text-center" style="' + (potVal != null ? potentialGradient(potVal) : '') + '" title="'+potTooltip+'">'
      +(potVal != null ? Math.round(potVal) : '—')
      +'</td>';

    // Średnie minuty
    h += '<td class="text-right c-muted">'+Math.round(avgMin)+'&prime;</td>';

    // xA/90 (expected assists per 90 min)
    const xa90 = p.xa_per_90;
    h += '<td class="text-right c-muted">'+(xa90 != null ? xa90.toFixed(2) : '—')+'</td>';

    // xG/90 (expected goals per 90 min)
    const xg90 = p.xg_per_90;
    h += '<td class="text-right c-muted">'+(xg90 != null ? xg90.toFixed(2) : '—')+'</td>';



    // Pewność
    h += '<td class="text-center">'+confidenceBadge(p.confidence)+'</td>';

    h += '</tr>';
  }});

  h += '</tbody></table></div></div>';

  // Atrybucja źródła statystyk xA/xG
  h += '<div style="font-size:11px;color:var(--text-dim);text-align:center;margin-top:12px">'
     + 'Statystyki xA/xG: Sofascore, via <a href="https://arturkarpinski.com/ekstraklasa-scouting/" target="_blank" rel="noopener" style="color:var(--text-dim);text-decoration:underline">ekstraklasa-scouting</a>'
     + '</div>';

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

  h += '<div class="kpi-row">';
  h += '<div class="kpi"><div class="kpi-label"><span class="kpi-mark"></span>MAE ogólne</div><div class="kpi-val">' + latest.mae + ' pkt</div><div class="kpi-sub">Średni błąd prognozy</div></div>';
  h += '<div class="kpi"><div class="kpi-label"><span class="kpi-mark gold"></span>Hit rate</div><div class="kpi-val">' + Math.round(latest.hit_rate * 100) + '%</div><div class="kpi-sub">Błąd &lt; 3 pkt</div></div>';
  h += '<div class="kpi"><div class="kpi-label"><span class="kpi-mark violet"></span>Najlepsza pozycja</div><div class="kpi-val">' + bestPos + ' — ' + bestPosVal + '</div><div class="kpi-sub">Najniższy MAE</div></div>';
  h += '<div class="kpi"><div class="kpi-label"><span class="kpi-mark"></span>Top 10 MAE</div><div class="kpi-val">' + latest.top10_mae + ' pkt</div><div class="kpi-sub">Trafność liderów</div></div>';
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
      svg += '<line x1="' + PAD + '" y1="' + yy + '" x2="' + (W - PADR) + '" y2="' + yy + '" style="stroke:var(--border)" stroke-width="1"/>';
      svg += '<text x="' + (PAD - 8) + '" y="' + (yy + 4) + '" text-anchor="end" style="fill:var(--text-dim)" font-size="11">' + val + '</text>';
    }}

    // X axis labels
    rounds.forEach(r => {{
      svg += '<text x="' + x(r) + '" y="' + (H - 8) + '" text-anchor="middle" style="fill:var(--text-dim)" font-size="11">K' + r + '</text>';
    }});

    // Position lines
    const posColors = {{BR:'var(--pos-gk)', OBR:'var(--pos-def)', POM:'var(--pos-mid)', NAP:'var(--pos-fwd)'}};
    ['BR','OBR','POM','NAP'].forEach(pos => {{
      const pts = [];
      ACCURACY_HISTORY.forEach(a => {{
        if (a.mae_by_pos && a.mae_by_pos[pos] !== undefined) pts.push({{r: a.round, v: a.mae_by_pos[pos]}});
      }});
      if (pts.length > 1) {{
        const d = pts.map((p, i) => (i === 0 ? 'M' : 'L') + x(p.r) + ',' + y(p.v)).join(' ');
        svg += '<path d="' + d + '" fill="none" style="stroke:' + posColors[pos] + '" stroke-width="1.5" opacity="0.6"/>';
      }} else if (pts.length === 1) {{
        svg += '<circle cx="' + x(pts[0].r) + '" cy="' + y(pts[0].v) + '" r="4" style="fill:' + posColors[pos] + '" opacity="0.6"/>';
      }}
    }});

    // Overall MAE line (thick, white)
    if (ACCURACY_HISTORY.length > 1) {{
      const d = ACCURACY_HISTORY.map((a, i) => (i === 0 ? 'M' : 'L') + x(a.round) + ',' + y(a.mae)).join(' ');
      svg += '<path d="' + d + '" fill="none" style="stroke:var(--text)" stroke-width="2.5"/>';
    }}
    // Dots for overall MAE
    ACCURACY_HISTORY.forEach(a => {{
      svg += '<circle cx="' + x(a.round) + '" cy="' + y(a.mae) + '" r="4" style="fill:var(--text)"/>';
    }});

    svg += '</svg>';

    // Legend
    let legend = '<div class="chart-legend" style="justify-content:center">';
    legend += '<span class="cli"><span class="csw" style="background:var(--text)"></span>MAE ogólne</span>';
    Object.entries(posColors).forEach(([p, c]) => {{
      legend += '<span class="cli"><span class="csw" style="background:' + c + '"></span>' + p + '</span>';
    }});
    legend += '</div>';

    h += '<div class="sec" style="margin-top:24px"><h2>Trend MAE</h2><span class="rule"></span></div>';
    h += '<div class="chart-card">' + svg + legend + '</div>';
  }}

  // === DETAIL TABLE (latest round) ===
  const details = latest.details || [];
  if (details.length) {{
    h += '<div class="sec" style="margin-top:24px"><h2>Szczegóły — Kolejka ' + latest.round + '</h2><span class="rule"></span></div>';

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

    h += '<div class="panel" style="padding:0;overflow:hidden"><div class="tscroll"><table class="dt"><thead><tr>';
    h += '<th class="text-left sortable" data-tab="accuracy" data-col="name">Zawodnik' + accArrow('name') + '</th>';
    h += '<th class="text-center sortable" data-tab="accuracy" data-col="position">Poz' + accArrow('position') + '</th>';
    h += '<th class="text-left sortable" data-tab="accuracy" data-col="team">Drużyna' + accArrow('team') + '</th>';
    h += '<th class="text-right sortable" data-tab="accuracy" data-col="predicted">Prognoza' + accArrow('predicted') + '</th>';
    h += '<th class="text-right sortable" data-tab="accuracy" data-col="actual">Rzeczywistość' + accArrow('actual') + '</th>';
    h += '<th class="text-right sortable" data-tab="accuracy" data-col="abs_error">Błąd' + accArrow('abs_error') + '</th>';
    h += '</tr></thead><tbody>';

    sorted.forEach(d => {{
      const absErr = Math.abs(d.error);
      let errColor = 'var(--down)';
      if (absErr < 2) errColor = 'var(--up)';
      else if (absErr < 4) errColor = 'var(--text-muted)';

      h += '<tr>';
      h += '<td class="text-left">' + (d.name || '') + '</td>';
      h += '<td class="text-center">' + posBadge(d.position || '') + '</td>';
      h += '<td class="text-left c-muted">' + (d.team || '') + '</td>';
      h += '<td class="text-right">' + (d.predicted != null ? d.predicted.toFixed(1) : '—') + '</td>';
      h += '<td class="text-right">' + (d.actual != null ? d.actual : '—') + '</td>';
      h += '<td class="text-right" style="color:' + errColor + ';font-weight:700;">' + absErr.toFixed(1) + '</td>';
      h += '</tr>';
    }});

    h += '</tbody></table></div></div>';
  }}

  // === AUTO-TUNING SECTION ===
  // Sekcja pokazuje status i wyniki auto-tunera parametrów predictora
  h += '<div class="sec" style="margin-top:32px"><h2>Auto-tuning</h2><span class="rule"></span></div>';
  h += '<div class="panel" style="padding:20px;">';

  if (!TUNED_PARAMS) {{
    // Tuning jeszcze nie miał wystarczająco danych — zbieramy historię
    const totalRounds = ACCURACY_HISTORY ? ACCURACY_HISTORY.length : 0;
    h += '<div style="text-align:center;padding:16px 0;">';
    h += '<div style="font-size:32px;margin-bottom:8px;">⏳</div>';
    h += '<div style="color:var(--text-muted);font-size:14px;">Zbiera dane (' + totalRounds + '/4 kolejek)</div>';
    h += '<div style="color:var(--text-dim);font-size:12px;margin-top:4px;">Auto-tuning uruchomi się automatycznie po zebraniu min. 4 kolejek historii trafności</div>';
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
    h += '<span style="background:var(--up);color:var(--text-inverse);padding:4px 12px;border-radius:12px;font-size:12px;font-weight:700;">✅ Aktywny</span>';
    h += '<span style="color:var(--text-muted);font-size:13px;">' + tp.rounds_used + ' kolejek · ostatni tuning: ' + (tp.last_tuned || '—') + '</span>';
    h += '</div>';

    // Tabela porównawcza parametrów
    h += '<table class="dt"><thead><tr>';
    h += '<th class="text-left">PARAMETR</th>';
    h += '<th class="text-right">DOMYŚLNA</th>';
    h += '<th class="text-right">WYTUNOWANA</th>';
    h += '<th class="text-right">ZMIANA</th>';
    h += '</tr></thead><tbody>';

    function tuneRow(label, key, fmt) {{
      const defVal = defaults[key];
      const tunedVal = tp[key];
      if (tunedVal === undefined || tunedVal === null) return '';
      const diff = tunedVal - defVal;
      const diffStr = diff > 0.001 ? '+' + fmt(diff) : diff < -0.001 ? fmt(diff) : '—';
      const diffColor = Math.abs(diff) > 0.001 ? 'var(--gold)' : 'var(--text-dim)';
      return '<tr>'
        + '<td class="text-left">' + label + '</td>'
        + '<td class="text-right c-dim">' + fmt(defVal) + '</td>'
        + '<td class="text-right fw-700">' + fmt(tunedVal) + '</td>'
        + '<td class="text-right" style="color:' + diffColor + '">' + diffStr + '</td>'
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
      const color = improved ? 'var(--up)' : 'var(--down)';
      const sign = improved ? '' : '+';
      h += '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">';
      h += '<div style="background:var(--surface-inset);border-radius:8px;padding:12px 20px;">';
      h += '<div style="color:var(--text-dim);font-size:11px;font-weight:600;margin-bottom:4px;">POPRAWA MAE</div>';
      h += '<div style="font-size:18px;font-weight:700;">';
      h += '<span style="color:var(--text-muted);">' + tp.mae_before.toFixed(1) + '</span>';
      h += ' <span style="color:var(--text-dim);font-size:14px;">→</span> ';
      h += '<span style="color:var(--text);">' + tp.mae_after.toFixed(1) + '</span>';
      const pct = tp.improvement_pct != null ? tp.improvement_pct : 0;
      h += ' <span style="color:' + color + ';font-size:14px;">(' + arrow + Math.abs(pct).toFixed(1) + '%)</span>';
      h += '</div>';
      h += '</div>';
      h += '</div>';
    }}
  }}

  h += '</div>';  // end panel (auto-tuning)

  return h;
}}

// ========== SEASON TRACKER ==========
// Stan widoku sezonu — przechowywany poza renderSeason(), bo render() czyści DOM
let seasonView = 'positions';  // 'positions' (bump) lub 'points' (słupki klasyfikacji)
let seasonFilter = 'all';     // 'all', 'top5', 'bottom5'
let seasonHidden = {{}};       // {{teamName: true}} — ukryte drużyny

// Paleta kolorów — serie tokenów Concept C (Sezon + Porównanie)
const SEASON_COLORS = [
  'var(--series-1)','var(--series-2)','var(--series-3)','var(--series-4)',
  'var(--series-5)','var(--series-6)','var(--series-7)','var(--series-8)',
  'var(--series-9)','var(--series-10)','var(--series-11)','var(--series-12)',
];

// Ładny krok osi (1 / 2 / 5 × 10^n) — do siatki i podpisów
function seasonNiceStep(raw) {{
  if (!(raw > 0)) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / pow;
  const m = n <= 1 ? 1 : (n <= 2 ? 2 : (n <= 5 ? 5 : 10));
  return m * pow;
}}

// Bezpieczny tekst w atrybutach HTML/SVG (cudzysłowy w nazwie drużyny)
function seasonAttr(t) {{
  return String(t).replace(/"/g, '&quot;');
}}

// Dostępna szerokość wykresu. Na desktopie cel jak dotychczas (1100 / 1042 px),
// na wąskich ekranach rysujemy tak, żeby wykres zmieścił się w karcie bez
// przewijania w poziomie — na 360px inaczej widać 2 z 9 kolejek, a słupki
// ucinają się w połowie i wszystkie wyglądają jednakowo.
// fit = wykres mieści się w karcie (nie potrzebujemy min-width → brak scrolla)
function seasonWidth(maxW, minW) {{
  const vw = (typeof window !== 'undefined' && window.innerWidth) ? window.innerWidth : 1440;
  const avail = Math.max(260, vw - 76);   // margines strony + padding karty
  const w = Math.round(Math.max(minW || 260, Math.min(maxW, avail)));
  return {{ w: w, fit: w <= avail }};
}}

// Podświetlenie drużyny: najechanie na linię/słupek albo na pozycję w legendzie.
// Reszta wykresu przygasza — czytelne też przy 30 drużynach.
function seasonSetFocus(team) {{
  const chart = document.getElementById('seasonChart');
  if (!chart) return;
  chart.classList.toggle('has-focus', !!team);
  chart.querySelectorAll('[data-team]').forEach(g => g.classList.toggle('is-focus', g.getAttribute('data-team') === team));
  document.querySelectorAll('.season-legend-item').forEach(li => li.classList.toggle('is-focus', li.dataset.steam === team));
}}

// ===== Widok "Pozycje" — bump chart, pozycja 1 na górze =====
function seasonLinesSVG(o) {{
  const marginL = 46, marginR = 26, marginT = 26, marginB = 34;
  const numRounds = o.rounds.length;
  // Szerokość kolejki: cel ~1100px na desktopie, na wąskim ekranie tyle,
  // ile zmieści się w karcie (min. 26px na kolejkę)
  const sw = seasonWidth(1100, 260);
  const targetW = sw.w;
  const ptFloor = targetW < 584 ? 26 : 64;
  const ptW = Math.max(ptFloor, Math.min(150, (targetW - marginL - marginR) / Math.max(numRounds - 1, 1)));
  const chartW = Math.round(marginL + marginR + ptW * Math.max(numRounds - 1, 1));
  const minStyle = sw.fit ? '' : ' style="min-width:' + chartW + 'px"';
  const chartH = 344;
  const plotW = chartW - marginL - marginR;
  const plotH = chartH - marginT - marginB;
  const maxPos = Math.max(o.allCount, 1);
  const xScale = (idx) => marginL + (numRounds > 1 ? idx / (numRounds - 1) * plotW : plotW / 2);
  const yScale = (val) => marginT + (val - 1) / Math.max(maxPos - 1, 1) * plotH;

  let svg = '<svg width="' + chartW + '" height="' + chartH + '" viewBox="0 0 ' + chartW + ' ' + chartH + '"' + minStyle + ' xmlns="http://www.w3.org/2000/svg">';

  // Strefa TOP 5 — o co gra się w sezonie
  const bTop = yScale(1) - 7;
  const bBot = yScale(Math.min(5, maxPos)) + 7;
  svg += '<rect x="' + marginL + '" y="' + bTop + '" width="' + plotW + '" height="' + (bBot - bTop) + '" style="fill:var(--tint-soft)"/>';
  svg += '<text class="sband-lbl" x="' + (marginL + plotW - 8) + '" y="' + ((bTop + bBot) / 2 + 3.5) + '" text-anchor="end">TOP 5</text>';

  // Siatka pozioma — pozycje co ładny krok (wcześniej tylko 1..10)
  const step = seasonNiceStep(maxPos / 6);
  const ticks = [1];
  for (let v = step; v <= maxPos; v += step) {{
    if (v - ticks[ticks.length - 1] >= step * 0.6) ticks.push(v);
  }}
  ticks.forEach(v => {{
    const y = yScale(v);
    svg += '<line class="sgrid" x1="' + marginL + '" y1="' + y + '" x2="' + (chartW - marginR) + '" y2="' + y + '"/>';
    svg += '<text class="axis-txt" x="' + (marginL - 12) + '" y="' + (y + 4) + '" text-anchor="end">' + v + '</text>';
  }});
  svg += '<line class="axis" x1="' + marginL + '" y1="' + (marginT - 10) + '" x2="' + marginL + '" y2="' + (chartH - marginB + 6) + '"/>';

  // Podpisy osi X — numery kolejek
  o.rounds.forEach((r, i) => {{
    svg += '<text class="axis-txt" x="' + xScale(i) + '" y="' + (chartH - 10) + '" text-anchor="middle">' + r.round + '</text>';
  }});

  // Punkty danych per drużyna
  const lines = {{}};
  o.visibleTeams.forEach(team => {{
    lines[team] = [];
    o.rounds.forEach((r, ri) => {{
      const s = (r.standings || []).find(x => x.team === team);
      if (s) lines[team].push({{ x: xScale(ri), y: yScale(s.position), round: r.round, position: s.position, total_points: s.total_points }});
    }});
  }});

  // Kolejność rysowania: własna drużyna na samym końcu — jej podkład "wycina" krzyżowania
  const order = o.visibleTeams.slice().sort((a, b) => (o.own(a) ? 1 : 0) - (o.own(b) ? 1 : 0));

  // 1) Podkład (tło w kolorze karty) rysowany WSZYSTKI przed liniami
  order.forEach(team => {{
    if (o.hidden[team] || !o.own(team) || !lines[team].length) return;
    const p = lines[team].map(q => q.x + ',' + q.y).join(' ');
    svg += '<polyline points="' + p + '" fill="none" style="stroke:var(--surface);stroke-linejoin:round;stroke-linecap:round" stroke-width="' + (o.lw(team) + 4) + '"/>';
  }});

  // 2) Linie + punkty
  order.forEach(team => {{
    if (o.hidden[team]) return;
    const pts = lines[team];
    if (!pts.length) return;
    const own = o.own(team);
    const lc = o.lc(team);
    const p = pts.map(q => q.x + ',' + q.y).join(' ');
    svg += '<g class="steam' + (own ? ' is-own' : '') + '" data-team="' + seasonAttr(team) + '" data-tip="' + seasonAttr(o.summary(team)) + '">';
    svg += '<polyline class="shit" points="' + p + '"/>';
    svg += '<polyline class="sline" points="' + p + '" style="--lc:' + lc + ';--lw:' + o.lw(team) + 'px"/>';
    pts.forEach(q => {{
      svg += '<circle class="sdot" cx="' + q.x + '" cy="' + q.y + '" r="' + (own ? 4.5 : 3) + '" style="--lc:' + lc + '" data-tip="Kolejka ' + q.round + ': ' + seasonAttr(team) + ' — poz. ' + q.position + ' (' + q.total_points + ' pkt)"/>';
    }});
    svg += '</g>';
  }});

  svg += '</svg>';
  return svg;
}}

// ===== Widok "Punkty łącznie" — słupki klasyfikacji końcowej =====
// 30 linii naraz jest nieczytelne, dlatego tu czytamy długość słupka + etykietę,
// a nie kolor. Pas tła pokazuje dystans do lidera.
function seasonBarsSVG(o) {{
  const marginT = 16, marginB = 36;
  // Wąski ekran: krótsza kolumna z nazwami, słupki rysowane w całości —
  // przy przewijaniu ucinają się w połowie i wszystkie wyglądają na takie same
  const sw = seasonWidth(1042, 260);
  const targetW = sw.w;
  const compact = targetW < 760;
  const marginL = compact ? 150 : 214;
  const marginR = compact ? 44 : 86;
  const rowH = 20;
  const rows = o.visibleTeams.filter(t => !o.hidden[t]);
  rows.sort((a, b) => (o.pos(a) || 99) - (o.pos(b) || 99));
  const chartW = Math.max(targetW, marginL + marginR + (compact ? 60 : 220));
  const plotW = chartW - marginL - marginR;
  const chartH = marginT + marginB + rowH * Math.max(rows.length, 1);
  const minStyle = sw.fit ? '' : ' style="min-width:' + chartW + 'px"';

  let maxPts = 0;
  rows.forEach(t => {{ const p = o.pts(t); if (p > maxPts) maxPts = p; }});
  const xStep = seasonNiceStep((maxPts || 1) / 6);
  const axisMax = Math.max(xStep, Math.ceil((maxPts || 1) / xStep) * xStep);
  // Na wąskim ekranie podpisy osi co ~3 zamiast co 6 działek — inaczej się nachodzą
  const tickStep = compact ? Math.max(xStep, seasonNiceStep(axisMax / 3)) : xStep;
  const xOf = (v) => marginL + (v / axisMax) * plotW;

  let svg = '<svg width="' + chartW + '" height="' + chartH + '" viewBox="0 0 ' + chartW + ' ' + chartH + '"' + minStyle + ' xmlns="http://www.w3.org/2000/svg">';

  // Pionowa siatka + podpisy osi X (punkty)
  for (let v = 0; v <= axisMax + 0.5; v += tickStep) {{
    const x = xOf(v);
    svg += '<line class="sgrid" x1="' + x + '" y1="' + marginT + '" x2="' + x + '" y2="' + (chartH - marginB + 6) + '"/>';
    svg += '<text class="axis-txt" x="' + x + '" y="' + (chartH - 12) + '" text-anchor="middle">' + v + '</text>';
  }}
  svg += '<line class="axis" x1="' + marginL + '" y1="' + marginT + '" x2="' + marginL + '" y2="' + (chartH - marginB + 6) + '"/>';

  rows.forEach((team, i) => {{
    const y = marginT + i * rowH;
    const cy = y + rowH / 2;
    const own = o.own(team);
    const val = o.pts(team);
    const pr = o.pos(team);
    const bw = Math.max(2, xOf(val) - marginL);
    svg += '<g class="steam' + (own ? ' is-own' : '') + '" data-team="' + seasonAttr(team) + '" data-tip="' + seasonAttr(o.summary(team)) + '">';
    svg += '<rect class="sband" x="0" y="' + y + '" width="' + chartW + '" height="' + rowH + '"/>';
    svg += '<text class="srank' + (pr === 1 ? ' top1' : '') + '" x="8" y="' + (cy + 3.5) + '">' + (pr || '–') + '</text>';
    svg += '<text class="srow-name" x="' + (marginL - 16) + '" y="' + (cy + 4) + '" text-anchor="end">' + team + '</text>';
    svg += '<rect class="strack" x="' + marginL + '" y="' + (y + 4) + '" width="' + plotW + '" height="' + (rowH - 8) + '" rx="4"/>';
    svg += '<rect class="sbar" x="' + marginL + '" y="' + (y + 4) + '" width="' + bw + '" height="' + (rowH - 8) + '" rx="4" style="--lc:' + o.lc(team) + '"/>';
    svg += '<text class="sval" x="' + (marginL + bw + 9) + '" y="' + (cy + 3.5) + '">' + val + '</text>';
    svg += '</g>';
  }});

  svg += '</svg>';
  return svg;
}}

function renderSeason() {{
  const rounds = (LEAGUE_HISTORY.rounds || []);
  if (rounds.length < 1) {{
    return '<div class="empty-msg">Zbieranie danych — wykres pojawi się po 2+ kolejkach</div>';
  }}

  // Wszystkie drużyny + ranking wg ostatniej kolejki (stabilne przypisanie kolorów)
  const teamSet = new Set();
  rounds.forEach(r => (r.standings || []).forEach(s => teamSet.add(s.team)));
  const allTeams = [...teamSet];
  const lastRound = rounds[rounds.length - 1];
  const lastStandings = {{}};
  (lastRound.standings || []).forEach(s => lastStandings[s.team] = s);

  const ranked = allTeams.filter(t => lastStandings[t])
    .sort((a, b) => lastStandings[a].position - lastStandings[b].position);
  allTeams.forEach(t => {{ if (!lastStandings[t]) ranked.push(t); }});

  const teamColor = {{}};
  ranked.forEach((t, i) => teamColor[t] = SEASON_COLORS[i % SEASON_COLORS.length]);

  // Filtr zakresu — kolejność legenda/tabela jak w klasyfikacji (od lidera)
  let visibleTeams = ranked.slice();
  if (seasonFilter === 'top5') {{
    visibleTeams = ranked.filter(t => lastStandings[t] && lastStandings[t].position <= 5);
  }} else if (seasonFilter === 'bottom5') {{
    visibleTeams = ranked.filter(t => lastStandings[t]).slice(-5).reverse();
  }}

  const numRounds = rounds.length;
  const isOwn = (t) => t.toLowerCase().includes('tokusatsu');

  const opts = {{
    rounds: rounds,
    allCount: ranked.length,
    visibleTeams: visibleTeams,
    hidden: seasonHidden,
    own: isOwn,
    // Własna drużyna zawsze w akcencie (mint), reszta z palety wg pozycji
    lc: (t) => isOwn(t) ? 'var(--accent)' : (teamColor[t] || 'var(--text-dim)'),
    lw: (t) => isOwn(t) ? 3.4 : 2,
    pos: (t) => lastStandings[t] ? lastStandings[t].position : 0,
    pts: (t) => lastStandings[t] ? lastStandings[t].total_points : 0,
    summary: (t) => {{
      const s = lastStandings[t];
      if (!s) return t;
      return t + ' — ' + s.total_points + ' pkt · poz. ' + s.position
        + ' · śr. ' + (s.total_points / numRounds).toFixed(1) + '/kol.';
    }},
  }};

  const svg = seasonView === 'points' ? seasonBarsSVG(opts) : seasonLinesSVG(opts);

  // === Buduj HTML ===
  const note = seasonView === 'points'
    ? 'Punkty łącznie — stan po ' + numRounds + ' kolejkach'
    : 'Pozycja po każdej kolejce';
  let h = '<div class="sec" style="margin-top:26px"><h2>Sezon — historia ligi</h2><span class="rule"></span>'
    + '<span class="sec-note">' + note + '</span></div>';

  // Kontrolki
  h += '<div class="toolbar">';
  h += '<div class="seg" id="season-mode" role="group" aria-label="Tryb wykresu"><span class="seg-label">Wykres</span>';
  h += '<button class="seg-btn season-btn' + (seasonView === 'positions' ? ' active' : '') + '" data-sview="positions">Pozycje</button>';
  h += '<button class="seg-btn season-btn' + (seasonView === 'points' ? ' active' : '') + '" data-sview="points">Punkty łącznie</button>';
  h += '</div>';
  h += '<div class="seg" id="season-range" role="group" aria-label="Zakres"><span class="seg-label">Zakres</span>';
  h += '<button class="seg-btn season-btn' + (seasonFilter === 'all' ? ' active' : '') + '" data-sfilter="all">Wszystkie</button>';
  h += '<button class="seg-btn season-btn' + (seasonFilter === 'top5' ? ' active' : '') + '" data-sfilter="top5">Top 5</button>';
  h += '<button class="seg-btn season-btn' + (seasonFilter === 'bottom5' ? ' active' : '') + '" data-sfilter="bottom5">Dolne 5</button>';
  h += '</div>';
  h += '</div>';

  // Wykres
  h += '<div class="chart-card"><div class="season-chart" id="seasonChart">';
  h += svg;
  h += '<div class="season-tooltip" id="seasonTooltip"></div>';
  h += '</div>';

  // Legenda — klik ukrywa/pokazuje, najechanie podświetla linię/słupek
  h += '<div class="chart-legend" id="season-legend">';
  visibleTeams.forEach(team => {{
    const cls = (seasonHidden[team] ? ' hidden' : '') + (isOwn(team) ? ' is-own' : '');
    h += '<span class="cli season-legend-item' + cls + '" data-steam="' + seasonAttr(team) + '">';
    h += '<span class="csw" style="background:' + opts.lc(team) + '"></span>' + team;
    h += '</span>';
  }});
  h += '</div>';
  h += '</div>';  // chart-card

  // === Tabela szczegółów ===
  if (lastRound && lastRound.standings && lastRound.standings.length > 0) {{
    h += '<div class="sec" style="margin-top:24px"><h2>Tabela sezonu</h2><span class="rule"></span></div>';
    h += '<div class="panel" style="padding:0;overflow:hidden"><div class="tscroll"><table class="dt">';
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
        ? '<span class="chg chg-up">▲' + ts.trend + '</span>'
        : ts.trend < 0
          ? '<span class="chg chg-down">▼' + Math.abs(ts.trend) + '</span>'
          : '<span class="chg chg-flat">—</span>';
      const color = teamColor[ts.team] || 'var(--text)';
      h += '<tr>';
      h += '<td class="text-left" style="color:' + color + ';font-weight:600">' + ts.team + '</td>';
      h += '<td class="text-center fw-700">' + ts.position + '</td>';
      h += '<td class="text-right fw-600">' + ts.totalPts + '</td>';
      h += '<td class="text-right">' + ts.avg.toFixed(1) + '</td>';
      h += '<td class="text-right" style="color:var(--up)">' + ts.bestRound + '</td>';
      h += '<td class="text-right" style="color:var(--down)">' + ts.worstRound + '</td>';
      h += '<td class="text-center">' + trendHtml + '</td>';
      h += '</tr>';
    }});

    h += '</tbody></table></div></div>';
  }}

  return h;
}}

function attachSeasonHandlers() {{
  // Po obróceniu telefonu / zmianie szerokości okna przeliczamy wykres
  // (szerokość zależy od viewportu). Listener dokładamy tylko raz.
  if (!window.__seasonResizeBound) {{
    window.__seasonResizeBound = true;
    let seasonResizeTimer;
    window.addEventListener('resize', () => {{
      clearTimeout(seasonResizeTimer);
      seasonResizeTimer = setTimeout(() => {{ if (tab === 'season') render(); }}, 200);
    }});
  }}
  // Przełączniki widoku i filtra
  document.querySelectorAll('[data-sview]').forEach(btn => {{
    btn.onclick = () => {{ seasonView = btn.dataset.sview; render(); }};
  }});
  document.querySelectorAll('[data-sfilter]').forEach(btn => {{
    btn.onclick = () => {{ seasonFilter = btn.dataset.sfilter; render(); }};
  }});
  // Legenda — klik ukrywa/pokazuje, najechanie podświetla
  document.querySelectorAll('.season-legend-item').forEach(item => {{
    item.onclick = () => {{
      const team = item.dataset.steam;
      seasonHidden[team] = !seasonHidden[team];
      render();
    }};
    item.onmouseenter = () => seasonSetFocus(item.dataset.steam);
    item.onmouseleave = () => seasonSetFocus(null);
  }});

  const chart = document.getElementById('seasonChart');
  const tip = document.getElementById('seasonTooltip');
  if (chart && tip) {{
    // Podświetlenie linii / wiersza po najechaniu
    chart.addEventListener('mouseover', (e) => {{
      const g = e.target.closest('[data-team]');
      seasonSetFocus(g ? g.getAttribute('data-team') : null);
    }});
    chart.addEventListener('mouseleave', () => {{
      seasonSetFocus(null);
      tip.classList.remove('visible');
    }});

    // Tooltip — kotwiczony do kursora (grupa/kolumna ma szeroką bounding box,
    // więc pozycja liczona z niej trafiała w krzak); zawsze trzymamy go w karcie
    chart.addEventListener('mouseover', (e) => {{
      const el = e.target.closest('[data-tip]');
      if (!el) {{ tip.classList.remove('visible'); return; }}
      tip.textContent = el.getAttribute('data-tip');
      tip.classList.add('visible');
      const cr = chart.getBoundingClientRect();
      const sl = chart.scrollLeft, st = chart.scrollTop;
      const w = tip.offsetWidth, h = tip.offsetHeight;
      const maxL = sl + chart.clientWidth - w - 8;
      const maxT = st + chart.clientHeight - h - 8;
      let left = e.clientX - cr.left + sl + 14;
      let top = e.clientY - cr.top + st - h - 12;
      // Gdy po prawej zabraknie miejsca — flip na drugą stronę kursora
      if (left + w > sl + chart.clientWidth - 8) left = e.clientX - cr.left + sl - w - 14;
      tip.style.left = Math.min(Math.max(left, sl + 6), Math.max(sl + 6, maxL)) + 'px';
      tip.style.top = Math.min(Math.max(top, st + 4), Math.max(st + 4, maxT)) + 'px';
    }});
  }}
}}

// ============================================================
// 📖 PORÓWNYWARKA ZAWODNIKÓW
// Pozwala wybrać 2-3 graczy i porównać ich obok siebie:
// karty, tabela statystyk, wykres formy (SVG), siatka FDR.
// ============================================================

// 📖 Kolory przypisane do pozycji w kartach — stałe, czytelne
const CMP_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)'];

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

  let h = '<div class="sec" style="margin-top:26px"><h2>Porównanie zawodników</h2><span class="rule"></span>'
    + '<span class="sec-note">Wybierz od 2 do 3 zawodników — kolory kart, wykresu i tabeli FDR są spójne</span></div>';

  // --- Pole wyszukiwania ---
  h += '<div class="toolbar">';
  h += '<div class="search-wrap" style="max-width:420px">';
  h += '<input class="input" id="cmpSearchInput" type="text" placeholder="Wpisz imię zawodnika… (min 2, max 3)" autocomplete="off">';
  h += '<div class="ac" id="cmpAutocomplete" role="listbox" aria-label="Podpowiedzi"></div>';
  h += '</div>';
  h += '<button class="clear-btn" onclick="cmpClear()">Wyczyść</button>';
  h += '<span class="hint">Minimum 2, maksimum 3 zawodników.</span>';
  h += '</div>';

  // --- Chipy wybranych zawodników ---
  if (cmpSelected.length) {{
    h += '<div class="chips">';
    cmpSelected.forEach((id, i) => {{
      const p = allPlayers.find(x => x.player_id === id);
      if (!p) return;
      const pk = POS_ID[p.position] || p.position || '';
      h += '<span class="chip" style="border-color:'+CMP_COLORS[i]+'">';
      h += posBadge(p.position) + '<span>' + p.name + '</span><span class="chip-meta">' + p.team + '</span>';
      h += '<button class="chip-x" onclick="cmpRemovePlayer('+id+')" aria-label="Usuń ' + p.name + '">✕</button>';
      h += '</span>';
    }});
    h += '</div>';
  }}

  // Jeśli mniej niż 2 zawodników — pokaż instrukcję
  if (cmpSelected.length < 2) {{
    h += '<div class="cmp-empty"><strong>Potrzebne są co najmniej 2 zawodnicy</strong>';
    h += 'Wybierz <b>2 lub 3</b> zawodników aby zobaczyć porównanie. Zacznij wpisywać nazwisko w polu powyżej.</div>';
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
    const teamFdr = (FDR_DATA.teams || []).find(t => normalizeTeamNameJS(t.name) === normalizeTeamNameJS(p.team));
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

    h += '<div class="cmp-card"><span class="cc-bar" style="background:'+CMP_COLORS[i]+'"></span>';
    h += '<div class="cc-pos">' + posBadge(p.position) + '</div>';
    h += '<div class="cc-name">' + p.name + '</div>';
    h += '<div class="cc-team">' + p.team + '</div>';
    h += '<div style="margin-top:14px">';
    h += '<div class="ccmp-stat"><span class="cs-k">Cena</span><span class="cs-v">' + (p.price || 0).toFixed(1) + 'M</span></div>';
    h += '<div class="ccmp-stat"><span class="cs-k">Łączne pkt</span><span class="cs-v">' + (p.total_points || 0) + '</span></div>';
    h += '<div class="ccmp-stat"><span class="cs-k">Średnia (forma)</span><span class="cs-v">' + formAvg + '</span></div>';
    h += '<div class="ccmp-stat"><span class="cs-k">Prognoza</span><span class="cs-v" style="color:var(--accent)">' + predPts + '</span></div>';
    h += '<div class="ccmp-stat"><span class="cs-k">Następny rywal</span><span class="cs-v">' + nextOpp + ' <span class="hw'+(isHome?' d':'')+'">'+(isHome?'D':'W')+'</span> <span class="fdr fdr-'+mainFdr+'">'+mainFdr+'</span></span></div>';
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

  h += '<div class="panel" style="padding:0;overflow:hidden;margin-bottom:20px"><div class="tscroll"><table class="dt cmp-table"><thead><tr><th class="text-left">Statystyka</th>';
  selected.forEach((p,i) => {{ h += '<th class="text-center" style="color:'+CMP_COLORS[i]+'">' + p.name.split(' ').pop() + '</th>'; }});
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
    h += '<tr><td class="metric">' + label + '</td>';
    vals.forEach((v, i) => {{
      let display = v;
      // Formatowanie
      if (label === 'Cena') display = v.toFixed(1) + 'M';
      else if (label === 'Pkt/Cena' || label === 'Średnia (forma)' || label === 'Prognoza' || label === 'Śr. minut') display = v.toFixed(1);
      else if (label === 'Popularność') display = v.toFixed(0) + '%';
      else if (label === 'Pewność prognozy') display = ['—','Low','Medium','High'][v] || '—';
      const isBest = bestIdx !== -1 && v === vals[bestIdx] && mode !== 'neutral';
      h += '<td class="text-center' + (isBest ? ' best' : '') + '">' + display + '</td>';
    }});
    h += '</tr>';
  }});
  h += '</tbody></table></div></div>';

  // === SEKCJA C: Wykres formy (SVG) ===
  // 📖 Zbieramy punkty z formy, rysujemy linie SVG bez zewnętrznych bibliotek
  h += '<div class="sec"><h2>Forma — ostatnie kolejki</h2><span class="rule"></span></div>';
  h += '<div class="chart-card">';
  h += '<div class="chart-legend" style="margin:0 0 14px">';
  selected.forEach((p,i) => {{
    h += '<span class="cli"><span class="csw" style="background:'+CMP_COLORS[i]+'"></span>' + p.name.split(' ').pop() + '</span>';
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
      h += '<line x1="'+padL+'" y1="'+y+'" x2="'+(svgW-padR)+'" y2="'+y+'" style="stroke:var(--border)" stroke-width="0.5"/>';
      h += '<text x="'+(padL-6)+'" y="'+(y+4)+'" style="fill:var(--text-dim)" font-size="10" text-anchor="end">'+yVal+'</text>';
    }}

    // Etykiety X (numery kolejek)
    rounds.forEach((r, idx) => {{
      h += '<text x="'+xScale(idx)+'" y="'+(svgH-6)+'" style="fill:var(--text-dim)" font-size="10" text-anchor="middle">'+r+'</text>';
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
      h += '<polyline points="'+lineStr+'" fill="none" style="stroke:'+CMP_COLORS[pi]+'" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>';
      // Kropki
      points.forEach(pt => {{
        h += '<circle cx="'+pt.x+'" cy="'+pt.y+'" r="4" style="fill:'+CMP_COLORS[pi]+';stroke:var(--surface-inset)" stroke-width="2"/>';
        h += '<text x="'+pt.x+'" y="'+(pt.y-8)+'" style="fill:'+CMP_COLORS[pi]+'" font-size="9" font-weight="700" text-anchor="middle">'+pt.pts+'</text>';
      }});
    }});

    h += '</svg></div>';
  }} else {{
    h += '<div style="color:var(--text-dim);text-align:center;padding:20px">Za mało danych o formie.</div>';
  }}
  h += '</div>';

  // === SEKCJA D: FDR następne kolejki ===
  const fdrTeams = FDR_DATA.teams || [];
  const fdrGws = FDR_DATA.gameweeks || [];
  if (fdrGws.length) {{
    h += '<div class="sec"><h2>Trudność najbliższych meczów (FDR)</h2><span class="rule"></span>'
      + '<span class="sec-note">1 = bardzo łatwy · 5 = bardzo trudny</span></div>';
    h += '<div class="panel" style="padding:0;overflow:hidden"><div class="tscroll"><table class="dt"><thead><tr><th class="text-left">Kolejka</th>';
    selected.forEach((p,i) => {{ h += '<th class="text-center" style="color:'+CMP_COLORS[i]+'">' + p.name.split(' ').pop() + '</th>'; }});
    h += '</tr></thead><tbody>';

    fdrGws.forEach(gw => {{
      h += '<tr><td class="text-left fw-700 c-muted">' + gw + '</td>';
      selected.forEach((p, pi) => {{
        const teamFdr = fdrTeams.find(t => normalizeTeamNameJS(t.name) === normalizeTeamNameJS(p.team));
        const fix = teamFdr ? (teamFdr.fixtures || []).find(f => f.gw === gw) : null;
        if (fix) {{
          const pk = POS_ID[p.position] || p.position || '';
          const isAtk = (pk === 'NAP' || pk === 'POM');
          const mainFdr = isAtk ? fix.def : fix.atk;
          const ha = fix.home ? 'D' : 'W';
          h += '<td class="text-center"><span class="opp"><span class="o-code"><span class="o-nm">' + fix.opponent_short + '</span><span class="hw'+(fix.home?' d':'')+'">' + ha + '</span></span><span class="fdr fdr-'+mainFdr+'">'+mainFdr+'</span></span></td>';
        }} else {{
          h += '<td class="text-center c-dim">—</td>';
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
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('active', el.id === 'v-'+tab));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.go === tab));
  document.querySelectorAll('.pos-btn').forEach(b => b.classList.toggle('active', b.dataset.pos === pos));
  document.querySelectorAll('.scope-btn:not(.fdr-sort-btn)').forEach(b => b.classList.toggle('active', b.dataset.scope === scope));
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
  // Duet row click handlers (expand/collapse) — tożsamość wiersza = managers
  document.querySelectorAll('tr[data-duet]').forEach(el => {{
    el.onclick = () => {{
      const name = decodeURIComponent(el.dataset.duet);
      selectedDuet = selectedDuet === name ? '' : name;
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
      if (q.length < 2) {{ cmpAc.classList.remove('open'); cmpAc.innerHTML = ''; return; }}
      // 📖 Szukamy w PLAYERS — filtrujemy po nazwisku, drużynie
      const matches = PLAYERS.filter(p =>
        !cmpSelected.includes(p.player_id) &&
        (p.name.toLowerCase().includes(q) || p.team.toLowerCase().includes(q))
      ).slice(0, 8);
      if (!matches.length) {{ cmpAc.classList.remove('open'); cmpAc.innerHTML = ''; return; }}
      let acH = '';
      matches.forEach(p => {{
        acH += '<button type="button" data-cmpid="'+p.player_id+'">';
        acH += posBadge(p.position) + '<span>' + p.name + '</span>';
        acH += '<span class="ac-team">' + p.team + ' · ' + (p.price||0).toFixed(1) + 'M · ' + (p.total_points||0) + 'pkt</span>';
        acH += '</button>';
      }});
      cmpAc.innerHTML = acH;
      cmpAc.classList.add('open');
      // Klik na element listy
      cmpAc.querySelectorAll('button[data-cmpid]').forEach(el => {{
        el.onclick = () => {{
          cmpAddPlayer(parseInt(el.dataset.cmpid));
          cmpAc.classList.remove('open');
          cmpAc.innerHTML = '';
        }};
      }});
    }};
    // Zamknij autocomplete po kliknięciu poza
    document.addEventListener('click', (e) => {{
      if (!e.target.closest('.search-wrap')) {{
        cmpAc.classList.remove('open');
      }}
    }});
  }}
}}

function show(view) {{
  if (view === 'landing') {{
    document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'v-landing'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    return;
  }}
  tab = view;
  render();
}}
document.addEventListener('click', function(e) {{
  const el = e.target.closest ? e.target.closest('[data-go]') : null;
  if (!el) return;
  show(el.dataset.go);
}});
document.querySelectorAll('.pos-btn').forEach(b => b.addEventListener('click', () => {{ pos = b.dataset.pos; render(); }}));
document.querySelectorAll('.scope-btn').forEach(b => b.addEventListener('click', () => {{ scope = b.dataset.scope; render(); }}));
const pq = document.getElementById('players-q');
if (pq) pq.addEventListener('input', () => {{ playersQ = pq.value.trim(); render(); }});
document.querySelectorAll('#league-view .seg-btn').forEach(b => {{
  b.addEventListener('click', () => {{
    currentTeamsView = b.dataset.lview;
    document.querySelectorAll('#league-view .seg-btn').forEach(x => x.classList.toggle('active', x === b));
    render();
  }});
}});
// Start: landing jest widokiem domyślnym (render zakładek uruchamia się po kliknięciu)
document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'v-landing'));
document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
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
