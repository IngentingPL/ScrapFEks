"""
fdr.py - obliczenia Fixture Difficulty Rating (trudność rywala).
Dla każdej drużyny i każdej nadchodzącej kolejki oblicza siłę
ataku (ATK) i obrony (DEF) rywala w skali 1-5.
"""

from datetime import datetime


def compute_fdr(ekstra_stats: dict, fixtures_data: dict, current_round: int = 0, num_rounds: int = 6) -> dict:
    """Oblicza osobne wskaźniki ATK i DEF rywala (1-5) dla każdego meczu.

    ATK rywala = siła ataku rywala (wysoki = rywal dużo strzela = źle dla Twoich obrońców)
    DEF rywala = siła obrony rywala (wysoki = rywal mało traci = źle dla Twoich napastników)

    Skala 1-5 (kwantyle):
      1 = najsłabszy (korzystny mecz)
      5 = najsilniejszy (trudny mecz)
    """
    teams = fixtures_data.get("teams", [])
    rounds = fixtures_data.get("rounds", [])
    matches = fixtures_data.get("matches", {})
    abbrevs = fixtures_data.get("abbrevs", {})

    if not teams or not rounds or not ekstra_stats:
        return {"teams": [], "gameweeks": [], "team_strengths": {}}

    # Sprawdź czy mamy dane dom/wyjazd
    sample = next(iter(ekstra_stats.values()), {})
    has_ha = "gf_home" in sample and sample.get("mp_home", 0) > 0

    # Oblicz średnie ligowe
    total_gf_home = total_ga_home = total_mp_home = 0
    total_gf_away = total_ga_away = total_mp_away = 0

    for team in teams:
        st = ekstra_stats.get(team)
        if not st:
            continue
        if has_ha:
            total_gf_home += st.get("gf_home", 0)
            total_ga_home += st.get("ga_home", 0)
            total_mp_home += st.get("mp_home", 0)
            total_gf_away += st.get("gf_away", 0)
            total_ga_away += st.get("ga_away", 0)
            total_mp_away += st.get("mp_away", 0)
        else:
            mp = st.get("mp", 0) or 1
            total_gf_home += st["gf"]
            total_ga_home += st["ga"]
            total_mp_home += mp
            total_gf_away += st["gf"]
            total_ga_away += st["ga"]
            total_mp_away += mp

    avg_gf_home = total_gf_home / total_mp_home if total_mp_home else 1
    avg_ga_home = total_ga_home / total_mp_home if total_mp_home else 1
    avg_gf_away = total_gf_away / total_mp_away if total_mp_away else 1
    avg_ga_away = total_ga_away / total_mp_away if total_mp_away else 1

    # Siła ataku i obrony każdej drużyny
    team_strengths = {}
    for team in teams:
        st = ekstra_stats.get(team)
        if not st:
            team_strengths[team] = {"attack_h": 1.0, "attack_a": 1.0, "defense_h": 1.0, "defense_a": 1.0}
            continue

        if has_ha:
            mp_h = st.get("mp_home", 1) or 1
            mp_a = st.get("mp_away", 1) or 1
            gf_h_avg = st.get("gf_home", 0) / mp_h
            ga_h_avg = st.get("ga_home", 0) / mp_h
            gf_a_avg = st.get("gf_away", 0) / mp_a
            ga_a_avg = st.get("ga_away", 0) / mp_a
        else:
            mp = st.get("mp", 1) or 1
            gf_avg = st["gf"] / mp
            ga_avg = st["ga"] / mp
            gf_h_avg = gf_a_avg = gf_avg
            ga_h_avg = ga_a_avg = ga_avg

        team_strengths[team] = {
            "attack_h": round(gf_h_avg / avg_gf_home, 2) if avg_gf_home else 1.0,
            "attack_a": round(gf_a_avg / avg_gf_away, 2) if avg_gf_away else 1.0,
            "defense_h": round(ga_h_avg / avg_ga_home, 2) if avg_ga_home else 1.0,
            "defense_a": round(ga_a_avg / avg_ga_away, 2) if avg_ga_away else 1.0,
        }

    # Określ nadchodzące kolejki na podstawie dat meczów
    today = datetime.now()
    current_year = today.year

    def _round_is_past(round_num):
        """Sprawdza czy wszystkie mecze w kolejce już się odbyły."""
        ms = matches.get(str(round_num), [])
        if not ms:
            return True
        for m in ms:
            date_str = m.get("date", "")
            if not date_str:
                return False
            try:
                day, month = date_str.split(".")
                # Zakładamy bieżący rok; dla meczów lip-gru może być rok wcześniejszy
                match_date = datetime(current_year, int(month), int(day))
                if int(month) >= 7 and today.month <= 6:
                    match_date = datetime(current_year - 1, int(month), int(day))
                if match_date >= today:
                    return False  # Jest mecz w przyszłości
            except (ValueError, TypeError):
                return False
        return True

    upcoming = [r for r in rounds if not _round_is_past(r)]
    if not upcoming:
        upcoming = rounds[-num_rounds:]  # fallback: ostatnie kolejki
    shown_rounds = upcoming[:num_rounds]

    # Zbierz surowe wartości ATK i DEF rywala dla kwantyli
    raw_atk_vals = []
    raw_def_vals = []
    fixture_map = {}  # (team, round) -> {atk_raw, def_raw}

    for r in shown_rounds:
        ms = matches.get(str(r), [])
        for m in ms:
            home_team = m["home"]
            away_team = m["away"]
            opp_away = team_strengths.get(away_team, {"attack_a": 1.0, "defense_a": 1.0})
            opp_home = team_strengths.get(home_team, {"attack_h": 1.0, "defense_h": 1.0})

            # Dla gospodarza: rywal gra na wyjeździe
            atk_raw_h = opp_away["attack_a"]   # atak wyjazdowy rywala
            def_raw_h = opp_away["defense_a"]   # obrona wyjazdowa rywala (GA-based)

            # Dla gościa: rywal gra u siebie
            atk_raw_a = opp_home["attack_h"]    # atak domowy rywala
            def_raw_a = opp_home["defense_h"]   # obrona domowa rywala (GA-based)

            raw_atk_vals.extend([atk_raw_h, atk_raw_a])
            raw_def_vals.extend([def_raw_h, def_raw_a])
            fixture_map[(home_team, r)] = {"atk": atk_raw_h, "def": def_raw_h}
            fixture_map[(away_team, r)] = {"atk": atk_raw_a, "def": def_raw_a}

    # Kwantyle dla ATK (direct: wysoki attack_strength → wysoki rating 5)
    def _quantile_thresholds(vals):
        if not vals:
            return [0.8, 0.95, 1.05, 1.2]
        s = sorted(vals)
        n = len(s)
        return [s[max(0, int(n * 0.2) - 1)], s[max(0, int(n * 0.4) - 1)],
                s[max(0, int(n * 0.6) - 1)], s[max(0, int(n * 0.8) - 1)]]

    atk_thr = _quantile_thresholds(raw_atk_vals)
    def_thr = _quantile_thresholds(raw_def_vals)

    def _val_to_rating(val, thr):
        """Direct: niska wartość → rating 1, wysoka → rating 5."""
        if val <= thr[0]: return 1
        if val <= thr[1]: return 2
        if val <= thr[2]: return 3
        if val <= thr[3]: return 4
        return 5

    def _val_to_rating_inv(val, thr):
        """Inverted: niska wartość → rating 5 (silna obrona), wysoka → rating 1."""
        if val <= thr[0]: return 5
        if val <= thr[1]: return 4
        if val <= thr[2]: return 3
        if val <= thr[3]: return 2
        return 1

    # Buduj dane per drużyna
    fdr_teams = []
    for team in teams:
        ab = abbrevs.get(team, team[:3].upper())
        fixtures_list = []
        total_atk = 0
        total_def = 0
        for r in shown_rounds:
            ms = matches.get(str(r), [])
            fixture_info = None
            for m in ms:
                if m["home"] == team:
                    fixture_info = {"opponent": m["away"], "home": True, "date": m.get("date", "")}
                    break
                elif m["away"] == team:
                    fixture_info = {"opponent": m["home"], "home": False, "date": m.get("date", "")}
                    break
            if fixture_info:
                raw = fixture_map.get((team, r), {"atk": 1.0, "def": 1.0})
                atk_r = _val_to_rating(raw["atk"], atk_thr)
                # DEF: niska defense_strength = mało bramek traci = silna obrona = rating 5
                def_r = _val_to_rating_inv(raw["def"], def_thr)
                total_atk += atk_r
                total_def += def_r
                opp_ab = abbrevs.get(fixture_info["opponent"], fixture_info["opponent"][:3].upper())
                fixtures_list.append({
                    "gw": r,
                    "opponent": fixture_info["opponent"],
                    "opponent_short": opp_ab,
                    "home": fixture_info["home"],
                    "atk": atk_r,
                    "def": def_r,
                    "date": fixture_info["date"],
                })
            else:
                fixtures_list.append({"gw": r, "opponent": "", "opponent_short": "—", "home": True, "atk": 0, "def": 0, "date": ""})

        fdr_teams.append({
            "name": team,
            "short": ab,
            "total_atk": total_atk,
            "total_def": total_def,
            "fixtures": fixtures_list,
        })

    if shown_rounds:
        print(f"  📊 FDR: obliczono ATK/DEF dla {len(fdr_teams)} drużyn, kolejki K{shown_rounds[0]}-K{shown_rounds[-1]}")
    else:
        print("  📊 FDR: brak nadchodzących kolejek")

    return {
        "teams": fdr_teams,
        "gameweeks": shown_rounds,
        "team_strengths": {t: team_strengths.get(t, {}) for t in teams},
    }
