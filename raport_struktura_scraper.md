# Raport: Struktura scraper.py – przygotowanie do podziału na moduły

**Plik:** `scraper.py` (6370 linii)  
**Data analizy:** 2026-06-18

---

## CZĘŚĆ 1: Inwentarz funkcji

Każda funkcja/klasa na poziomie modułu (niezagnieżdżona):

| # | Nazwa | Linie | Długość | Co robi |
|---|---|---|---|---|
| 1 | `normalize_team_name` | 41–46 | 6 | Normalizuje nazwę drużyny: lowercase + usuwa polskie diakrytyki |
| 2 | `_normalize_name` | 48–55 | 8 | Normalizuje imię i nazwisko (jak wyżej, zachowuje spację) |
| 3 | `cryptojs_aes_encrypt` | 58–80 | 23 | Szyfruje AES kompatybilnie z CryptoJS (EVP_BytesToKey, MD5) |
| 4 | `_request_with_retry` | 151–168 | 18 | HTTP z retry (exponential backoff: 1s, 2s, 4s) |
| 5 | `_load_external_cache` | 175–181 | 7 | Wczytuje `external_cache.json` |
| 6 | `_get_cached_external` | 183–196 | 14 | Zwraca dane z cache jeśli świeższe niż TTL (domyślnie 24h) |
| 7 | `_save_external_cache` | 198–207 | 10 | Zapisuje dane do cache, zachowując inne klucze |
| 8 | `login` | 210–367 | 158 | Loguje się do Fantasy Ekstraklasa przez wicket API + /connect + /login-sso |
| 9 | `get_session` | 370–379 | 10 | Tworzy sesję HTTP, loguje, zwraca gotową sesję (lub sys.exit) |
| 10 | `get_player_ids_from_stats_page` | 382–437 | 56 | Pobiera listę ID zawodników ze strony `/stats` (HTML) |
| 11 | `get_player_ids_by_scanning` | 440–476 | 37 | Skanuje ID zawodników (1–max), fallback gdy `/stats` nie działa |
| 12 | `get_user_team_slug` | 479–512 | 34 | Zwraca slug drużyny (env lub pierwszy z ranking-list) |
| 13 | `get_player_ids_from_transfers` | 515–658 | 144 | Pobiera zawodników z zakładki transferów (AJAX + HTML fallback) |
| 14 | `get_player_ids_from_ranking_squads` | 661–739 | 79 | Pobiera unikalnych zawodników przez scrape składów drużyn z rankingu |
| 15 | `parse_player_detail` | 742–881 | 140 | Parsuje HTML z `/stats-player/{id}`, wyciąga dane, statystyki, ceny |
| 16 | `fetch_player_detail` | 884–910 | 27 | Pobiera szczegóły zawodnika z API (thread-safe) |
| 17 | `fetch_all_players` | 913–946 | 34 | Pobiera dane wszystkich zawodników równolegle (ThreadPoolExecutor) |
| 18 | `filter_by_round` | 949–978 | 30 | Filtruje statystyki zawodników do konkretnej kolejki |
| 19 | `save_to_csv` | 981–1001 | 21 | Zapisuje dane do pliku CSV |
| 20 | `save_full_json` | 1004–1011 | 8 | Zapisuje pełne dane JSON (ze statystykami per kolejka) |
| 21 | `save_rounds_csv` | 1014–1047 | 34 | Zapisuje statystyki per kolejka jako CSV (jeden wiersz = zawodnik + kolejka) |
| 22 | `print_round_summary` | 1050–1092 | 43 | Wyświetla podsumowanie kolejki (top 10 punktujących, popularnych, droższych) |
| 23 | `_safe_int` | 1095–1100 | 6 | Bezpieczna konwersja string→int |
| 24 | `_safe_float` | 1103–1108 | 6 | Bezpieczna konwersja string→float |
| 25 | `scrape_stats_page` | 1115–1166 | 52 | Scrapuje stronę `/stats` (HTML per pozycja) jako alternatywa |
| 26 | `fetch_ranking_teams` | 1173–1214 | 42 | Pobiera listę drużyn z rankingu generalnego (POST /ranking-list) |
| 27 | `fetch_league_teams` | 1217–1255 | 39 | Pobiera drużyny z ligi prywatnej (POST /ranking-list + league) |
| 28 | `scrape_team_squad` | 1258–1369 | 112 | Scrapuje skład drużyny ze strony `/user-team/view/{slug}` (thread-safe) |
| 29 | `_process_team` | 1372–1392 | 21 | Worker: przetwarza jedną drużynę (skład + kapitan) |
| 30 | `scrape_teams_captains` | 1395–1506 | 112 | Scrapuje składy drużyn równolegle, z checkpointem i limitem czasu |
| 31 | `_compute_captain_stats` | 1509–1527 | 19 | Oblicza statystyki kapitanów (bez zapisu do CSV) |
| 32 | `_compute_squad_stats` | 1530–1560 | 31 | Oblicza statystyki ownership (bez zapisu do CSV) |
| 33 | `generate_captain_stats` | 1563–1578 | 16 | Generuje statystyki kapitanów i zapisuje do CSV |
| 34 | `generate_squad_stats` | 1581–1596 | 16 | Generuje statystyki ownership i zapisuje do CSV |
| 35 | `_fetch_prev_squad` | 1599–1611 | 13 | Worker: pobiera skład z poprzedniej kolejki (dla transferów) |
| 36 | `compute_league_transfers` | 1614–1728 | 115 | Oblicza transfery w lidze (K{n-1} → K{n}) |
| 37 | `_parse_90min_table` | 1777–1831 | 55 | Parsuje pojedynczą tabelę ligową z 90minut.pl |
| 38 | `_map_team_name` | 1834–1841 | 8 | Mapuje nazwę drużyny z 90minut.pl na lokalną z terminarz.txt |
| 39 | `_find_standings_tables` | 1844–1857 | 14 | Znajduje tabele z klasyfikacją na stronie 90minut.pl |
| 40 | `fetch_ekstraklasa_table` | 1860–1922 | 63 | Scrapuje tabelę Ekstraklasy z 90minut.pl (bramki ogółem + dom/wyjazd) |
| 41 | `fetch_extra_player_stats` | 1950–2098 | 149 | Pobiera rozszerzone statystyki (xG, strzały, podania) z API ekstraklasy |
| 42 | `compute_player_stats_per90` | 2101–2215 | 115 | Przelicza statystyki na wartość per 90 minut + dopasowuje do zawodników |
| 43 | `compute_fdr` | 2218–2436 | 219 | Oblicza wskaźniki ATK/DEF rywala (1-5) dla każdego meczu |
| 44 | `_normalize_team` | 2445–2447 | 3 | Normalizuje nazwę drużyny (strip, NFKD, lower) – inna niż `normalize_team_name` |
| 45 | `parse_terminarz` | 2449–2534 | 86 | Parsuje `terminarz.txt` i zwraca dane do fixture ticker |
| 46 | `generate_dashboard_html` | 2535–5463 | 2929 | Generuje interaktywny dashboard HTML (CSS + JS inline) – **OGROMNA funkcja** |
| 47 | `cleanup_old_output_files` | 5470–5503 | 34 | Usuwa stare pliki z output/, zachowując N najnowszych |
| 48 | `main` | 5509–6370 | 862 | Główna orkiestracja całego pipeline'u |

**Sumarycznie:** 48 funkcji, ~6370 linii

---

## CZĘŚĆ 2: Naturalne grupy

### Grupa A: Uwierzytelnianie / Sesja (Auth)
- Funkcje: `cryptojs_aes_encrypt`, `login`, `get_session`
- Łącznie: ~191 linii
- Odpowiedzialność: Logowanie do Fantasy Ekstraklasa, zarządzanie sesją HTTP, szyfrowanie AES

### Grupa B: Sieć / Cache (Network)
- Funkcje: `_request_with_retry`, `_load_external_cache`, `_get_cached_external`, `_save_external_cache`
- Łącznie: ~49 linii
- Odpowiedzialność: HTTP z retry, cache zewnętrznych statystyk (90minut.pl + ekstraklasa.org API)

### Grupa C: Narzędzia / Normalizacja (Utils)
- Funkcje: `normalize_team_name`, `_normalize_name`, `_safe_int`, `_safe_float`, `_normalize_team`
- Łącznie: ~29 linii
- Odpowiedzialność: Normalizacja nazw (diakrytyki), bezpieczne konwersje typów

### Grupa D: Scraping zawodników (Player Scraping)
- Funkcje: `get_player_ids_from_stats_page`, `get_player_ids_by_scanning`, `get_player_ids_from_transfers`, `get_player_ids_from_ranking_squads`, `parse_player_detail`, `fetch_player_detail`, `fetch_all_players`, `scrape_stats_page`, `filter_by_round`
- Łącznie: ~599 linii
- Odpowiedzialność: Pozyskiwanie listy ID zawodników i szczegółowych danych

### Grupa E: Zapis danych (Data Output)
- Funkcje: `save_to_csv`, `save_full_json`, `save_rounds_csv`, `print_round_summary`
- Łącznie: ~106 linii
- Odpowiedzialność: Zapis danych do CSV/JSON, podsumowania tekstowe

### Grupa F: Drużyny i kapitanowie (Team Scraping + Stats)
- Funkcje: `get_user_team_slug`, `fetch_ranking_teams`, `fetch_league_teams`, `scrape_team_squad`, `_process_team`, `scrape_teams_captains`, `_compute_captain_stats`, `_compute_squad_stats`, `generate_captain_stats`, `generate_squad_stats`, `_fetch_prev_squad`, `compute_league_transfers`
- Łącznie: ~638 linii
- Odpowiedzialność: Rankingi drużyn, scrapowanie składów, statystyki kapitanów/ownership, transfery ligowe

### Grupa G: Statystyki zewnętrzne (External Stats)
- Funkcje: `_parse_90min_table`, `_map_team_name`, `_find_standings_tables`, `fetch_ekstraklasa_table`, `fetch_extra_player_stats`, `compute_player_stats_per90`
- Łącznie: ~404 linii
- Odpowiedzialność: Pobieranie i przetwarzanie statystyk z 90minut.pl (bramki) i ekstraklasa.org (xG, strzały)

### Grupa H: FDR i terminarz (FDR / Fixtures)
- Funkcje: `compute_fdr`, `parse_terminarz`
- Łącznie: ~308 linii
- Odpowiedzialność: Fixture Difficulty Rating (ATK/DEF rywala 1-5), parsowanie terminarza

### Grupa I: Dashboard HTML (Dashboard)
- Funkcje: `generate_dashboard_html`
- Łącznie: ~2929 linii (45.9% pliku!)
- Odpowiedzialność: Generowanie kompletnego dashboardu HTML z inline CSS i JavaScript

### Grupa J: Orkiestracja / Czyszczenie (Main + Cleanup)
- Funkcje: `cleanup_old_output_files`, `main`
- Łącznie: ~896 linii
- Odpowiedzialność: Główna pętla pipeline'u, czyszczenie starych plików

---

## CZĘŚĆ 3: Globalny stan modułu

### Stałe niezmienne (CONST)

| Nazwa | Linie | Typ | Opis | Czytane przez |
|---|---|---|---|---|
| `BASE_URL` | 125 | str | URL bazowy Fantasy Ekstraklasa | login, get_player_ids_from_stats_page, get_player_ids_by_scanning, get_player_ids_from_transfers, get_player_ids_from_ranking_squads, fetch_player_detail, scrape_stats_page, fetch_ranking_teams, fetch_league_teams, scrape_team_squad |
| `LOGIN_API_URL` | 126 | str | Endpoint wicket API logowania | login |
| `TOKEN_CREATE_URL` | 127 | str | Endpoint tworzenia tokenu connect | login |
| `LOGIN_SSO_URL` | 128 | str | Endpoint SSO logowania | login |
| `APPLICATION_ID` | 129 | str | ID aplikacji fantasy | login |
| `HEADERS` | 131–138 | dict | Nagłówki HTTP dla zapytań AJAX | login, get_player_ids_from_transfers, fetch_player_detail, get_player_ids_from_ranking_squads |
| `BROWSER_HEADERS` | 141–145 | dict | Nagłówki przeglądarki (czyste, bez X-Requested-With) | get_player_ids_from_transfers, scrape_stats_page, scrape_team_squad |
| `RANKING_HEADERS` | 148 | dict | Nagłówki do endpointów AJAX POST | get_user_team_slug, get_player_ids_from_ranking_squads, fetch_ranking_teams, fetch_league_teams |
| `OUTPUT_DIR` | 121 | str | Katalog wyjściowy ("output") | cache functions, main, cleanup_old_output_files, generate_dashboard_html (pośrednio przez filename) |
| `SCRIPT_START` | 118 | float | Timestamp startu skryptu | scrape_teams_captains |
| `TEAM_ABBREVS` | 1735–1743 | dict | Mapowanie nazw drużyn na skróty | parse_terminarz |
| `NINETYM_TEAM_MAP` | 1746–1771 | dict | Mapowanie nazw z 90minut.pl → lokalne | _map_team_name |
| `NINETYM_LIGA_ID` | 1774 | str | ID ligi na 90minut.pl | fetch_ekstraklasa_table |
| `EXTRA_STATS_API` | 1932 | str | URL API statystyk ekstraklasy | fetch_extra_player_stats |
| `EXTRA_STATS_PARAMS` | 1935–1943 | dict | Parametry filtrów API | fetch_extra_player_stats |
| `MONTHS_PL` | 2439–2443 | dict | Nazwy miesięcy po polsku → numery | parse_terminarz |

### Konfiguracja ze środowiska (NIEZMIENNA po załadowaniu modułu)

| Nazwa | Linie | Typ | Opis |
|---|---|---|---|
| `FANTASY_EMAIL` | 88 | str | Login do Fantasy (z env) |
| `FANTASY_PASSWORD` | 89 | str | Hasło (z env) |
| `TARGET_ROUND` | 92 | int/None | Docelowa kolejka (z env) |
| `MAX_PLAYER_ID` | 95 | int | Maksymalne ID zawodnika (domyślnie 4000) |
| `TEAMS_TO_SCRAPE` | 98 | int | Ile drużyn z rankingu scrapować (domyślnie 1000) |
| `LEAGUE_SLUG` | 101 | str | Slug ligi prywatnej |
| `LEAGUE_ID` | 103 | str | ID ligi prywatnej |
| `USER_TEAM_SLUG` | 106 | str | Slug drużyny użytkownika |
| `REQUEST_DELAY` | 109 | float | Opóźnienie między requestami (0.3s) |
| `WORKERS` | 112 | int | Liczba workerów ThreadPoolExecutor |
| `MAX_RUNTIME_MINUTES` | 115 | int | Maksymalny czas pracy (300 min) |
| `EXTRA_API_TOKEN` | 1947 | str | Token API ekstraklasy (z env) |

### Stan mutowalny

| Nazwa | Linia | Typ | ZAPISUJE | CZYTA |
|---|---|---|---|---|
| `SCRIPT_START` | 118 | float | main (raz przy starcie) | scrape_teams_captains |

**Wniosek:** Praktycznie **brak mutowalnego stanu globalnego**. Jedyny element – `SCRIPT_START` – jest ustawiany raz w `main()` i tylko odczytywany w `scrape_teams_captains()`. To znacząco upraszcza podział.

---

## CZĘŚĆ 4: main() – szkielet orkiestracji

`main()` (linie 5509–6370, ~862 linie)

| Krok | Linie | Co robi |
|---|---|---|
| 0 | 5509–5515 | Inicjalizacja: timestamp, OUTPUT_DIR, nagłówek |
| 1 | 5519 | `session = get_session()` – autoryzacja |
| 2a | 5524 | `ranking_players = get_player_ids_from_ranking_squads(session, 150)` |
| 2b | 5534–5537 | Fallback: `player_ids = get_player_ids_by_scanning(session, MAX_PLAYER_ID)` |
| 3 | 5551 | `players = fetch_all_players(session, unique_ids)` – szczegóły wszystkich graczy |
| 4a | 5561 | `save_full_json(players, json_file)` |
| 4b | 5565–5616 | Oblicza `current_round`, buduje `summary_data`, zapisuje CSV |
| 4c | 5619 | `save_rounds_csv(players, rounds_file)` |
| 4d | 5623 | `print_round_summary(players, current_round)` |
| 5a | 5631 | `fetch_ranking_teams(session, TEAMS_TO_SCRAPE)` → `ranking_teams` |
| 5b | 5635 | `scrape_teams_captains(session, ranking_teams)` → `team_results` |
| 5c | 5643–5648 | `generate_captain_stats()` + `generate_squad_stats()` |
| 5d | 5651–5667 | Buduje `tiers` (top10, top100, all) |
| 6a | 5675 | `fetch_league_teams(session, LEAGUE_SLUG, LEAGUE_ID)` → `league_teams` |
| 6b | 5679 | `scrape_teams_captains(session, league_teams)` → `league_results` |
| 6c | 5687–5691 | `generate_captain_stats()` + `generate_squad_stats()` dla ligi |
| 7 | 5693–5765 | Buduje `league_rosters`, `league_teams_detail`, `player_lookup` |
| 8 | 5769 | `save_round_standings()` (z league_tracker) |
| 9 | 5773 | `parse_terminarz("terminarz.txt")` → `fixtures_data` |
| 10 | 5778 | `fetch_ekstraklasa_table()` → `ekstra_stats` |
| 11 | 5782 | `fetch_extra_player_stats()` → `extra_player_stats` |
| 12 | 5793 | `compute_player_stats_per90()` → wzbogaca `players` |
| 13 | 5797–5801 | `compute_fdr(ekstra_stats, fixtures_data)` → `fdr_data` |
| 14 | 5803–5904 | Buduje `predictions_data` przez `predict_all_players()` (z predictor.py) |
| 15 | 5908–5917 | `evaluate_predictions()` + `load_accuracy_history()` |
| 16 | 5921–5925 | `run_tuning()` (z tuner.py) |
| 17 | 5928–5935 | `compute_league_transfers()` → `transfers_data` |
| 18 | 5937–6047 | **Liga Hokejowa**: wzbogaca `league_teams_detail` o jesienne punkty, ranking łączny, zapisuje `hockey_prev_ranking.json` |
| 19 | 6049–6121 | **Duety**: wczytuje `duets.json`, oblicza punkty duetów, ranking zmian |
| 20 | 6124–6141 | Wczytuje `tuned_params.json` i `league_history.json` |
| 21 | 6156–6178 | `generate_dashboard_html(...)` – generuje dashboard |
| 22 | 6187–6347 | **Discord**: importuje z `discord_notify.py`, wysyła powiadomienia (captains summary, pre-round, expert predictions, post-round + newsletter) |
| 23 | 6350 | `cleanup_old_output_files()` |
| 24 | 6352–6366 | Podsumowanie końcowe |

---

## CZĘŚĆ 5: Zależności między grupami

Bezpośrednie wywołania funkcji z jednej grupy przez funkcje z innej grupy (z pominięciem `main()`):

### Grupa A ← (nikt nie woła A bezpośrednio, tylko main → get_session)
- `get_session()` → `login()` (wewnątrz grupy A)
- `login()` → `cryptojs_aes_encrypt()` (wewnątrz grupy A)

### Grupa D → Grupa F
- `get_player_ids_from_ranking_squads()` → `scrape_team_squad()` (linia 706)
- `get_player_ids_from_transfers()` używa `BROWSER_HEADERS`, `HEADERS` (stałe globalne)
- `fetch_player_detail()` → `_request_with_retry()` (Grupa B)
- `parse_player_detail()` używa `_safe_int`, `_safe_float` (Grupa C)

### Grupa F (wewnętrzne)
- `scrape_teams_captains()` → `_process_team()` → `scrape_team_squad()`
- `compute_league_transfers()` → `_fetch_prev_squad()` → `scrape_team_squad()`
- `generate_captain_stats()` → `_compute_captain_stats()` → `save_to_csv()` (Grupa E)
- `generate_squad_stats()` → `_compute_squad_stats()` → `save_to_csv()` (Grupa E)
- `scrape_team_squad()` → `_request_with_retry()` (Grupa B)

### Grupa G → Grupa B
- `fetch_ekstraklasa_table()` → `_get_cached_external()`, `_save_external_cache()`, `_request_with_retry()`
- `fetch_extra_player_stats()` → `_get_cached_external()`, `_save_external_cache()`

### Grupa G → Grupa C
- `compute_player_stats_per90()` → `_normalize_name()`

### Grupa G → Grupa G (wewnętrzne)
- `fetch_ekstraklasa_table()` → `_find_standings_tables()` → `_parse_90min_table()`
- `fetch_ekstraklasa_table()` → `_map_team_name()`

### Grupa H → (stałe globalne)
- `parse_terminarz()` → `TEAM_ABBREVS`, `MONTHS_PL` (stałe)
- `compute_fdr()` nie woła niczego z innych grup – tylko operuje na danych wejściowych

### Grupa I (Dashboard) → **CAŁKOWICIE IZOLOWANA**
- `generate_dashboard_html()` **nie woła ŻADNEJ innej funkcji z modułu**. Przyjmuje wszystkie dane jako parametry. To czysta funkcja transformująca dane → HTML.

### Grupa J → Wszystkie grupy
- `main()` woła funkcje ze wszystkich grup (to jest orkiestrator)

### Podsumowanie zależności międzygrupowych:

```
Grupa A: izolowana (tylko main → A)
Grupa B: używana przez D, F, G (cache + HTTP retry)
Grupa C: używana przez D, G (normalizacje)
Grupa D → F (przez get_player_ids_from_ranking_squads → scrape_team_squad)
Grupa E: używana przez F (zapis CSV)
Grupa F: duża, wewnętrznie spójna, używa B, C, E
Grupa G: używa B, C, G(wewnętrzne)
Grupa H: używa stałych globalnych (TEAM_ABBREVS, MONTHS_PL)
Grupa I: **całkowicie izolowana** – zero zależności od innych grup
Grupa J: orkiestruje wszystko (ale sama nie jest wołana przez nikogo)
```

**Kluczowy wniosek:** `generate_dashboard_html()` (Grupa I, 2929 linii) jest **całkowicie odseparowana** – nie importuje, nie woła żadnych funkcji ze scrapera. To idealny kandydat do wydzielenia jako pierwszy.

---

## CZĘŚĆ 6: Zależności zewnętrzne

### Kto importuje z `scraper.py`?

Tylko **jeden** plik:

```
generate_from_cache.py:14: from scraper import generate_dashboard_html
```

Żaden inny plik w projekcie nie importuje niczego z `scraper.py`.

### Co scraper.py importuje z innych plików projektu?

```python
from predictor import predict_all_players                               # linia 33
from accuracy import evaluate_predictions, find_latest_predictions_csv, load_accuracy_history  # linia 34
from tuner import run_tuning                                            # linia 35
from league_tracker import save_round_standings                         # linia 5769 (w main)
from discord_notify import send_pre_round, send_post_round, ...          # linia 6187 (w main)
from newsletter import generate_newsletter                              # linia 6320 (w main)
```

**Wniosek:** `generate_dashboard_html` musi pozostać dostępne jako `from scraper import generate_dashboard_html` (lub przekierowane przez nowy moduł), chyba że zmienimy też `generate_from_cache.py`.

---

## CZĘŚĆ 7: Ocena ryzyka i rekomendacja

### 7.1 Proponowany podział na pliki

Na podstawie analizy zależności i naturalnych granic:

| Plik | Zawartość (grupy/funkcje) | Łącznie linii | Ryzyko |
|---|---|---|---|
| `config.py` | Wszystkie stałe (HEADERS, BROWSER_HEADERS, RANKING_HEADERS, URL-e, TEAM_ABBREVS, NINETYM_TEAM_MAP, NINETYM_LIGA_ID, EXTRA_STATS_API, EXTRA_STATS_PARAMS, MONTHS_PL) + zmienne konfiguracyjne ze środowiska (FANTASY_EMAIL, …, WORKERS, OUTPUT_DIR, SCRIPT_START) | ~120 | **NISKIE** |
| `auth.py` | Grupa A: `cryptojs_aes_encrypt`, `login`, `get_session` (+ importy Crypto) | ~191 | **NISKIE** |
| `network.py` | Grupa B: `_request_with_retry`, `_load_external_cache`, `_get_cached_external`, `_save_external_cache` | ~49 | **NISKIE** |
| `utils.py` | Grupa C: `normalize_team_name`, `_normalize_name`, `_safe_int`, `_safe_float`, `_normalize_team` | ~29 | **NISKIE** |
| `players.py` | Grupa D: 9 funkcji scrapingu zawodników + Grupa E: 4 funkcje zapisu danych | ~705 | **ŚREDNIE** (zależność od `scrape_team_squad` w F) |
| `teams.py` | Grupa F: 12 funkcji (drużyny, kapitanowie, ownership, transfery) | ~638 | **ŚREDNIE** (używa utils, network, config) |
| `external_stats.py` | Grupa G: 6 funkcji (90minut.pl + ekstraklasa.org API + compute_player_stats_per90) | ~404 | **NISKIE** |
| `fdr.py` | Grupa H: `compute_fdr`, `parse_terminarz` | ~308 | **NISKIE** |
| `dashboard.py` | Grupa I: `generate_dashboard_html` | ~2929 | **NISKIE** (całkowicie izolowana!) |
| `scraper.py` | Grupa J: `main()` + `cleanup_old_output_files()` + importy z nowych modułów | ~900 | **WYSOKIE** (na końcu – zostaje jako orkiestrator) |

### 7.2 Ocena ryzyka per plik

**`config.py` – NISKIE**
- Same stałe. Brak logiki. Żadnych zależności od innych modułów poza `os.environ`.
- Zmiana: wszystkie moduły importują z `config` zamiast ze `scraper`.

**`auth.py` – NISKIE**
- Wyizolowana logika logowania. Tylko `login()` i `get_session()`. Nie zależy od niczego poza `config` i `cryptojs_aes_encrypt` (wewnątrz).
- Używa `_request_with_retry`? Sprawdźmy… Nie, `login()` używa `session.post()` bezpośrednio (z własnym timeout/obsługą błędów).
- Wniosek: brak zależności od `network.py`.

**`network.py` – NISKIE**
- Proste funkcje cache + retry. Zależą tylko od `config.OUTPUT_DIR` i `datetime`.

**`utils.py` – NISKIE**
- Czyste funkcje bezstanowe. Zero zależności poza `unicodedata` i `re`.

**`players.py` – ŚREDNIE**
- **Problem:** `get_player_ids_from_ranking_squads()` woła `scrape_team_squad()` (z teams.py). To jedyne międzygrupowe bezpośrednie wywołanie.
- Rozwiązanie: albo przenieść `scrape_team_squad` do wspólnego modułu (np. `squad_scraper.py`), albo przekazać ją jako zależność (dependency injection), albo zaakceptować cykliczny import (Python sobie poradzi jeśli import jest na poziomie funkcji, nie modułu).
- Używa `config.HEADERS`, `config.WORKERS`, `config.REQUEST_DELAY`, `config.BROWSER_HEADERS`.

**`teams.py` – ŚREDNIE**
- Największa grupa po dashboard. Sporo funkcji, ale spójna wewnętrznie.
- Zależności: `utils._safe_int`, `network._request_with_retry`, `config.*`.
- Eksportuje: `scrape_team_squad` (używane przez `players.py`).
- **Uwaga:** Niektóre funkcje (generate_captain_stats, generate_squad_stats) wołają `save_to_csv` z `players.py` (Grupa E). Proponuję przenieść zapis CSV do `utils.py` lub zostawić w `players.py` i importować.

**`external_stats.py` – NISKIE**
- Używa `network._get_cached_external`, `network._save_external_cache`, `network._request_with_retry`.
- Używa `utils._normalize_name`.
- Używa stałych `NINETYM_TEAM_MAP`, `NINETYM_LIGA_ID`, `TEAM_ABBREVS` z config.
- Ładnie odizolowane.

**`fdr.py` – NISKIE**
- `compute_fdr` nie woła nic z innych grup (tylko operuje na dict).
- `parse_terminarz` używa stałych `TEAM_ABBREVS`, `MONTHS_PL` z config.
- `compute_fdr` używa `_round_is_past` (lokalna funkcja zagnieżdżona, nie problem).
- Bardzo czysta granica.

**`dashboard.py` – NISKIE**
- **Idealny kandydat na pierwszy ruch.** 2929 linii, zero zależności od innych funkcji scrapera.
- Jedyny external import: `generate_from_cache.py` → `from scraper import generate_dashboard_html`.
- Po wydzieleniu: `from dashboard import generate_dashboard_html` i w `scraper.py`: `from dashboard import generate_dashboard_html`. `generate_from_cache.py` trzeba zaktualizować.
- Używa `glob.glob` do sprawdzenia archiwum – to nie zależy od innych funkcji.

**`scraper.py` (pozostałość) – WYSOKIE (ale tylko dlatego, że robione na końcu)**
- `main()` zostaje jako orkiestrator, importujący ze wszystkich nowych modułów.
- Po wydzieleniu wszystkiego innego, `main()` będzie importować ~10 modułów zamiast mieć wszystko w jednym pliku.
- Ryzyko nie wynika z zależności, tylko z faktu że to ostatni krok – wszystko musi działać przed nim.

### 7.3 Bezpieczna kolejność wydzielania

**(od najbardziej izolowanego do najbardziej wplecionego):**

1. **`utils.py`** – 29 linii, zero zależności, wszyscy będą go importować. Najmniejsze ryzyko.
2. **`config.py`** – 120 linii, same stałe. Po wydzieleniu zmieniamy importy we wszystkich funkcjach.
3. **`network.py`** – 49 linii, zależne tylko od `config` i `datetime`.
4. **`auth.py`** – 191 linii, zależne tylko od `config`.
5. **`external_stats.py`** – 404 linii, zależne od `config`, `network`, `utils`.
6. **`fdr.py`** – 308 linii, zależne od `config`.
7. **`dashboard.py`** – 2929 linii, **całkowicie izolowana**. Największy zysk (~46% pliku). Zaktualizować `generate_from_cache.py`.
8. **`squad_scraper.py`** (opcjonalnie) – wydzielenie `scrape_team_squad` jako wspólnej zależności dla `teams.py` i `players.py`.
9. **`teams.py`** – 638 linii, zależne od `config`, `network`, `utils`, `players.save_to_csv`. Używa `squad_scraper.scrape_team_squad`.
10. **`players.py`** – 705 linii, zależne od `config`, `network`, `utils`, `squad_scraper.scrape_team_squad`.
11. **`scraper.py`** (pozostałość) – `main()` + `cleanup_old_output_files()`. Importuje ze wszystkich powyższych.

### 7.4 Czego NIE rekomenduję przenosić teraz

1. **`main()`** – zostawić w `scraper.py` jako orkiestrator. Próba podziału `main()` na mniejsze funkcje na tym etapie wprowadziłaby dodatkowe ryzyko. 862 linie to dużo, ale to *jeden* przepływ, który można czytać sekwencyjnie. Podział na "krok 1-5 w jednym pliku, krok 6-10 w drugim" zaciemniłby flow.

2. **`generate_dashboard_html()` wewnętrzny podział** – 2929 linii to jeden wielki f-string generujący HTML+CSS+JS. Można to podzielić na mniejsze funkcje pomocnicze (`_generate_css()`, `_generate_js()`, `_generate_players_tab()`, …), ale:
   - To jest **jedna funkcja**, która działa i jest testowana w całości.
   - Podział wewnętrzny może poczekać na osobną sesję.
   - Na razie wystarczy przenieść całą funkcję do `dashboard.py`.

3. **Konfiguracja `SCRIPT_START`** – to jedyny mutowalny stan. Jest ustawiany w `main()` i czytany w `scrape_teams_captains()`. To nie jest problem przy podziale – `config.SCRIPT_START` będzie dostępny dla obu modułów.

4. **Zagnieżdżone funkcje wewnątrz `parse_player_detail`, `scrape_team_squad`, `compute_league_transfers`, `compute_fdr`** – są to lokalne helpery, nie wymagają wydzielania. Zostają w swoich funkcjach nadrzędnych.

### 7.5 Dodatkowe uwagi

- **Import `from Crypto.Cipher import AES`** jest używany tylko w `cryptojs_aes_encrypt()` (auth.py). Po przeniesieniu, import Crypto będzie tylko w `auth.py`.
- **Import `from bs4 import BeautifulSoup`** jest używany w `parse_player_detail`, `scrape_stats_page`, `scrape_team_squad`, `_parse_90min_table`, `_find_standings_tables` – czyli w `players.py`, `teams.py`, `external_stats.py`. Każdy z nich będzie potrzebował własnego importu.
- **Import `from predictor import predict_all_players`** – używany tylko w `main()`. Zostaje w `scraper.py`.
- **Import `from accuracy import ...`** – używany tylko w `main()`. Zostaje.
- **Import `from tuner import run_tuning`** – używany tylko w `main()`. Zostaje.
- **Import `from league_tracker import save_round_standings`** – używany tylko w `main()`. Zostaje.
- **Import `from discord_notify import ...`** – używany tylko w `main()`. Zostaje.
- **Import `from newsletter import generate_newsletter`** – używany tylko w `main()`. Zostaje.

To potwierdza, że `main()` jest czystym orkiestratorem – wszystkie "ciężkie" importy (predictor, discord_notify, newsletter) są używane tylko tam.

---

*Koniec raportu.*
