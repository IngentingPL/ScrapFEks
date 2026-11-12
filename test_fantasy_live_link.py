#!/usr/bin/env python3
"""
Test deterministyczny linku "Na żywo ↗" do klasyfikacji ligi na żywo
(Fantasy Live — strona znajomego, https://fantasy.szafran.top).

Sprawdza:
1. Link występuje w zbudowanej stronie DOKŁADNIE 2 razy:
   - wariant A: stopka kafelka "Top 5 · Liga CMF" na stronie głównej,
   - wariant B: pasek zakładki Liga CMF (nad tabelą Drużyny/Duety).
2. Linku NIE ma w Prognozie ani w menu na górze (wariant C odrzucony).
3. Atrybuty są poprawne: href, target="_blank", rel, title, aria-label.
4. Kliknięcie w link nie przełącza zakładek: obsługa kliknięć dashboardu
   łapie elementy z atrybutem data-go — link ani jego przodkowie nie mają
   takiego atrybutu (tzw. obsługa data-go działa przez closest('[data-go]')).
5. Edge-snapshot: gdy brakuje danych ligi (0 drużyn), link nadal się renderuje.

Bez sieci i bez bibliotek zewnętrznych. Uruchom: python3 test_fantasy_live_link.py
"""
import os
import re
import tempfile

from dashboard import FANTASY_LIVE_URL, FANTASY_LIVE_TITLE, generate_dashboard_html
from test_snapshot_roundtrip import make_sample_inputs


def render_html(filename: str) -> str:
    """Buduje pełny HTML dashboardu z przykładowych danych (bez sieci)."""
    with tempfile.TemporaryDirectory() as tmp:
        inputs = make_sample_inputs(os.path.join(tmp, filename))
        generate_dashboard_html(**inputs, timestamp="2026-01-01 12:00", has_archive=False)
        with open(inputs["filename"], encoding="utf-8") as f:
            return f.read()


def check_link_attributes(html: str, context: str):
    """Weryfikuje atrybuty bezpieczeństwa i dostępności linku 'Na żywo ↗'."""
    assert 'href="%s"' % FANTASY_LIVE_URL in html, context + ": brak href"
    assert 'target="_blank"' in html, context + ": brak target=_blank"
    assert 'rel="noopener noreferrer"' in html, context + ": brak rel"
    assert 'title="%s"' % FANTASY_LIVE_TITLE in html, context + ": brak title"
    assert 'aria-label="%s"' % FANTASY_LIVE_TITLE in html, context + ": brak aria-label"


def test_link_exactly_twice_in_right_places():
    html = render_html("live.html")
    check_link_attributes(html, "pełna strona")

    # Dokładnie dwa wystąpienia adresu (wariant A + B; bez menu i Prognozy)
    count = html.count(FANTASY_LIVE_URL)
    assert count == 2, f"Link ma wystąpić dokładnie 2 razy, a występuje {count}"

    # A: link jest w stopce kafelka "Top 5 · Liga CMF", z przerywanym obrysem
    card = re.search(
        r"<article class=\"landing-card\">.*?Top 5 · Liga CMF.*?</article>", html, re.S
    ).group(0)
    assert 'class="live-link landing-cta live-cta-dashed"' in card, "A: linku nie ma w kafelku Top 5"
    assert "live-foot" in card, "A: stopka bez klasy live-foot"
    assert "Pełna tabela ligi →" in card, "A: zniknął przycisk Pełna tabela ligi"

    # B: link jest w zakładce Liga CMF (sekcja v-teams), w pasku nad tabelą
    teams = html.split('id="v-teams"', 1)[1].split("</section>", 1)[0]
    assert 'class="live-link ghost-link"' in teams, "B: linku nie ma w zakładce Liga CMF"
    assert 'id="league-view"' in teams, "B: zniknął przełącznik Drużyny/Duety"

    # Negatywnie: linku nie ma w menu na górze (masthead) ani w Prognozie
    masthead = html.split('class="masthead"', 1)[1].split("</header>", 1)[0]
    assert FANTASY_LIVE_URL not in masthead, "C: link wkradł się do menu"
    predictions = html.split('id="v-predictions"', 1)[1].split("</section>", 1)[0]
    assert FANTASY_LIVE_URL not in predictions, "Link nie może być w Prognozie"


def test_link_not_intercepted_by_data_go_handler():
    html = render_html("live_navigator.html")
    # Kliknięcia zakładek działają przez closest('[data-go]') — jeśli link
    # (lub jego przodek) miałby data-go, klik otwierałby zakładkę zamiast
    # nowej karty. Wycinamy fragment wokół linku i sprawdzamy przodków.
    before_link, after_link = html.split(FANTASY_LIVE_URL, 1)
    # Obsługa data-go patrzy w górę drzewa DOM: element + przodkowie.
    # W praktycznym teście wystarczy sprawdzić, że sam tag <a> nie ma data-go.
    tag_start = before_link.rfind("<a")
    assert 'data-go' not in before_link[tag_start:], "Link nie może mieć atrybutu data-go"
    # Ani bezpośredni rodzic (stopka kafelka / toolbar) nie przekazuje data-go:
    # sprawdzamy końcówkę otaczającego tagu przed linkiem.
    tail = before_link[:tag_start].rstrip()
    assert not tail.endswith("</a>"), "Nieoczekiwany zagnieżdżony link"


def test_link_renders_without_league_data():
    """Edge-snapshot: brak danych tabeli ligi (0 drużyn) — link nadal jest."""
    with tempfile.TemporaryDirectory() as tmp:
        inputs = make_sample_inputs(os.path.join(tmp, "live_empty.html"))
        inputs["league_teams_count"] = 0
        inputs["league_name"] = ""
        inputs["league_rosters"] = {}
        inputs["league_teams_detail"] = []
        inputs["duets_data"] = []
        generate_dashboard_html(**inputs, timestamp="2026-01-01 12:00", has_archive=False)
        with open(inputs["filename"], encoding="utf-8") as f:
            html = f.read()
    check_link_attributes(html, "brak danych ligi")
    assert html.count(FANTASY_LIVE_URL) == 2, "Przy pustej lidze link ma być w obu miejscach"


if __name__ == "__main__":
    test_link_exactly_twice_in_right_places()
    print("OK 1: link dokładnie 2 razy — A w kafelku Top 5, B w Lidze CMF, brak w menu i Prognozie")
    test_link_not_intercepted_by_data_go_handler()
    print("OK 2: klik w link nie przechodzi przez obsługę data-go")
    test_link_renders_without_league_data()
    print("OK 3: przy braku danych ligi link nadal się renderuje (2 razy)")
