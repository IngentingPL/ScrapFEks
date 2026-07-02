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
│   ├── archive.yml             # Archiwizacja sezonu (workflow_dispatch)
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
├── config.py                   # Globalne stałe: URL-e, nagłówki, zmienne środowiskowe
├── auth.py                     # Logowanie do fantasy.ekstraklasa.org (AES + SSO)
├── network.py                  # Warstwa HTTP: retry, cache 24h dla zewnętrznych statystyk
├── utils.py                    # Normalizacja nazw, bezpieczne konwersje typów
├── dashboard.py                # Generowanie HTML dashboardu (~2900 linii)
├── export.py                   # Zapis CSV/JSON, filtrowanie po kolejce
├── generate_from_cache.py      # Regeneruje dashboard z istniejącego JSON, bez nowego scrapowania
├── archive.py                  # Archiwizacja sezonu do docs/archive/
├── predictor.py                # Logika prognoz zawodników
├── players.py                  # Pobieranie i parsowanie danych zawodników
├── squads.py                   # Scrapowanie składów drużyn, statystyki kapitanów/ownership
├── external_stats.py           # Zewnętrzne statystyki: 90minut.pl i API ekstraklasa.org
├── fdr.py                      # Obliczenia FDR (Fixture Difficulty Rating)
├── transfers.py                # Transfery ligowe, statystyki per 90 minut
├── schedule.py                 # Parsowanie terminarz.txt, czyszczenie starych plików
├── tuner.py                    # Optymalizacja parametrów predykcji
├── accuracy.py                 # Śledzenie trafności prognoz
├── ai_client.py                 # Wspólny klient AI (DeepSeek + Gemini) – używany przez discord_notify.py i newsletter.py
├── discord_notify.py           # Wysyłanie powiadomień Discord + eksperci Rabbti i Tlinf
├── newsletter.py               # Newsletter przez DeepSeek (fallback: Gemini)
├── analytics.py                # Wspólne funkcje analityczne (hidden gem, disappointment, kapitanowie)
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
7. **Nagłówki HTTP do fantasy.ekstraklasa.org** – używaj istniejących stałych `HEADERS` / `BROWSER_HEADERS` / `RANKING_HEADERS` w scraper.py, nie twórz nowych słowników nagłówków od zera

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

### Eksperci AI:
- **⚽ Rabbti** – doświadczony analityk Ekstraklasy, rzetelny, pracuje na danych
- **🛋️ Tlinf** – zwykły kibic, kontrowersyjny, podważa konsensus

Każda wiadomość Discord max **2000 znaków** (limit webhooków). Wiadomości ekspertów są wysyłane jako zwykły tekst (nie embed), jako osobne webhook calle.

---

## AI: DeepSeek (główny) + Gemini (fallback)

- **DeepSeek** (`deepseek-chat`) – główny model, próbowany pierwszy
- **Gemini** (`gemini-2.5-flash`) – fallback, używany tylko gdy DeepSeek zawiedzie (błąd HTTP, timeout, brak klucza)
- Wspólna logika wywołań HTTP do obu API żyje w `ai_client.py` (funkcje `call_deepseek()`, `call_gemini()`) – używana przez `newsletter.py` i `discord_notify.py`
- Logika fallbacku (kolejność prób, retry, parsowanie wyniku) jest osobna w każdym pliku – `newsletter.py` ma `call_ai()`, `discord_notify.py` ma `_call_ai_expert()` (z retry + exponential backoff dla ekspertów)
- Klucze API: `DEEPSEEK_API_KEY` (główny), `GEMINI_API_KEY` (fallback)
- Używany w: `newsletter.py` (newsletter), `discord_notify.py` (eksperci Rabbti i Tlinf)

**Jeśli zmieniasz coś w wywołaniu API (URL, nagłówki, timeout)** – zmień w `ai_client.py`, nie twórz nowej kopii w `newsletter.py` albo `discord_notify.py`.

---

## GitHub Secrets

| Secret | Do czego |
|---|---|
| `FANTASY_EMAIL` | Login do fantasy.ekstraklasa.org |
| `FANTASY_PASSWORD` | Hasło do fantasy.ekstraklasa.org |
| `DEEPSEEK_API_KEY` | DeepSeek API – główny model AI (newsletter + eksperci Discord) |
| `GEMINI_API_KEY` | Gemini API – fallback, używany tylko gdy DeepSeek zawiedzie |
| `DISCORD_WEBHOOK_URL` | Webhook Discord |
| `EXTRAKLASA_API_TOKEN` | Rozszerzone statystyki zawodników (xG, strzały) z API ekstraklasa.org |
| `WORKFLOW_PAT` | Personal Access Token – wymagany TYLKO przez `update_schedule.yml`. Ten workflow edytuje plik `.github/workflows/scrape.yml`, a domyślny `GITHUB_TOKEN` nie ma uprawnień do modyfikacji plików w `.github/workflows/` (twarde ograniczenie GitHuba). `scrape.yml` i `archive.yml` NIE potrzebują tego sekretu. |

---

## Cache zewnętrznych statystyk (24h)

`output/external_cache.json` cache'uje dwa źródła zewnętrzne na 24h, żeby nie odpytywać ich przy każdym uruchomieniu (workflow odpala się kilka razy w dzień meczowy):
- Tabela z **90minut.pl** (bramki strzelone/stracone)
- Extra statystyki z API ekstraklasa.org (xG, strzały, podania kluczowe)

Jeśli dane wydają się nieaktualne po meczu – to oczekiwane, cache odświeży się automatycznie po 24h. Plik jest commitowany do repo (przetrwa między uruchomieniami workflow).

## Trafność prognoz (accuracy.py)

`accuracy_history.json` śledzi trafność prognoz kolejka po kolejce i zasila auto-tuning parametrów (tuner.py). Wymaga **4+ kolejek danych**, zanim auto-tuning zacznie działać.

Zawiera guard: jeśli plik prognoz (`fantasy_predictions_*.csv`) dotyczy innej kolejki niż ta którą sprawdzamy, porównanie jest pomijane z jasnym komunikatem w logach – zamiast cichego "0 dopasowań".

---

## Inne nazwane stałe (sesja optymalizacyjna)

| Stała | Plik | Wartość | Co kontroluje |
|---|---|---|---|
| `FDR_NEUTRAL` | predictor.py | 3 | Środek skali FDR (1-5), neutralny fallback |
| `AI_TEMPERATURE` | ai_client.py | 0.7 | Temperatura modeli DeepSeek/Gemini |
| `AI_MAX_RETRIES` | discord_notify.py | 3 | Liczba prób wywołań AI dla ekspertów |
| `DISCORD_CONTENT_MAX_LEN` | discord_notify.py | 1900 | Limit znaków na część wiadomości (margines pod limitem Discorda 2000) |
| `ERROR_PREVIEW_LEN` | ai_client.py | 300 | Ile znaków błędu HTTP pokazać w logach |

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
10. **Archiwum** – linki do zarchiwizowanych sezonów (`docs/archive/`); wyszarzona jeśli nie ma jeszcze żadnego zarchiwizowanego sezonu

---

## Uruchamianie lokalne

```bash
python scraper.py
```

Dashboard generuje się do `output/dashboard.html` i `docs/index.html`.

---

## Archiwizacja sezonu

Archiwizacja została przeniesiona do osobnego pliku `archive.py` i workflow `archive.yml`.

### Uruchamianie lokalne

```bash
python archive.py 2025-26
python archive.py "2025-26 Wiosna"
```

Lub przez zmienną środowiskową:

```bash
SEASON_NAME=2025-26 python archive.py
```

### Uruchamianie przez GitHub Actions

1. Przejdź do zakładki **Actions**
2. Wybierz workflow **Archive Season**
3. Kliknij **Run workflow**
4. Wpisz nazwę sezonu (np. `2025-26` lub `2025-26 Wiosna`)
5. Kliknij **Run workflow**

Archiwizacja:
- Generuje plik HTML `docs/archive/sezon-{SEASON}.html`
- Kopiuje dane do `docs/archive/`:
  - `autumn_points_{SEASON}.json`
  - `league_history_{SEASON}.json`
  - `duets_{SEASON}.json`
  - `players_{SEASON}.json`
- Aktualizuje index archiwum `docs/archive/index.html`
