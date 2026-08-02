"""
test_squad_auth.py — tymczasowy test diagnostyczny logowania i dostępu do składów.
Używa prawdziwych funkcji z auth.py i squads.py.
NIE commituje, NIE pushuje, NIE woła discord_notify.
"""
import sys
import requests
from config import BASE_URL, BROWSER_HEADERS, LEAGUE_SLUG, LEAGUE_ID
from auth import get_session
from squads import fetch_league_teams


def cookie_names(session):
    """Zwróć posortowaną listę nazw cookies (bez wartości)."""
    return sorted(c.name for c in session.cookies)


def test_team_view(session, slug, label=""):
    """GET /user-team/view/{slug} — te same headery co scrape_team_squad().
    Zwraca: status_code, final_url, czy '$squad.push' jest w treści.
    """
    url = f"{BASE_URL}/user-team/view/{slug}"
    # Dokładnie jak scrape_team_squad: BROWSER_HEADERS + Upgrade-Insecure-Requests,
    # BEZ X-Requested-With
    browser_headers = {
        **BROWSER_HEADERS,
        "Upgrade-Insecure-Requests": "1",
    }
    resp = session.get(url, headers=browser_headers, timeout=15)

    has_squad = "$squad.push" in resp.text
    # Sprawdź czy finalny URL zawiera 'login' (przekierowanie do ekranu logowania)
    is_login_redirect = "login" in resp.url.lower()

    print(f"\n   [{label}] GET {url}")
    print(f"   status_code: {resp.status_code}")
    print(f"   final_url:   {resp.url}")
    print(f"   przekierowanie do login: {is_login_redirect}")
    print(f"   '$squad.push' w treści: {has_squad}")
    print(f"   długość treści: {len(resp.text)} znaków")

    return {
        "status_code": resp.status_code,
        "final_url": resp.url,
        "has_squad": has_squad,
        "is_login_redirect": is_login_redirect,
    }


def main():
    print("=== Test Squad Auth (diagnostyczny) ===\n")

    # 1. Logowanie przez get_session() z auth.py
    print("1. Logowanie (get_session z auth.py)...")
    session = get_session()

    cookies_before = cookie_names(session)
    print(f"\n   Cookies po zalogowaniu: {cookies_before}")

    # 2. Pobierz listę drużyn z ligi prywatnej — ta sama logika co w scraper.py
    print(f"\n2. Pobieranie drużyn z ligi (slug={LEAGUE_SLUG}, id={LEAGUE_ID})...")
    teams = fetch_league_teams(session, LEAGUE_SLUG, LEAGUE_ID)

    if not teams:
        print("   ❌ Brak drużyn w lidze — przerywam")
        sys.exit(1)

    first_slug = teams[0]["slug"]
    print(f"   ✅ Pierwsza drużyna: {first_slug} (pozycja {teams[0].get('position', '?')})")

    # 3. Test składu PRZED wejściem na stronę główną
    print(f"\n3. Test GET /user-team/view/{first_slug} — PRZED stroną główną:")
    result_before = test_team_view(session, first_slug, "PRZED")

    cookies_before_main = cookie_names(session)

    # 4. GET strona główna
    print(f"\n4. GET {BASE_URL}/ (strona główna)...")
    resp_main = session.get(BASE_URL, headers=BROWSER_HEADERS, timeout=15)
    print(f"   status_code: {resp_main.status_code}")
    print(f"   final_url:   {resp_main.url}")

    cookies_after_main = cookie_names(session)
    new_cookies = [c for c in cookies_after_main if c not in cookies_before_main]
    print(f"\n   Cookies PO stronie głównej: {cookies_after_main}")
    print(f"   NOWE cookies: {new_cookies if new_cookies else '(brak)'}")

    # 5. Test składu PO stronie głównej
    print(f"\n5. Test GET /user-team/view/{first_slug} — PO stronie głównej:")
    result_after = test_team_view(session, first_slug, "PO")

    # 6. Podsumowanie
    print("\n" + "=" * 60)
    print("PODSUMOWANIE")
    print("=" * 60)

    def summarize(result, label):
        success = (
            result["status_code"] == 200
            and result["has_squad"]
            and not result["is_login_redirect"]
        )
        redirect = result["is_login_redirect"]
        if success:
            status = "SUKCES (200 + $squad.push)"
        elif redirect:
            status = "REDIRECT → prawdopodobnie login"
        else:
            status = (
                f"NIEPOWODZENIE "
                f"(HTTP {result['status_code']}, "
                f"$squad.push={result['has_squad']})"
            )
        print(f"   {label} stroną główną: [{status}]")

    summarize(result_before, "PRZED")
    summarize(result_after, "PO")
    print()


if __name__ == "__main__":
    main()
