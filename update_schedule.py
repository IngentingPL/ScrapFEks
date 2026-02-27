#!/usr/bin/env python3
"""
Parsuje terminarz.txt i aktualizuje schedule w scrape.yml.

Dla każdego dnia meczowego bierze najpóźniejszy mecz, dodaje 3 godziny
i generuje cron trigger w UTC.

Użycie:
    python update_schedule.py
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TERMINARZ_FILE = "terminarz.txt"
WORKFLOW_FILE = ".github/workflows/scrape.yml"

# Marker comments in scrape.yml
MARKER_START = "  # AUTO-SCHEDULE-START"
MARKER_END = "  # AUTO-SCHEDULE-END"

MONTHS_PL = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
}

TZ_WARSAW = ZoneInfo("Europe/Warsaw")
TZ_UTC = ZoneInfo("UTC")

TRIGGER_DELAY_HOURS = 3


def parse_terminarz(filepath: str) -> list[dict]:
    """Parsuje terminarz.txt i zwraca listę meczów z datą/godziną."""
    matches = []
    current_round = None

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Nagłówek kolejki: "Kolejka 23 - 28 lutego-1 marca"
            round_match = re.match(r"Kolejka\s+(\d+)", line)
            if round_match:
                current_round = int(round_match.group(1))
                continue

            # Linia meczu: "Team A\t-\tTeam B\tDD miesiąc, HH:MM"
            date_match = re.search(
                r"(\d{1,2})\s+(\w+),\s*(\d{1,2}):(\d{2})\s*$", line
            )
            if date_match:
                day = int(date_match.group(1))
                month_name = date_match.group(2)
                hour = int(date_match.group(3))
                minute = int(date_match.group(4))

                month = MONTHS_PL.get(month_name)
                if month is None:
                    print(f"  ⚠️  Nieznany miesiąc: {month_name}")
                    continue

                # Rok: bieżący, chyba że miesiąc jest >2 miesiące w tyle
                now = datetime.now()
                year = now.year
                if month < now.month - 6:
                    year += 1

                match_local = datetime(
                    year, month, day, hour, minute, tzinfo=TZ_WARSAW
                )

                matches.append(
                    {
                        "round": current_round,
                        "datetime": match_local,
                        "day": match_local.date(),
                    }
                )

    return matches


def generate_crons(matches: list[dict]) -> list[tuple]:
    """
    Dla każdego meczu dodaje 3h i generuje cron trigger w UTC.
    Deduplikuje identyczne czasy triggerów (mecze o tej samej godzinie).

    Zwraca: [(match_local, trigger_utc, cron_str, round), ...]
    """
    seen = set()
    crons = []
    for m in sorted(matches, key=lambda x: x["datetime"]):
        trigger_local = m["datetime"] + timedelta(hours=TRIGGER_DELAY_HOURS)
        trigger_utc = trigger_local.astimezone(TZ_UTC)

        # Deduplikuj — mecze o tej samej godzinie dają ten sam trigger
        key = (trigger_utc.month, trigger_utc.day, trigger_utc.hour, trigger_utc.minute)
        if key in seen:
            continue
        seen.add(key)

        cron = (
            f"{trigger_utc.minute} {trigger_utc.hour} "
            f"{trigger_utc.day} {trigger_utc.month} *"
        )
        crons.append((m["datetime"], trigger_utc, cron, m["round"]))

    return crons


def update_workflow(workflow_path: str, crons: list[tuple]):
    """Aktualizuje sekcję schedule w scrape.yml między markerami."""
    with open(workflow_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Buduj blok schedule
    lines = [MARKER_START]
    if crons:
        lines.append("  schedule:")
        for match_local, trigger_utc, cron, rnd in crons:
            tz_name = match_local.strftime("%Z")
            trigger_local = match_local + timedelta(hours=TRIGGER_DELAY_HOURS)
            comment = (
                f"K{rnd} {match_local.strftime('%d.%m')} "
                f"mecz {match_local.strftime('%H:%M')} {tz_name} → "
                f"trigger {trigger_local.strftime('%H:%M')} {tz_name}"
            )
            lines.append(f"    - cron: '{cron}'  # {comment}")
    lines.append(MARKER_END)
    new_block = "\n".join(lines)

    # Zamień istniejący blok między markerami
    if MARKER_START in content and MARKER_END in content:
        pattern = re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END)
        content = re.sub(pattern, new_block, content, flags=re.DOTALL)
    else:
        # Pierwsze uruchomienie — wstaw przed "jobs:"
        # Szukaj starego zakomentowanego schedule
        old_schedule = re.search(
            r"\n  # Automatyczne uruchomienie.*?\n(  #   - cron:.*?\n)?",
            content,
            re.DOTALL,
        )
        if old_schedule:
            content = content[: old_schedule.start()] + "\n" + new_block + "\n" + content[old_schedule.end() :]
        else:
            content = content.replace("\njobs:", f"\n{new_block}\n\njobs:")

    with open(workflow_path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    print("📅 Parsowanie terminarz.txt...")
    matches = parse_terminarz(TERMINARZ_FILE)
    print(f"   Znaleziono {len(matches)} meczów")

    if not matches:
        print("⚠️  Brak meczów w terminarzu!")
        return

    # Filtruj tylko przyszłe mecze
    now = datetime.now(tz=TZ_WARSAW)
    future = [m for m in matches if m["datetime"] > now]
    print(f"   Przyszłych meczów: {len(future)}")

    crons = generate_crons(future)
    print(f"\n⏰ Wygenerowano {len(crons)} triggerów:")
    for match_local, trigger_utc, cron, rnd in crons:
        tz_name = match_local.strftime("%Z")
        trigger_local = match_local + timedelta(hours=TRIGGER_DELAY_HOURS)
        print(
            f"   K{rnd} {match_local.strftime('%d.%m %H:%M')} {tz_name}"
            f" → trigger {trigger_local.strftime('%H:%M')} {tz_name}"
            f" ({trigger_utc.strftime('%H:%M')} UTC)"
        )

    print(f"\n📝 Aktualizacja {WORKFLOW_FILE}...")
    update_workflow(WORKFLOW_FILE, crons)
    print("✅ Gotowe!")


if __name__ == "__main__":
    main()
