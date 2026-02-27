# ⚽ Fantasy Ekstraklasa Stats

Scraper i interaktywny dashboard dla [fantasy.ekstraklasa.org](https://fantasy.ekstraklasa.org/) — statystyki zawodników, ownership drużyn z rankingu, analiza ligi prywatnej.

Uruchamiany automatycznie przez **GitHub Actions** z publikacją dashboardu na GitHub Pages.

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

**👑 Kapitanowie** — ranking najpopularniejszych kapitanów z paskami popularności.

**⚽ Zawodnicy** — pełna tabela ze statystykami i ownership:
- Punkty, cena, Pkt/Cena, popularność
- **±Avg** — różnica vs średnia punktów na danej pozycji (wszyscy grający)
- **±Liga** — różnica vs średnia punktów na danej pozycji w drużynach z Twojej ligi
- Ownership: W składzie %, Start XI %, Kapitan % (kolorowe paski)
- Kliknięcie na zawodnika rozwija panel z **wykresem formy** (słupki z 5 kolejek przed obecną + średnia) i **listą drużyn ligowych** z tym graczem

**📋 Drużyny ligi** — podgląd składów z ligi prywatnej:
- Dropdown z wszystkimi drużynami sortowanymi wg pozycji w rankingu
- Tabela z sortowalnymi kolumnami (domyślnie wg pozycji: GK → DEF → MID → FWD)
- Podział na Starting XI i ławkę rezerwowych
- Kolumny ±Avg i ±Liga z podsumowaniem na dole

### Filtry i zakresy

- **Filtr pozycji** — BR / OBR / POM / NAP / Wszyscy
- **Zakres ownership** — dynamiczne przyciski Top 10 / Top 100 / Wszystkie / Liga — ownership i kapitanowie filtrowane per zakres
- Wszystkie kolumny sortowalne (kliknij nagłówek)

### Forma zawodnika

Kliknięcie na nazwisko zawodnika rozwija panel szczegółów:
- Wykres słupkowy z **5 kolejek przed obecną** (stała skala, jednolite wysokości)
- Kolejki nierozegrane oznaczone przerywanym konturem (0 pkt, nie wliczane do średniej)
- Kolory: cyan (≥8 pkt), zielony (≥4), szary (≥0), czerwony (<0)
- Średnia z rozegranych meczów obok wykresu
- Lista drużyn ligowych z tym graczem (pozycja, rola: C/XI/RES)

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

Scraper uruchamia się automatycznie 3 godziny po każdym meczu na podstawie pliku `terminarz.txt`.

### Jak to działa

1. Edytujesz `terminarz.txt` (format jak z ekstraklasa.org — kolejki, daty, godziny)
2. Pushasz do repo
3. Workflow **Update Schedule** automatycznie:
   - parsuje terminarz
   - grupuje mecze per dzień, bierze najpóźniejszy
   - dodaje 3h i konwertuje na UTC
   - aktualizuje cron w `scrape.yml`
   - commituje zmianę

Przykład: mecz o 20:15 CET → trigger o 23:15 CET (22:15 UTC).

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
