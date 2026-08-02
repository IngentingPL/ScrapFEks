"""
test_squad_auth.py — tymczasowy test diagnostyczny: warianty nagłówków + porównanie własna vs cudza drużyna.
Używa prawdziwych funkcji z auth.py.
NIE commituje, NIE pushuje, NIE woła discord_notify.
"""
import sys
import requests
from config import BASE_URL, BROWSER_HEADERS, RANKING_HEADERS, LEAGUE_SLUG, LEAGUE_ID
from auth import get_session

SLUG_CUDZA = "lubliniankakonskie"
LEAGUE_SLUG_LOCAL = LEAGUE_SLUG


def cookie_names(session):
    return sorted(c.name for c in session.cookies)


def fetch_league_teams_with_names(session):
    """
    Pobiera listę drużyn z ligi prywatnej, zwraca listę {slug, name, position}.
    Używa tego samego endpointu co squads.fetch_league_teams().
    """
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
            name = team.get("name", "")  # nazwa wyświetlana
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


def run_variant(session, slug, name, headers):
    """Wykonuje GET /user-team/view/{slug} i zwraca wynik."""
    url = f"{BASE_URL}/user-team/view/{slug}"
    resp = session.get(url, headers=headers, timeout=15)

    is_redirect = "login" in resp.url.lower()
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
    print("=== Eksperyment: warianty nagłówków + własna vs cudza ===\n")

    # Logowanie
    print("Logowanie (get_session)...")
    session = get_session()
    print()

    # Warianty nagłówków — tylko A (baseline) dla porównania
    headers_a = {
        **BROWSER_HEADERS,
        "Upgrade-Insecure-Requests": "1",
    }

    # ----- CUDZA drużyna (lubliniankakonskie) -----
    print("=== CUDZA drużyna ===")
    r_cudza = run_variant(session, SLUG_CUDZA, "CUDZA (lubliniankakonskie)", headers_a)
    print(f"    status_code:  {r_cudza['status_code']}")
    print(f"    redirect:     {'TAK' if r_cudza['is_redirect'] else 'nie'}")
    print(f"    $squad.push:  {'TAK' if r_cudza['has_squad'] else 'nie'}")
    print(f"    preview:      {r_cudza['preview']}")
    print()

    # ----- WŁASNA drużyna (Tokusatsu Soccer) -----
    league_teams = fetch_league_teams_with_names(session)
    print()

    # Szukaj "Tokusatsu Soccer" po nazwie
    własna = None
    for t in league_teams:
        if t["name"].lower() == "tokusatsu soccer":
            własna = t
            break

    if własna is None:
        print("❌ Nie znaleziono drużyny 'Tokusatsu Soccer' w lidze.")
        print("   Pełna lista drużyn w lidze:")
        for i, t in enumerate(league_teams):
            print(f"   {i+1}. slug={t['slug']:<40} name={t.get('name', '(brak)')}")
        sys.exit(1)

    print(f"Znaleziono: slug={własna['slug']}, name={własna['name']}, position={własna.get('position', '?')}")
    print()

    print("=== WŁASNA drużyna ===")
    r_wlasna = run_variant(session, własna["slug"], f"WŁASNA ({własna['name']})", headers_a)
    print(f"    status_code:  {r_wlasna['status_code']}")
    print(f"    redirect:     {'TAK' if r_wlasna['is_redirect'] else 'nie'}")
    print(f"    $squad.push:  {'TAK' if r_wlasna['has_squad'] else 'nie'}")
    print(f"    preview:      {r_wlasna['preview']}")
    print()

    # ----- Podsumowanie -----
    print("=" * 60)
    print("PORÓWNANIE: WŁASNA vs CUDZA drużyna")
    print("=" * 60)
    for r in [r_wlasna, r_cudza]:
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
