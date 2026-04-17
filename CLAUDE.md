# CLAUDE.md – ScrapFEks

Repozytorium: https://github.com/IngentingPL/ScrapFEks/

## Czym jest projekt

ScrapFEks to automatyczny scraper i dashboard dla Fantasy Ekstraklasy (fantasy.ekstraklasa.org). Śledzi prywatną ligę "Discord FMForumCMF" oraz drużynę "Tokusatsu Soccer". Generuje dashboard HTML oraz wysyła powiadomienia na Discord przez webhook.

---

## Struktura plików

```
ScrapFEks/
├── .github/workflows/
│   ├── scrape.yml              # Główny workflow – uruchamia scraper
│   ├── test_gemini.yml         # Testowanie klucza Gemini API
│   └── update_schedule.yml    # Aktualizacja terminarza
├── docs/
│   ├── index.html              # Wygenerowany dashboard (GitHub Pages)
│   └── logo.PNG
├── output/
│   ├── dashboard.html          # Roboczy dashboard
│   ├── discord_sent.json       # Flagi wysłanych powiadomień Discord
│   ├── fantasy_captains_*.csv  # Historia kapitanów
│   └── debug_team_*.html       # Pliki debugowe drużyn
├── scraper.py                  # GŁÓWNY PLIK – scraping + generowanie HTML
├── predictor.py                # Logika prognoz zawodników
├── tuner.py                    # Optymalizacja parametrów predykcji
├── accuracy.py                 # Śledzenie trafności prognoz
├── discord_notify.py           # Wysyłanie powiadomień Discord
├── newsletter.py               # Newsletter generowany przez Gemini AI
├── league_tracker.py           # Tracker sezonu ligowego
├── update_schedule.py          # Aktualizacja terminarza kolejek
├── test_single_player.py       # Testowanie pojedynczego zawodnika
├── terminarz.txt               # Terminarz kolejek (daty meczów)
├── autumn_points.json          # Punkty z rundy jesiennej
├── duets.json                  # Dane par (duety) w lidze CMF
├── duets_prev_ranking.json     # Poprzedni ranking duetów
├── hockey_prev_ranking.json    # Poprzedni ranking ligi hokejowej
├── design.md                   # Dokumentacja systemu designu
├── requirements.txt            # Zależności Python
└── README.md
```

---

## Zasady – ZAWSZE przestrzegaj

1. **Czytaj przed edycją** – zawsze przeczytaj plik w całości zanim go zmienisz, nigdy nie edytuj z pamięci
2. **Nie ruszaj istniejących zakładek** – chyba że użytkownik wyraźnie o to prosi
3. **Tylko Python standard library** – bez zewnętrznych bibliotek (chyba że już są w requirements.txt)
4. **Komentarze po polsku** – krótkie, beginner-friendly, przy każdej ważniejszej zmianie
5. **Przyrostowe zmiany** – małe kroki, sprawdzaj każdy etap
6. **Jeden plik HTML** – cały CSS i JS inline w generowanym pliku, bez osobnych plików

---

## Generowanie dashboardu

- HTML jest generowany dynamicznie przez `scraper.py` – **nie ma osobnego pliku HTML do edycji**
- CSS jest wbudowany w generowany HTML (szukaj sekcji `<style>` w funkcjach generujących)
- Dashboard trafia do `docs/index.html` (GitHub Pages) i `output/dashboard.html`

---

## Motywy CSS

Dashboard obsługuje dwa motywy – każda zmiana CSS musi działać w obu:

- **Dark** – domyślny motyw, oparty na systemie designu opisanym w `design.md` (inspirowany The Verge)
- **Fantasy** – jasny motyw, aktywowany przez klasę `html.theme-fantasy`

### Przed jakąkolwiek zmianą CSS przeczytaj `design.md` w całości.

Kluczowe zasady z `design.md` (skrót):
- Tło canvas: `#131313` (Canvas Black)
- Akcenty: `#3cffd0` (Jelly Mint) i `#5200ff` (Verge Ultraviolet) – używane oszczędnie jako "hazard tape", nie jako tło
- Tekst główny: `#ffffff`, metadane: `#949494`
- Karty: zaokrąglone rogi (20–40px), obramowanie 1px – **zero box-shadow**
- Bez gradientów – tylko solid color blocks
- Hover na linkach: zawsze `#3860be` (Deep Link Blue)

Przykład jak pisać style dla obu motywów:
```css
/* domyślnie dark */
.element { color: #fff; }
/* dla motywu fantasy */
html.theme-fantasy .element { color: #000; }
```

---

## Responsywność

Dashboard musi działać na:
- Mobile: 360px
- Tablet: 768px
- Desktop: 1440px
- Ultrawide: 3440px

Główny kontener powinien mieć `max-width` z `margin: auto` – treść nie może się rozciągać na pełną szerokość ultrawide. Używaj CSS Grid lub Flexbox z wrappingiem zamiast sztywnych szerokości pikselowych.

---

## Powiadomienia Discord

Powiadomienia są wysyłane przez `discord_notify.py` i zarządzane w `scraper.py`. Flagi wysłanych powiadomień są zapisywane w `output/discord_sent.json` – zapobiega to podwójnemu wysyłaniu.

### Typy powiadomień (kolejność w ciągu kolejki):

| Kiedy | Co |
|---|---|
| Dzień przed pierwszym meczem | Pre-match: prognoza + eksperci Rabbti i Tlinf |
| Godzinę po pierwszym meczu | Podsumowanie kapitanów |
| Po ostatnim meczu kolejki | Post-match: wyniki |

### Eksperci AI (Gemini):
- **⚽ Rabbti** – doświadczony analityk Ekstraklasy, rzetelny, pracuje na danych
- **🛋️ Tlinf** – zwykły kibic, kontrowersyjny, podważa konsensus

Każda wiadomość Discord max **2000 znaków** (limit webhooków). Wiadomości ekspertów są wysyłane jako zwykły tekst (nie embed), jako osobne webhook calle.

---

## Gemini AI

- Model: `gemini-2.5-flash`
- Klucz API: GitHub Secret `GEMINI_API_KEY`
- Używany w: `newsletter.py`, prognozach ekspertów w `discord_notify.py`

---

## GitHub Secrets

| Secret | Do czego |
|---|---|
| `GEMINI_API_KEY` | Gemini API |
| `DISCORD_WEBHOOK_URL` | Webhook Discord |
| `PAT` | Personal Access Token do pushowania zmian przez Actions |

---

## Tabela CMF League

- Tabela kombinowana: **jesień + wiosna** (suma punktów z obu rund)
- To jest "tabela sumaryczna" – używana do sortowania drużyn w widoku kapitanów i przy zawodnikach
- Dane z rundy jesiennej są w `autumn_points.json`
- Scraper oblicza tabelę sumaryczną podczas działania – dane są dostępne w pamięci

---

## Średnia ocen zawodników

- Średnia za **ostatnie 5 kolejek**
- Uwzględnia **wszystkie** kolejki, włącznie z tymi gdzie zawodnik nie grał (ocena = 0)
- Ta sama logika musi być używana wszędzie: zakładka Zawodnicy, zakładka Prognoza, Discord

---

## Zakładki dashboardu

1. **Liga CMF** – tabela sumaryczna + widok Duety
2. **Liga Hokejowa** – kombinowane standings z tygodniowym śledzeniem zmian
3. **Zawodnicy** – statystyki zawodników, klikalne (modal z właścicielami posortowanymi wg tabeli sumarycznej)
4. **Prognoza** – predykcje na następną kolejkę (predictor.py)
5. **Terminarz** – wszystkie kolejki sezonu
6. **Transfery** – historia transferów
7. **Trafność** – accuracy tracker
8. **Sezon** – league tracker sezonu
9. **FDR** – wskaźnik trudności rywala (ATK/DEF, skala 1-5)

---

## Uruchamianie lokalne

```bash
python scraper.py
```

Dashboard generuje się do `output/dashboard.html` i `docs/index.html`.
