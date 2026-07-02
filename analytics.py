"""
analytics.py - współdzielone funkcje analityczne używane przez
newsletter.py i discord_notify.py. Ta sama logika musi dawać
identyczny wynik niezależnie czy trafia do newslettera AI czy na
Discord embed - inaczej użytkownik zobaczy niespójność.
"""
from predictor import parse_ownership_pct
from config import POS_MAP


def find_hidden_gem(players_data, round_number, ownership_threshold=20.0):
    """
    Szuka zawodnika z najwyższymi punktami w danej kolejce, którego
    ownership jest niższy niż ownership_threshold - "perełka", którą
    mało kto wybrał, a zagrała dobrze.
    Zwraca (player_dict, points) albo (None, -1) jeśli nic nie znaleziono.
    """
    best = None
    best_pts = -1
    for player in players_data:
        own = parse_ownership_pct(player.get("popularity_pct", "100%"))
        if own >= ownership_threshold:
            continue
        for r in player.get("rounds", []):
            if r.get("round") == round_number and r.get("played"):
                pts = r.get("points", 0) or 0
                if pts > best_pts:
                    best_pts = pts
                    best = player
                break
    return best, best_pts


def find_disappointment(players_data, round_number, ownership_threshold=40.0):
    """
    Szuka zawodnika z najniższymi punktami w danej kolejce, którego
    ownership jest wyższy niż ownership_threshold - "rozczarowanie",
    którego wielu wybrało, a zagrał słabo.
    Zwraca (player_dict, points) albo (None, None) jeśli nic nie znaleziono.
    """
    worst = None
    worst_pts = None
    for player in players_data:
        own = parse_ownership_pct(player.get("popularity_pct", "0%"))
        if own <= ownership_threshold:
            continue
        for r in player.get("rounds", []):
            if r.get("round") == round_number and r.get("played"):
                pts = r.get("points", 0) or 0
                if worst_pts is None or pts < worst_pts:
                    worst_pts = pts
                    worst = player
                break
    if worst is None:
        return None, None
    return worst, worst_pts


def collect_captains(league_teams_detail, players_data, round_number, league_data):
    """
    Zbiera dane kapitanów z każdej drużyny ligi - nazwa drużyny,
    kapitan, jego pozycja i punkty w danej kolejce. Sortowane wg
    punktów kapitana (najwyższe pierwsze).
    Zwraca listę: [{"team_name", "cap_name", "cap_pos", "cap_pts"}, ...]
    """

    player_round_pts = {}
    if players_data and round_number:
        for player in players_data:
            pid = str(player.get("player_id", ""))
            if not pid:
                continue
            for r in player.get("rounds", []):
                if r.get("round") == round_number and r.get("played"):
                    player_round_pts[pid] = r.get("points", 0) or 0
                    break

    display_name_map = {
        t.get("slug", ""): t.get("display_name") or t.get("slug", "").replace("-", " ").title()
        for t in (league_data or [])
    }

    captain_entries = []
    for team in league_teams_detail:
        team_slug = team.get("slug", "")
        team_name = display_name_map.get(team_slug) or team_slug.replace("-", " ").title()
        for p in team.get("players", []):
            if p.get("C"):
                cap_pid = str(p.get("pid", ""))
                cap_name = p.get("name", "?")
                cap_pos = POS_MAP.get(p.get("pos", ""), p.get("pos", ""))
                cap_pts = player_round_pts.get(cap_pid, 0)
                captain_entries.append({
                    "team_name": team_name,
                    "cap_name": cap_name,
                    "cap_pos": cap_pos,
                    "cap_pts": cap_pts,
                })
                break  # Każda drużyna ma jednego kapitana

    captain_entries.sort(key=lambda c: c["cap_pts"], reverse=True)
    return captain_entries
