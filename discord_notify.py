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
import random
import time
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta
from ai_client import call_deepseek, call_gemini, DEEPSEEK_MODEL, GEMINI_MODEL  # wspólny klient API
from predictor import parse_ownership_pct, captain_differential_score, FDR_NEUTRAL
from analytics import find_hidden_gem, find_disappointment, collect_captains
from config import POS_MAP


# ============================================================
# STAŁE KONFIGURACYJNE
# ============================================================

OUTPUT_DIR = "output"

# Plik do śledzenia wysłanych postów — żeby nie wysyłać dwa razy
# Przykład zawartości: {"pre_round": 27, "post_round": 26}
DISCORD_SENT_FILE = os.path.join(OUTPUT_DIR, "discord_sent.json")

# Timeout dla requestów do Discord (sekundy)
WEBHOOK_TIMEOUT = 10

# limit znaków na część wiadomości (2000 - margines)
DISCORD_CONTENT_MAX_LEN = 1900
# liczba prób dla wywołań DeepSeek/Gemini przed poddaniem się
AI_MAX_RETRIES = 3

# Link do dashboardu — pojawi się w footerze każdego embeda
DASHBOARD_URL = "ingentingpl.github.io/ScrapFEks"

# Nagłówki do Discord webhook API
DISCORD_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "DiscordBot (https://github.com/IngentingPL/ScrapFEks, 1.0)",
}


# ============================================================
# FUNKCJE POMOCNICZE — obsługa pliku z logiem wysłanych postów
# ============================================================

def _load_sent_log():
    """
    Wczytuje log wysłanych postów Discord z pliku JSON.

    Zwraca słownik {"pre_round": N, "post_round": M, "captains_round": K}.
    Jeśli plik nie istnieje (pierwsze uruchomienie) — zwraca zera.

    📖 LEKCJA: Zaczynamy od 0, bo żadna kolejka nie była jeszcze obsłużona.
    """
    if not os.path.exists(DISCORD_SENT_FILE):
        return {"pre_round": 0, "post_round": 0, "captains_round": 0}
    try:
        with open(DISCORD_SENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # Jeśli plik jest uszkodzony — zacznij od nowa
        return {"pre_round": 0, "post_round": 0, "captains_round": 0}


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

def _send_to_discord(webhook_url, payload):
    """
    Wspólna warstwa transportowa dla wszystkich wiadomości Discord.
    Przyjmuje gotowy payload dict i wysyła POST przez webhook.
    Wywołujący sam buduje payload zgodnie z Discord API:
      - embed:  {"embeds": [embed_dict], "content": "opcjonalnie"}
      - tekst:  {"content": "tekst wiadomości"}
    Zwraca True jeśli HTTP 200/204, False przy błędzie.
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers=DISCORD_HEADERS,
        method="POST",
    )
    url_preview = (
        webhook_url[:50] + "..." + webhook_url[-10:]
        if len(webhook_url) > 60 else webhook_url
    )
    print(f"  🔍 Discord wysyłam: {url_preview} ({len(data)} B)")
    try:
        with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as resp:
            print(f"  🔍 Discord odpowiedź: HTTP {resp.status}")
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  ⚠️  Discord HTTP błąd: {e.code} {e.reason}")
        print(f"  🔍 Discord treść błędu: {body}")
        return False
    except urllib.error.URLError as e:
        print(f"  ⚠️  Discord błąd połączenia: {e.reason}")
        return False
    except Exception as e:
        print(f"  ⚠️  Discord nieoczekiwany błąd: {e}")
        return False


def _send_embed(webhook_url, embed, content=None, embeds=None):
    """
    Wysyła Discord embed(y) przez webhook URL.

    Discord API oczekuje JSON: {"embeds": [{ ... }], "content": "..."}
    - "embeds" to lista kart z tytułem, kolorem i sekcjami
    - "content" to zwykły tekst pojawiający się NAD embedem (np. wzmianki @)

    Można podać 'embed' (jeden embed) albo 'embeds' (lista embedów).
    Jeśli podano 'embeds', parametr 'embed' jest ignorowany.

    📖 LEKCJA: Discord pozwala wysłać do 10 embedów w jednym requeście.
    Dzięki temu możemy podzielić długą wiadomość na kilka kart
    i wysłać je razem — wyświetlą się jako jedna wiadomość.

    Zwraca True jeśli wysyłka się powiodła, False w przypadku błędu.

    📖 LEKCJA: urllib.request.Request pozwala zbudować dowolny HTTP request.
    Ustawiamy headers (nagłówki) żeby Discord wiedział, że wysyłamy JSON.
    """
    if embeds:
        payload = {"embeds": embeds}
    else:
        payload = {"embeds": [embed]}
    if content:
        payload["content"] = content
    return _send_to_discord(webhook_url, payload)


def _send_content(webhook_url, content):
    """
    Wysyła zwykłą wiadomość tekstową przez webhook URL.

    Używamy tej ścieżki dla długich sekcji, które Discord potrafi wizualnie
    ucinać w embedach (np. długie listy kapitanów lub newsletter AI).
    """
    return _send_to_discord(webhook_url, {"content": content})


def _split_text_for_content(text, max_len=DISCORD_CONTENT_MAX_LEN):
    """
    Dzieli długi tekst na części bezpieczne dla zwykłego Discord content.

    Limit content dla webhooka to 2000 znaków, więc zostawiamy zapas
    na nagłówki części typu (1/3). Cięcie preferuje granice akapitów,
    potem nowych linii, potem spacji.
    """
    if not text:
        return []

    remaining = str(text).strip()
    if not remaining:
        return []

    parts = []
    while len(remaining) > max_len:
        cut = remaining.rfind("\n\n", 0, max_len)
        if cut == -1:
            cut = remaining.rfind("\n", 0, max_len)
        if cut == -1:
            cut = remaining.rfind(" ", 0, max_len)
        if cut == -1 or cut < int(max_len * 0.5):
            cut = max_len

        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()

    if remaining:
        parts.append(remaining)

    return parts


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
        year = datetime.now().year  # dynamicznie: datetime.now().year zawsze zwraca aktualny rok kalendarzowy
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


# ============================================================
# LOGIKA TIMINGOWA — kiedy wysyłać który post
# ============================================================

def should_send_pre_round(round_number, fixtures_data):
    """
    Sprawdza czy DZIŚ należy wysłać pre-round dla podanej kolejki.

    Warunek: dzisiejsza data == dzień PRZED pierwszym meczem kolejki
    LUB dzisiejsza data == dzień pierwszego meczu (okno ratunkowe na opóźnienia).

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
    # Wysyłaj w dzień przed lub w dzień meczu (okno ratunkowe)
    return today == first_date - timedelta(days=1) or today == first_date


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


def should_send_captains_summary(round_number, fixtures_data):
    """
    Sprawdza czy DZIŚ należy wysłać captains_summary dla podanej kolejki.

    Warunek: dzisiejsza data == dzień pierwszego meczu kolejki.
    (wysyłane godzinę po rozpoczęciu pierwszego meczu)

    Parametry:
        round_number: numer kolejki (np. 27)
        fixtures_data: dane terminarza z parse_terminarz()

    Zwraca True/False.
    """
    if not round_number:
        return False
    first_date, _ = _get_round_date_range(fixtures_data, round_number)
    if not first_date:
        return False
    today = date.today()
    return today == first_date


# ============================================================
# FUNKCJA A: PRE-ROUND — prognozy i captain pick
# ============================================================

def send_pre_round(predictions, players_data, webhook_url, round_number,
                   fixtures, fdr_data=None):
# fdr_data=None zapewnia backward compatibility jeśli ktoś wywoła
# bez tego parametru - stary kod zadziała z gorszym FDR fallbackiem
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
    captain = max(predictions, key=captain_differential_score)
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

    # --- SEKCJA 3: TOP PER POZYCJA ---
    # 📖 LEKCJA: Grupujemy prognozy po pozycji i wybieramy najlepszego z każdej.
    # dict.setdefault() tworzy klucz z wartością domyślną, jeśli go jeszcze nie ma.
    pos_emoji = {"BR": "🧤", "OBR": "🛡️", "POM": "🎯", "NAP": "⚡"}
    pos_order = ["BR", "OBR", "POM", "NAP"]  # Kolejność wyświetlania

    best_per_pos = {}
    for pred in predictions:
        pos = pred.get("position", "")
        pts = pred.get("predicted_points") or 0
        if pos in pos_order and pts > 0:
            if pos not in best_per_pos or pts > (best_per_pos[pos].get("predicted_points") or 0):
                best_per_pos[pos] = pred

    top_pos_text = ""
    if best_per_pos:
        top_pos_lines = []
        for pos in pos_order:
            if pos not in best_per_pos:
                continue
            p = best_per_pos[pos]
            emoji = pos_emoji.get(pos, "")
            _parts = p.get("name", "?").split()
            name = _parts[-1] if _parts else "?"  # Tylko nazwisko
            pts = p.get("predicted_points") or 0
            opp = p.get("opponent_short") or p.get("next_opponent", "?")
            home_str = "D" if p.get("is_home", True) else "W"
            top_pos_lines.append(f"{emoji} {pos}:  {name} — {pts:.1f} pkt | vs {opp} ({home_str})")
        top_pos_text = "\n".join(top_pos_lines)

    # --- SEKCJA 4: DIFFERENTIAL PICK ---
    # 📖 LEKCJA: "Differential" to gracz, którego mało kto ma w składzie (niski ownership),
    # ale ma wysoką prognozę. Daje przewagę nad rywalami, bo punktuje "tylko u Ciebie".
    diff_text = ""
    for pred in predictions:
        pts = pred.get("predicted_points") or 0
        own = parse_ownership_pct(pred.get("popularity_pct", "100%"))
        if pts > 6 and own < 10:
            pos = pred.get("position", "")
            team = pred.get("team", "")
            opp = pred.get("opponent_short") or pred.get("next_opponent", "?")
            home_str = "D" if pred.get("is_home", True) else "W"
            diff_text = (
                f"💎 **{pred.get('name', '?')}** ({pos}, {team}) — prognoza **{pts:.1f} pkt**\n"
                f"   Ownership: {own:.0f}% · vs {opp} ({home_str})"
            )
            break  # Bierzemy pierwszego (najwyższa prognoza, bo lista jest posortowana)

    # --- SEKCJA 5: UNIKAJ ---
    # 📖 LEKCJA: Gracze z wysokim ownership i niską prognozą to "pułapki" —
    # wielu graczy ich ma, ale model prognozuje im mało punktów.
    # Jeśli ich unikniesz, a oni zawiodą — zyskujesz przewagę nad rywalami.
    avoid_candidates = []
    for pred in predictions:
        own = parse_ownership_pct(pred.get("popularity_pct", "0%"))
        pts = pred.get("predicted_points") or 0
        if own > 30 and pts > 0:
            avoid_candidates.append(pred)

    # Sortuj od najniższej prognozy — najgorsi na początku
    avoid_candidates.sort(key=lambda x: x.get("predicted_points") or 0)
    avoid_text = ""
    if len(avoid_candidates) >= 2:
        avoid_lines = []
        for pred in avoid_candidates[:2]:
            pos = pred.get("position", "")
            _parts = pred.get("name", "?").split()
            name = _parts[-1] if _parts else "?"  # Nazwisko
            pts = pred.get("predicted_points") or 0
            own = parse_ownership_pct(pred.get("popularity_pct", "0%"))
            opp = pred.get("opponent_short") or pred.get("next_opponent", "?")
            home_str = "D" if pred.get("is_home", True) else "W"
            avoid_lines.append(
                f"⚠️ {name} ({pos}) — {pts:.1f} pkt | Ownership: {own:.0f}% | vs {opp} ({home_str})"
            )
        avoid_text = "\n".join(avoid_lines)

    # --- SEKCJA 6: MAPA FDR KOLEJKI ---
    # Bezpośredni lookup z fdr_data zamiast iteracji po predictions —
    # pewniejsze i szybsze (O(1) per mecz zamiast O(n*m))
    fdr_map_text = ""
    round_matches = fixtures.get("matches", {}).get(str(round_number), [])
    if round_matches and fdr_data:
        # Zbuduj lookup {nazwa_drużyny: {atk, def}} dla tej kolejki
        # 📖 LEKCJA: dict comprehension to jednorazowe przejście przez dane,
        # zamiast szukania od nowa dla każdego meczu
        fdr_lookup = {}
        for team in fdr_data.get("teams", []):
            team_name = team.get("name", "")
            for fix in team.get("fixtures", []):
                if fix.get("gw") == round_number:
                    fdr_lookup[team_name] = {
                        "atk": fix.get("atk", FDR_NEUTRAL),
                        "def": fix.get("def", FDR_NEUTRAL),
                    }
                    break

        match_fdr = []
        for m in round_matches:
            home_team = m.get("home", "")
            away_team = m.get("away", "")
            home_fdr = fdr_lookup.get(home_team)
            if home_fdr is None:
                continue  # brak danych FDR dla tej drużyny — pomijamy mecz
            # Sumujemy atk + def rywala z perspektywy gospodarza
            # (ta sama semantyka co poprzedni kod)
            fdr_sum = home_fdr["atk"] + home_fdr["def"]
            match_fdr.append({
                "label": f"{home_team} vs {away_team} (D)",
                "fdr": fdr_sum,
            })

        if len(match_fdr) >= 4:
            match_fdr.sort(key=lambda x: x["fdr"])
            easy = [m["label"] for m in match_fdr[:2]]
            hard = [m["label"] for m in match_fdr[-2:]]
            fdr_map_text = (
                f"🟢 Łatwe:  {' · '.join(easy)}\n"
                f"🔴 Trudne: {' · '.join(hard)}"
            )

    # --- SEKCJA 7: FORMA DRUŻYN ---
    # 📖 LEKCJA: "Forma" to seria ostatnich wyników drużyny (W=wygrana, D=remis, L=przegrana).
    # Nie mamy bezpośrednio tych danych, ale możemy je odtworzyć z danych graczy.
    # Patrzymy na punkty zdobyte przez drużynę (średnia punktów graczy) per kolejka —
    # ale to nie daje W/D/L. Pomijamy sekcję jeśli nie ma pewnych danych.
    form_text = ""
    # Sekcja formy wymaga danych o wynikach meczów, których nie ma w dostępnych danych.
    # Zgodnie ze specyfikacją: "Jeśli dane do sekcji nie są dostępne → pomiń sekcję"

    # --- BUDUJ EMBEDY ---
    # 📖 LEKCJA: Discord embed ma limit 6000 znaków. Jeśli dodamy dużo sekcji,
    # możemy przekroczyć limit. Rozwiązanie: dzielimy na dwa embedy w jednym requeście.
    # Discord wyświetli oba jako jedną wiadomość.

    # Zbierz wszystkie sekcje (fields) — podstawowe + nowe
    fields_part1 = [
        {"name": "👑 Captain Pick", "value": captain_text, "inline": False},
        {"name": "🔮 Top 5 Prognoz", "value": top5_text, "inline": False},
    ]
    if top_pos_text:
        fields_part1.append({"name": "🏅 Top per pozycja", "value": top_pos_text, "inline": False})
    if diff_text:
        fields_part1.append({"name": "💎 Differential pick", "value": diff_text, "inline": False})

    fields_part2 = []
    if avoid_text:
        fields_part2.append({"name": "⚠️ Unikaj", "value": avoid_text, "inline": False})
    if fdr_map_text:
        fields_part2.append({"name": "📅 Mapa FDR kolejki", "value": fdr_map_text, "inline": False})
    if form_text:
        fields_part2.append({"name": "🔥 Forma drużyn", "value": form_text, "inline": False})

    all_fields = fields_part1 + fields_part2

    # Zmierz łączną długość tekstu w embedzie
    # 📖 LEKCJA: Discord liczy znaki w: title + description + field.name + field.value
    # + footer.text + author.name. Limit to 6000 znaków na embed.
    def _embed_char_count(emb):
        count = len(emb.get("title", ""))
        count += len(emb.get("description", ""))
        for f in emb.get("fields", []):
            count += len(f.get("name", "")) + len(f.get("value", ""))
        count += len(emb.get("footer", {}).get("text", ""))
        return count

    footer_obj = {"text": f"🔗 {DASHBOARD_URL} · {timestamp}"}

    single_embed = {
        "title": f"🔮 ScrapFEks — Kolejka {round_number} Prognoza",
        "color": 0x00BFFF,
        "fields": all_fields,
        "footer": footer_obj,
    }

    if _embed_char_count(single_embed) <= 5500:
        # Mieści się w jednym embedzie — wysyłaj normalnie
        success = _send_embed(webhook_url, single_embed, content="<@&1262764454404296759>")
    else:
        # 📖 LEKCJA: Podział na dwa embedy — Discord wyświetli je jako jedną wiadomość.
        # Embed 1: Captain Pick + Top 5 + Top per pozycja + Differential
        # Embed 2: Unikaj + Mapa FDR + Forma
        embed1 = {
            "title": f"🔮 ScrapFEks — Kolejka {round_number} Prognoza",
            "color": 0x00BFFF,
            "fields": fields_part1,
        }
        embed2 = {
            "color": 0x00BFFF,
            "fields": fields_part2,
            "footer": footer_obj,
        }
        # Wyślij oba embedy w jednym requeście
        embeds_list = [embed1]
        if fields_part2:
            embeds_list.append(embed2)
        else:
            # Brak sekcji w part2 — dodaj footer do embed1
            embed1["footer"] = footer_obj
        success = _send_embed(webhook_url, embed=None, content="<@&1262764454404296759>", embeds=embeds_list)

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

def send_post_round(league_data, players_data, accuracy_data, webhook_url, round_number,
                     league_teams_detail=None, newsletter_text=None):
    """
    Wysyła Discord embed z podsumowaniem PO kolejce.

    Sekcje embeda (każda jest opcjonalna):
    1. 🏆 Top 3 drużyny ligi       — najlepsze drużyny w tej kolejce (wg last_points)
    2. 💎 Zawodnik-niespodzianka   — wysoki wynik + niski ownership (< 20%)
    3. 😤 Rozczarowanie kolejki    — niski wynik + wysoki ownership (> 40%)
    4. ©️ Kapitanowie w lidze       — kogo każda drużyna wybrała na kapitana
    5. 🎯 Trafność prognozy        — MAE i przykłady trafień/pomyłek

    Parametry:
        league_data:         lista drużyn ligi prywatnej z fetch_league_teams()
                             (każda drużyna ma pola: slug, last_points, total_points)
        players_data:        pełna lista graczy z API (ma 'rounds' z punktami per kolejka,
                             'popularity_pct' z globalnym ownership)
        accuracy_data:       wynik ewaluacji z evaluate_predictions() lub None
        webhook_url:         URL Discord webhooka
        round_number:        numer ZAKOŃCZONEJ kolejki
        league_teams_detail: lista drużyn ligi z danymi składów (slug, rank, pts, players)
                             — używana do sekcji kapitanów. Opcjonalna.
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
    captain_lines = []

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
        hidden_gem, hidden_gem_pts = find_hidden_gem(players_data, round_number)

    if hidden_gem and hidden_gem_pts > 0:
        pos = POS_MAP.get(hidden_gem.get("position", ""), hidden_gem.get("position", ""))
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

    # --- SEKCJA 3: ROZCZAROWANIE KOLEJKI ---
    # Szukamy gracza z NAJNIŻSZYMI punktami (lub ujemnymi) w tej kolejce,
    # który miał ownership > 40%. "Pułapka" = prawie wszyscy go mieli, a zawiódł.
    disappointment = None
    disappointment_pts = None  # szukamy minimum, startujemy od None

    if players_data and round_number:
        disappointment, disappointment_pts = find_disappointment(players_data, round_number)

    if disappointment and disappointment_pts is not None and disappointment_pts < 5:
        # Pokazuj rozczarowanie tylko gdy punkty są naprawdę niskie (< 5)
        pos = POS_MAP.get(disappointment.get("position", ""), disappointment.get("position", ""))
        team_name = disappointment.get("team", "")
        own_str = disappointment.get("popularity_pct", "?")
        # Oblicz ile drużyn z top 1000 go miało (przybliżenie: ownership% × 10)
        own_pct = parse_ownership_pct(own_str)
        approx_count = int(own_pct * 10)  # top 1000 × ownership% = ile drużyn

        dis_text = (
            f"😤 **{disappointment.get('name', '?')}** ({pos}, {team_name}) — **{disappointment_pts} pkt**\n"
            f"Ownership: {own_str} · Miało go ~{approx_count} z top 1000 drużyn"
        )

        fields.append({
            "name": "😤 Rozczarowanie kolejki",
            "value": dis_text,
            "inline": False,
        })

    # --- SEKCJA 4: KAPITANOWIE W LIDZE ---
    # Lista WSZYSTKICH drużyn z ligi prywatnej — kogo wybrały na kapitana
    # i ile ten kapitan zdobył. Sortuj od najwyższych punktów kapitana.
    #
    # 📖 LEKCJA: Dane kapitanów pochodzą z league_teams_detail, które zawiera
    # skład każdej drużyny (players) z flagą C=True dla kapitana.
    # Punkty kapitana za konkretną kolejkę szukamy w players_data (rounds).
    if league_teams_detail:
        captain_entries = collect_captains(league_teams_detail, players_data, round_number, league_data)

        if captain_entries:
            # Sortuj od najwyższych punktów kapitana do najniższych
            captain_entries.sort(key=lambda c: c["cap_pts"], reverse=True)

            # Emoji: ✅ przy najlepszym, ❌ przy najgorszym
            best_pts = captain_entries[0]["cap_pts"]
            worst_pts = captain_entries[-1]["cap_pts"]

            for ce in captain_entries:
                emoji = ""
                if ce["cap_pts"] == best_pts and best_pts > worst_pts:
                    emoji = " ✅"
                elif ce["cap_pts"] == worst_pts and worst_pts < best_pts:
                    emoji = " ❌"
                captain_lines.append(
                    f"**{ce['team_name']}**: {ce['cap_name']} ({ce['cap_pos']}) — "
                    f"{ce['cap_pts']} pkt{emoji}"
                )

    # --- SEKCJA 5: TRAFNOŚĆ PROGNOZY ---
    # MAE (Mean Absolute Error) = średni błąd prognozy w punktach.
    # Niższe MAE = lepszy model. Sekcja opcjonalna — brak danych accuracy = pomijamy.
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

    # --- WYSYŁKA ---
    # Główny embed zostawiamy krótki. Długie sekcje (kapitanowie, newsletter)
    # wysyłamy jako zwykły text content, bo Discord potrafi wizualnie ucinać
    # długie embedy mimo poprawnych limitów API.
    success = _send_embed(webhook_url, embed, content="<@&1262764454404296759>")

    # --- KAPITANOWIE W LIDZE jako zwykły tekst ---
    if success and captain_lines:
        captains_text = "\n".join(captain_lines)
        captain_parts = _split_text_for_content(captains_text, max_len=DISCORD_CONTENT_MAX_LEN)
        print(f"  🔎 Kapitanowie — części: {len(captain_parts)} | długości: {[len(p) for p in captain_parts]}")

        for idx, part in enumerate(captain_parts, start=1):
            if len(captain_parts) == 1:
                header = "©️ **Kapitanowie w lidze**\n"
            else:
                header = f"©️ **Kapitanowie w lidze ({idx}/{len(captain_parts)})**\n"

            ok = _send_content(webhook_url, header + part)
            success = success and ok
            if not ok:
                break

    # --- NEWSLETTER AI jako zwykły tekst ---
    if success and newsletter_text:
        cleaned = str(newsletter_text).strip()

        # Usuń powtarzające się nagłówki dodawane czasem przez model
        for header in [
            "📰 ScrapFEks Weekly",
            "📰 Newsletter",
            "Newsletter",
            "## Newsletter",
            "📋 Newsletter",
            "📌 Newsletter",
        ]:
            if cleaned.lower().startswith(header.lower()):
                cleaned = cleaned[len(header):].lstrip("\n :-—")
                break

        newsletter_parts = _split_text_for_content(cleaned, max_len=DISCORD_CONTENT_MAX_LEN)
        print(f"  🔎 Newsletter — części: {len(newsletter_parts)} | długości: {[len(p) for p in newsletter_parts]}")

        for idx, part in enumerate(newsletter_parts, start=1):
            if len(newsletter_parts) == 1:
                header = f"📰 **ScrapFEks Weekly — Kolejka {round_number}**\n"
            else:
                header = f"📰 **ScrapFEks Weekly — Kolejka {round_number} ({idx}/{len(newsletter_parts)})**\n"

            ok = _send_content(webhook_url, header + part)
            success = success and ok
            if not ok:
                break

        if success:
            disclaimer = "_Wygenerowano przez AI · Dane mogą nie oddawać pełnego obrazu_"
            ok = _send_content(webhook_url, disclaimer)
            success = success and ok

    if success:
        # Zaktualizuj log — ta kolejka post-round jest już wysłana
        sent_log["post_round"] = round_number
        _save_sent_log(sent_log)
        print(f"  ✅ Discord post-round K{round_number} wysłany pomyślnie!")
    else:
        print(f"  ⚠️  Discord post-round K{round_number} — wysyłka nieudana")

    return success


def send_captains_summary(league_teams_detail, cmf_standings, webhook_url, round_number):
    """
    Wysyła Discord embed z podsumowaniem kapitanów CMF League.

    Wysyłane godzinę po rozpoczęciu pierwszego meczu w kolejce.
    Sekcje embeda:
    1. Nagłówek: "Gameweek X!"
    2. Lista kapitanów posortowana według pozycji w tabeli CMF

    Parametry:
        league_teams_detail: lista drużyn z składami (slug, players z C=True)
        cmf_standings: słownik {slug: pozycja} z tabeli CMF (jesień+wiosna)
        webhook_url: URL Discord webhooka
        round_number: numer kolejki
    """
    if not league_teams_detail:
        print("  ℹ️  Discord captains: brak danych drużyn — pomijam")
        return False

    sent_log = _load_sent_log()
    if sent_log.get("captains_round", 0) >= round_number:
        print(f"  ℹ️  Discord captains K{round_number} już wysłany — pomijam duplikat")
        return False

    print(f"\n📣 Discord: przygotowuję captains embed dla kolejki {round_number}...")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ZMIANA 1: POMIŃ drużyny bez kapitana (cap_name != "?")
    # ZMIANA 2: sortuj według cmf_standings (tabela sumaryczna jesień+wiosna)
    # - ujemne wartości w cmf_standings oznaczają więcej punktów = wyższa pozycja
    captain_entries = []
    captain_counts = {}  # {cap_name: liczba drużyn}

    for team in league_teams_detail:
        team_slug = team.get("slug", "")
        cmf_pos = cmf_standings.get(team_slug, 999)
        cap_name = "?"
        vice_name = "?"

        for p in team.get("players", []):
            if p.get("C"):
                cap_name = p.get("name", "?")
            if p.get("VC") or p.get("S"):
                vice_name = p.get("name", "?")

        # POMIŃ drużyny bez kapitana - zmiana #1
        if cap_name == "?":
            continue

        display_name = team_slug.replace("-", " ").title()
        captain_entries.append({
            "position": cmf_pos,
            "team_name": display_name,
            "cap_name": cap_name,
            "vice_name": vice_name,
        })

        # Zlicz unikalnych kapitanów - zmiana #3
        if cap_name != "?":
            captain_counts[cap_name] = captain_counts.get(cap_name, 0) + 1

    if not captain_entries:
        print("  ℹ️  Discord captains: brak kapitanów — pomijam")
        return False

    captain_entries.sort(key=lambda x: x["position"])

    lines = []
    for i, ce in enumerate(captain_entries, start=1):
        line = f"{i}. {ce['team_name']} - {ce['cap_name']} ({ce['vice_name']})"
        lines.append(line)

    captains_text = "Captains:\n" + "\n".join(lines)

    embed = {
        "title": f"🏆 Gameweek {round_number}!",
        "color": 0xFF6B00,
        "description": captains_text,
        "footer": {"text": f"🔗 {DASHBOARD_URL} · {timestamp}"},
    }

    success = _send_embed(webhook_url, embed, content="<@&1262764454404296759>")

    # ZMIANA 3: Dodaj zestawienie kapitanów na końcu wiadomości
    # Lista unikalnych kapitanów posortowana malejąco według liczby drużyn
    if success and captain_counts:
        # Sortuj: najpierw po liczbie drużyn (malejąco), potem alfabetycznie
        sorted_captains = sorted(
            captain_counts.items(),
            key=lambda x: (-x[1], x[0])  # -x[1] = malejąco, x[0] = alfabetycznie
        )
        cap_summary_lines = [f"{name} x{count}" for name, count in sorted_captains]
        cap_summary_text = "Kapitanowie:\n" + "\n".join(cap_summary_lines)

        # Sprawdź limit 2000 znaków - jeśli za długa, podziel na części
        if len(cap_summary_text) > DISCORD_CONTENT_MAX_LEN:
            cap_parts = _split_text_for_content(cap_summary_text, max_len=DISCORD_CONTENT_MAX_LEN)
            for idx, part in enumerate(cap_parts, start=1):
                header = f"Kapitanowie ({idx}/{len(cap_parts)}):\n" if len(cap_parts) > 1 else "Kapitanowie:\n"
                ok = _send_content(webhook_url, header + part)
                if not ok:
                    break
        else:
            _send_content(webhook_url, cap_summary_text)

    if success:
        sent_log["captains_round"] = round_number
        _save_sent_log(sent_log)
        print(f"  ✅ Discord captains K{round_number} wysłany pomyślnie!")
    else:
        print(f"  ⚠️  Discord captains K{round_number} — wysyłka nieudana")

    return success


# ============================================================
# STAŁE KONFIGURACYJNE DLA AI (DeepSeek + Gemini fallback)
# ============================================================
# (importy urllib są na górze pliku)

# 📖 DEEPSEEK_MODEL, GEMINI_MODEL przeniesione do ai_client.py
# 📖 DEEPSEEK_TIMEOUT, GEMINI_TIMEOUT, GEMINI_THINKING_BUDGET, DEEPSEEK_HEADERS
#     usunięte jako martwy kod — używane tylko w usuniętych funkcjach transportowych

# Lokalne wartości max_tokens — różne od newsletter.py (tam 2200, tu 1500)
DEEPSEEK_MAX_OUTPUT_TOKENS = 1500
GEMINI_MAX_OUTPUT_TOKENS = 1500


def _call_ai_expert(prompt: str, deepseek_key: str = "", gemini_key: str = "", label: str = "expert") -> dict:
    """
    Wywołuje API AI dla prognoz eksperckich: DeepSeek jako główny model, Gemini jako fallback.
    
    Oba modele mają własną logikę retry (exponential backoff).
    Zwraca dict z 'text' (treść odpowiedzi), 'error' (opis błędu lub None) i 'model'.
    """
    # --- KROK 1: DeepSeek (model podstawowy) ---
    if deepseek_key:
        last_error = None
        for attempt in range(AI_MAX_RETRIES):
            try:
                result = call_deepseek(prompt, deepseek_key, max_tokens=DEEPSEEK_MAX_OUTPUT_TOKENS)
                text = ""
                choices = result.get("choices", [])
                if choices:
                    text = choices[0].get("message", {}).get("content", "")
                if text:
                    print(f"  ✅ {label}: DeepSeek odpowiedź ({len(text)} znaków)")
                    return {"text": text, "error": None, "model": DEEPSEEK_MODEL}
                last_error = "Pusta odpowiedź od DeepSeek"
            except Exception as e:
                last_error = str(e)
            
            if attempt < AI_MAX_RETRIES - 1:
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                print(f"  ⚠️  {label}: DeepSeek próba {attempt + 1} nieudana ({last_error}), retry za {wait_time:.1f}s...")
                time.sleep(wait_time)
        
        print(f"  ⚠️  {label}: DeepSeek failed after 3 attempts ({last_error}), próbuję Gemini...")
    else:
        print(f"  ℹ️  {label}: brak DEEPSEEK_API_KEY, próbuję Gemini...")
    
    # --- KROK 2: Gemini (fallback) ---
    if gemini_key:
        max_retries = AI_MAX_RETRIES
        last_error = None
        for attempt in range(max_retries):
            try:
                result = call_gemini(prompt, gemini_key, max_tokens=GEMINI_MAX_OUTPUT_TOKENS)
                text = ""
                candidates = result.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text = "".join(p.get("text", "") for p in parts)
                if text:
                    print(f"  ✅ {label}: Gemini odpowiedź ({len(text)} znaków)")
                    return {"text": text, "error": None, "model": GEMINI_MODEL}
                last_error = "Pusta odpowiedź od Gemini"
            except Exception as e:
                last_error = str(e)
            
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                print(f"  ⚠️  {label}: Gemini próba {attempt + 1} nieudana ({last_error}), retry za {wait_time:.1f}s...")
                time.sleep(wait_time)
        
        print(f"  ⚠️  {label}: Gemini failed after {max_retries} attempts ({last_error})")
        return {"text": "", "error": f"Gemini fallback: {last_error}", "model": ""}
    else:
        print(f"  ℹ️  {label}: brak GEMINI_API_KEY")
    
    return {"text": "", "error": "Brak klucza API", "model": ""}


def _build_expert_context(all_data: dict) -> dict:
    """
    Buduje słownik kontekstu z dostępnych danych dla prognoz eksperckich.
    
    Przekazuje możliwie najwięcej informacji: tabelę ligi, mecze kolejki,
    statystyki zawodników, FDR, składy drużyn.
    """
    ctx = {}
    
    round_number = all_data.get("round_number")
    if round_number:
        ctx["round_number"] = round_number
    
    # Tabela ligi (jesień + wiosna)
    league_data = all_data.get("league_data", [])
    if league_data:
        # Posortuj po punktach sezonowych
        sorted_teams = sorted(
            league_data,
            key=lambda t: t.get("total_points") or t.get("season_total") or 0,
            reverse=True,
        )
        standings = []
        for i, t in enumerate(sorted_teams):
            name = t.get("display_name") or t.get("slug", "").replace("-", " ").title()
            total_pts = t.get("total_points") or t.get("season_total") or 0
            last_pts = t.get("last_points") or 0
            standings.append({
                "pos": i + 1,
                "name": name,
                "total_pts": total_pts,
                "pts_this_round": last_pts,
            })
        if standings:
            ctx["standings"] = standings
    
    # Mecze kolejki z terminarza
    fixtures = all_data.get("fixtures_data", {})
    if fixtures and round_number:
        matches = fixtures.get("matches", {}).get(str(round_number), [])
        if matches:
            ctx["fixtures"] = matches
    
    # Tabela Ekstraklasy (FDR)
    ekstra_stats = all_data.get("ekstra_stats", {})
    if ekstra_stats:
        # Uprość statystyki żeby nie zaśmiecać prompta
        team_stats = []
        for team, stats in ekstra_stats.items():
            gf = stats.get("gf", 0)
            ga = stats.get("ga", 0)
            mp = stats.get("mp", 0) or 1
            team_stats.append({
                "team": team,
                "gf": gf,
                "ga": ga,
                "gd": gf - ga,
                "ppm": round((gf - ga) / mp, 2) if mp > 0 else 0,
            })
        # Sortuj po bramkach
        team_stats.sort(key=lambda x: x["gf"], reverse=True)
        ctx["ekstraklasa_attack"] = team_stats[:10]  # Top 10 ataku
        team_stats.sort(key=lambda x: x["ga"])  # Najmniej straconych = najlepsza obrona
        ctx["ekstraklasa_defense"] = team_stats[:10]  # Top 10 obrony
    
    # FDR
    fdr_data = all_data.get("fdr_data", {})
    if fdr_data and round_number:
        fdr_teams = fdr_data.get("teams", [])
        next_round_fdr = []
        for team_data in fdr_teams:
            name = team_data.get("name", "")
            fixtures_list = team_data.get("fixtures", [])
            for fix in fixtures_list:
                if fix.get("gw") == round_number:
                    next_round_fdr.append({
                        "team": name,
                        "opponent": fix.get("opponent", ""),
                        "home": fix.get("home", True),
                        "atk": fix.get("atk", 0),
                        "def": fix.get("def", 0),
                    })
                    break
        if next_round_fdr:
            ctx["next_round_fdr"] = next_round_fdr
    
    # Prognozy
    predictions = all_data.get("predictions_data", [])
    if predictions:
        # Top 10 prognoz
        top_preds = []
        for pred in predictions[:10]:
            top_preds.append({
                "name": pred.get("name", "?"),
                "team": pred.get("team", "?"),
                "position": pred.get("position", "?"),
                "predicted_points": round(pred.get("predicted_points") or 0, 1),
                "ownership_pct": pred.get("popularity_pct", "?"),
                "opponent": pred.get("opponent_short") or pred.get("next_opponent", "?"),
                "is_home": pred.get("is_home", True),
            })
        ctx["top_predictions"] = top_preds
        
        # Captain pick (differential formula)
        if predictions:
            cap = max(predictions, key=captain_differential_score)
            ctx["captain_pick"] = {
                "name": cap.get("name", "?"),
                "team": cap.get("team", "?"),
                "position": cap.get("position", "?"),
                "predicted_points": round(cap.get("predicted_points") or 0, 1),
                "ownership_pct": cap.get("popularity_pct", "?"),
            }
    
    # Ownership i kapitanowie (dla differential picks)
    league_teams_detail = all_data.get("league_teams_detail", [])
    if league_teams_detail:
        # Top kapitanowie w lidze
        captains = []
        for team in league_teams_detail[:10]:
            cap_name = team.get("captain_name", "")
            if cap_name:
                captains.append(cap_name)
        if captains:
            ctx["popular_captains"] = captains
    
    # Składy drużyn (ownership)
    league_teams = all_data.get("league_teams", [])
    if league_teams:
        ownership = []
        for team in league_teams:
            slug = team.get("slug", "")
            display_name = team.get("display_name", slug.replace("-", " ").title())
            ownership.append(display_name)
        ctx["league_teams_sample"] = ownership[:15]
    
    return ctx


def _generate_single_expert(
    name, emoji, system_prompt, context_json,
    round_number, deepseek_key, gemini_key, label
):
    """
    Generuje prognozę jednego eksperta AI (Rabbti lub Tlinf).
    Zwraca dict: {"name": str, "emoji": str, "text": str, "error": str|None, "model": str}
    """
    print(f"  🤖 Generuję prognozę {emoji} {name}...")
    full_prompt = system_prompt.format(round_number=round_number)
    result = _call_ai_expert(
        prompt=f"{full_prompt}\n\nDANE:\n{context_json}",
        deepseek_key=deepseek_key,
        gemini_key=gemini_key,
        label=label,
    )
    text = result.get("text", "")
    error = result.get("error")
    if not text:
        print(f"  ⚠️  {name}: brak tekstu ({error})")
    else:
        print(f"  ✅ {name}: {len(text)} znaków (model: {result.get('model', '?')})")
    return {
        "name": name,
        "emoji": emoji,
        "text": text,
        "error": error,
        "model": result.get("model", ""),
    }


def generate_expert_predictions(all_data: dict, deepseek_key: str = "", gemini_key: str = "") -> tuple[dict, dict]:
    """
    Generuje dwie prognozy eksperckie (Rabbti i Tlinf) przez API AI.
    DeepSeek jako model podstawowy, Gemini jako fallback.
    
    Parametry:
        all_data: słownik z wszystkimi danymi (predictions, players, fixtures, etc.)
        deepseek_key: klucz DeepSeek API
        gemini_key: klucz Gemini API (fallback)
    
    Zwraca tuple z dwoma dict:
        - {"name": "Rabbti", "text": "...", "error": None/str, "model": "..."}
        - {"name": "Tlinf", "text": "...", "error": None/str, "model": "..."}
    
    Każda prognoza zawiera:
        - Rekomendację kapitana (z uzasadnieniem)
        - 2 transfery do rozważenia
    """
    if not deepseek_key and not gemini_key:
        return (
            {"name": "Rabbti", "text": "", "error": "Brak klucza API", "model": ""},
            {"name": "Tlinf", "text": "", "error": "Brak klucza API", "model": ""},
        )
    
    round_number = all_data.get("round_number", "?")
    print(f"\n🔮 Generuję prognozy eksperckie dla kolejki {round_number}...")
    
    # Buduj kontekst
    ctx = _build_expert_context(all_data)
    context_json = json.dumps(ctx, ensure_ascii=False, indent=2)
    
    rabbti_prompt = """Jesteś Rabbti - doświadczony analityk ligi PKO BP Ekstraklasy w Fantasy.
Pracujesz na danych i faktach, nie na przeczuciach. Twoje rekomendacje są rzetelne i konkretne.

KONTEKST:

ZADANIE:
Na podstawie powyższych danych przygotuj krótką prognozę przed kolejką {round_number}.

FORMAT ODPOWIEDZI (dokładnie taki, bez odstępstw):
⚽ Rabbti:

**Kapitan:**
[Imię Nazwisko] (Pozycja, Drużyna) vs Rywal - Uzasadnienie 1-2 zdania

**Transfery do rozważenia:**
1. [Imię Nazwisko] (Pozycja) - Krótkie uzasadnienie
2. [Imię Nazwisko] (Pozycja) - Krótkie uzasadnienie

WYMAGANIA:
- Odpowiedź maksymalnie 2000 znaków (Discord limit)
- Tylko 1 kapitan + 2 transfery
- Konkretne nazwiska z danych, nie zgaduj
- Po polsku, krótko i rzeczowo
- Nie dodawaj wstępu ani zakończenia"""

    rabbti = _generate_single_expert(
        name="Rabbti", emoji="⚽", system_prompt=rabbti_prompt,
        context_json=context_json, round_number=round_number,
        deepseek_key=deepseek_key, gemini_key=gemini_key, label="rabbti"
    )
    
    tlinf_prompt = """Jesteś Tlinf - zwykły kibic Ekstraklasy, który ogląda mecze z kanapy.
Nie boisz się podważać konsensusu i szukasz nietypowych rozwiązań. Czasem obstawiasz kontrowersyjnie,
ale zawsze masz argumenty. Lubisz graczy, których nikt nie bierze.

KONTEKST:

ZADANIE:
Na podstawie powyższych danych przygotuj kontrowersyjną prognozę przed kolejką {round_number}.

FORMAT ODPOWIEDZI (dokładnie taki, bez odstępstw):
🛋️ Tlinf:

**Kapitan:**
[Imię Nazwisko] (Pozycja, Drużyna) vs Rywal - Odwrotne uzasadnienie 1-2 zdania, dlaczego inni się mylą

**Transfery do rozważenia:**
1. [Imię Nazwisko] (Pozycja) - Dlaczego to dobry timing/wartość
2. [Imię Nazwisko] (Pozycja) - Ryzykowny ale może się opłacić

WYMAGANIA:
- Odpowiedź maksymalnie 2000 znaków (Discord limit)
- Tylko 1 kapitan + 2 transfery
- Możesz polecać zawodników z niskim ownership (różniąc się od tłumu)
- Po polsku, w stylu kibica z forum
- Nie dodawaj wstępu ani zakończenia"""

    tlinf = _generate_single_expert(
        name="Tlinf", emoji="🛋️", system_prompt=tlinf_prompt,
        context_json=context_json, round_number=round_number,
        deepseek_key=deepseek_key, gemini_key=gemini_key, label="tlinf"
    )
    return rabbti, tlinf


def send_expert_predictions(all_data: dict, webhook_url: str, deepseek_key: str = "", gemini_key: str = "", round_number: int = 0):
    """
    Generuje i wysyła prognozy eksperckie (Rabbti i Tlinf) na Discord.
    
    Wysyła dwie osobne wiadomości tekstowe zaraz po pre-match.
    
    Parametry:
        all_data: słownik z wszystkimi danymi (predictions, players, fixtures, etc.)
        webhook_url: URL Discord webhooka
        deepseek_key: klucz DeepSeek API
        gemini_key: klucz Gemini API (fallback)
        round_number: numer kolejki
    """
    # Generuj prognozy przez AI (DeepSeek + Gemini fallback)
    rabbti, tlinf = generate_expert_predictions(all_data, deepseek_key=deepseek_key, gemini_key=gemini_key)
    
    # Wyślij każdą prognozę jako osobną wiadomość Discord
    predictions_to_send = [rabbti, tlinf]
    
    for expert in predictions_to_send:
        name = expert["name"]
        text = expert["text"]
        error = expert.get("error")
        
        if error:
            print(f"  ⚠️  {name}: pomijam wysyłkę - {error}")
            continue
        
        if not text:
            print(f"  ⚠️  {name}: pusta odpowiedź - pomijam")
            continue
        
        # Przytnij jeśli za długa (limity Discord)
        if len(text) > 2000:
            text = text[:1997] + "..."
            print(f"  ℹ️  {name}: obcięto do 2000 znaków")
        
        # Wyślij na Discord
        success = _send_content(webhook_url, text)
        if success:
            print(f"  ✅ {name}: wysłano na Discord")
        else:
            print(f"  ⚠️  {name}: błąd wysyłki na Discord")
