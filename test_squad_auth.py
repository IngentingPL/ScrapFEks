"""
test_squad_auth.py — tymczasowy test diagnostyczny: warianty nagłówków dla /user-team/view/{slug}.
Używa prawdziwych funkcji z auth.py.
NIE commituje, NIE pushuje, NIE woła discord_notify.
"""
import requests
from config import BASE_URL, BROWSER_HEADERS
from auth import get_session

SLUG = "lubliniankakonskie"
LEAGUE_SLUG = "fmforumdiscord-iii"


def run_variant(session, name, headers):
    """Wykonuje GET /user-team/view/{slug} i zwraca wynik."""
    url = f"{BASE_URL}/user-team/view/{SLUG}"
    resp = session.get(url, headers=headers, timeout=15)

    is_redirect = "login" in resp.url.lower()
    has_squad = "$squad.push" in resp.text
    preview = resp.text[:150].replace("\n", "\\n")

    return {
        "name": name,
        "status_code": resp.status_code,
        "is_redirect": is_redirect,
        "has_squad": has_squad,
        "preview": preview,
    }


def main():
    print("=== Eksperyment: warianty nagłówków dla /user-team/view/ ===\n")
    print(f"Slug: {SLUG}")
    print(f"Liga: {LEAGUE_SLUG}\n")

    # Logowanie
    print("Logowanie (get_session)...")
    session = get_session()
    print()

    # Definicje wariantów
    variants = [
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
                "Referer": f"https://fantasy.ekstraklasa.org/league/{LEAGUE_SLUG}",
            },
        ),
        (
            "D (-Upgrade-IR +Referer league)",
            {
                **BROWSER_HEADERS,
                "Referer": f"https://fantasy.ekstraklasa.org/league/{LEAGUE_SLUG}",
            },
        ),
        (
            "E (+X-Requested-With +Referer league)",
            {
                **BROWSER_HEADERS,
                "Upgrade-Insecure-Requests": "1",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://fantasy.ekstraklasa.org/league/{LEAGUE_SLUG}",
            },
        ),
    ]

    results = []

    for name, headers in variants:
        print(f"--- {name} ---")
        # pokaż tylko niestandardowe headery (bez UA/Accept/Language)
        relevant = {
            k: v for k, v in headers.items()
            if k not in ("User-Agent", "Accept", "Accept-Language")
        }
        print(f"    Headery: {relevant}")

        r = run_variant(session, name, headers)
        results.append(r)

        print(f"    status_code:  {r['status_code']}")
        print(f"    redirect:     {r['is_redirect']}")
        print(f"    $squad.push:  {r['has_squad']}")
        print(f"    preview:      {r['preview']}")
        print()

    # Tabela porównawcza
    print("=" * 90)
    print("TABELA PORÓWNAWCZA")
    print("=" * 90)
    print(f"{'Wariant':<38} {'Status':>6} {'Redirect':>8} {'$squad':>7}  Preview")
    print("-" * 90)
    for r in results:
        redirect = "TAK" if r["is_redirect"] else "nie"
        squad = "TAK" if r["has_squad"] else "nie"
        preview_short = r["preview"][:55]
        print(
            f"{r['name']:<38} {r['status_code']:>6} "
            f"{redirect:>8} {squad:>7}  {preview_short}"
        )
    print()


if __name__ == "__main__":
    main()
