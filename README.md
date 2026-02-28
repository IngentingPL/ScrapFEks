# ⚽ Fantasy Ekstraklasa Stats

Scraper i interaktywny dashboard dla [fantasy.ekstraklasa.org](https://fantasy.ekstraklasa.org/) — statystyki zawodników, ownership drużyn z rankingu, analiza ligi prywatnej.

Uruchamiany automatycznie przez **GitHub Actions** po każdym meczu, z publikacją dashboardu na GitHub Pages.

## 🚀 Szybki start

### 1. Fork repozytorium

Skopiuj pliki do nowego repozytorium na GitHubie.

### 2. Dodaj dane logowania do GitHub Secrets

**Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

- `FANTASY_EMAIL` — email konta na fantasy.ekstraklasa.org
- `FANTASY_PASSWORD` — hasło do tego konta

### 3. Włącz GitHub Pages (dashboard online)

**Settings** → **Pages** → Source: **Deploy from a branch** → Branch: `main`, folder: `/docs`

Dashboard będzie dostępny pod adresem `https://<user>.github.io/<repo>/`.

### 4. Uruchom scraper

**Actions** → **Fantasy Ekstraklasa Scraper** → **Run workflow**

Parametry (wszystkie opcjonalne):

| Parametr | Domyślnie | Opis |
|---|---|---|
| `max_players` | 4000 | Maksymalna liczba zawodników do pobrania |
| `teams_to_scrape` | 1000 | Ile drużyn z rankingu scrapować (ownership/kapitanowie) |
| `league_slug` | `discord-fmforumcmf` | Slug ligi prywatnej (pusty = pomiń) |
| `league_id` | `304` | ID ligi (z Network tab w przeglądarce) |
| `target_round` | *(ostatnia)* | Numer kolejki do analizy |
| `workers` | 10 | Liczba równoległych workerów do scrapowania drużyn |
| `max_runtime` | 300 | Maksymalny czas pracy w minutach |

## 📊 Dashboard

Interaktywny dashboard HTML z ciemnym motywem, generowany automatycznie po każdym uruchomieniu.

### Zakładki

**👑 Kapitanowie** — ranking najpopularniejszych kapitanów z paskami popularności. Kliknięcie na zawodnika rozwija panel z drużynami ligowymi.

**⚽ Zawodnicy** — pełna tabela ze statystykami, formą i ownership:

| Kolumna | Opis |
|---|---|
| Punkty | Łączne punkty w sezonie |
| Cena | Aktualna cena zawodnika |
| ±Avg | Punkty zawodnika minus średnia punktów wszystkich grających na tej pozycji |
| ±Liga | Punkty zawodnika minus średnia punktów graczy na tej pozycji w drużynach z Twojej ligi |
| Pkt/Cena | Stosunek punktów do ceny |
| Forma | Mini wykres słupkowy z 5 kolejek przed obecną |
| Średnia | Średnia punktów z rozegranych meczów (ostatnie 5 kolejek przed obecną) |
| Pop. | Oficjalny % popularności z API Fantasy Ekstraklasa — procent **wszystkich** graczy fantasy, którzy mają tego zawodnika |
| W składzie | % drużyn z wybranego zakresu (Top 10/100/Wszystkie/Liga), które mają tego zawodnika w składzie |
| Start XI | % drużyn z wybranego zakresu, które mają tego zawodnika w Starting XI (nie na ławce) |
| Kapitan | % drużyn z wybranego zakresu, które mają tego zawodnika jako kapitana |

Kliknięcie na zawodnika rozwija panel z listą drużyn z Twojej ligi, które go mają (pozycja w rankingu, rola: C/XI/RES).

**📋 Drużyny ligi** — podgląd składów z ligi prywatnej:
- Dropdown z wszystkimi drużynami sortowanymi wg pozycji w rankingu
- Tabela z sortowalnymi kolumnami (domyślnie wg pozycji: GK → DEF → MID → FWD)
- Podział na Starting XI i ławkę rezerwowych
- Kolumny ±Avg, ±Liga, Forma i Średnia z podsumowaniem na dole
- Kliknięcie na zawodnika rozwija panel z drużynami ligowymi

### Filtry i zakresy

- **Filtr pozycji** — BR / OBR / POM / NAP / Wszyscy
- **Zakres ownership** — dynamiczne przyciski Top 10 / Top 100 / Wszystkie / Liga — kolumny ownership (W składzie, Start XI, Kapitan) zmieniają się z zakresem, a Pop. zawsze pokazuje globalną popularność
- Wszystkie kolumny sortowalne (kliknij nagłówek)

### Forma

Mini wykres słupkowy w kolumnie tabeli (5 kolejek przed obecną):
- Kolory: cyan (≥8 pkt), zielony (≥4), szary (≥0), czerwony (<0)
- Kolejki nierozegrane oznaczone przerywanym konturem (0 pkt, nie wliczane do średniej)

### Różnica Pop. vs W składzie

Obie kolumny mierzą popularność zawodnika, ale z różnych źródeł:
- **Pop.** — oficjalna wartość z API fantasy.ekstraklasa.org, obliczana z **wszystkich** graczy fantasy. Stała niezależnie od wybranego zakresu.
- **W składzie** — obliczona z naszego scrapowania drużyn z rankingu. Zmienia się z wybranym zakresem (Top 10/100/Wszystkie/Liga), co pozwala porównać popularność zawodnika wśród najlepszych graczy vs ogółu.

## 📁 Pliki wyjściowe

| Plik | Zawartość |
|---|---|
| `dashboard.html` | Interaktywny dashboard (kopiowany też do `docs/index.html`) |
| `fantasy_full_*.json` | Pełne dane JSON — wszystkie kolejki, historia cen |
| `fantasy_players_*.csv` | Podsumowanie: imię, drużyna, punkty, cena, pkt/cena, popularność, forma |
| `fantasy_rounds_*.csv` | Statystyki per kolejka + zmiana ceny |
| `fantasy_captains_*.csv` | Ranking popularności kapitanów |
| `fantasy_ownership_*.csv` | Ownership — W składzie / Start XI / Kapitan % |

## 📂 Pliki konfiguracyjne

| Plik | Opis |
|---|---|
| `terminarz.txt` | Terminarz meczów — edytowany ręcznie, triggeruje automatyczne uruchomienia |
| `update_schedule.py` | Skrypt parsujący terminarz i aktualizujący cron w scrape.yml |

## ⚙️ Jak to działa

1. **Logowanie** — automatyczne logowanie emailem/hasłem z szyfrowaniem AES
2. **Skanowanie zawodników** — równoległe pobieranie statystyk (ID 1–4000), dane z profili zawodników
3. **Scrapowanie drużyn** — 1000 drużyn z rankingu (10 workerów), parsowanie HTML składów (`$squad.push` + `$subs.push`)
4. **Liga prywatna** — pobieranie składów z ligi, matching z pełnymi danymi graczy
5. **Obliczenia** — ownership, kapitanowie, średnie pozycyjne (globalne + ligowe), forma
6. **Dashboard** — generowanie HTML z osadzonym JS, publikacja na GitHub Pages
7. **Auto-kontynuacja** — jeśli limit czasu zostanie przekroczony, workflow restartuje się automatycznie z checkpointu

## ⏰ Automatyczne uruchomienie

Scraper uruchamia się automatycznie na podstawie pliku `terminarz.txt`:
- **+30 minut** po pierwszym meczu każdej kolejki (szybkie odświeżenie na start)
- **+3 godziny** po każdym meczu (pełne odświeżenie po zakończeniu)

### Jak to działa

1. Edytujesz `terminarz.txt` (format jak z ekstraklasa.org — kolejki, daty, godziny)
2. Pushasz do repo
3. Workflow **Update Schedule** automatycznie:
   - parsuje terminarz
   - generuje cron trigger po każdym meczu (+3h) i na start kolejki (+30min)
   - konwertuje czasy na UTC (obsługuje zmianę CET/CEST)
   - aktualizuje cron w `scrape.yml`
   - commituje zmianę

Przykład kolejki z meczami o 18:00, 20:15, 20:30 CET:
- 18:30 CET — start kolejki (+30min po pierwszym meczu)
- 21:00 CET — +3h po meczu 18:00
- 23:15 CET — +3h po meczu 20:15
- 23:30 CET — +3h po meczu 20:30

Możesz też uruchomić **Update Schedule** ręcznie z zakładki Actions.

### Format terminarz.txt

```
Kolejka 23 - 28 lutego-1 marca

Arka Gdynia	-	Lechia Gdańsk	27 lutego, 20:30 
Cracovia	-	Piast Gliwice	27 lutego, 18:00 
...
```

## 🔧 Uruchomienie lokalne

```bash
pip install -r requirements.txt

export FANTASY_EMAIL="twoj@email.pl"
export FANTASY_PASSWORD="twoje_haslo"

# Opcjonalne parametry
export MAX_PLAYER_ID=4000
export TEAMS_TO_SCRAPE=1000
export LEAGUE_SLUG="discord-fmforumcmf"
export LEAGUE_ID="304"

python scraper.py
```

## ⚠️ Uwagi

- **Logowanie automatyczne** — scraper sam się loguje, zero ręcznej pracy z cookies
- **Konto dedykowane** — zalecane jest osobne konto do scrapowania
- **Szanuj serwer** — domyślne opóźnienie 0.3s między requestami
- **Checkpoint** — przerwane scrapowanie drużyn jest kontynuowane automatycznie
- **GitHub Pages** — dashboard dostępny online po włączeniu Pages w ustawieniach repo
- **Opóźnienia cron** — GitHub Actions może opóźnić cron triggery o kilka do kilkunastu minut
