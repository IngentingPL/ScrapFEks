#!/usr/bin/env python3
"""
Parsuje terminarz.txt i aktualizuje schedule w scrape.yml.

Dla każdego dnia meczowego bierze najpóźniejszy mecz, dodaje 2.5 godziny
i generuje cron trigger w UTC.

Użycie:
    python update_schedule.py
"""

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from round_dates import round_date_range

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

TRIGGER_DELAY_HOURS = 2.5
DEFAULT_FIRST_MATCH_HOUR = 21
DEFAULT_FIRST_MATCH_MINUTE = 0

# Karencja przy czyszczeniu harmonogramu.
# Slot, którego czas minął mniej niż 48 h temu, zostaje w scrape.yml.
# Dzięki temu opóźniony bieg GitHub Actions nie traci swojego triggera.
RETENTION_HOURS = 48

# Zapasowy slot PRE: rano w dniu pierwszego meczu (UTC).
# Godzina 5:07 UTC daje 6 h zapasu przed wieczornym meczem.
# Jeśli pierwszy mecz jest wyjątkowo wcześnie, cofamy się o kolejne godziny.
PRE_BACKUP_HOUR_UTC = 5
PRE_BACKUP_MINUTE = 7
PRE_BACKUP_DELAY_HOURS = 6

# Zapasowy slot POST: 16:07 UTC w dniu POST.
# Główny POST jest około 11:00 UTC, więc zapas jest kilka godzin później,
# a nawet z opóźnieniem 5 h zdąży przed północą UTC.
POST_BACKUP_HOUR_UTC = 16
POST_BACKUP_MINUTE = 7


def parse_terminarz(filepath: str) -> tuple[list[dict], dict]:
    """
    Parsuje terminarz.txt i zwraca:
    - listę meczów z datą/godziną
    - słownik statystyk per kolejka (ile meczów, ile z godziną)
    """
    matches = []
    current_round = None
    round_start_date = None  # pierwsza data z nagłówka kolejki
    round_stats = {}  # round -> {"total": X, "with_time": Y, "dates": "DD-DD.MM"}

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Nagłówek kolejki: obsługa dwóch formatów:
            # (a) "DD-DD miesiąc" np. "19-20 września" - ten sam miesiąc
            # (b) "DD miesiąc-DD miesiąc" np. "31 października-1 listopada" - przełom miesięcy
            round_match = re.match(r"Kolejka\s+(\d+)\s*-\s*(.+)", line)
            if round_match:
                current_round = int(round_match.group(1))
                date_part = round_match.group(2).strip()

                day_start = None
                month_start = None

                # Format (b): "31 października-1 listopada" - dzień i miesiąc przed myślnikiem
                # Wzorzec: cyfra + spacja + nazwa miesiąca + myślnik
                cross_month_match = re.match(r"(\d{1,2})\s+(\w+)\s*[–\-]", date_part)
                if cross_month_match:
                    day_start = int(cross_month_match.group(1))
                    month_name = cross_month_match.group(2).lower()
                    month_start = MONTHS_PL.get(month_name)

                # Format (a): "19-20 września" - tylko dzień przed myślnikiem
                # Sprawdź tylko jeśli format (b) nie pasował
                if day_start is None:
                    simple_match = re.match(r"(\d{1,2})[–\-]", date_part)
                    if simple_match:
                        day_start = int(simple_match.group(1))
                        # Miesiąc jest na końcu nagłówka
                        month_match = re.search(r"(\w+)(?:[–\-]\d+)?\s*$", date_part)
                        if month_match:
                            month_name = month_match.group(1).lower()
                            month_start = MONTHS_PL.get(month_name)

                if day_start and month_start:
                    # Zbuduj datę początku kolejki (rok: bieżący lub następny)
                    now = datetime.now()
                    year = now.year
                    if month_start < now.month - 6:
                        year += 1
                    round_start_date = datetime(year, month_start, day_start).date()

                    # Format dat do wyświetlenia - szukamy dnia końcowego
                    # Dla formatu (a): "19-20 września" -> wyciągnij 20
                    # Dla formatu (b): "31 października-1 listopada" -> wyciągnij 1
                    end_day_match = re.search(r"[–\-](\d{1,2})(?:\s|$)", date_part)
                    if end_day_match:
                        end_day = int(end_day_match.group(1))
                        date_str = f"{day_start}-{end_day}.{month_start:02d}"
                    else:
                        date_str = f"{day_start}.{month_start:02d}"

                    round_stats[current_round] = {
                        "total": 0,
                        "with_time": 0,
                        "start_date": round_start_date,
                        "dates": date_str,
                        "match_dates": [],
                        "all_dates_confirmed": True,
                    }
                continue

            # Linia meczu z godziną: "Team A\t-\tTeam B\tDD miesiąc, HH:MM"
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

                if current_round in round_stats:
                    round_stats[current_round]["match_dates"].append(match_local.date())

                # Zlicz mecze w kolejce
                if current_round in round_stats:
                    round_stats[current_round]["total"] += 1
                    round_stats[current_round]["with_time"] += 1
            else:
                # Mecz bez godziny może mieć zwykły myślnik albo zapisany wynik.
                has_match_separator = (
                    " - " in line
                    or "\t-\t" in line
                    or "–" in line
                    or re.search(r"\t+\d+\s*:\s*\d+\t+", line)
                    or re.search(r"\t+\d+-\d+\t+", line)
                )
                if current_round and has_match_separator:
                    # Filtruj: mecz to linia bez cyfr w nazwach drużyn i bez opisów zdarzeń
                    has_digit_in_teams = re.search(r'^[^\d]*\d[^\d]*[–\-]', line)
                    is_event_line = re.search(r'żółt|kartk|czerwon|ukar|sędzi|minucie', line, re.IGNORECASE)
                    if not has_digit_in_teams and not is_event_line:
                        # To mecz bez godziny
                        if current_round in round_stats:
                            round_stats[current_round]["total"] += 1
                            # Zachowaj jawną datę meczu, nawet jeśli nie ma godziny.
                            no_time_date = re.search(r"(\d{1,2})\s+(\w+),\s*$", line)
                            if no_time_date:
                                month = MONTHS_PL.get(no_time_date.group(2))
                                if month:
                                    now = datetime.now()
                                    year = now.year
                                    if month < now.month - 6:
                                        year += 1
                                    try:
                                        match_day = datetime(
                                            year, month, int(no_time_date.group(1))
                                        ).date()
                                    except ValueError:
                                        match_day = None
                                    if match_day:
                                        round_stats[current_round]["match_dates"].append(match_day)
                                    else:
                                        round_stats[current_round]["all_dates_confirmed"] = False
                                else:
                                    round_stats[current_round]["all_dates_confirmed"] = False
                            else:
                                round_stats[current_round]["all_dates_confirmed"] = False

    return matches, round_stats


def select_first_day_datetime(
    matches: list[dict], first_day
) -> datetime:
    """Wybiera najwcześniejszą godzinę z pierwszego dnia lub używa 21:00."""
    same_day = [
        m["datetime"]
        for m in matches
        if m.get("datetime") is not None and m["datetime"].date() == first_day
    ]
    if same_day:
        return min(same_day)
    return datetime(
        first_day.year,
        first_day.month,
        first_day.day,
        DEFAULT_FIRST_MATCH_HOUR,
        DEFAULT_FIRST_MATCH_MINUTE,
        tzinfo=TZ_WARSAW,
    )


def generate_crons(
    matches: list[dict],
    round_dates: dict[int, list] | None = None,
    all_dates_confirmed: dict[int, bool] | None = None,
) -> list[tuple]:
    """
    Generuje cron triggery:
    1. 30 min po pierwszym meczu każdej kolejki (szybkie odświeżenie)
    2. 2.5h po każdym meczu (pełne odświeżenie)
    3. Dzień przed pierwszym meczem kolejki o 20:00 (Discord pre-round)
    4. Dzień po ostatnim meczu kolejki o 10:00 (Discord post-round)
    5. Zapasowy pre-round rano w dniu pierwszego meczu (UTC)
    6. Zapasowy post-round kilka godzin po głównym (UTC)

    Deduplikuje identyczne czasy triggerów.
    Zwraca: [(label, match_local, trigger_utc, cron_str, round), ...]
    """
    seen = set()
    crons = []

    sorted_matches = sorted(matches, key=lambda x: x["datetime"])

    # Daty kolejki obejmują też mecze bez godziny.
    round_dates = round_dates or {}
    all_dates_confirmed = all_dates_confirmed or {}
    matches_per_round = {}
    for m in sorted_matches:
        rnd = m["round"]
        matches_per_round.setdefault(rnd, []).append(m)

    first_per_round = {}
    last_day_per_round = {}
    for rnd, round_matches in matches_per_round.items():
        all_dates = list(round_dates.get(rnd, []))
        all_dates.extend(m["datetime"].date() for m in round_matches)
        first_day, last_day = round_date_range(
            all_dates, all_dates_confirmed.get(rnd, True)
        )
        if first_day is None:
            continue
        first_per_round[rnd] = {
            "round": rnd,
            "datetime": select_first_day_datetime(round_matches, first_day),
        }
        last_day_per_round[rnd] = last_day

    # 1. Pierwszy mecz per kolejka + 30 min (szybkie odświeżenie po starcie kolejki)
    for rnd, m in sorted(first_per_round.items()):
        trigger_local = m["datetime"] + timedelta(minutes=30)
        trigger_utc = trigger_local.astimezone(TZ_UTC)
        key = (trigger_utc.month, trigger_utc.day, trigger_utc.hour, trigger_utc.minute)
        if key not in seen:
            seen.add(key)
            cron = (
                f"{trigger_utc.minute} {trigger_utc.hour} "
                f"{trigger_utc.day} {trigger_utc.month} *"
            )
            crons.append(("start", m["datetime"], trigger_utc, cron, rnd))

    # 2. Każdy mecz + 2.5h (pełne odświeżenie po meczu)
    for m in sorted_matches:
        trigger_local = m["datetime"] + timedelta(hours=TRIGGER_DELAY_HOURS)
        trigger_utc = trigger_local.astimezone(TZ_UTC)
        key = (trigger_utc.month, trigger_utc.day, trigger_utc.hour, trigger_utc.minute)
        if key in seen:
            continue
        seen.add(key)
        cron = (
            f"{trigger_utc.minute} {trigger_utc.hour} "
            f"{trigger_utc.day} {trigger_utc.month} *"
        )
        crons.append(("post", m["datetime"], trigger_utc, cron, m["round"]))

    # 3. Dzień przed pierwszym meczem o 20:00 (Discord pre-round notification)
    # Scraper sprawdzi warunek timingowy i wyśle prognozę na Discord
    for rnd, m in sorted(first_per_round.items()):
        first_day = m["datetime"].date()
        notify_day = first_day - timedelta(days=1)
        notify_local = datetime(
            notify_day.year, notify_day.month, notify_day.day, 20, 0,
            tzinfo=TZ_WARSAW,
        )
        trigger_utc = notify_local.astimezone(TZ_UTC)
        key = (trigger_utc.month, trigger_utc.day, trigger_utc.hour, trigger_utc.minute)
        if key not in seen:
            seen.add(key)
            cron = (
                f"{trigger_utc.minute} {trigger_utc.hour} "
                f"{trigger_utc.day} {trigger_utc.month} *"
            )
            crons.append(("discord_pre", notify_local, trigger_utc, cron, rnd))

    # 3.5. Godzinę po pierwszym meczu (Discord captains notification)
    for rnd, m in sorted(first_per_round.items()):
        first_dt = m["datetime"]
        notify_dt = first_dt + timedelta(hours=1)
        notify_local = notify_dt.astimezone(TZ_WARSAW)
        trigger_utc = notify_local.astimezone(TZ_UTC)
        key = (trigger_utc.month, trigger_utc.day, trigger_utc.hour, trigger_utc.minute)
        if key not in seen:
            seen.add(key)
            cron = (
                f"{trigger_utc.minute} {trigger_utc.hour} "
                f"{trigger_utc.day} {trigger_utc.month} *"
            )
            crons.append(("discord_captains", notify_local, trigger_utc, cron, rnd))

    # 4. Dzień po ostatnim meczu o 12:00 (Discord post-round notification)
    # Scraper sprawdzi warunek timingowy i wyśle podsumowanie kolejki na Discord
    for rnd, last_day in sorted(last_day_per_round.items()):
        notify_day = last_day + timedelta(days=1)
        notify_local = datetime(
            notify_day.year, notify_day.month, notify_day.day, 12, 0,
            tzinfo=TZ_WARSAW,
        )
        trigger_utc = notify_local.astimezone(TZ_UTC)
        key = (trigger_utc.month, trigger_utc.day, trigger_utc.hour, trigger_utc.minute)
        if key not in seen:
            seen.add(key)
            cron = (
                f"{trigger_utc.minute} {trigger_utc.hour} "
                f"{trigger_utc.day} {trigger_utc.month} *"
            )
            crons.append(("discord_post", notify_local, trigger_utc, cron, rnd))

    # 5. Zapasowy slot PRE rano w dniu pierwszego meczu (UTC).
    # Ma wystartować nawet z opóźnieniem 6 h, więc cofamy godzinę,
    # dopóki trigger + 6 h nie wypadnie przed pierwszym meczem.
    for rnd, m in sorted(first_per_round.items()):
        first_match_utc = m["datetime"].astimezone(TZ_UTC)
        backup_hour = PRE_BACKUP_HOUR_UTC
        while backup_hour >= 0:
            backup_utc = datetime(
                first_match_utc.year,
                first_match_utc.month,
                first_match_utc.day,
                backup_hour,
                PRE_BACKUP_MINUTE,
                tzinfo=TZ_UTC,
            )
            if backup_utc + timedelta(hours=PRE_BACKUP_DELAY_HOURS) < first_match_utc:
                break
            backup_hour -= 1
        if backup_hour < 0:
            continue
        key = (backup_utc.month, backup_utc.day, backup_utc.hour, backup_utc.minute)
        if key not in seen:
            seen.add(key)
            cron = (
                f"{backup_utc.minute} {backup_utc.hour} "
                f"{backup_utc.day} {backup_utc.month} *"
            )
            crons.append(
                (
                    "discord_pre_backup",
                    backup_utc.astimezone(TZ_WARSAW),
                    backup_utc,
                    cron,
                    rnd,
                )
            )

    # 6. Zapasowy slot POST w dniu POST, kilka godzin po głównym.
    # 16:07 UTC + 5 h opóźnienia = 21:07 UTC, czyli jeszcze przed północą.
    for rnd, last_day in sorted(last_day_per_round.items()):
        notify_day = last_day + timedelta(days=1)
        backup_utc = datetime(
            notify_day.year,
            notify_day.month,
            notify_day.day,
            POST_BACKUP_HOUR_UTC,
            POST_BACKUP_MINUTE,
            tzinfo=TZ_UTC,
        )
        key = (backup_utc.month, backup_utc.day, backup_utc.hour, backup_utc.minute)
        if key not in seen:
            seen.add(key)
            cron = (
                f"{backup_utc.minute} {backup_utc.hour} "
                f"{backup_utc.day} {backup_utc.month} *"
            )
            crons.append(
                (
                    "discord_post_backup",
                    backup_utc.astimezone(TZ_WARSAW),
                    backup_utc,
                    cron,
                    rnd,
                )
            )

    # Sortuj chronologicznie
    crons.sort(key=lambda x: x[2])
    return crons


def extract_existing_crons(workflow_path: str) -> dict[int, list[str]]:
    """
    Wyciąga istniejące linie cron z scrape.yml per kolejka.
    Zwraca słownik: {round_number: [linie_cron]}.
    Linia cron to pełna linia z komentarzem "# K{n} ...".
    """
    existing = {}
    try:
        with open(workflow_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Znajdź blok między markerami
        if MARKER_START not in content or MARKER_END not in content:
            return existing

        start_idx = content.find(MARKER_START)
        end_idx = content.find(MARKER_END)
        block = content[start_idx:end_idx]

        # Szukaj linii cron z komentarzem "# K{num} ..."
        for line in block.split("\n"):
            # Szukaj komentarza z numerem kolejki
            match = re.search(r"#\s*K(\d+)\s", line)
            if match:
                round_num = int(match.group(1))
                if round_num not in existing:
                    existing[round_num] = []
                existing[round_num].append(line.rstrip())
    except Exception:
        pass

    return existing


def _parse_cron_fields(cron: str):
    """Zwraca (minuta, godzina, dzień, miesiąc) z prostego crona."""
    parts = cron.split()
    if len(parts) < 5:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return None


def _nearest_trigger_utc(month, day, hour, minute, now_utc):
    """
    Cron nie ma roku, więc wybieramy rok, w którym data wypada najbliżej
    „teraz”. Działa to także na przełomie roku (np. grudzień w styczniu).
    """
    candidates = []
    for year in (now_utc.year - 1, now_utc.year, now_utc.year + 1):
        try:
            candidates.append(
                datetime(year, month, day, hour, minute, tzinfo=TZ_UTC)
            )
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda value: abs(value - now_utc))


def _parse_existing_cron(line: str, now_utc: datetime):
    """Zwraca (kolejka, czas UTC, cron) dla linii z bloku AUTO-SCHEDULE."""
    cron_match = re.search(r"cron:\s*'([^']+)'", line)
    if not cron_match:
        return None
    fields = _parse_cron_fields(cron_match.group(1))
    if fields is None:
        return None
    round_match = re.search(r"#\s*K(\d+)\b", line)
    if not round_match:
        return None
    minute, hour, day, month = fields
    trigger_utc = _nearest_trigger_utc(month, day, hour, minute, now_utc)
    if trigger_utc is None:
        return None
    return int(round_match.group(1)), trigger_utc, cron_match.group(1)


def _retention_end_for_round(round_number: int, round_stats: dict):
    """
    Zwraca koniec ochrony kolejki: koniec dnia POST + 1 dzień (UTC).

    POST wypada dzień po ostatnim meczu, więc ochrona trwa do
    (ostatni mecz + 3 dni) o 00:00 UTC.
    """
    stats = round_stats.get(round_number, {})
    dates = [day for day in stats.get("match_dates", []) if day is not None]
    if stats.get("all_dates_confirmed", True) and dates:
        end_day = max(dates) + timedelta(days=3)
    elif stats.get("start_date"):
        # Brak potwierdzonych dat — zakładamy 3 dni meczowe i dokładamy POST+1.
        end_day = stats["start_date"] + timedelta(days=6)
    elif dates:
        end_day = max(dates) + timedelta(days=3)
    else:
        return None
    return datetime(end_day.year, end_day.month, end_day.day, tzinfo=TZ_UTC)


def _format_generated_cron(entry: dict) -> str:
    """Formatuje jedną nową linię schedule z komentarzem po polsku."""
    rnd = entry["round"]
    label = entry["label"]
    match_local = entry["match_local"]
    trigger_utc = entry["trigger"]
    cron = entry["cron"]
    tz_name = match_local.strftime("%Z")

    if label == "start":
        trigger_local = match_local + timedelta(minutes=30)
        comment = (
            f"K{rnd} START {match_local.strftime('%d.%m')} "
            f"mecz {match_local.strftime('%H:%M')} {tz_name} → "
            f"+30min {trigger_local.strftime('%H:%M')} {tz_name}"
        )
    elif label == "discord_pre":
        comment = (
            f"K{rnd} DISCORD PRE {match_local.strftime('%d.%m')} "
            f"20:00 {tz_name} — prognoza przed kolejką"
        )
    elif label == "discord_pre_backup":
        comment = (
            f"K{rnd} DISCORD PRE ZAPAS {trigger_utc.strftime('%d.%m')} "
            f"{trigger_utc.strftime('%H:%M')} UTC — zapas przed kolejką"
        )
    elif label == "discord_post":
        comment = (
            f"K{rnd} DISCORD POST {match_local.strftime('%d.%m')} "
            f"12:00 {tz_name} — podsumowanie po kolejce"
        )
    elif label == "discord_post_backup":
        comment = (
            f"K{rnd} DISCORD POST ZAPAS {trigger_utc.strftime('%d.%m')} "
            f"{trigger_utc.strftime('%H:%M')} UTC — zapas po kolejce"
        )
    elif label == "discord_captains":
        comment = (
            f"K{rnd} DISCORD CAPTAINS {match_local.strftime('%d.%m')} "
            f"{match_local.strftime('%H:%M')} {tz_name} — podsumowanie kapitanów"
        )
    else:
        trigger_local = match_local + timedelta(hours=TRIGGER_DELAY_HOURS)
        comment = (
            f"K{rnd} {match_local.strftime('%d.%m')} "
            f"mecz {match_local.strftime('%H:%M')} {tz_name} → "
            f"+2.5h {trigger_local.strftime('%H:%M')} {tz_name}"
        )
    return f"    - cron: '{cron}'  # {comment}"


def build_schedule_block(
    crons: list[tuple],
    existing_crons: dict[int, list[str]],
    round_stats: dict,
    now: datetime | None = None,
) -> list[str]:
    """
    Buduje NOWĄ listę linii schedule w pamięci.

    Zasady:
    - nowe crony dotyczą tylko przyszłości (przeszły trigger i tak nie wystartuje),
    - istniejący slot zostaje, jeśli jego czas minął mniej niż 48 h temu,
    - przyszły slot kolejki zostaje do końca dnia POST + 1 dzień (UTC),
      nawet gdy terminarz nie ma już godzin meczów (wyniki są kompletne).
    """
    now_utc = (now or datetime.now(TZ_UTC)).astimezone(TZ_UTC)
    cutoff_utc = now_utc - timedelta(hours=RETENTION_HOURS)

    all_rounds = set(round_stats)
    all_rounds.update(existing_crons)
    all_rounds.update(rnd for _, _, _, _, rnd in crons)
    retention_end = {
        rnd: _retention_end_for_round(rnd, round_stats) for rnd in all_rounds
    }

    entries = []
    seen = set()

    def _cron_key(trigger_utc: datetime):
        # Bez roku — tak jak dotychczasowa deduplikacja w generatorze.
        return (
            trigger_utc.month,
            trigger_utc.day,
            trigger_utc.hour,
            trigger_utc.minute,
        )

    # 1. Nowe crony — tylko przyszłe. Przeszły trigger jest już bezużyteczny.
    for label, match_local, trigger_utc, cron, rnd in crons:
        if trigger_utc <= now_utc:
            continue
        key = _cron_key(trigger_utc)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "round": rnd,
                "trigger": trigger_utc,
                "line": None,
                "label": label,
                "match_local": match_local,
                "cron": cron,
            }
        )

    # 2. Stare wpisy — karencja 48 h oraz okno kolejki do końca POST+1 (UTC).
    for rnd, lines in existing_crons.items():
        for line in lines:
            parsed = _parse_existing_cron(line, now_utc)
            if parsed is None:
                continue
            line_round, trigger_utc, cron = parsed
            keep = trigger_utc >= cutoff_utc and (
                trigger_utc <= now_utc
                or (
                    retention_end.get(line_round) is not None
                    and trigger_utc < retention_end[line_round]
                )
            )
            if not keep:
                continue
            key = _cron_key(trigger_utc)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "round": line_round,
                    "trigger": trigger_utc,
                    "line": line,
                    "label": None,
                    "match_local": None,
                    "cron": cron,
                }
            )

    if not entries:
        return [MARKER_START, MARKER_END]

    def _round_sort_key(rnd):
        start_date = round_stats.get(rnd, {}).get("start_date")
        if start_date is not None:
            return (0, start_date, rnd)
        earliest = min(
            (entry["trigger"] for entry in entries if entry["round"] == rnd),
            default=now_utc,
        )
        return (1, earliest, rnd)

    entries.sort(key=lambda entry: (_round_sort_key(entry["round"]), entry["trigger"]))

    lines = [MARKER_START, "  schedule:"]
    for entry in entries:
        if entry["line"] is not None:
            # Zachowany stary wpis — zostawiamy jego linię bez zmian.
            lines.append(entry["line"])
        else:
            lines.append(_format_generated_cron(entry))
    lines.append(MARKER_END)
    return lines


def update_workflow(workflow_path: str, new_lines: list[str]):
    """
    Aktualizuje sekcję schedule w scrape.yml między markerami.
    Przyjmuje już przygotowaną listę linii (z build_schedule_block).
    """
    with open(workflow_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_block = "\n".join(new_lines)

    # Zamień istniejący blok między markerami
    if MARKER_START in content and MARKER_END in content:
        pattern = re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END)
        content = re.sub(pattern, new_block, content, flags=re.DOTALL)
    else:
        # Pierwsze uruchomzenie — wstaw przed "jobs:"
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


def check_missing_times(round_stats: dict) -> bool:
    """
    Sprawdza czy kolejki w ciągu ±14 dni mają mecze bez godziny.
    Zwraca True jeśli znaleziono braki (ale NIE przerywa działania).
    Wypisuje ostrzeżenia dla użytkownika.
    """
    today = datetime.now().date()
    window_start = today - timedelta(days=14)
    window_end = today + timedelta(days=14)
    has_warnings = False

    for round_num, stats in sorted(round_stats.items()):
        start_date = stats.get("start_date")
        if not start_date:
            continue
        # Sprawdź czy kolejka zaczyna się w oknie ±14 dni (łącznie z kolejkami w trakcie)
        if window_start <= start_date <= window_end:
            without_time = stats["total"] - stats["with_time"]
            if without_time > 0:
                print(
                    f"⚠️  Kolejka {round_num} ({stats['dates']}) — "
                    f"{without_time} z {stats['total']} meczów bez godziny, "
                    f"crony zostaną zachowane w oknie ochrony"
                )
                has_warnings = True

    return has_warnings


def main():
    print("📅 Parsowanie terminarz.txt...")
    matches, round_stats = parse_terminarz(TERMINARZ_FILE)
    print(f"   Znaleziono {len(matches)} meczów z godziną")

    # WALIDACJA: Sprawdź czy terminarz nie jest pusty/błędny
    if not round_stats:
        print("❌ Błąd: terminazarz.txt jest pusty lub niepoprawny!")
        print("   scrape.yml NIE został zmieniony.")
        sys.exit(1)

    # Sprawdź mecze bez godziny w kolejkach w ciągu 14 dni (ostrzeżenie, nie błąd)
    has_missing_times = check_missing_times(round_stats)
    if has_missing_times:
        print("   ℹ️  Brakujące godziny — istniejące crony zostaną zachowane w oknie ochrony.")

    # Krok 1: Wyciągnij istniejące crony z scrape.yml (do zachowania)
    print(f"\n📝 Parsowanie {WORKFLOW_FILE}...")
    existing_crons = extract_existing_crons(WORKFLOW_FILE)
    print(f"   Znaleziono crony dla {len(existing_crons)} kolejek")

    # Krok 2: Generuj nowe crony (tylko dla kolejek z godzinami)
    crons = []
    if matches:
        dates_by_round = {
            rnd: stats.get("match_dates", [])
            for rnd, stats in round_stats.items()
        }
        confirmed_by_round = {
            rnd: stats.get("all_dates_confirmed", True)
            for rnd, stats in round_stats.items()
        }
        crons = generate_crons(matches, dates_by_round, confirmed_by_round)
        print(f"\n⏰ Wygenerowano {len(crons)} nowych triggerów:")
        for label, match_local, trigger_utc, cron, rnd in crons:
            tz_name = match_local.strftime("%Z")
            if label == "start":
                trigger_local = match_local + timedelta(minutes=30)
                tag = "START       "
                print(
                    f"   {tag} K{rnd} {match_local.strftime('%d.%m %H:%M')} {tz_name}"
                    f" → {trigger_local.strftime('%H:%M')} {tz_name}"
                    f" ({trigger_utc.strftime('%H:%M')} UTC)"
                )
            elif label == "discord_pre":
                tag = "📣 DISC PRE  "
                print(
                    f"   {tag} K{rnd} {match_local.strftime('%d.%m')} 20:00 {tz_name}"
                    f" ({trigger_utc.strftime('%H:%M')} UTC)"
                )
            elif label == "discord_post":
                tag = "📣 DISC POST "
                print(
                    f"   {tag} K{rnd} {match_local.strftime('%d.%m')} 10:00 {tz_name}"
                    f" ({trigger_utc.strftime('%H:%M')} UTC)"
                )
            elif label == "discord_pre_backup":
                tag = "📣 PRE ZAPAS"
                print(
                    f"   {tag} K{rnd} {trigger_utc.strftime('%d.%m')} "
                    f"{trigger_utc.strftime('%H:%M')} UTC — zapas przed kolejką"
                )
            elif label == "discord_post_backup":
                tag = "📣 POST ZAPAS"
                print(
                    f"   {tag} K{rnd} {trigger_utc.strftime('%d.%m')} "
                    f"{trigger_utc.strftime('%H:%M')} UTC — zapas po kolejce"
                )
            elif label == "discord_captains":
                tag = "👑 DISC CAPT "
                print(
                    f"   {tag} K{rnd} {match_local.strftime('%d.%m')} {match_local.strftime('%H:%M')} {tz_name}"
                    f" ({trigger_utc.strftime('%H:%M')} UTC)"
                )
            else:
                trigger_local = match_local + timedelta(hours=TRIGGER_DELAY_HOURS)
                tag = "            "
                print(
                    f"   {tag} K{rnd} {match_local.strftime('%d.%m %H:%M')} {tz_name}"
                    f" → {trigger_local.strftime('%H:%M')} {tz_name}"
                    f" ({trigger_utc.strftime('%H:%M')} UTC)"
                )

    # Krok 3: Buduj nowy blok schedule w pamięci (nowe + zachowane)
    new_lines = build_schedule_block(crons, existing_crons, round_stats)

    # Krok 4: Zapisz scrape.yml (dopiero na końcu, po wszystkich walidacjach)
    print(f"\n📝 Aktualizacja {WORKFLOW_FILE}...")
    update_workflow(WORKFLOW_FILE, new_lines)
    print("✅ Gotowe!")


if __name__ == "__main__":
    main()
