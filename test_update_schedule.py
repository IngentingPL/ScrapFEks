"""Testy harmonogramu scrape.yml: karencja 48 h i zapasowe sloty PRE/POST."""

import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import discord_notify
from update_schedule import build_schedule_block, generate_crons

WARSAW = ZoneInfo("Europe/Warsaw")
UTC = ZoneInfo("UTC")


def cron_line(cron: str, comment: str) -> str:
    """Buduje linię schedule tak, jak wygląda w scrape.yml."""
    return f"    - cron: '{cron}'  # {comment}"


def round_stats(start_date: date, match_dates: list[date]) -> dict:
    """Minimalne statystyki kolejki potrzebne przez build_schedule_block."""
    return {
        "start_date": start_date,
        "match_dates": list(match_dates),
        "dates": "",
        "total": len(match_dates),
        "with_time": 0,
        "all_dates_confirmed": True,
    }


class ScheduleRetentionTests(unittest.TestCase):
    def test_slot_z_9_listopada_zostaje_przy_aktualizacji_o_1514(self):
        # Scenariusz awarii: slot POST K14 09.11 11:00 UTC.
        # Aktualizacja terminarza o 15:14 UTC nie może go usunąć.
        now = datetime(2026, 11, 9, 15, 14, tzinfo=UTC)
        existing = {
            14: [
                cron_line(
                    "0 11 9 11 *",
                    "K14 DISCORD POST 09.11 12:00 CET — podsumowanie po kolejce",
                )
            ]
        }
        stats = {
            14: round_stats(
                date(2026, 11, 6),
                [
                    date(2026, 11, 6),
                    date(2026, 11, 7),
                    date(2026, 11, 8),
                ],
            )
        }

        block = "\n".join(build_schedule_block([], existing, stats, now=now))

        self.assertIn("0 11 9 11 *", block)

    def test_slot_starszy_niz_48h_znika(self):
        now = datetime(2026, 11, 9, 15, 14, tzinfo=UTC)
        existing = {
            14: [
                cron_line("0 19 5 11 *", "K14 DISCORD PRE 05.11 20:00 CET"),
                cron_line("0 11 9 11 *", "K14 DISCORD POST 09.11 12:00 CET"),
            ]
        }
        stats = {
            14: round_stats(
                date(2026, 11, 6), [date(2026, 11, 6), date(2026, 11, 8)]
            )
        }

        block = "\n".join(build_schedule_block([], existing, stats, now=now))

        self.assertNotIn("0 19 5 11 *", block)
        self.assertIn("0 11 9 11 *", block)

    def test_przyszle_sloty_kolejki_zostaja_do_konca_post_plus_1(self):
        # K15 kończy się 23.11. POST jest 24.11, a POST+1 to 25.11.
        # Harmonogram może czyścić kolejkę dopiero od 26.11 00:00 UTC.
        now = datetime(2026, 11, 24, 6, 0, tzinfo=UTC)
        existing = {
            15: [
                cron_line("7 16 24 11 *", "K15 DISCORD POST ZAPAS"),
                cron_line("7 16 25 11 *", "K15 slot w dniu POST+1"),
                cron_line("7 16 26 11 *", "K15 slot po oknie ochrony"),
            ]
        }
        stats = {
            15: round_stats(
                date(2026, 11, 20), [date(2026, 11, 23)]
            )
        }

        block = "\n".join(build_schedule_block([], existing, stats, now=now))

        self.assertIn("7 16 24 11 *", block)
        self.assertIn("7 16 25 11 *", block)
        self.assertNotIn("7 16 26 11 *", block)

    def test_kolejka_bez_godzin_nie_znika_przed_koncem_okna(self):
        # Po rozegraniu kolejki terminarz nie ma już godzin meczów.
        # Mimo to przyszły zapasowy POST musi zostać.
        now = datetime(2026, 11, 24, 6, 0, tzinfo=UTC)
        existing = {15: [cron_line("7 16 24 11 *", "K15 DISCORD POST ZAPAS")]}
        stats = {
            15: round_stats(
                date(2026, 11, 20), [date(2026, 11, 23)]
            )
        }

        block = "\n".join(build_schedule_block([], existing, stats, now=now))

        self.assertIn("7 16 24 11 *", block)

    def test_niepotwierdzone_daty_daja_dluzsze_okno_ochrony(self):
        # Gdy daty kolejki nie są potwierdzone, nie znamy prawdziwego
        # ostatniego meczu. Wtedy trzymamy kolejkę dłużej (start + 6 dni).
        now = datetime(2026, 12, 10, 0, 1, tzinfo=UTC)
        existing = {17: [cron_line("7 16 10 12 *", "K17 slot kolejki")]}
        stats = {17: round_stats(date(2026, 12, 5), [date(2026, 12, 5)])}
        stats[17]["all_dates_confirmed"] = False

        block = "\n".join(build_schedule_block([], existing, stats, now=now))

        self.assertIn("7 16 10 12 *", block)

    def test_generowane_sloty_z_przeszlosci_nie_wracaja(self):
        now = datetime(2026, 11, 9, 15, 14, tzinfo=UTC)
        matches = [
            {
                "round": 14,
                "datetime": datetime(2026, 11, 8, 20, 15, tzinfo=WARSAW),
                "day": date(2026, 11, 8),
            }
        ]
        crons = generate_crons(
            matches,
            {14: [date(2026, 11, 6), date(2026, 11, 8)]},
            {14: True},
        )

        block = "\n".join(build_schedule_block(crons, {}, {}, now=now))

        # 08.11 22:45 CET (21:45 UTC) już minęło.
        self.assertNotIn("45 21 8 11 *", block)
        # Zapasowy POST 09.11 16:07 UTC jest jeszcze przyszły.
        self.assertIn("7 16 9 11 *", block)


class ScheduleBackupTests(unittest.TestCase):
    def test_zapasowe_sloty_pre_i_post_dla_kolejki(self):
        matches = [
            {
                "round": 15,
                "datetime": datetime(2026, 11, 20, 18, 0, tzinfo=WARSAW),
                "day": date(2026, 11, 20),
            },
            {
                "round": 15,
                "datetime": datetime(2026, 11, 23, 19, 0, tzinfo=WARSAW),
                "day": date(2026, 11, 23),
            },
        ]
        dates = [
            date(2026, 11, 20),
            date(2026, 11, 21),
            date(2026, 11, 22),
            date(2026, 11, 23),
        ]

        crons = generate_crons(matches, {15: dates}, {15: True})

        pre_backup = crons[[c[0] for c in crons].index("discord_pre_backup")]
        post_backup = crons[[c[0] for c in crons].index("discord_post_backup")]

        self.assertEqual(pre_backup[2], datetime(2026, 11, 20, 5, 7, tzinfo=UTC))
        self.assertEqual(pre_backup[3], "7 5 20 11 *")
        self.assertEqual(post_backup[2], datetime(2026, 11, 24, 16, 7, tzinfo=UTC))
        self.assertEqual(post_backup[3], "7 16 24 11 *")
        self.assertEqual(pre_backup[2].minute, 7)
        self.assertEqual(post_backup[2].minute, 7)

    def test_pre_zapas_cofa_godzine_dla_bardzo_wczesnego_meczu(self):
        # 12:30 CEST to 10:30 UTC. Slot 05:07 + 6 h = 11:07 byłby za późno,
        # więc generator musi cofnąć się do 04:07 UTC.
        matches = [
            {
                "round": 99,
                "datetime": datetime(2026, 8, 15, 12, 30, tzinfo=WARSAW),
                "day": date(2026, 8, 15),
            }
        ]

        crons = generate_crons(
            matches, {99: [date(2026, 8, 15)]}, {99: True}
        )
        pre_backup = [
            entry for entry in crons if entry[0] == "discord_pre_backup"
        ][0]

        self.assertEqual(pre_backup[2], datetime(2026, 8, 15, 4, 7, tzinfo=UTC))
        self.assertEqual(pre_backup[3], "7 4 15 8 *")

    def test_brak_duplikatu_gdy_stary_slot_ma_ten_sam_czas(self):
        matches = [
            {
                "round": 15,
                "datetime": datetime(2026, 11, 20, 18, 0, tzinfo=WARSAW),
                "day": date(2026, 11, 20),
            },
            {
                "round": 15,
                "datetime": datetime(2026, 11, 23, 19, 0, tzinfo=WARSAW),
                "day": date(2026, 11, 23),
            },
        ]
        dates = [
            date(2026, 11, 20),
            date(2026, 11, 21),
            date(2026, 11, 22),
            date(2026, 11, 23),
        ]
        crons = generate_crons(matches, {15: dates}, {15: True})
        existing = {
            15: [
                cron_line("7 5 20 11 *", "K15 DISCORD PRE ZAPAS"),
                cron_line("7 16 24 11 *", "K15 DISCORD POST ZAPAS"),
            ]
        }
        stats = {15: round_stats(date(2026, 11, 20), dates)}
        now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

        block = "\n".join(build_schedule_block(crons, existing, stats, now=now))

        self.assertEqual(block.count("7 5 20 11 *"), 1)
        self.assertEqual(block.count("7 16 24 11 *"), 1)


class DiscordIdempotencyTests(unittest.TestCase):
    """Flagi discord_sent.json muszą blokować duplikaty z zapasowych slotów."""

    @patch(
        "discord_notify._load_sent_log",
        return_value={"pre_round": 15, "post_round": 15, "captains_round": 15},
    )
    @patch("discord_notify._send_embed")
    def test_pre_round_nie_jest_wysylany_drugi_raz(self, send_mock, _log_mock):
        result = discord_notify.send_pre_round(
            predictions=[{"player_id": 1}],
            players_data=[],
            webhook_url="https://example.invalid/webhook",
            round_number=15,
            fixtures={},
        )

        self.assertFalse(result)
        send_mock.assert_not_called()

    @patch(
        "discord_notify._load_sent_log",
        return_value={"pre_round": 15, "post_round": 15, "captains_round": 15},
    )
    @patch("discord_notify._send_embed")
    def test_post_round_nie_jest_wysylany_drugi_raz(self, send_mock, _log_mock):
        result = discord_notify.send_post_round(
            league_data=[{}],
            players_data={},
            accuracy_data={},
            webhook_url="https://example.invalid/webhook",
            round_number=15,
        )

        self.assertFalse(result)
        send_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
