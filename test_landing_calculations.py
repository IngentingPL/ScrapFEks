"""Deterministyczne testy obliczeń kart landing page, bez dostępu do sieci."""
import os
import re
import tempfile

from dashboard import generate_dashboard_html
from test_snapshot_roundtrip import make_sample_inputs


def render(inputs):
    generate_dashboard_html(**inputs, timestamp="2026-01-01 12:00", has_archive=False)
    with open(inputs["filename"], encoding="utf-8") as html_file:
        return html_file.read()


def test_form_minimum_appearances_and_average():
    with tempfile.TemporaryDirectory() as tmp:
        inputs = make_sample_inputs(os.path.join(tmp, "form.html"))
        inputs["summary_data"] = [
            {"player_id": "few", "name": "Dwa występy", "team": "Klub A", "position": "FW",
             "form": [{"r": 5, "pts": 8}, {"r": 4, "pts": 6}, {"r": 3, "pts": 100, "p": False}]},
            {"player_id": "enough", "name": "Trzy występy", "team": "Klub B", "position": "MF",
             "form": [{"r": 5, "pts": 10}, {"r": 4, "pts": 4}, {"r": 3, "pts": 100, "p": False},
                      {"r": 2, "pts": 6}]},
        ]
        html = render(inputs)
        form_table = re.search(r"<table class='dt landing-table landing-form-table'.*?</table>", html, re.S)
        assert form_table
        form_html = form_table.group(0)
        assert "Dwa występy" not in form_html
        assert "Trzy występy" in form_html
        assert ">6.7</td>" in form_html  # (10 + 4 + 6) / 3; nierozstrzygnięta kolejka wykluczona
        assert ">3/4</td>" in form_html


def test_easiest_fixtures_order_top_five_and_dgw():
    with tempfile.TemporaryDirectory() as tmp:
        inputs = make_sample_inputs(os.path.join(tmp, "fixtures.html"))
        fixtures = []
        teams = []
        for index in range(7):
            name = "Zespół DGW" if index == 0 else f"Zespół {index}"
            team_fixtures = [{"gw": 12, "opponent": f"Rywal {index}A", "def": 7-index, "atk": index+1, "home": True}]
            if index == 0:
                team_fixtures.append({"gw": 12, "opponent": "Rywal DGW B", "def": 1, "atk": 1, "home": False})
            teams.append({"name": name, "fixtures": team_fixtures})
        inputs["fdr_data"] = {"gameweeks": [12], "teams": teams}
        html = render(inputs)

        # Etykiety są teraz we wspólnym pasie nad listami, więc sekcje wycinamy po elementach list
        lists_html = html.split("landing-fixture-lists", 1)[1]
        attack_section = lists_html.split("</section>", 1)[0]
        defence_section = lists_html.split("</section>", 1)[1].split("</section>", 1)[0]
        def ratings(section):
            ordered_list = re.search(r"<ol class='landing-fixture-list'>(.*?)</ol>", section, re.S)
            assert ordered_list
            return re.findall(r"class='fdr fdr-([1-5])'", ordered_list.group(1))

        def team_order(section):
            ordered_list = re.search(r"<ol class='landing-fixture-list'>(.*?)</ol>", section, re.S)
            assert ordered_list
            rows = re.findall(r"<span class='landing-team'>(.*?)</span>", ordered_list.group(1), re.S)
            return [re.match(r"(.*?) <span class='landing-dgw'>DGW", row).group(1)
                    if "landing-dgw" in row else row for row in rows]

        attack_ratings = ratings(attack_section)
        defence_ratings = ratings(defence_section)
        assert len(attack_ratings) == len(defence_ratings) == 5
        assert attack_ratings == sorted(attack_ratings, key=int)
        assert defence_ratings == sorted(defence_ratings, key=int)
        assert team_order(attack_section) == ["Zespół 6", "Zespół DGW", "Zespół 5", "Zespół 4", "Zespół 3"]
        assert team_order(defence_section) == ["Zespół DGW", "Zespół DGW", "Zespół 1", "Zespół 2", "Zespół 3"]
        assert "Zespół DGW" in attack_section and "landing-dgw'>DGW" in attack_section
        assert "Zespół DGW" in defence_section and "landing-dgw'>DGW" in defence_section
