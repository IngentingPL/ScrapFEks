# ⚽ ScrapFEks — Fantasy Ekstraklasa Stats

Scraper i interaktywny dashboard dla [fantasy.ekstraklasa.org](https://fantasy.ekstraklasa.org/) — statystyki zawodników, ownership drużyn z rankingu, analiza ligi prywatnej, fixture ticker z trudnością meczów.

Uruchamiany automatycznie przez **GitHub Actions** po każdym meczu, z publikacją dashboardu na GitHub Pages.

---

## 🚀 Szybki start

### 1. Fork repozytorium

Skopiuj pliki do nowego repozytorium na GitHubie.

### 2. Dodaj dane logowania do GitHub Secrets

**Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

**Wymagane:**
- `FANTASY_EMAIL` — email konta na fantasy.ekstraklasa.org
- `FANTASY_PASSWORD` — hasło do tego konta

**Opcjonalne (włączają dodatkowe funkcje):**
- `DEEPSEEK_API_KEY` — newsletter i eksperci AI na Discordzie (model główny)
- `GEMINI_API_KEY` — fallback dla powyższego, gdy DeepSeek zawiedzie
- `DISCORD_WEBHOOK_URL` — powiadomienia na Discord
- `EXTRAKLASA_API_TOKEN` — rozszerzone statystyki zawodników (xG, strzały)
- `WORKFLOW_PAT` — Personal Access Token, wymagany TYLKO jeśli chcesz używać workflow **Update Schedule** (edytuje plik workflow, czego domyślny token GitHuba nie może zrobić)

> **Zalecenie:** użyj osobnego konta fantasy do scrapowania.

### 3. Włącz GitHub Pages (dashboard online)

**Settings** → **Pages** → Source: **Deploy from a branch** → Branch: `main`, folder: `/docs`

Dashboard będzie dostępny pod adresem `https://<user>.github.io/<repo>/`.

### 4. Uruchom scraper

**Actions** → **Fantasy Ekstraklasa Scraper** → **Run workflow**

Parametry (wszystkie opcjonalne):

| Parametr | Domyślnie | Opis |
|---|---|---|
| `max_players` | 4000 | Maksymalna liczba ID zawodników do przeskanowania |
| `teams_to_scrape` | 1000 | Ile drużyn z rankingu scrapować (ownership/kapitanowie) |
| `league_slug` | `discord-fmforumcmf` | Slug ligi prywatnej (pusty = pomiń) |
| `league_id` | `304` | ID ligi (z Network tab w przeglądarce) |
| `target_round` | *(ostatnia)* | Numer kolejki do analizy |
| `workers` | 10 | Liczba równoległych workerów do scrapowania drużyn |
| `max_runtime` | 300 | Maksymalny czas pracy w minutach przed zapisem checkpointu |

---

## 📊 Dashboard

Interaktywny dashboard HTML z ciemnym motywem, generowany automatycznie po każdym uruchomieniu.

### Zakładki

**⚽ Zawodnicy** — domyślna zakładka. Pełna tabela ze statystykami, formą i ownership:

| Kolumna | Opis |
|---|---|
| Punkty | Łączne punkty w sezonie |
| Cena | Aktualna cena zawodnika |
| ±Avg | Punkty zawodnika minus średnia pozycji (wszyscy gracze fantasy) |
| ±Liga | Punkty zawodnika minus średnia pozycji wśród graczy z Twojej ligi prywatnej |
| Pkt/Cena | Stosunek punktów do ceny (value metric) |
| Forma | Mini wykres słupkowy z 5 kolejek przed obecną |
| Średnia | Średnia punktów z rozegranych meczów (ostatnie 5 kolejek przed obecną) |
| Pop. | Oficjalny % popularności z API — procent **wszystkich** graczy fantasy, którzy mają tego zawodnika |
| W składzie | % drużyn z wybranego zakresu, które mają zawodnika w składzie |
| Start XI | % drużyn z wybranego zakresu, które mają zawodnika w Starting XI |
| Kapitan | % drużyn z wybranego zakresu, które mają zawodnika jako kapitana |

Kliknięcie na zawodnika rozwija panel z listą drużyn z Twojej ligi, które go mają (pozycja w rankingu, rola: C / XI / RES).

**📋 Liga prywatna** — podgląd składów (zakładka dynamicznie nazwana wg Twojej ligi):
- Dropdown z wszystkimi drużynami sortowanymi wg pozycji w rankingu
- Tabela z sortowalnymi kolumnami (domyślnie wg pozycji: GK → DEF → MID → FWD)
- Podział na Starting XI i ławkę rezerwowych
- Kolumny ±Avg, ±Liga, Forma i Średnia z podsumowaniem na dole
- Kliknięcie na zawodnika rozwija panel z drużynami ligowymi, które go mają
- Wykrywanie transferów między kolejkami

**📅 Terminarz** — fixture ticker z trudnością meczów:
- Siatka: drużyny w wierszach, kolejki w kolumnach
- Każda komórka = skrót przeciwnika + (D)om / (W)yjazd
- Kolory od zielonego (łatwy) do czerwonego (trudny) na podstawie siły drużyn i dom/wyjazd
- Kolumna ze średnią trudnością nadchodzących meczów
- Kliknięcie na nazwę drużyny otwiera modal z suwakami do edycji siły ataku i obrony (1–5)
- Sortowanie: alfabetyczne lub wg średniej trudności
- Terminarz z pliku `terminarz.txt`; siła drużyn (bramki strzelone/stracone) scrapowana z **90minut.pl**

**📊 Dodatkowe dane** — szczegółowe zestawienia:
- Ranking popularności kapitanów
- Procent ownership zawodników (W składzie / Start XI / Kapitan)
- Statystyki per kolejka
- Śledzenie transferów w lidze prywatnej

### Filtry i zakresy

- **Filtr pozycji** — BR / OBR / POM / NAP / Wszyscy
- **Zakres ownership** — przyciski Top 10 / Top 100 / Wszystkie / Liga — kolumny ownership zmieniają się z zakresem; Pop. zawsze pokazuje globalną popularność z API
- Wszystkie kolumny sortowalne (kliknij nagłówek)

### Forma — kolory mini wykresu

| Kolor | Próg |
|---|---|
| Cyan | ≥ 8 pkt |
| Zielony | ≥ 4 pkt |
| Szary | ≥ 0 pkt |
| Czerwony | < 0 pkt |

Kolejki nierozegrane oznaczone przerywanym konturem — 0 pkt, nie wliczane do średniej.

### Pop. vs W składzie — różnica

| Kolumna | Źródło | Zakres |
|---|---|---|
| **Pop.** | Oficjalne API fantasy.ekstraklasa.org | Wszyscy gracze fantasy (stała wartość) |
| **W składzie** | Własne scrapowanie rankingu | Zmienia się z Top 10 / Top 100 / Wszystkie / Liga |

Dzięki temu możesz porównać popularność zawodnika wśród najlepszych graczy vs ogółu.

---

## ⚙️ Jak to działa

1. **Logowanie** — automatyczne logowanie emailem/hasłem z szyfrowaniem AES (kompatybilne z CryptoJS)
2. **Skanowanie zawodników** — sekwencyjne pobieranie profili (ID 1–4000), statystyki per kolejka, historia cen
3. **Scrapowanie drużyn** — top 1000 drużyn z rankingu (10 workerów równolegle), parsowanie HTML składów
4. **Liga prywatna** — pobieranie składów, matching z pełnymi danymi zawodników, wykrywanie transferów
5. **Siła drużyn** — scrapowanie tabeli z **90minut.pl** (bramki strzelone/stracone) na potrzeby fixture tickera
6. **Obliczenia** — ownership %, średnie pozycyjne (globalne + ligowe), forma (5 ostatnich kolejek)
7. **Dashboard** — generowanie HTML z osadzonym JS, publikacja na GitHub Pages
8. **Auto-kontynuacja** — przekroczenie limitu czasu → zapis checkpointu → automatyczny restart workflow

---

## ⏰ Automatyczne uruchomienie

Scraper uruchamia się automatycznie na podstawie pliku `terminarz.txt`:

- **+30 minut** po pierwszym meczu każdej kolejki — szybkie odświeżenie na start
- **+2.5 godziny** po każdym meczu — pełne odświeżenie po zakończeniu

### Jak działa aktualizacja harmonogramu

1. Edytujesz `terminarz.txt` (format jak z ekstraklasa.org — kolejki, daty, godziny po polsku)
2. Pushujesz do repo
3. Workflow **Update Schedule** automatycznie:
   - parsuje terminarz i konwertuje polskie nazwy miesięcy
   - generuje wyrażenia cron w UTC (obsługuje zmianę CET ↔ CEST)
   - aktualizuje harmonogram w `scrape.yml`
   - commituje zmianę

Możesz też uruchomić **Update Schedule** ręcznie z zakładki Actions.

### Przykład — kolejka z meczami o 18:00, 20:15, 20:30 CET

| Czas (CET) | Trigger |
|---|---|
| 18:30 | Start kolejki (+30 min po pierwszym meczu) |
| 20:30 | +2.5h po meczu 18:00 |
| 22:45 | +2.5h po meczu 20:15 |
| 23:00 | +2.5h po meczu 20:30 |

### Format terminarz.txt

```
Kolejka 23 - 28 lutego-1 marca

Arka Gdynia	-	Lechia Gdańsk	27 lutego, 20:30
Cracovia	-	Piast Gliwice	27 lutego, 18:00
...
```

---

## 🔧 Uruchomienie lokalne

```bash
pip install -r requirements.txt

export FANTASY_EMAIL="twoj@email.pl"
export FANTASY_PASSWORD="twoje_haslo"

# Opcjonalne
export MAX_PLAYER_ID=4000
export TEAMS_TO_SCRAPE=1000
export LEAGUE_SLUG="twoja-liga"
export LEAGUE_ID="304"
export WORKERS=10
export MAX_RUNTIME_MINUTES=300

python scraper.py
```

Do testowania pobierania danych jednego zawodnika:

```bash
python test_single_player.py [player_id]
```

---

## 📁 Pliki wyjściowe

Wszystkie pliki zapisywane do katalogu `output/` ze znacznikiem czasu (`YYYYMMDD_HHMMSS`).

| Plik | Zawartość |
|---|---|
| `dashboard.html` | Interaktywny dashboard (kopiowany też do `docs/index.html` → GitHub Pages) |
| `fantasy_full_*.json` | Pełne dane — wszystkie kolejki, historia cen |
| `fantasy_players_*.csv` | Podsumowanie: imię, drużyna, punkty, cena, pkt/cena, popularność, forma |
| `fantasy_rounds_*.csv` | Statystyki per kolejka + zmiana ceny |
| `fantasy_captains_*.csv` | Ranking popularności kapitanów |
| `fantasy_ownership_*.csv` | Ownership — W składzie / Start XI / Kapitan % |
| `checkpoint_global.json` | Punkt wznowienia dla scrapowania zawodników |
| `checkpoint_league.json` | Punkt wznowienia dla scrapowania drużyn |

Artefakty z GitHub Actions przechowywane przez **7 dni**.

---

## 📂 Pliki projektu

| Plik | Opis |
|---|---|
| `scraper.py` | Główny skrypt — logowanie, scrapowanie, obliczenia, generowanie dashboardu |
| `update_schedule.py` | Parser terminarza → generuje cron triggery w `scrape.yml` |
| `test_single_player.py` | Narzędzie do testowania pobierania danych jednego zawodnika |
| `terminarz.txt` | Terminarz meczów — źródło danych dla fixture tickera i auto-uruchomień |
| `.github/workflows/scrape.yml` | Workflow GitHub Actions — główny scraper |
| `.github/workflows/update_schedule.yml` | Workflow GitHub Actions — aktualizacja harmonogramu |
| `predictor.py` | Logika prognoz punktowych zawodników |
| `tuner.py` | Auto-tuning parametrów predykcji na podstawie trafności |
| `accuracy.py` | Śledzenie trafności prognoz kolejka po kolejce |
| `analytics.py` | Wspólne funkcje analityczne (hidden gem, disappointment, kapitanowie) |
| `ai_client.py` | Wspólny klient DeepSeek/Gemini używany przez newsletter i Discord |
| `discord_notify.py` | Wysyłanie powiadomień na Discord |
| `newsletter.py` | Generowanie newslettera przez AI |
| `league_tracker.py` | Tracker sezonu ligowego |
| `archive.py` | Archiwizacja zakończonego sezonu |
| `generate_from_cache.py` | Regeneruje dashboard z istniejącego JSON |

---

## ⚠️ Uwagi

- **Logowanie automatyczne** — scraper sam się loguje, zero ręcznej pracy z cookies
- **Konto dedykowane** — zalecane osobne konto fantasy do scrapowania
- **Szanuj serwer** — domyślne opóźnienie 0.3s między requestami
- **Checkpoint** — przerwane scrapowanie jest wznawiane automatycznie z ostatniego punktu
- **GitHub Pages** — dashboard dostępny online po włączeniu Pages w ustawieniach repo
- **Opóźnienia cron** — GitHub Actions może opóźnić cron triggery o kilka do kilkunastu minut
