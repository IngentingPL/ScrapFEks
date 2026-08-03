"""
auth.py - logowanie do fantasy.ekstraklasa.org przez OAuth 2.0 + PKCE.
Flow (2026/27): api.id.ekstraklasa.org → id.ekstraklasa.org → PHPSESSID

Flow:
  0. GET fantasy.ekstraklasa.org/login (allow_redirects=False)
     → parsujemy z Location: client_id, code_challenge, code_challenge_method,
       state, redirect_uri, scope (WYGENEROWANE PRZEZ SERWER fantasy, nie nasze)
  1. POST /oauth/token (password grant, sso-client)
     → access_token + refresh_token
  2. POST /v1/authorization_token (authorization_code grant, esa-fantasy,
     Bearer access_token z kroku 1, PKCE z kroku 0)
     → authorization_token
  3. GET api.id.ekstraklasa.org/oauth/authorize?authorization_token=...
     → 302 do /login/check-green-sso?code=...&state=...
  4. GET /login/check-green-sso?code=...&state=...
     → 302 z Set-Cookie: PHPSESSID
"""
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


def login(session: requests.Session) -> bool:
    """
    Loguje się do fantasy.ekstraklasa.org przez OAuth 2.0 + PKCE.
    Po sukcesie session.cookies zawiera prawdziwy PHPSESSID.
    Zwraca True jeśli PHPSESSID został ustawiony, False przy błędzie.
    """

    # KROK 0: GET /login → wyciągnij prawdziwe PKCE z redirectu serwera
    #         Serwer fantasy.ekstraklasa.org generuje code_challenge i state,
    #         które są częścią sesji logowania. Użycie własnych wartości
    #         skutkuje odrzuceniem przez serwer przy dostępie do /user-team/view/.
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
            return False

        print(f"   Location: {location[:120]}...")
        parsed = urllib.parse.urlparse(location)
        if "id.ekstraklasa.org" not in parsed.netloc:
            print(f"   ❌ Nieoczekiwany redirect (nie id.ekstraklasa.org): "
                  f"{parsed.netloc}")
            print(f"   Pełny Location: {location}")
            return False

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
            return False

        print(f"   ✅ client_id:            {srv_client_id}")
        print(f"   ✅ code_challenge:       {srv_challenge[:20]}...")
        print(f"   ✅ code_challenge_method:{srv_challenge_method or '(brak)'}")
        print(f"   ✅ state:               {srv_state[:20]}...")
        print(f"   ✅ redirect_uri:        {srv_redirect_uri[:60]}...")
        print(f"   ✅ scope:               {srv_scope}")
    except Exception as e:
        print(f"   ❌ Błąd krok 0: {e}")
        return False

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
                "username": FANTASY_EMAIL,
                "password": FANTASY_PASSWORD,
                "scope": srv_scope,
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
    #         Używamy PKCE od serwera (krok 0), nie generujemy własnego!
    print("   🔐 Krok 2: Authorization code grant (esa-fantasy + Bearer)...")
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
        if returned_state != srv_state:
            print(f"   ❌ State mismatch: {returned_state} != {srv_state}")
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
            params={"code": code, "state": srv_state},
            allow_redirects=True,
            timeout=15,
        )
        phpsessid = session.cookies.get("PHPSESSID", "")
        if not phpsessid:
            print("   ❌ /login/check-green-sso nie ustawiło PHPSESSID")
            return False
        print(f"   ✅ Zalogowano! PHPSESSID: {phpsessid[:20]}...")

        # Cookie wymagany przez serwer do dostępu do stron drużyn
        # Normalnie ustawiany przez JavaScript po zalogowaniu
        session.cookies.set(
            "premium-show", "1",
            domain="fantasy.ekstraklasa.org",
            path="/",
        )
        print("   ✅ Cookie premium-show=1 ustawiony")
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
