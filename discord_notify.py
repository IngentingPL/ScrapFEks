"""
discord_notify.py — Powiadomienia Discord dla ScrapFEks
=========================================================

Wysyła dwa rodzaje postów na Discord przez webhook:
1. PRE-ROUND  — dzień przed kolejką: prognozy i captain pick
2. POST-ROUND — dzień po kolejce:   wyniki ligi prywatnej

📖 LEKCJA: Webhook to prosty URL, na który możemy wysłać POST request
z danymi JSON — Discord sam wyświetli wiadomość na kanale.
Nie potrzebujemy żadnej zewnętrznej biblioteki, używamy TYLKO urllib.request
z biblioteki standardowej Pythona.

Autor: Wygenerowane przez Claude dla Piotra
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta


# ============================================================
# STAŁE KONFIGURACYJNE
# ============================================================

OUTPUT_DIR = "output"

# Plik do śledzenia wysłanych postów — żeby nie wysyłać dwa razy
# Przykład zawartości: {"pre_round": 27, "post_round": 26}
DISCORD_SENT_FILE = os.path.join(OUTPUT_DIR, "discord_sent.json")

# Timeout dla requestów do Discord (sekundy)
WEBHOOK_TIMEOUT = 10

# Link do dashboardu — pojawi się w footerze każdego embeda
DASHBOARD_URL = "ingentingpl.github.io/ScrapFEks"


# ============================================================
# FUNKCJE POMOCNICZE — obsługa pliku z logiem wysłanych postów
# ============================================================

def _load_sent_log():
    """
    Wczytuje log wysłanych postów Discord z pliku JSON.

    Zwraca słownik {"pre_round": N, "post_round": M}.
    Jeśli plik nie istnieje (pierwsze uruchomienie) — zwraca zera.

    📖 LEKCJA: Zaczynamy od 0, bo żadna kolejka nie była jeszcze obsłużona.
    """
    if not os.path.exists(DISCORD_SENT_FILE):
        return {"pre_round": 0, "post_round": 0}
    try:
        with open(DISCORD_SENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # Jeśli plik jest uszkodzony — zacznij od nowa
        return {"pre_round": 0, "post_round": 0}


def _save_sent_log(log):
    """
    Zapisuje log wysłanych postów do pliku JSON.

    📖 LEKCJA: os.makedirs z exist_ok=True tworzy katalog jeśli nie istnieje,
    ale nie wyrzuca błędu jeśli już istnieje — bardzo przydatne!
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(DISCORD_SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ============================================================
# FUNKCJE POMOCNICZE — wysyłanie requestów do Discord
# ============================================================

def _send_embed(webhook_url, embed, content=None):
    """
    Wysyła jeden Discord embed przez webhook URL.

    Discord API oczekuje JSON: {"embeds": [{ ... }], "content": "..."}
    - "embeds" to lista kart z tytułem, kolorem i sekcjami
    - "content" to zwykły tekst pojawiający się NAD embedem (np. wzmianki @)

    Zwraca True jeśli wysyłka się powiodła, False w przypadku błędu.

    📖 LEKCJA: urllib.request.Request pozwala zbudować dowolny HTTP request.
    Ustawiamy headers (nagłówki) żeby Discord wiedział, że wysyłamy JSON.
    """
    data = {"embeds": [embed]}
    if content:
        # content pojawia się nad embedem — tu wstawiamy @wzmianki
        data["content"] = content
    payload = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/IngentingPL/ScrapFEks, 1.0)",
        },
        method="POST",
    )

    # DEBUG: pokaż pierwsze/ostatnie znaki URL żeby wykryć literówki bez ujawniania tokenu
    url_preview = webhook_url[:50] + "..." + webhook_url[-10:] if len(webhook_url) > 60 else webhook_url
    print(f"  🔍 DEBUG webhook URL: {url_preview} (długość: {len(webhook_url)})")
    print(f"  🔍 DEBUG payload: {len(payload)} bajtów")

    try:
        with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as resp:
            # Discord zwraca 204 No Content przy sukcesie
            print(f"  🔍 DEBUG odpowiedź: HTTP {resp.status}")
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        # Błąd HTTP np. 401 (zły webhook), 429 (rate limit)
        body = e.read().decode("utf-8", errors="replace")
        print(f"  ⚠️  Discord webhook HTTP błąd: {e.code} {e.reason}")
        print(f"  🔍 DEBUG odpowiedź Discord: {body}")
        return False
    except urllib.error.URLError as e:
        # Błąd sieci — brak połączenia, timeout
        print(f"  ⚠️  Discord webhook błąd połączenia: {e.reason}")
        return False
    except Exception as e:
        # Inny nieoczekiwany błąd — logujemy i kontynuujemy
        print(f"  ⚠️  Discord webhook nieoczekiwany błąd: {e}")
        return False


# ============================================================
# FUNKCJE POMOCNICZE — parsowanie dat z terminarz.txt
# ============================================================

def _parse_date_str(date_str):
    """
    Parsuje datę w formacie 'DD.MM' (z terminarz.txt) na obiekt datetime.date.

    Rok określamy na podstawie sezonu 2025-2026:
    - sierpień–grudzień → 2025
    - styczeń–lipiec    → 2026

    Zwraca None jeśli nie udało się sparsować.

    📖 LEKCJA: Sezon ligowy w Polsce trwa od sierpnia do maja.
    Mecze sierpień-grudzień to runda jesienna (2025), styczeń-maj to wiosenna (2026).
    """
    if not date_str or "." not in date_str:
        return None
    try:
        parts = date_str.strip().split(".")
        day = int(parts[0])
        month = int(parts[1])
        # Sezon 2025-2026: sierpień-grudzień = 2025, styczeń-lipiec = 2026
        year = 2025 if month >= 8 else 2026
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def _get_round_date_range(fixtures_data, round_num):
    """
    Zwraca (first_date, last_date) — zakres dat meczów danej kolejki.

    Używa danych z parse_terminarz() gdzie matches to dict:
    {"25": [{"home": "Lech", "away": "Legia", "date": "14.03"}, ...], ...}

    Zwraca (None, None) jeśli brak danych dla tej kolejki.
    """
    matches = fixtures_data.get("matches", {}).get(str(round_num), [])
    dates = []
    for m in matches:
        d = _parse_date_str(m.get("date", ""))
        if d:
            dates.append(d)
    if not dates:
        return None, None
    return min(dates), max(dates)


def _parse_ownership_pct(pct_str):
    """
    Parsuje string popularności np. '12.3%' na float 12.3.

    Zwraca 100.0 (maksimum) jeśli nie udało się sparsować —
    bezpieczny fallback, żeby gracz nie był przypadkowo wybierany
    jako "differential" przy błędnych danych.
    """
    if not pct_str:
        return 100.0
    try:
        return float(str(pct_str).replace("%", "").strip())
    except (ValueError, TypeError):
        return 100.0


# ============================================================
# LOGIKA TIMINGOWA — kiedy wysyłać który post
# ============================================================

def should_send_pre_round(round_number, fixtures_data):
    """
    Sprawdza czy DZIŚ należy wysłać pre-round dla podanej kolejki.

    Warunek: dzisiejsza data == dzień PRZED pierwszym meczem kolejki.

    Parametry:
        round_number: numer nadchodzącej kolejki (np. 27)
        fixtures_data: dane terminarza z parse_terminarz()

    Zwraca True/False.
    """
    if not round_number:
        return False
    first_date, _ = _get_round_date_range(fixtures_data, round_number)
    if not first_date:
        return False
    today = date.today()
    return today == first_date - timedelta(days=1)


def should_send_post_round(round_number, fixtures_data):
    """
    Sprawdza czy DZIŚ należy wysłać post-round dla podanej kolejki.

    Warunek: dzisiejsza data == dzień PO ostatnim meczu kolejki.

    Parametry:
        round_number: numer zakończonej kolejki (np. 26)
        fixtures_data: dane terminarza z parse_terminarz()

    Zwraca True/False.
    """
    if not round_number:
        return False
    _, last_date = _get_round_date_range(fixtures_data, round_number)
    if not last_date:
        return False
    today = date.today()
    return today == last_date + timedelta(days=1)


# ============================================================
# FUNKCJA A: PRE-ROUND — prognozy i captain pick
# ============================================================

def send_pre_round(predictions, players_data, webhook_url, round_number, fixtures):
    """
    Wysyła Discord embed z prognozami PRZED kolejką.

    📖 LEKCJA: Discord embed to "karta" z tytułem, kolorem paska, sekcjami (fields)
    i stopką. Budujemy ją jako słownik Python, potem zamieniamy na JSON.

    Sekcje embeda:
    1. 👑 Captain Pick   — gracz z najwyższą prognozą × (1 - ownership%)
                          "differential captain" = wysoka prognoza + mało ludzi go ma
    2. 🔮 Top 5 Prognoz — 5 zawodników z najwyższą prognozą

    Parametry:
        predictions:  lista prognoz z predictor.py (posortowana wg predicted_points)
        players_data: pełna lista graczy z API (nieużywana bezpośrednio —
                      ownership jest już zawarty w predictions['popularity_pct'])
        webhook_url:  URL Discord webhooka ze zmiennej środowiskowej
        round_number: numer NADCHODZĄCEJ kolejki
        fixtures:     dane terminarza z parse_terminarz()
    """
    if not predictions:
        print("  ℹ️  Discord pre-round: brak prognoz — pomijam")
        return False

    # --- Anti-duplicate: sprawdź czy ten post dla tej kolejki już był wysłany ---
    sent_log = _load_sent_log()
    if sent_log.get("pre_round", 0) >= round_number:
        print(f"  ℹ️  Discord pre-round K{round_number} już wysłany — pomijam duplikat")
        return False

    print(f"\n📣 Discord: przygotowuję pre-round embed dla kolejki {round_number}...")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- SEKCJA 1: CAPTAIN PICK ---
    # Formuła: prognoza × (1 - ownership/100)
    # Gracz z wysoką prognozą i małym ownership = "differential" — mało kto go ma,
    # więc dobre wyniki dadzą przewagę nad rywalami w lidze.
    def _captain_score(pred):
        pts = pred.get("predicted_points") or 0.0
        own = _parse_ownership_pct(pred.get("popularity_pct", "100%"))
        return pts * (1.0 - own / 100.0)

    captain = max(predictions, key=_captain_score)
    cap_pid = captain.get("player_id")
    cap_pts = captain.get("predicted_points") or 0.0
    cap_own = captain.get("popularity_pct", "?")
    # opponent_short to skrót rywala (np. "LEG"), next_opponent to pełna nazwa
    cap_opp = captain.get("opponent_short") or captain.get("next_opponent", "?")
    cap_home_str = "D" if captain.get("is_home", True) else "W"  # D=dom, W=wyjazd
    cap_team = captain.get("team", "")

    captain_text = (
        f"👑 **{captain.get('name', '?')}** ({cap_team})\n"
        f"Prognoza: **{cap_pts:.1f} pkt** | Ownership: {cap_own} | vs {cap_opp} ({cap_home_str})"
    )

    # --- SEKCJA 2: TOP 5 PROGNOZ ---
    # Pięciu zawodników z najwyższą bezwzględną prognozą punktową.
    # Gwiazdka ⭐ pojawia się przy captain picku jeśli jest w top 5.
    top5 = predictions[:5]
    medals = ["1.", "2.", "3.", "4.", "5."]

    top5_lines = []
    for i, pred in enumerate(top5):
        pts = pred.get("predicted_points") or 0.0
        opp = pred.get("opponent_short") or pred.get("next_opponent", "?")
        home_str = "D" if pred.get("is_home", True) else "W"
        pos = pred.get("position", "")
        name = pred.get("name", "?")
        team = pred.get("team", "")

        # Gwiazdka ⭐ jeśli to captain pick (porównujemy player_id)
        star = "⭐ " if pred.get("player_id") == cap_pid else "   "

        top5_lines.append(
            f"`{medals[i]}` {star}**{name}** ({pos}, {team}) — **{pts:.1f} pkt** | vs {opp} ({home_str})"
        )

    top5_text = "\n".join(top5_lines)

    # --- BUDUJ EMBED ---
    embed = {
        "title": f"🔮 ScrapFEks — Kolejka {round_number} Prognoza",
        "color": 0x00BFFF,  # Cyan — odróżnia pre-round od post-round
        "fields": [
            {
                "name": "👑 Captain Pick",
                "value": captain_text,
                "inline": False,
            },
            {
                "name": "🔮 Top 5 Prognoz",
                "value": top5_text,
                "inline": False,
            },
        ],
        "footer": {
            "text": f"🔗 {DASHBOARD_URL} · {timestamp}",
        },
    }

    success = _send_embed(webhook_url, embed, content="<@&1262764454404296759>")

    if success:
        # Zaktualizuj log — ta kolejka pre-round jest już wysłana
        sent_log["pre_round"] = round_number
        _save_sent_log(sent_log)
        print(f"  ✅ Discord pre-round K{round_number} wysłany pomyślnie!")
    else:
        print(f"  ⚠️  Discord pre-round K{round_number} — wysyłka nieudana")

    return success


# ============================================================
# FUNKCJA B: POST-ROUND — podsumowanie wyników ligi
# ============================================================

def send_post_round(league_data, players_data, accuracy_data, webhook_url, round_number):
    """
    Wysyła Discord embed z podsumowaniem PO kolejce.

    Sekcje embeda (każda jest opcjonalna):
    1. 🏆 Top 3 drużyny ligi   — najlepsze drużyny w tej kolejce (wg last_points)
    2. 💎 Zawodnik-niespodzianka — wysoki wynik + niski ownership (< 20%)
    3. 🎯 Trafność prognozy     — MAE i przykłady trafień/pomyłek

    Parametry:
        league_data:   lista drużyn ligi prywatnej z fetch_league_teams()
                       (każda drużyna ma pola: slug, last_points, total_points)
        players_data:  pełna lista graczy z API (ma 'rounds' z punktami per kolejka,
                       'popularity_pct' z globalnym ownership)
        accuracy_data: wynik ewaluacji z evaluate_predictions() lub None
        webhook_url:   URL Discord webhooka
        round_number:  numer ZAKOŃCZONEJ kolejki
    """
    # Jeśli brak i danych ligi, i trafności — nie ma czego wysyłać
    if not league_data and not accuracy_data:
        print("  ℹ️  Discord post-round: brak danych ligi i trafności — pomijam")
        return False

    # Brak danych ligi to sygnał, że liga nie jest skonfigurowana → pomijamy post-round
    if not league_data:
        print("  ℹ️  Discord post-round: brak danych ligi — pomijam")
        return False

    # --- Anti-duplicate: sprawdź czy ten post dla tej kolejki już był wysłany ---
    sent_log = _load_sent_log()
    if sent_log.get("post_round", 0) >= round_number:
        print(f"  ℹ️  Discord post-round K{round_number} już wysłany — pomijam duplikat")
        return False

    print(f"\n📣 Discord: przygotowuję post-round embed dla kolejki {round_number}...")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    fields = []

    # --- SEKCJA 1: TOP 3 DRUŻYNY LIGI W TEJ KOLEJCE ---
    # last_points to punkty zdobyte w ostatniej rozgranej kolejce (z API /ranking-list)
    sorted_teams = sorted(
        league_data,
        key=lambda t: t.get("last_points") or t.get("pts", 0) or 0,
        reverse=True,
    )
    top3 = sorted_teams[:3]

    if top3:
        medals = ["🥇", "🥈", "🥉"]
        top3_lines = []
        for i, team in enumerate(top3):
            # Próbuj display_name (z autumn_points.json), potem formatuj slug
            name = (
                team.get("display_name")
                or team.get("slug", "").replace("-", " ").title()
            )
            pts = team.get("last_points") or team.get("pts", 0) or 0
            top3_lines.append(f"{medals[i]} **{name}** — {pts} pkt")

        fields.append({
            "name": "🏆 Top 3 drużyny kolejki",
            "value": "\n".join(top3_lines),
            "inline": False,
        })

    # --- SEKCJA 2: ZAWODNIK-NIESPODZIANKA ---
    # Szukamy gracza z NAJWYŻSZYM wynikiem w tej kolejce, który miał ownership < 20%.
    # "Niespodzianka" = mało kto go miał, a dał dużo punktów.
    # Używamy popularity_pct z API Fantasy Ekstraklasa (globalny ownership).
    hidden_gem = None
    hidden_gem_pts = -1

    if players_data and round_number:
        for player in players_data:
            # Sprawdź globalny ownership — jeśli >= 20%, to nie "niespodzianka"
            own = _parse_ownership_pct(player.get("popularity_pct", "100%"))
            if own >= 20.0:
                continue

            # Szukaj punktów tej kolejki w danych per-kolejkowych gracza
            # 'rounds' to lista {"round": N, "played": True/False, "points": X, ...}
            rounds = player.get("rounds", [])
            for r in rounds:
                if r.get("round") == round_number and r.get("played"):
                    pts = r.get("points", 0) or 0
                    if pts > hidden_gem_pts:
                        hidden_gem_pts = pts
                        hidden_gem = player
                    break  # Każdy gracz ma co najwyżej jeden wpis na kolejkę

    if hidden_gem and hidden_gem_pts > 0:
        # Mapowanie pełnych nazw pozycji → skróty używane w aplikacji
        pos_map = {
            "Bramkarz": "BR",
            "Obrońca": "OBR",
            "Pomocnik": "POM",
            "Napastnik": "NAP",
        }
        pos = pos_map.get(hidden_gem.get("position", ""), hidden_gem.get("position", ""))
        team_name = hidden_gem.get("team", "")
        own_str = hidden_gem.get("popularity_pct", "?")

        gem_text = (
            f"💎 **{hidden_gem.get('name', '?')}** ({pos}, {team_name}) — **{hidden_gem_pts} pkt**\n"
            f"Ownership: {own_str}"
        )

        fields.append({
            "name": "💎 Zawodnik-niespodzianka",
            "value": gem_text,
            "inline": False,
        })
    # Jeśli brak gracza spełniającego kryteria — sekcja jest pomijana (spec: pomiń sekcję)

    # --- SEKCJA 3: TRAFNOŚĆ PROGNOZY ---
    # MAE (Mean Absolute Error) = średni błąd prognozy w punktach.
    # Niższe MAE = lepszy model. Sekcja jest opcjonalna — brak danych = brak sekcji.
    if accuracy_data:
        mae = accuracy_data.get("mae", "?")

        # Najlepsze trafienie: gracz gdzie prognoza była najbliżej rzeczywistości
        best_hits = accuracy_data.get("best_hits", [])
        best_str = ""
        if best_hits:
            b = best_hits[0]
            best_str = (
                f"\nNajlepsze trafienie: **{b.get('name', '?')}** "
                f"(prognoza {b.get('predicted', '?')} → reality {b.get('actual', '?')})"
            )

        # Największa pomyłka: gracz gdzie prognoza najbardziej się myliła
        worst_misses = accuracy_data.get("worst_misses", [])
        worst_str = ""
        if worst_misses:
            w = worst_misses[0]
            worst_str = (
                f"\nNajwiększa pomyłka: **{w.get('name', '?')}** "
                f"(prognoza {w.get('predicted', '?')} → reality {w.get('actual', '?')})"
            )

        accuracy_text = f"MAE: **{mae} pkt**{best_str}{worst_str}"

        fields.append({
            "name": "🎯 Trafność prognozy",
            "value": accuracy_text,
            "inline": False,
        })

    # Jeśli żadna sekcja nie ma danych — nie wysyłaj pustego embeda
    if not fields:
        print("  ℹ️  Discord post-round: wszystkie sekcje puste — pomijam")
        return False

    # --- BUDUJ EMBED ---
    embed = {
        "title": f"📊 ScrapFEks — Kolejka {round_number} Podsumowanie",
        "color": 0x23A55A,  # Zielony — odróżnia post-round od pre-round (cyan)
        "fields": fields,
        "footer": {
            "text": f"🔗 {DASHBOARD_URL} · {timestamp}",
        },
    }

    success = _send_embed(webhook_url, embed, content="<@&1262764454404296759>")

    if success:
        # Zaktualizuj log — ta kolejka post-round jest już wysłana
        sent_log["post_round"] = round_number
        _save_sent_log(sent_log)
        print(f"  ✅ Discord post-round K{round_number} wysłany pomyślnie!")
    else:
        print(f"  ⚠️  Discord post-round K{round_number} — wysyłka nieudana")

    return success
