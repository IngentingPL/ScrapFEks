"""
auth.py - logowanie do fantasy.ekstraklasa.org przez OAuth 2.0 + PKCE.
Nowy flow (2026/27): api.id.ekstraklasa.org → id.ekstraklasa.org → PHPSESSID
Stary flow (AES + wicket-api) usunięty.

Flow (reverse-engineered z kodu JS Cognito):
  1. POST /v1/authorization_token (password grant, sso-client)
     → access_token + refresh_token
  2. Generujemy własny PKCE challenge + state
  3. POST /v1/authorization_token (authorization_code grant, esa-fantasy,
     Bearer access_token z kroku 1)
     → authorization_token
  4. GET api.id.ekstraklasa.org/oauth/authorize?authorization_token=...
     → 302 do /login/check-green-sso?code=...&state=...
  5. GET /login/check-green-sso?code=...&state=...
     → 302 z Set-Cookie: PHPSESSID
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

# Client ID dla password grant (login formularza Cognito)
SSO_CLIENT_ID = "sso-client-8aaa228311424773ac37c83b36f51a40"
# Client ID dla authorization grant (aplikacji fantasy)
FANTASY_CLIENT_ID = "esa-fantasy-019eb5ae177d703c8f736a11594aa705"

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

    # KROK 1: Password grant → access_token
    # Używa /oauth/token (standardowy Cognito endpoint),
    # NIE /v1/authorization_token (ten wymaga Bearer tokena z kroku 1).
    print("   🔐 Krok 1: Password grant (sso-client, /oauth/token)...")
    try:
        resp = session.post(
            f"{COGNITO_API}/oauth/token",
            data={
                "grant_type": "password",
                "client_id": SSO_CLIENT_ID,
                "email": FANTASY_EMAIL,
                "password": FANTASY_PASSWORD,
                "scope": SCOPE,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ❌ Password grant HTTP {resp.status_code}: "
                  f"{resp.text[:300]}")
            return False

        token_data = resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            print(f"   ❌ Brak access_token w odpowiedzi. Klucze: "
                  f"{list(token_data.keys())}")
            return False
        print(f"   ✅ access_token: {access_token[:20]}...")
    except Exception as e:
        print(f"   ❌ Błąd krok 1: {e}")
        return False

    # KROK 2: Authorization code grant (z Bearer) → authorization_token
    print("   🔐 Krok 2: Authorization code grant (esa-fantasy + Bearer)...")
    verifier, challenge = _pkce_pair()
    state = _random_state()
    try:
        resp = session.post(
            f"{COGNITO_API}/v1/authorization_token",
            json={
                "grant_type": "authorization_code",
                "client_id": FANTASY_CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "scope": SCOPE,
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
            },
            headers={
                "Authorization": f"Bearer {access_token}",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ❌ Authorization code grant HTTP {resp.status_code}: "
                  f"{resp.text[:300]}")
            return False

        auth_data = resp.json()
        authorization_token = auth_data.get("authorization_token")
        if not authorization_token:
            print(f"   ❌ Brak authorization_token. Klucze: "
                  f"{list(auth_data.keys())}")
            return False
        print(f"   ✅ authorization_token: {authorization_token[:20]}...")
    except Exception as e:
        print(f"   ❌ Błąd krok 2: {e}")
        return False

    # KROK 3: Przekaż authorization_token do OAuth authorize
    #         → redirect do /login/check-green-sso?code=...&state=...
    print("   🔐 Krok 3: OAuth authorize → redirect z code...")
    try:
        params = {
            "authorization_token": authorization_token,
            "response_type": "code",
            "client_id": FANTASY_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        resp = session.get(
            f"{COGNITO_API}/oauth/authorize",
            params=params,
            allow_redirects=False,
            timeout=15,
        )
        location = resp.headers.get("Location", "")
        if resp.status_code not in (302, 301) or not location:
            print(f"   ❌ Oczekiwano redirect, dostano HTTP "
                  f"{resp.status_code}")
            print(f"   Body: {resp.text[:200]}")
            return False

        # Wyciągnij code i state z Location
        parsed = urllib.parse.urlparse(location)
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [None])[0]
        returned_state = qs.get("state", [None])[0]

        if not code:
            print(f"   ❌ Brak 'code' w redirect: {location[:200]}")
            return False
        if returned_state != state:
            print(f"   ❌ State mismatch: {returned_state} != {state}")
            return False
        print(f"   ✅ code: {code[:20]}...")
    except Exception as e:
        print(f"   ❌ Błąd krok 3: {e}")
        return False

    # KROK 4: check-green-sso → ustawia PHPSESSID
    print("   🔐 Krok 4: check-green-sso → PHPSESSID...")
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
        print(f"   ❌ Błąd krok 4: {e}")
        return False


def get_session() -> requests.Session:
    """Tworzy sesję HTTP i loguje się. Kończy proces przy błędzie."""
    session = requests.Session()
    session.headers.update(HEADERS)
    if not login(session):
        print("❌ Logowanie nieudane — kończę")
        sys.exit(1)
    return session
