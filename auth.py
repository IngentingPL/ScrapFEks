"""
auth.py - logowanie do fantasy.ekstraklasa.org (AES + SSO).
Krytyczna część projektu - błąd tutaj zatrzymuje cały scraper.
"""
import base64
import hashlib
import sys
import requests
from urllib.parse import quote
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from Crypto.Random import get_random_bytes
from config import (
    FANTASY_EMAIL, FANTASY_PASSWORD, APPLICATION_ID,
    LOGIN_API_URL, TOKEN_CREATE_URL, BASE_URL,
    LOGIN_SSO_URL, HEADERS,
)


def cryptojs_aes_encrypt(plaintext: str, passphrase: str) -> str:
    """
    Szyfruje tekst kompatybilnie z CryptoJS.AES.encrypt(text, passphrase).
    Używa OpenSSL EVP_BytesToKey (MD5) do wyprowadzenia klucza i IV.
    Zwraca base64 string w formacie: "Salted__" + salt + ciphertext.
    """
    salt = get_random_bytes(8)

    # EVP_BytesToKey z MD5 — kompatybilne z CryptoJS
    key_iv = b""
    prev = b""
    while len(key_iv) < 48:  # 32 bytes key + 16 bytes IV
        prev = hashlib.md5(prev + passphrase.encode("utf-8") + salt).digest()
        key_iv += prev

    key = key_iv[:32]
    iv = key_iv[32:48]

    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))

    result = base64.b64encode(b"Salted__" + salt + ciphertext).decode("utf-8")
    return result


def login(session: requests.Session) -> bool:
    """
    Automatycznie loguje się do Fantasy Ekstraklasa.
    
    Flow:
    1. POST email+hasło → wicket API → dostajemy tokeny
    2. POST tokeny → fantasy.ekstraklasa.org/login-sso → dostajemy sesję
    """
    if not FANTASY_EMAIL or not FANTASY_PASSWORD:
        print("❌ Brak danych logowania!")
        print("   Ustaw zmienne środowiskowe FANTASY_EMAIL i FANTASY_PASSWORD")
        print("   lub dodaj je jako GitHub Secrets.")
        return False

    print(f"🔐 Logowanie jako {FANTASY_EMAIL}...")

    # Krok 1: Pobranie tokenów z wicket API
    login_payload = {
        "email": FANTASY_EMAIL,
        "password": FANTASY_PASSWORD,
        "fan_application_sub": APPLICATION_ID,
        "fk_dict_device_type_id": 1,
    }

    try:
        resp = session.post(LOGIN_API_URL, json=login_payload, timeout=30)
        if resp.status_code != 201:
            print(f"   ❌ Błąd logowania (krok 1): HTTP {resp.status_code}")
            print(f"   Odpowiedź: {resp.text[:200]}")
            return False

        token_data = resp.json()
        access_token = token_data.get("token")

        if not access_token:
            print("   ❌ Brak tokenu w odpowiedzi!")
            return False

        print("   ✅ Tokeny pobrane")

    except Exception as e:
        print(f"   ❌ Błąd połączenia z API logowania: {e}")
        return False

    # Krok 2: Szyfrowanie tokenu (CryptoJS.AES.encrypt kompatybilne)
    id_token = token_data.get("id_token", "")
    encrypted = cryptojs_aes_encrypt(access_token, "secret")
    encrypted_urlencoded = quote(encrypted, safe="")
    print("   ✅ Token zaszyfrowany")

    # Krok 3: Tworzenie tokenu connect — POST /p/anonymous/token/create
    try:
        create_payload = {
            "token_text": encrypted_urlencoded,
            "fan_application_sub": APPLICATION_ID,
        }
        resp = session.post(
            TOKEN_CREATE_URL,
            json=create_payload,
            headers={
                "Authorization": id_token,
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://konto.ekstraklasa.org",
                "Referer": "https://konto.ekstraklasa.org/",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"   ❌ Błąd tworzenia tokenu connect: HTTP {resp.status_code}")
            return False  # krytyczny błąd – bez tokenu connect nie można się zalogować

        create_data = resp.json()
        connect_hash = create_data.get("token") or create_data.get("hash") or create_data.get("code")

        if not connect_hash:
            print("   ❌ Brak connect_hash w odpowiedzi token/create – nie można dokończyć logowania")
            print(f"   🔍 token/create response keys: {list(create_data.keys())}")
            print(f"   🔍 token/create response (500 znaków): {str(create_data)[:500]}")
            return False  # krytyczny błąd – bez connect_hash /connect nie zadziała

        print(f"   ✅ Connect hash: {str(connect_hash)[:50]}...")
        print(f"   🔍 token/create full response keys: {list(create_data.keys())}")

    except Exception as e:
        print(f"   ❌ Błąd token/create: {e}")
        return False  # krytyczny błąd – token/create się nie powiodło

    # Krok 4: GET /connect?g4t7hjq3rcyb0s2m={hash} — ustawia PHPSESSID
    try:
        # Tymczasowo użyj czystych headerów przeglądarki (bez X-Requested-With)
        saved_headers = dict(session.headers)
        session.headers.clear()
        browser_hdrs = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9",
        }
        session.headers.update(browser_hdrs)

        # Wyczyść ciasteczka dla domeny – symuluj PIERWSZĄ wizytę na stronie
        # (w prawdziwej przeglądarce /connect to pierwszy request na fantasy.ekstraklasa.org,
        #  więc serwer ustawia świeże PHPSESSID. Fake cookie blokowałoby to.)
        session.cookies.clear(domain="fantasy.ekstraklasa.org")
        print("   🔍 Cookies przed /connect (wyczyszczone):", dict(session.cookies))

        # Teraz GET /connect z hashem
        resp = session.get(
            f"{BASE_URL}/connect",
            params={"g4t7hjq3rcyb2s0m": connect_hash},
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=30,
            allow_redirects=True,
        )

        # Debug: /connect – pokaż redirect Location i Set-Cookie
        print(f"   🔍 /connect final status: {resp.status_code}, url: {resp.url}")
        final_set_cookie = resp.headers.get("Set-Cookie", "")
        if final_set_cookie:
            print(f"   🔍 /connect final Set-Cookie: {final_set_cookie[:200]}")
        if resp.history:
            print(f"   🔍 /connect redirect chain ({len(resp.history)} hops):")
            for h in resp.history:
                location = h.headers.get("Location", "")
                set_cookie = h.headers.get("Set-Cookie", "")
                print(f"      {h.status_code} → Location: {location[:120]}")
                if set_cookie:
                    print(f"         Set-Cookie: {set_cookie[:200]}")
        print(f"   🔍 PHPSESSID po /connect: {session.cookies.get('PHPSESSID', '')!r}")
        print(f"   🔍 Wszystkie cookies po /connect: {dict(session.cookies)}")

    except Exception as e:
        print(f"   ❌ Błąd /connect: {e}")
        session.headers.clear()
        session.headers.update(saved_headers)
        return False  # krytyczny błąd – /connect się nie powiodło

    # Krok 5: POST /login-sso — autoryzuje sesję (prawdopodobnie ustawia PHPSESSID)
    try:
        resp = session.post(
            LOGIN_SSO_URL,
            data={"id_token": id_token},
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/connect",
            },
            timeout=30,
            allow_redirects=True,
        )
        # Sprawdź czy serwer nie odpowiedział błędem (np. 403/500)
        if not resp.ok:
            session.headers.clear()
            session.headers.update(saved_headers)
            print(f"   ❌ Login SSO nie powiódł się: HTTP {resp.status_code}")
            return False

        print(f"   🔍 /login-sso final status: {resp.status_code}, url: {resp.url}")
        final_set_cookie = resp.headers.get("Set-Cookie", "")
        if final_set_cookie:
            print(f"   🔍 /login-sso final Set-Cookie: {final_set_cookie[:200]}")
        if resp.history:
            print(f"   🔍 /login-sso redirect chain ({len(resp.history)} hops):")
            for h in resp.history:
                location = h.headers.get("Location", "")
                set_cookie = h.headers.get("Set-Cookie", "")
                print(f"      {h.status_code} → Location: {location[:120]}")
                if set_cookie:
                    print(f"         Set-Cookie: {set_cookie[:200]}")

        # Guard: PHPSESSID musi być ustawiony i nie może być fake wartością
        phpsessid_final = session.cookies.get("PHPSESSID", "")
        if not phpsessid_final or phpsessid_final == "init_session_000":
            print(f"   ❌ PHPSESSID nie został ustawiony (wartość: {phpsessid_final!r})")
            session.headers.clear()
            session.headers.update(saved_headers)
            return False

        # Przywróć oryginalne headers sesji
        session.headers.clear()
        session.headers.update(saved_headers)

        print(f"   ✅ Zalogowano! PHPSESSID: {phpsessid_final[:20]}...")
        return True

    except Exception as e:
        print(f"   ❌ Błąd SSO: {e}")
        session.headers.clear()
        session.headers.update(saved_headers)
        return False


def get_session() -> requests.Session:
    """Tworzy sesję HTTP i loguje się automatycznie."""
    session = requests.Session()
    session.headers.update(HEADERS)

    if not login(session):
        print("\n❌ Nie udało się zalogować. Sprawdź dane logowania.")
        sys.exit(1)

    return session
