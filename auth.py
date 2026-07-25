"""
auth.py - logowanie do fantasy.ekstraklasa.org przez OAuth 2.0 + PKCE.
Nowy flow (2026/27): api.id.ekstraklasa.org → id.ekstraklasa.org → PHPSESSID
Stary flow (AES + wicket-api) usunięty.
"""
import base64
import hashlib
import os
import sys
import urllib.parse
import requests

from config import (
    FANTASY_EMAIL, FANTASY_PASSWORD,
    BASE_URL, HEADERS,
)

# Stałe OAuth
COGNITO_BASE = "https://id.ekstraklasa.org"
COGNITO_API  = "https://api.id.ekstraklasa.org"
CLIENT_ID    = "esa-fantasy-019eb5ae177d703c8f736a11594aa705"
REDIRECT_URI = f"{BASE_URL}/login/check-green-sso"
SCOPE        = "profile"


def _pkce_pair():
    """Generuje parę code_verifier / code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(
        os.urandom(32)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b'=').decode()
    return verifier, challenge


def _random_state():
    """Losowy state dla OAuth."""
    return base64.urlsafe_b64encode(
        os.urandom(8)).rstrip(b'=').decode()


def login(session: requests.Session) -> bool:
    """
    Loguje się do fantasy.ekstraklasa.org przez OAuth 2.0 + PKCE.
    Po sukcesie session.cookies zawiera prawdziwy PHPSESSID.
    Zwraca True jeśli PHPSESSID został ustawiony, False przy błędzie.
    """

    # KROK 1: Pobierz authorization_token przez password grant
    print("   🔐 Krok 1: Pobieranie authorization_token...")
    try:
        resp = session.post(
            f"{COGNITO_API}/v1/authorization_token",
            json={
                "email": FANTASY_EMAIL,
                "password": FANTASY_PASSWORD,
                "redirect_uri": REDIRECT_URI,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ❌ authorization_token HTTP {resp.status_code}: "
                  f"{resp.text[:200]}")
            return False
        auth_token = resp.json().get("authorization_token")
        if not auth_token:
            print(f"   ❌ Brak authorization_token w odpowiedzi: "
                  f"{resp.text[:200]}")
            return False
        print(f"   ✅ authorization_token: {auth_token[:20]}...")
    except Exception as e:
        print(f"   ❌ Błąd krok 1: {e}")
        return False

    # KROK 2: OAuth authorize z PKCE → redirect z ?code=
    print("   🔐 Krok 2: OAuth authorize (PKCE)...")
    verifier, challenge = _pkce_pair()
    state = _random_state()
    try:
        resp = session.get(
            f"{COGNITO_BASE}/oauth/authorize",
            params={
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": SCOPE,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "authorization_token": auth_token,
            },
            allow_redirects=False,
            timeout=15,
        )
        location = resp.headers.get("Location", "")
        if resp.status_code not in (302, 301) or not location:
            print(f"   ❌ Oczekiwano redirect, dostano HTTP "
                  f"{resp.status_code}")
            return False

        # Wyciągnij code z Location
        parsed = urllib.parse.urlparse(location)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        returned_state = params.get("state", [None])[0]

        if not code:
            print(f"   ❌ Brak 'code' w redirect: {location[:200]}")
            return False
        if returned_state != state:
            print(f"   ❌ State mismatch: {returned_state} != {state}")
            return False
        print(f"   ✅ code: {code[:20]}...")
    except Exception as e:
        print(f"   ❌ Błąd krok 2: {e}")
        return False

    # KROK 3: check-green-sso → ustawia PHPSESSID
    print("   🔐 Krok 3: check-green-sso → PHPSESSID...")
    try:
        resp = session.get(
            f"{BASE_URL}/login/check-green-sso",
            params={"code": code, "state": state},
            allow_redirects=True,
            timeout=15,
        )
        phpsessid = session.cookies.get("PHPSESSID", "")
        if not phpsessid:
            print("   ❌ /login/check-green-sso nie ustawiło PHPSESSID")
            return False
        print(f"   ✅ Zalogowano! PHPSESSID: {phpsessid[:20]}...")
        return True
    except Exception as e:
        print(f"   ❌ Błąd krok 3: {e}")
        return False


def get_session() -> requests.Session:
    """Tworzy sesję HTTP i loguje się. Kończy proces przy błędzie."""
    session = requests.Session()
    session.headers.update(HEADERS)
    if not login(session):
        print("❌ Logowanie nieudane — kończę")
        sys.exit(1)
    return session
