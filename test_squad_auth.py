"""
test_squad_auth.py — EKSPERYMENT: warianty nagłówków (A-G) + własna vs cudza.
Działa poza repo — /tmp/, czysto diagnostyczne.
NIE zmienia squads.py/auth.py/scraper.py.
"""
import sys
import requests
import curl_cffi
from config import BASE_URL, BROWSER_HEADERS, RANKING_HEADERS, LEAGUE_SLUG, LEAGUE_ID
from auth import get_session

SLUG_CUDZA = "lubliniankakonskie"
LEAGUE_SLUG_LOCAL = LEAGUE_SLUG


def cookie_names(session):
    return sorted(c.name for c in session.cookies)


def cookies_as_dict(requests_session):
    """Wyciąga cookies z requests.Session jako zwykły słownik (dla curl_cffi)."""
    return {c.name: c.value for c in requests_session.cookies}


def fetch_league_teams_with_names(session):
    """Pobiera listę drużyn z ligi, zwraca listę {slug, name, position}."""
    print(f"Pobieranie drużyn z ligi (slug={LEAGUE_SLUG_LOCAL}, id={LEAGUE_ID})...")
    teams = []
    try:
        payload = f"start=0&length=100&league={LEAGUE_ID}&round=0"
        resp = session.post(
            f"{BASE_URL}/ranking-list",
            data=payload,
            headers={**RANKING_HEADERS, "Referer": f"{BASE_URL}/league/{LEAGUE_SLUG_LOCAL}"},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"   ⚠️  HTTP {resp.status_code}")
            return teams

        data = resp.json()
        for team in data.get("data", []):
            slug = team.get("slug", "")
            name = team.get("name", "")
            if slug:
                teams.append({
                    "slug": slug,
                    "name": name,
                    "position": team.get("pos"),
                })
        print(f"   ✅ Pobrano {len(teams)} drużyn")
    except Exception as e:
        print(f"   ⚠️  Błąd: {e}")

    return teams


def run_variant_requests(session, slug, name, headers):
    """Wykonuje GET przez requests (jak dotąd)."""
    url = f"{BASE_URL}/user-team/view/{slug}"
    resp = session.get(url, headers=headers, timeout=15)
    return _parse_response(resp, name, slug)


def run_variant_curl_cffi(cookies_dict, slug, name, headers):
    """Wykonuje GET przez curl_cffi (odcisk TLS Chrome)."""
    url = f"{BASE_URL}/user-team/view/{slug}"
    resp = curl_cffi.get(
        url,
        impersonate="chrome",  # najnowszy profil Chrome (obecnie 146)
        cookies=cookies_dict,
        headers=headers,
        timeout=15,
    )
    return _parse_response(resp, name, slug)


def _parse_response(resp, name, slug):
    """Parsuje response (zarówno requests jak i curl_cffi mają .status_code, .text, .url)."""
    is_redirect = "login" in getattr(resp, "url", "").lower()
    has_squad = "$squad.push" in resp.text
    preview = resp.text[:150].replace("\n", "\\n")
    return {
        "name": name,
        "slug": slug,
        "status_code": resp.status_code,
        "is_redirect": is_redirect,
        "has_squad": has_squad,
        "preview": preview,
    }


def main():
    print("=== Eksperyment: warianty nagłówków A-G + własna vs cudza ===\n")
    print(f"Slug testowy (cudza): {SLUG_CUDZA}")

    # curl_cffi info
    print(f"curl_cffi zainstalowane: tak")
    print(f"Dostępne profile impersonate: chrome (alias → najnowszy Chrome)")
    print()

    # Logowanie (requests — to już działa)
    print("Logowanie (get_session z auth.py, requests)...")
    session = get_session()
    cookies_dict = cookies_as_dict(session)
    print(f"   Cookies: {list(cookies_dict.keys())}")
    print()

    # ====================================================================
    # CZĘŚĆ 1: Warianty A-G dla cudzej drużyny
    # ====================================================================
    print("=" * 70)
    print("CZĘŚĆ 1: Warianty nagłówków A-G (cudza drużyna)")
    print("=" * 70)

    results = []

    # ------ Warianty A-E (requests) ------
    variants_requests = [
        (
            "A (baseline)",
            {
                **BROWSER_HEADERS,
                "Upgrade-Insecure-Requests": "1",
            },
        ),
        (
            "B (+Referer root)",
            {
                **BROWSER_HEADERS,
                "Upgrade-Insecure-Requests": "1",
                "Referer": "https://fantasy.ekstraklasa.org/",
            },
        ),
        (
            "C (+Referer league)",
            {
                **BROWSER_HEADERS,
                "Upgrade-Insecure-Requests": "1",
                "Referer": f"https://fantasy.ekstraklasa.org/league/{LEAGUE_SLUG_LOCAL}",
            },
        ),
        (
            "D (-Upgrade-IR +Referer league)",
            {
                **BROWSER_HEADERS,
                "Referer": f"https://fantasy.ekstraklasa.org/league/{LEAGUE_SLUG_LOCAL}",
            },
        ),
        (
            "E (+X-Requested-With +Referer league)",
            {
                **BROWSER_HEADERS,
                "Upgrade-Insecure-Requests": "1",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://fantasy.ekstraklasa.org/league/{LEAGUE_SLUG_LOCAL}",
            },
        ),
    ]

    for name, headers in variants_requests:
        print(f"\n--- {name} ---")
        r = run_variant_requests(session, SLUG_CUDZA, name, headers)
        results.append(r)
        print(f"    status_code:  {r['status_code']}")
        print(f"    redirect:     {'TAK' if r['is_redirect'] else 'nie'}")
        print(f"    $squad.push:  {'TAK' if r['has_squad'] else 'nie'}")
        print(f"    preview:      {r['preview']}")

    # ------ Wariant F (requests + prawdziwe nagłówki przeglądarki) ------
    headers_f = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }

    print(f"\n--- F (requests + prawdziwe nagłówki) ---")
    r_f = run_variant_requests(session, SLUG_CUDZA, "F (requests + nagłówki Chrome)", headers_f)
    results.append(r_f)
    print(f"    status_code:  {r_f['status_code']}")
    print(f"    redirect:     {'TAK' if r_f['is_redirect'] else 'nie'}")
    print(f"    $squad.push:  {'TAK' if r_f['has_squad'] else 'nie'}")
    print(f"    preview:      {r_f['preview']}")

    # ------ Wariant G (curl_cffi + odcisk TLS Chrome + te same nagłówki) ------
    print(f"\n--- G (curl_cffi + Chrome TLS impers + prawdziwe nagłówki) ---")
    r_g = run_variant_curl_cffi(cookies_dict, SLUG_CUDZA, "G (curl_cffi + Chrome TLS)", headers_f)
    results.append(r_g)
    print(f"    status_code:  {r_g['status_code']}")
    print(f"    redirect:     {'TAK' if r_g['is_redirect'] else 'nie'}")
    print(f"    $squad.push:  {'TAK' if r_g['has_squad'] else 'nie'}")
    print(f"    preview:      {r_g['preview']}")

    # Tabela porównawcza A-G
    print("\n" + "=" * 90)
    print("TABELA PORÓWNAWCZA (A-G)")
    print("=" * 90)
    print(f"{'Wariant':<42} {'Status':>6} {'Redirect':>8} {'$squad':>7}  Preview")
    print("-" * 90)
    for r in results:
        redirect = "TAK" if r["is_redirect"] else "nie"
        squad = "TAK" if r["has_squad"] else "nie"
        preview_short = r["preview"][:55]
        print(
            f"{r['name']:<42} {r['status_code']:>6} "
            f"{redirect:>8} {squad:>7}  {preview_short}"
        )

    # ====================================================================
    # CZĘŚĆ 2: Własna vs cudza (Variant A)
    # ====================================================================
    print("\n" + "=" * 70)
    print("CZĘŚĆ 2: Własna vs cudza (Variant A)")
    print("=" * 70)

    headers_a = {
        **BROWSER_HEADERS,
        "Upgrade-Insecure-Requests": "1",
    }

    # CUDZA (wynik już mamy z results[0])
    r_cudza_a = results[0]

    # WŁASNA
    league_teams = fetch_league_teams_with_names(session)

    własna = None
    for t in league_teams:
        if t["name"].lower() == "tokusatsu soccer":
            własna = t
            break

    if własna is None:
        print("\n❌ Nie znaleziono drużyny 'Tokusatsu Soccer' w lidze.")
        print("   Pełna lista drużyn w lidze:")
        for i, t in enumerate(league_teams):
            print(f"   {i+1}. slug={t['slug']:<40} name={t.get('name', '(brak)')}")
        sys.exit(1)

    print(f"\nZnaleziono: slug={własna['slug']}, name={własna['name']}, position={własna.get('position', '?')}\n")

    r_wlasna = run_variant_requests(session, własna["slug"], f"WŁASNA ({własna['name']})", headers_a)
    print(f"    status_code:  {r_wlasna['status_code']}")
    print(f"    redirect:     {'TAK' if r_wlasna['is_redirect'] else 'nie'}")
    print(f"    $squad.push:  {'TAK' if r_wlasna['has_squad'] else 'nie'}")
    print(f"    preview:      {r_wlasna['preview']}")

    # Podsumowanie własna vs cudza
    print("\n" + "=" * 60)
    print("PODSUMOWANIE: WŁASNA vs CUDZA")
    print("=" * 60)
    for r in [r_wlasna, r_cudza_a]:
        success = r["status_code"] == 200 and r["has_squad"] and not r["is_redirect"]
        redirect = r["is_redirect"]
        if success:
            status = "SUKCES (200 + $squad.push)"
        elif redirect:
            status = "REDIRECT → prawdopodobnie login"
        else:
            status = f"NIEPOWODZENIE (HTTP {r['status_code']}, $squad.push={r['has_squad']})"
        print(f"   {r['name']}: [{status}]")

    # Podsumowanie F vs G
    print("\n" + "=" * 60)
    print("PODSUMOWANIE: requests vs curl_cffi (oba z nagłówkami Chrome)")
    print("=" * 60)
    for r in [r_f, r_g]:
        success = r["status_code"] == 200 and r["has_squad"] and not r["is_redirect"]
        redirect = r["is_redirect"]
        if success:
            status = "SUKCES (200 + $squad.push)"
        elif redirect:
            status = "REDIRECT → prawdopodobnie login"
        else:
            status = f"NIEPOWODZENIE (HTTP {r['status_code']}, $squad.push={r['has_squad']})"
        print(f"   {r['name']}: [{status}]")
    print()


if __name__ == "__main__":
    main()
