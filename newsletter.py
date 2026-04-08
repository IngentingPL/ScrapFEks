"""
newsletter.py — Newsletter AI (Gemini) dla ScrapFEks
=====================================================

Po każdej kolejce generuje krótki komentarz po polsku na bazie danych z ScrapFEks.
Używa Gemini API (gemini-2.5-flash) przez urllib.request — BEZ zewnętrznych bibliotek.

📖 LEKCJA: API (Application Programming Interface) to sposób komunikacji między
programami. Wysyłasz JSON z pytaniem → dostajesz JSON z odpowiedzią.
Gemini API jest darmowe do ~15 requestów/minutę (model gemini-2.5-flash).

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

# Maksymalna długość newslettera zwracanego dalej do Discorda.
MAX_NEWSLETTER_CHARS = 1500

# Ustawienia Gemini — wersja diagnostyczna
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_MAX_OUTPUT_TOKENS = 2200
GEMINI_THINKING_BUDGET = 0  # 0 = wyłącz thinking dla newslettera
NEWSLETTER_END_MARKER = "### KONIEC NEWSLETTERA ###"


# ============================================================
# FUNKCJA GŁÓWNA
# ============================================================


def generate_newsletter(round_data: dict, api_key: str):
    """
    Generuje newsletter AI po zakończeniu kolejki.

    Wersja diagnostyczna:
    - loguje finish_reason i usageMetadata,
    - wykrywa podejrzanie urwaną odpowiedź,
    - robi jedną próbę awaryjną krótszym promptem.
    """
    if not api_key:
        print("  ℹ️  Newsletter: brak GEMINI_API_KEY — pomijam")
        return None

    round_number = round_data.get("round_number")
    print()
    print(f"📰 Newsletter: generuję dla kolejki {round_number}...")

    try:
        context = _build_context(round_data)
        prompt = _build_prompt(round_number, context)
        result = call_gemini(prompt, api_key, label="primary")
    except Exception as e:
        print(f"  ⚠️  Newsletter: błąd generowania — {e}")
        return None

    text = (result.get("text") or "").strip()

    if _should_retry_newsletter(result, text):
        print("  ⚠️  Newsletter: odpowiedź wygląda na urwaną lub niepełną — retry krótszym promptem")
        try:
            retry_prompt = _build_retry_prompt(round_number, context)
            retry_result = call_gemini(retry_prompt, api_key, label="retry")
            retry_text = (retry_result.get("text") or "").strip()
            if retry_text and not _should_retry_newsletter(retry_result, retry_text):
                result = retry_result
                text = retry_text
                print("  ✅ Newsletter: retry dał pełniejszą odpowiedź — używam retry")
            elif retry_text and len(retry_text) > len(text):
                result = retry_result
                text = retry_text
                print("  ℹ️  Newsletter: retry nadal nieidealny, ale dłuższy — używam retry")
        except Exception as e:
            print(f"  ⚠️  Newsletter: błąd retry — {e}")

    text = (text or "").strip()
    if not text:
        print("  ⚠️  Newsletter: Gemini zwrócił pusty tekst — pomijam")
        return None

    if len(text) > MAX_NEWSLETTER_CHARS:
        text = text[:MAX_NEWSLETTER_CHARS - 1].rstrip() + "…"
        print(f"  ℹ️  Newsletter: obcięto do {MAX_NEWSLETTER_CHARS} znaków")

    try:
        _save_newsletter(round_number, text)
    except Exception as e:
        print(f"  ⚠️  Newsletter: błąd zapisu do archiwum — {e}")

    print(f"  ✅ Newsletter wygenerowany ({len(text)} znaków)")
    return text


# ============================================================
# GEMINI API CALL
# ============================================================


def call_gemini(prompt: str, api_key: str, label: str = "primary") -> dict:
    """
    Wysyła prompt do Gemini API i zwraca słownik z tekstem i diagnostyką.

    Najważniejsze poprawki:
    - wyłącza thinkingBudget dla Gemini 2.5 Flash,
    - zwiększa maxOutputTokens,
    - łączy tekst ze wszystkich części odpowiedzi (parts),
    - loguje finishReason i usageMetadata.
    """
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={api_key}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
            "thinkingConfig": {
                "thinkingBudget": GEMINI_THINKING_BUDGET,
            },
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
        print(f"  ⚠️  Gemini API HTTP błąd ({label}): {e.code} {e.reason} — {body[:400]}")
        return {
            "text": None,
            "finish_reason": None,
            "usage_metadata": {},
            "marker_present": False,
            "candidate_parts_count": 0,
            "error": f"HTTP {e.code}",
            "raw": None,
        }
    except urllib.error.URLError as e:
        print(f"  ⚠️  Gemini API błąd połączenia ({label}): {e.reason}")
        return {
            "text": None,
            "finish_reason": None,
            "usage_metadata": {},
            "marker_present": False,
            "candidate_parts_count": 0,
            "error": str(e.reason),
            "raw": None,
        }
    except Exception as e:
        print(f"  ⚠️  Gemini API nieoczekiwany błąd ({label}): {e}")
        return {
            "text": None,
            "finish_reason": None,
            "usage_metadata": {},
            "marker_present": False,
            "candidate_parts_count": 0,
            "error": str(e),
            "raw": None,
        }

    parsed = _parse_gemini_result(result)
    _log_gemini_debug(parsed, label=label)
    return parsed

def _parse_gemini_result(result: dict) -> dict:
    """Parsuje odpowiedź Gemini i składa tekst ze wszystkich części odpowiedzi."""
    candidates = result.get("candidates") or []
    candidate = candidates[0] if candidates else {}
    finish_reason = candidate.get("finishReason") or candidate.get("finish_reason")
    usage_metadata = result.get("usageMetadata") or result.get("usage_metadata") or {}
    model_version = result.get("modelVersion") or result.get("model_version")

    parts = ((candidate.get("content") or {}).get("parts") or [])

    visible_text_parts = []
    all_text_parts = []
    for part in parts:
        part_text = part.get("text")
        if not part_text:
            continue
        all_text_parts.append(part_text)
        if not part.get("thought"):
            visible_text_parts.append(part_text)

    text = "\n".join(visible_text_parts).strip()
    if not text:
        text = "\n".join(all_text_parts).strip()

    marker_present = NEWSLETTER_END_MARKER in text
    if marker_present:
        text = text.replace(NEWSLETTER_END_MARKER, "").strip()

    return {
        "text": text,
        "finish_reason": finish_reason,
        "usage_metadata": usage_metadata,
        "marker_present": marker_present,
        "candidate_parts_count": len(parts),
        "model_version": model_version,
        "raw": result,
    }


def _looks_like_truncated_text(text: str) -> bool:
    """Heurystyka: tekst wygląda na urwany, jeśli nie kończy się pełnym zdaniem."""
    if not text:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    return not stripped.endswith((".", "!", "?", "…", "”", '"'))


def _should_retry_newsletter(result: dict, text: str) -> bool:
    """Decyduje, czy warto zrobić retry po diagnozie odpowiedzi Gemini."""
    finish_reason = (result.get("finish_reason") or "").upper()
    if finish_reason == "MAX_TOKENS":
        return True
    if not result.get("marker_present"):
        return True
    if _looks_like_truncated_text(text):
        return True
    return False


def _log_gemini_debug(parsed: dict, label: str = "primary") -> None:
    """Wypisuje pełną diagnostykę odpowiedzi Gemini w logach CI."""
    text = (parsed.get("text") or "")
    usage = parsed.get("usage_metadata") or {}

    print(f"  === GEMINI DEBUG ({label}) START ===")
    print(f"  model_version: {parsed.get('model_version')}")
    print(f"  finish_reason: {parsed.get('finish_reason')}")
    print(f"  candidate_parts_count: {parsed.get('candidate_parts_count')}")
    print(f"  marker_present: {parsed.get('marker_present')}")
    print(f"  newsletter_text_length: {len(text)}")
    print(f"  newsletter_text_ending: {repr(text[-200:])}")
    print(f"  prompt_token_count: {usage.get('promptTokenCount')}")
    print(f"  candidates_token_count: {usage.get('candidatesTokenCount')}")
    print(f"  thoughts_token_count: {usage.get('thoughtsTokenCount')}")
    print(f"  total_token_count: {usage.get('totalTokenCount')}")
    print(f"  === GEMINI DEBUG ({label}) END ===")


def _build_retry_prompt(round_number, context: dict) -> str:
    """Krótszy prompt retry: mniej swobody, większa szansa na domknięcie tekstu."""
    context_json = json.dumps(context, ensure_ascii=False, indent=2)
    return f"""Jesteś komentatorem Fantasy Ekstraklasa. Napisz bardzo krótki newsletter po polsku po kolejce {round_number}.

DANE Z KOLEJKI:
{context_json}

Napisz dokładnie 4 sekcje:
🔥 CO SIĘ DZIAŁO
🏆 WYŚCIG O TYTUŁ
💡 CO DALEJ
🎲 CIEKAWOSTKA

ZASADY:
- Każda sekcja: maksymalnie 2 krótkie zdania.
- Używaj tylko podanych danych.
- Nie dodawaj wstępu ani zakończenia.
- Zakończ pełnym ostatnim zdaniem.
- Na samym końcu dopisz dokładnie: {NEWSLETTER_END_MARKER}
"""


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

4. 🎲 CIEKAWOSTKA — jeden zaskakujący fakt z danych, śmieszne zestawienie, lub komentarz z przymrużeniem oka.

ZASADY:
- Pisz po polsku, naturalnym językiem — jak komentator sportowy, nie robot.
- Celuj w 700-900 znaków łącznie.
- Używaj emoji oszczędnie.
- Nie wymyślaj danych — korzystaj TYLKO z podanych.
- Każdą sekcję zacznij od nagłówka emoji (🔥, 🏆, 💡, 🎲).
- Nie dodawaj wstępu ani zakończenia — od razu sekcje.
- Zakończ pełnym ostatnim zdaniem.
- Na samym końcu dopisz dokładnie: {NEWSLETTER_END_MARKER}
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
        "model": GEMINI_MODEL,
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


# ============================================================
# CLI — test klucza Gemini API
# ============================================================
# Użycie:
#   GEMINI_API_KEY=twoj_klucz python newsletter.py
#
# Wysyła krótki testowy prompt do Gemini i wyświetla odpowiedź.
# NIE wysyła nic na Discord, NIE zapisuje do archiwum.

if __name__ == "__main__":
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("❌ Ustaw zmienną GEMINI_API_KEY, np.:")
        print("   GEMINI_API_KEY=AIza... python newsletter.py")
        raise SystemExit(1)

    print("🔑 Testuję klucz Gemini API...")
    test_prompt = "Odpowiedz jednym zdaniem po polsku: Czy działa połączenie z Gemini API?"
    result = call_gemini(test_prompt, api_key)

    if result:
        print(f"✅ Klucz działa! Odpowiedź Gemini:\n   {result.strip()}")
    else:
        print("❌ Brak odpowiedzi — sprawdź klucz lub logi powyżej.")
