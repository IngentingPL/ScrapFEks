# ⚽ Fantasy Ekstraklasa Stats

Scraper danych z [fantasy.ekstraklasa.org](https://fantasy.ekstraklasa.org/) — punkty, popularność, ceny, statystyki per kolejka.

Uruchamiany automatycznie przez **GitHub Actions** — bez potrzeby instalacji na komputerze.

## 🚀 Szybki start

### 1. Fork / stwórz repo

Skopiuj pliki do nowego repozytorium na GitHubie.

### 2. Dodaj dane logowania do GitHub Secrets

1. W repozytorium GitHub: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
2. Dodaj dwa secrety:
   - Name: `FANTASY_EMAIL` → Value: email konta na fantasy.ekstraklasa.org
   - Name: `FANTASY_PASSWORD` → Value: hasło do tego konta

Scraper automatycznie się zaloguje — zero ręcznej pracy z cookies!

### 3. Uruchom scraper

1. Przejdź do zakładki **Actions** w repozytorium
2. Kliknij **Fantasy Ekstraklasa Scraper** w lewym panelu
3. Kliknij **Run workflow**
4. Opcjonalnie zmień parametry:
   - `max_players` — ile zawodników pobrać (domyślnie 100, pełny scraping ~3000)
   - `target_round` — numer kolejki do analizy (puste = ostatnia rozegrana)
5. Kliknij **Run workflow**

### 4. Pobierz wyniki

Po zakończeniu:
- Wyniki zostaną zapisane jako **Artifact** do pobrania (zakładka Actions → kliknij run → Artifacts)
- Wyniki zostaną też wrzucone do katalogu `output/` w repozytorium

## 📁 Pliki wyjściowe

| Plik | Zawartość |
|---|---|
| `fantasy_full_*.json` | Pełne dane JSON ze wszystkimi kolejkami i historią cen |
| `fantasy_players_*.csv` | Podsumowanie: imię, drużyna, punkty, cena, points_per_price, popularność |
| `fantasy_rounds_*.csv` | Statystyki per kolejka + zmiana ceny (`price_change`) |

## ⏰ Automatyczne uruchomienie (opcjonalne)

Żeby scraper uruchamiał się automatycznie co tydzień, odkomentuj sekcję `schedule` w `.github/workflows/scrape.yml`:

```yaml
schedule:
  - cron: '0 20 * * 5'  # co piątek o 20:00 UTC
```

## 🔧 Uruchomienie lokalne

Jeśli wolisz uruchomić na swoim komputerze:

```bash
pip install -r requirements.txt

# Podaj dane logowania
export FANTASY_EMAIL="twoj@email.pl"
export FANTASY_PASSWORD="twoje_haslo"

# Uruchom
python scraper.py
```

## ⚠️ Uwagi

- **Logowanie automatyczne** — scraper sam się loguje mailem i hasłem, zero ręcznej pracy
- **Konto dedykowane** — zalecane jest osobne konto (email+hasło) do scrapowania
- **Szanuj serwer** — domyślne opóźnienie to 0.3s między requestami
- Dane o **kapitanach** nie są dostępne z tego endpointu
- Do pełnego scrapingu (~500+ zawodników) ustaw `max_players` na 3000
