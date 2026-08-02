"""
test_squad_auth.py — EKSPERYMENT: warianty nagłówków (A-H) + własna vs cudza.
Wariant H: PKCE code_challenge/state pobrane ze stronicowego /login redirect
(zamiast samodzielnie generowanych).
Działa poza repo — /tmp/, czysto diagnostyczne.
NIE zmienia squads.py/auth.py/scraper.py.
"""
import sys
import urllib.parse
import requests
import curl_cffi
from config import (
    BASE_URL, BROWSER_HEADERS, RANKING_HEADERS,
    LEAGUE_SLUG, LEAGUE_ID,
    FANTASY_EMAIL, FANTASY_PASSWORD,
)
from auth import (
    get_session,
    COGNITO_BASE, COGNITO_API,
    SSO_CLIENT_ID, FANTASY_CLIENT_ID,
    REDIRECT_URI, SCOPE,
)

SLUG_CUDZA = "lubliniankakonskie"
LEAGUE_SLUG_LOCAL = LEAGUE_SLUG


def cookie_names(session):
    return sorted(c.name for c in session.cookies)


def cookies_as_dict(requests_session):
    """Wyciąga cookies z requests.Session jako zwykły słownik (dla curl_cffi)."""
    return {c.name: c.value for c in requests_session.cookies}


def login_variant_h():
    """
    WARIANT H: logowanie przez OAuth 2.0 + PKCE, gdzie code_challenge i state
    pochodzą ze stronicowego redirectu /login → id.ekstraklasa.org/oauth/authorize.
    Nie generujemy własnych wartości PKCE — używamy tych, które wygenerował
    serwer fantasy.ekstraklasa.org.
    """
    print("\n--- Wariant H: logowanie (PKCE ze stronicowego /login) ---")
    session = requests.Session()

    # KROK 0: GET /login → wyciągnij prawdziwe PKCE z redirectu
    print("   🔐 Krok 0: GET /login → parsowanie PKCE z Location...")
    try:
        resp = session.get(
            f"{BASE_URL}/login",
            allow_redirects=False,
            timeout=15,
        )
        location = resp.headers.get("Location", "")
        if not location:
            print(f"   ❌ Brak Location w odpowiedzi (HTTP {resp.status_code})")
            print(f"   Headers: {dict(resp.headers)}")
            return None

        print(f"   Location: {location[:120]}...")
        parsed = urllib.parse.urlparse(location)
        if "id.ekstraklasa.org" not in parsed.netloc:
            print(f"   ❌ Nieoczekiwany redirect (nie id.ekstraklasa.org): "
                  f"{parsed.netloc}")
            print(f"   Pełny Location: {location}")
            return None

        qs = urllib.parse.parse_qs(parsed.query)
        srv_client_id = qs.get("client_id", [None])[0]
        srv_challenge = qs.get("code_challenge", [None])[0]
        srv_challenge_method = qs.get("code_challenge_method", [None])[0]
        srv_state = qs.get("state", [None])[0]
        srv_redirect_uri = qs.get("redirect_uri", [None])[0]
        srv_scope = qs.get("scope", [None])[0]

        missing = []
        if not srv_client_id: missing.append("client_id")
        if not srv_challenge: missing.append("code_challenge")
        if not srv_state: missing.append("state")
        if not srv_redirect_uri: missing.append("redirect_uri")
        if not srv_scope: missing.append("scope")
        if missing:
            print(f"   ❌ Brak parametrów w Location: {missing}")
            return None

        print(f"   ✅ client_id:            {srv_client_id}")
        print(f"   ✅ code_challenge:       {srv_challenge[:20]}...")
        print(f"   ✅ code_challenge_method:{srv_challenge_method or '(brak)'}")
        print(f"   ✅ state:               {srv_state[:20]}...")
        print(f"   ✅ redirect_uri:        {srv_redirect_uri[:60]}...")
        print(f"   ✅ scope:               {srv_scope}")
    except Exception as e:
        print(f"   ❌ Błąd krok 0: {e}")
        return None

    # KROK 1: Password grant → access_token (bez zmian)
    print("   🔐 Krok 1: Password grant (sso-client, /oauth/token)...")
    try:
        resp = session.post(
            f"{COGNITO_API}/oauth/token",
            data={
                "grant_type": "password",
                "client_id": SSO_CLIENT_ID,
                "username": FANTASY_EMAIL,
                "password": FANTASY_PASSWORD,
                "scope": srv_scope,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ❌ Password grant HTTP {resp.status_code}: "
                  f"{resp.text[:300]}")
            return None

        token_data = resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            print(f"   ❌ Brak access_token. Klucze: {list(token_data.keys())}")
            return None
        print(f"   ✅ access_token: {access_token[:20]}...")
    except Exception as e:
        print(f"   ❌ Błąd krok 1: {e}")
        return None

    # KROK 2: Authorization code grant → authorization_token
    #         UŻYWA PKCE OD SERWERA (nie generujemy własnych!)
    print("   🔐 Krok 2: Authorization code grant (esa-fantasy + Bearer + PKCE serwera)...")
    try:
        resp = session.post(
            f"{COGNITO_API}/v1/authorization_token",
            json={
                "grant_type": "authorization_code",
                "client_id": srv_client_id,
                "redirect_uri": srv_redirect_uri,
                "scope": srv_scope,
                "response_type": "code",
                "code_challenge": srv_challenge,
                "code_challenge_method": srv_challenge_method or "S256",
                "state": srv_state,
            },
            headers={
                "Authorization": f"Bearer {access_token}",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ❌ Authorization code grant HTTP {resp.status_code}: "
                  f"{resp.text[:300]}")
            return None

        auth_data = resp.json()
        authorization_token = auth_data.get("authorization_token")
        if not authorization_token:
            print(f"   ❌ Brak authorization_token. Klucze: "
                  f"{list(auth_data.keys())}")
            return None
        print(f"   ✅ authorization_token: {authorization_token[:20]}...")
    except Exception as e:
        print(f"   ❌ Błąd krok 2: {e}")
        return None

    # KROK 3: OAuth authorize → redirect z code
    print("   🔐 Krok 3: OAuth authorize → redirect z code...")
    try:
        params = {
            "authorization_token": authorization_token,
            "grant_type": "authorization_code",
            "response_type": "code",
            "client_id": srv_client_id,
            "redirect_uri": srv_redirect_uri,
            "scope": srv_scope,
            "code_challenge": srv_challenge,
            "code_challenge_method": srv_challenge_method or "S256",
            "state": srv_state,
        }
        resp = session.get(
            f"{COGNITO_API}/oauth/authorize",
            params=params,
            allow_redirects=False,
            timeout=15,
        )
        location = resp.headers.get("Location", "")
        if resp.status_code not in (302, 301) or not location:
            print(f"   ❌ Oczekiwano redirect, dostano HTTP {resp.status_code}")
            print(f"   Body: {resp.text[:200]}")
            return None

        parsed = urllib.parse.urlparse(location)
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [None])[0]
        returned_state = qs.get("state", [None])[0]

        if not code:
            print(f"   ❌ Brak 'code' w redirect: {location[:200]}")
            return None
        if returned_state != srv_state:
            print(f"   ❌ State mismatch: {returned_state} != {srv_state}")
            return None
        print(f"   ✅ code: {code[:20]}...")
    except Exception as e:
        print(f"   ❌ Błąd krok 3: {e}")
        return None

    # KROK 4: check-green-sso → PHPSESSID
    print("   🔐 Krok 4: check-green-sso → PHPSESSID...")
    try:
        resp = session.get(
            f"{BASE_URL}/login/check-green-sso",
            params={"code": code, "state": srv_state},
            allow_redirects=True,
            timeout=15,
        )
        phpsessid = session.cookies.get("PHPSESSID", "")
        if not phpsessid:
            print("   ❌ /login/check-green-sso nie ustawiło PHPSESSID")
            return None
        print(f"   ✅ Zalogowano! PHPSESSID: {phpsessid[:20]}...")

        # Cookie premium-show=1
        session.cookies.set(
            "premium-show", "1",
            domain="fantasy.ekstraklasa.org",
            path="/",
        )
        print("   ✅ Cookie premium-show=1 ustawiony")
        return session
    except Exception as e:
        print(f"   ❌ Błąd krok 4: {e}")
        return None


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
    print("=== Eksperyment: warianty nagłówków A-H + własna vs cudza ===\n")
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

    # ========================================================================
    # CZĘŚĆ 1B: Wariant H — logowanie z PKCE od serwera
    # ========================================================================
    print("\n" + "=" * 70)
    print("CZĘŚĆ 1B: Wariant H — logowanie z PKCE od serwera (ze stronicowego /login)")
    print("=" * 70)

    session_h = login_variant_h()
    if session_h is None:
        print("\n❌ Wariant H: logowanie NIEUDANE — pomijam test.")
        r_h = {
            "name": "H (PKCE od serwera → login FAIL)",
            "slug": SLUG_CUDZA,
            "status_code": 0,
            "is_redirect": False,
            "has_squad": False,
            "preview": "(logowanie nieudane)",
        }
    else:
        cookies_h = cookies_as_dict(session_h)
        print(f"\n   Cookies po H: {list(cookies_h.keys())}")
        print()

        headers_a = {
            **BROWSER_HEADERS,
            "Upgrade-Insecure-Requests": "1",
        }
        print(f"--- Wariant H (PKCE od serwera) + Variant A headers ---")
        r_h = run_variant_requests(session_h, SLUG_CUDZA,
                                   "H (PKCE od serwera, test A headers)", headers_a)
        print(f"    status_code:  {r_h['status_code']}")
        print(f"    redirect:     {'TAK' if r_h['is_redirect'] else 'nie'}")
        print(f"    $squad.push:  {'TAK' if r_h['has_squad'] else 'nie'}")
        print(f"    preview:      {r_h['preview']}")

    results_all = results + [r_h]

    # Tabela porównawcza A-H
    print("\n" + "=" * 90)
    print("TABELA PORÓWNAWCZA (A-H)")
    print("=" * 90)
    print(f"{'Wariant':<48} {'Status':>6} {'Redirect':>8} {'$squad':>7}  Preview")
    print("-" * 90)
    for r in results_all:
        redirect = "TAK" if r["is_redirect"] else "nie"
        squad = "TAK" if r["has_squad"] else "nie"
        preview_short = r["preview"][:50]
        print(
            f"{r['name']:<48} {r['status_code']:>6} "
            f"{redirect:>8} {squad:>7}  {preview_short}"
        )

    # Podsumowanie H vs reszta
    print("\n" + "=" * 70)
    print("PODSUMOWANIE: Wariant H (PKCE od serwera) vs dotychczasowe A-G")
    print("=" * 70)
    for r in results_all:
        success = r["status_code"] == 200 and r["has_squad"] and not r["is_redirect"]
        redirect = r["is_redirect"]
        if success:
            status = "SUKCES (200 + $squad.push)"
        elif r["status_code"] == 0:
            status = "LOGOWANIE NIEUDANE"
        elif redirect:
            status = "REDIRECT → prawdopodobnie login"
        else:
            status = f"NIEPOWODZENIE (HTTP {r['status_code']}, $squad.push={r['has_squad']})"
        print(f"   {r['name']}: [{status}]")

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
