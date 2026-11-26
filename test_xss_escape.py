"""Test, że złośliwa nazwa z snapshotu nie trafia do HTML-u w surowej postaci."""

import json
import os
import tempfile
import unittest

from dashboard import generate_dashboard_html
from snapshot import load_dashboard_snapshot

PAYLOAD = "<img src=x onerror=alert(1)></script><b>x</b>"
SNAPSHOT = os.path.join(os.path.dirname(__file__), "output", "dashboard_snapshot.json")


class XssEscapeTests(unittest.TestCase):
    def test_zlosliwa_nazwa_nie_jest_wstawiana_surowo(self):
        snapshot = load_dashboard_snapshot(SNAPSHOT)
        self.assertIsNotNone(snapshot, "Brak snapshotu — uruchom najpierw scraper.py")

        inputs = dict(snapshot["inputs"])
        inputs["league_teams_detail"] = [dict(t) for t in inputs["league_teams_detail"]]
        inputs["summary_data"] = [dict(p) for p in inputs["summary_data"]]
        inputs["league_teams_detail"][0]["display_name"] = PAYLOAD
        inputs["summary_data"][0]["name"] = PAYLOAD

        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "xss.html")
            inputs["filename"] = out_path
            generate_dashboard_html(
                **inputs,
                timestamp=snapshot.get("generated_at") or "",
                has_archive=False,
            )
            html = open(out_path, encoding="utf-8").read()

        # Surowy payload dałby działający <img onerror> albo zamknął <script>.
        self.assertNotIn("<img src=x onerror", html)
        self.assertNotIn("</script><b>", html)
        # Bezpieczna wersja tekstu nadal jest widoczna jako dane.
        self.assertIn("&lt;img src=x onerror", html)


if __name__ == "__main__":
    unittest.main()
