import os
import tempfile
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from discord_notify import _get_round_date_range, _parse_date_str
from schedule import parse_terminarz
from update_schedule import parse_terminarz as parse_schedule_for_generator
from update_schedule import select_first_day_datetime


class RoundDateTests(unittest.TestCase):
    def test_generator_keeps_explicit_dates_without_kickoff_time(self):
        # Stały tekst-fixture zamiast żywego terminarz.txt (test nie zależy
        # od tego, co scraper zapisze w pliku): kolejka 10 ma 10 meczów
        # z jawnymi datami, ale tylko 2 z godziną kick-offu.
        fixture = "\n".join(
            [
                "Kolejka 10 - 9-12 października",
                "",
                "Drużyna A - Drużyna B\t9 października, 18:00",
                "Drużyna C - Drużyna D\t9 października, 20:30",
                "Drużyna E - Drużyna F\t10 października,",
                "Drużyna G - Drużyna H\t10 października,",
                "Drużyna I - Drużyna J\t10 października,",
                "Drużyna K - Drużyna L\t11 października,",
                "Drużyna M - Drużyna N\t11 października,",
                "Drużyna O - Drużyna P\t11 października,",
                "Drużyna R - Drużyna S\t12 października,",
                "Drużyna T - Drużyna U\t12 października,",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_path = os.path.join(tmp_dir, "terminarz.txt")
            with open(fixture_path, "w", encoding="utf-8") as f:
                f.write(fixture + "\n")
            _, round_stats = parse_schedule_for_generator(fixture_path)
        season_year = datetime.now().year
        self.assertEqual(round_stats[10]["total"], 10)
        self.assertEqual(round_stats[10]["with_time"], 2)
        self.assertEqual(
            sorted(round_stats[10]["match_dates"]),
            [
                date(season_year, 10, 9),
                date(season_year, 10, 9),
                date(season_year, 10, 10),
                date(season_year, 10, 10),
                date(season_year, 10, 10),
                date(season_year, 10, 11),
                date(season_year, 10, 11),
                date(season_year, 10, 11),
                date(season_year, 10, 12),
                date(season_year, 10, 12),
            ],
        )

    def test_discord_date_range_matches_previous_logic_for_all_rounds(self):
        fixtures = parse_terminarz("terminarz.txt")
        for round_number, matches in fixtures["matches"].items():
            with self.subTest(round=round_number):
                # To jest poprzednia logika _get_round_date_range.
                if any(not match.get("date_confirmed", True) for match in matches):
                    expected = (None, None)
                else:
                    dates = [
                        parsed
                        for match in matches
                        if (parsed := _parse_date_str(match.get("date", "")))
                    ]
                    expected = (
                        (min(dates), max(dates)) if dates else (None, None)
                    )
                self.assertEqual(
                    _get_round_date_range(fixtures, int(round_number)), expected
                )

    def test_unconfirmed_fixture_keeps_the_whole_range_unknown(self):
        fixtures = {
            "matches": {
                "99": [
                    {"date": "09.10", "date_confirmed": True},
                    {"date": "10.10", "date_confirmed": False},
                ]
            }
        }
        self.assertEqual(_get_round_date_range(fixtures, 99), (None, None))

    def test_first_day_selects_earliest_known_kickoff(self):
        warsaw = ZoneInfo("Europe/Warsaw")
        year = datetime.now().year
        first_day = date(year, 10, 9)
        matches = [
            {"datetime": datetime(year, 10, 9, 20, 30, tzinfo=warsaw)},
            {"datetime": datetime(year, 10, 9, 18, 0, tzinfo=warsaw)},
            {"datetime": datetime(year, 10, 10, 12, 0, tzinfo=warsaw)},
        ]
        self.assertEqual(
            select_first_day_datetime(matches, first_day),
            datetime(year, 10, 9, 18, 0, tzinfo=warsaw),
        )

    def test_first_day_without_kickoff_uses_2100_warsaw(self):
        warsaw = ZoneInfo("Europe/Warsaw")
        year = datetime.now().year
        first_day = date(year, 10, 9)
        matches = [{"datetime": datetime(year, 10, 10, 12, 0, tzinfo=warsaw)}]
        self.assertEqual(
            select_first_day_datetime(matches, first_day),
            datetime(year, 10, 9, 21, 0, tzinfo=warsaw),
        )

    def test_mixed_first_day_uses_earliest_known_kickoff(self):
        warsaw = ZoneInfo("Europe/Warsaw")
        year = datetime.now().year
        first_day = date(year, 10, 9)
        # W dniu mieszanym wybieramy najwcześniejszą znaną godzinę.
        matches = [
            {"datetime": datetime(year, 10, 9, 19, 0, tzinfo=warsaw)},
            {"datetime": datetime(year, 10, 9, 17, 30, tzinfo=warsaw)},
            {"date": first_day, "datetime": None},
            {"datetime": datetime(year, 10, 10, 12, 0, tzinfo=warsaw)},
        ]
        self.assertEqual(
            select_first_day_datetime(matches, first_day),
            datetime(year, 10, 9, 17, 30, tzinfo=warsaw),
        )


if __name__ == "__main__":
    unittest.main()
