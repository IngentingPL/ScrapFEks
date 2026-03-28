"""
newsletter.py — Newsletter AI (Gemini) dla ScrapFEks
=====================================================

Po każdej kolejce generuje krótki komentarz po polsku na bazie danych z ScrapFEks.
Używa Gemini API (gemini-2.0-flash) przez urllib.request — BEZ zewnętrznych bibliotek.

📖 LEKCJA: API (Application Programming Interface) to sposób komunikacji między
programami. Wysyłasz JSON z pytaniem → dostajesz JSON z odpowiedzią.
Gemini API jest darmowe do ~15 requestów/minutę (model gemini-2.0-flash).

Autor: Wygenerowane przez Claude dla Piotra
"""

import json
import os
import urllib.request
import urllib.error
from datetime import date


OUTPUT_DIR = "output"
NEWSLETTER_HISTORY_FILE = os.path.join(OUTPUT_DIR, "newsletter_history.json")

# Timeout dla requestu do Gemini API (sekundy)
GEMINI_TIMEOUT = 30

# Maksymalna długość newslettera (znaki) — Discord embed description limit
MAX_NEWSLETTER_CHARS = 1500


# ============================================================
# FUNKCJA GŁÓWNA
# ============================================================

def generate_newsletter(round_data: dict, api_key: str):
    """
    Generuje newsletter AI po zakończeniu kolejki.

    Zbiera dane z round_data, wysyła prompt do Gemini API,
    zapisuje wynik do archiwum (newsletter_history.json)
    i zwraca tekst do umieszczenia w Discord embedzie.

    📖 LEKCJA: Funkcja "defensywna" — każdy błąd (API, dane, zapis)
    jest przechwytywany i logowany, ale NIGDY nie przerywa pipeline'u.

    Parametry:
        round_data: dict z danymi kolejki (patrz _build_context)
        api_key:    klucz Gemini API (z GEMINI_API_KEY)

    Zwraca:
        str — tekst newslettera (max 1500 znaków)
        None — jeśli cokolwiek poszło nie tak
    """
    if not api_key:
        print("  ℹ️  Newsletter: brak GEMINI_API_KEY — pomijam")
        return None

    round_number = round_data.get("round_number")
    print(f"\n📰 Newsletter: generuję dla kolejki {round_number}...")

    try:
        context = _build_context(round_data)
        prompt = _build_prompt(round_number, context)
        text = call_gemini(prompt, api_key)
    except Exception as e:
        print(f"  ⚠️  Newsletter: błąd generowania — {e}")
        return None

    if not text or not text.strip():
        print("  ⚠️  Newsletter: Gemini zwrócił pusty tekst — pomijam")
        return None

    # Obetnij do MAX_NEWSLETTER_CHARS jeśli za długi
    if len(text) > MAX_NEWSLETTER_CHARS:
        text = text[:MAX_NEWSLETTER_CHARS - 1] + "…"
        print(f"  ℹ️  Newsletter: obcięto do {MAX_NEWSLETTER_CHARS} znaków")

    # Zapisz do archiwum
    try:
        _save_newsletter(round_number, text)
    except Exception as e:
        print(f"  ⚠️  Newsletter: błąd zapisu do archiwum — {e}")
        # Błąd zapisu nie blokuje zwrócenia tekstu

    print(f"  ✅ Newsletter wygenerowany ({len(text)} znaków)")
    return text


# ============================================================
# GEMINI API CALL
# ============================================================

def call_gemini(prompt: str, api_key: str):
    """
    Wysyła prompt do Gemini API i zwraca odpowiedź.

    📖 LEKCJA: To samo co Discord webhook, ale w drugą stronę —
    tam WYSYŁALIŚMY treść do wyświetlenia, tu PYTAMY o wygenerowanie treści.
    Gemini endpoint przyjmuje JSON z "contents" i zwraca JSON z "candidates".

    Używamy modelu gemini-2.0-flash — szybki i darmowy (~15 req/min).

    Zwraca:
        str — tekst odpowiedzi Gemini
        None — przy błędzie (HTTP, timeout, parsowanie)
    """
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.8,       # kreatywność (0.0=sztywny, 1.0=kreatywny)
            "maxOutputTokens": 1500,  # max długość odpowiedzi w tokenach
        },
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  ⚠️  Gemini API HTTP błąd: {e.code} {e.reason} — {body[:200]}")
        return None
    except urllib.error.URLError as e:
        print(f"  ⚠️  Gemini API błąd połączenia: {e.reason}")
        return None
    except Exception as e:
        print(f"  ⚠️  Gemini API nieoczekiwany błąd: {e}")
        return None

    # Odpowiedź Gemini: result["candidates"][0]["content"]["parts"][0]["text"]
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        print(f"  ⚠️  Gemini API: nieoczekiwana struktura odpowiedzi — {e}")
        return None


# ============================================================
# BUDOWANIE KONTEKSTU DLA GEMINI
# ============================================================

def _build_context(round_data: dict) -> dict:
    """
    Buduje słownik kontekstu do wysłania do Gemini.

    Zbiera tylko te dane, które faktycznie istnieją —
    pomija pola z None lub pustymi listami.

    📖 LEKCJA: json.dumps z indent=2 zamienia słownik Pythona w
    czytelny tekst JSON — idealny format dla promptu AI.
    """
    ctx = {}

    round_number = round_data.get("round_number")
    if round_number:
        ctx["round_number"] = round_number

    # --- Wyniki kolejki i tabela sezonowa ---
    league_data = round_data.get("league_data", [])
    if league_data:
        # Top 3 i bottom 3 według punktów tej kolejki
        sorted_by_gw = sorted(
            league_data,
            key=lambda t: t.get("last_points") or t.get("pts", 0) or 0,
            reverse=True,
        )
        top3 = []
        for t in sorted_by_gw[:3]:
            name = t.get("display_name") or t.get("slug", "").replace("-", " ").title()
            top3.append({"name": name, "pts_this_round": t.get("last_points") or t.get("pts", 0) or 0})
        if top3:
            ctx["top3_teams"] = top3

        bottom3 = []
        for t in sorted_by_gw[-3:]:
            name = t.get("display_name") or t.get("slug", "").replace("-", " ").title()
            bottom3.append({"name": name, "pts_this_round": t.get("last_points") or t.get("pts", 0) or 0})
        if bottom3:
            ctx["bottom3_teams"] = bottom3

        # Tabela sezonowa według total_points
        sorted_by_total = sorted(
            league_data,
            key=lambda t: t.get("total_points") or t.get("season_total") or 0,
            reverse=True,
        )
        standings = []
        for i, t in enumerate(sorted_by_total):
            name = t.get("display_name") or t.get("slug", "").replace("-", " ").title()
            total = t.get("total_points") or t.get("season_total") or 0
            standings.append({"pos": i + 1, "name": name, "total_pts": total})
        if standings:
            ctx["standings"] = standings
            ctx["leader"] = standings[0]["name"]
            if len(standings) >= 2:
                ctx["leader_gap"] = standings[0]["total_pts"] - standings[1]["total_pts"]

    # --- Zawodnik-niespodzianka i rozczarowanie ---
    players_data = round_data.get("players_data", [])
    if players_data and round_number:
        hidden_gem, gem_pts = _find_hidden_gem(players_data, round_number)
        if hidden_gem and gem_pts > 0:
            ctx["surprise_player"] = {
                "name": hidden_gem.get("name", "?"),
                "team": hidden_gem.get("team", "?"),
                "points": gem_pts,
                "ownership_pct": hidden_gem.get("popularity_pct", "?"),
            }

        disappointment, dis_pts = _find_disappointment(players_data, round_number)
        if disappointment and dis_pts < 5:
            ctx["disappointment_player"] = {
                "name": disappointment.get("name", "?"),
                "team": disappointment.get("team", "?"),
                "points": dis_pts,
                "ownership_pct": disappointment.get("popularity_pct", "?"),
            }

    # --- Kapitanowie w lidze ---
    league_teams_detail = round_data.get("league_teams_detail", [])
    if league_teams_detail and players_data and round_number:
        captains = _collect_captains(league_teams_detail, players_data, round_number, league_data)
        if captains:
            ctx["captains"] = captains[:8]  # max 8 żeby prompt nie był za długi

    # --- Trafność prognozy ---
    accuracy_data = round_data.get("accuracy_data")
    if accuracy_data:
        mae = accuracy_data.get("mae")
        if mae is not None:
            ctx["accuracy_mae"] = mae

    # --- Prognozy na następną kolejkę ---
    predictions_data = round_data.get("predictions_data", [])
    if predictions_data:
        top5 = []
        for pred in predictions_data[:5]:
            top5.append({
                "name": pred.get("name", "?"),
                "team": pred.get("team", "?"),
                "position": pred.get("position", "?"),
                "predicted_points": pred.get("predicted_points", 0),
                "ownership_pct": pred.get("popularity_pct", "?"),
                "next_opponent": pred.get("opponent_short") or pred.get("next_opponent", "?"),
            })
        if top5:
            ctx["top5_predictions"] = top5

        # Captain pick (differential formula)
        def _captain_score(pred):
            pts = pred.get("predicted_points") or 0.0
            own_str = pred.get("popularity_pct", "100%")
            try:
                own = float(str(own_str).replace("%", "").strip())
            except (ValueError, TypeError):
                own = 100.0
            return pts * (1.0 - own / 100.0)

        cap = max(predictions_data, key=_captain_score)
        ctx["captain_pick"] = {
            "name": cap.get("name", "?"),
            "team": cap.get("team", "?"),
            "predicted_points": cap.get("predicted_points", 0),
            "ownership_pct": cap.get("popularity_pct", "?"),
        }

    return ctx


def _find_hidden_gem(players_data, round_number):
    """Szuka zawodnika z najwyższymi punktami przy ownership < 20%."""
    best = None
    best_pts = -1
    for player in players_data:
        try:
            own = float(str(player.get("popularity_pct", "100%")).replace("%", "").strip())
        except (ValueError, TypeError):
            own = 100.0
        if own >= 20.0:
            continue
        for r in player.get("rounds", []):
            if r.get("round") == round_number and r.get("played"):
                pts = r.get("points", 0) or 0
                if pts > best_pts:
                    best_pts = pts
                    best = player
                break
    return best, best_pts


def _find_disappointment(players_data, round_number):
    """Szuka gracza z najniższymi punktami przy ownership > 40%."""
    worst = None
    worst_pts = 999
    for player in players_data:
        try:
            own = float(str(player.get("popularity_pct", "0%")).replace("%", "").strip())
        except (ValueError, TypeError):
            own = 0.0
        if own <= 40.0:
            continue
        for r in player.get("rounds", []):
            if r.get("round") == round_number and r.get("played"):
                pts = r.get("points", 0) or 0
                if pts < worst_pts:
                    worst_pts = pts
                    worst = player
                break
    return worst, worst_pts


def _collect_captains(league_teams_detail, players_data, round_number, league_data):
    """Zbiera dane kapitanów z każdej drużyny ligi."""
    # Lookup: player_id → punkty w tej kolejce
    player_round_pts = {}
    for player in players_data:
        pid = str(player.get("player_id", ""))
        if not pid:
            continue
        for r in player.get("rounds", []):
            if r.get("round") == round_number and r.get("played"):
                player_round_pts[pid] = r.get("points", 0) or 0
                break

    # Lookup: slug → display_name
    display_name_map = {
        t.get("slug", ""): t.get("display_name") or t.get("slug", "").replace("-", " ").title()
        for t in (league_data or [])
    }

    captains = []
    for team in league_teams_detail:
        team_slug = team.get("slug", "")
        team_name = display_name_map.get(team_slug) or team_slug.replace("-", " ").title()
        for p in team.get("players", []):
            if p.get("C"):
                cap_pid = str(p.get("pid", ""))
                cap_name = p.get("name", "?")
                cap_pts = player_round_pts.get(cap_pid, 0)
                captains.append({
                    "team": team_name,
                    "captain": cap_name,
                    "captain_pts": cap_pts,
                })
                break  # Każda drużyna ma jednego kapitana

    captains.sort(key=lambda c: c["captain_pts"], reverse=True)
    return captains


# ============================================================
# PROMPT DLA GEMINI
# ============================================================

def _build_prompt(round_number, context: dict) -> str:
    """Buduje precyzyjny prompt dla Gemini z danymi kolejki."""
    context_json = json.dumps(context, ensure_ascii=False, indent=2)
    return f"""Jesteś komentatorem Fantasy Ekstraklasa. Piszesz krótki, energiczny newsletter po polsku po zakończeniu kolejki {round_number}.

DANE Z KOLEJKI:
{context_json}

NAPISZ NEWSLETTER W 4 SEKCJACH (każda 2-3 zdania max):

1. 🔥 CO SIĘ DZIAŁO — komentarz do wyników kolejki. Kto zaskoczył? Kto zawiódł? Użyj danych o zawodniku-niespodziance i rozczarowaniu. Bądź konkretny — podawaj nazwiska i punkty.

2. 🏆 WYŚCIG O TYTUŁ — analiza ligi prywatnej. Kto goni lidera? Kto spada? Jakie są szanse na zmianę pozycji? Użyj danych z tabeli i różnic punktowych.

3. 💡 CO DALEJ — rekomendacje transferowe na następną kolejkę. Kogo warto kupić? Kogo sprzedać? Oprzyj się na prognozach i FDR. Podaj 1-2 konkretne nazwiska.

4. 🎲 CIEKAWOSTKA — jeden zaskakujący fakt z danych, śmieszne zestawienie, lub komentarz z przymrużeniem oka. Może porównanie, rekord, albo statystyka która nikogo by nie napadła. Bądź kreatywny.

ZASADY:
- Pisz po polsku, naturalnym językiem — jak komentator sportowy, nie robot
- MAX 800 znaków łącznie (Discord ma limity)
- Używaj emoji oszczędnie
- Nie wymyślaj danych — korzystaj TYLKO z podanych
- Każdą sekcję zacznij od nagłówka emoji (🔥, 🏆, 💡, 🎲)
- Nie dodawaj wstępu ani zakończenia — od razu sekcje
"""


# ============================================================
# ARCHIWUM — zapis i odczyt newsletter_history.json
# ============================================================

def _save_newsletter(round_number, text: str) -> None:
    """
    Dopisuje newsletter do archiwum JSON.

    Format: lista słowników [{round, date, text, model}, ...]
    Najnowsze wpisy mają największy indeks (append).

    📖 LEKCJA: os.makedirs z exist_ok=True tworzy katalog jeśli nie istnieje,
    ale nie wyrzuca błędu jeśli już istnieje.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Wczytaj istniejące archiwum (lub zacznij od pustej listy)
    history = []
    if os.path.exists(NEWSLETTER_HISTORY_FILE):
        try:
            with open(NEWSLETTER_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            history = []

    # Dodaj nowy wpis
    entry = {
        "round": round_number,
        "date": date.today().isoformat(),
        "text": text,
        "model": "gemini-2.0-flash",
    }
    history.append(entry)

    with open(NEWSLETTER_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"  ✅ Newsletter zapisany do archiwum ({len(history)} wpisów)")


def load_newsletter_history() -> list:
    """
    Wczytuje archiwum newsletterów z pliku JSON.

    Zwraca listę wpisów (lub pustą listę jeśli brak pliku).
    Używane przez generate_dashboard_html do zakładki Newsletter.
    """
    if not os.path.exists(NEWSLETTER_HISTORY_FILE):
        return []
    try:
        with open(NEWSLETTER_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []
