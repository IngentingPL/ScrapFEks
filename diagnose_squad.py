#!/usr/bin/env python3
"""
diagnose_squad.py – tymczasowy skrypt diagnostyczny.
Sprawdza strukturę HTML strony /user-team/view/... w nowym sezonie 2026/27.
Uruchamiany tylko przez diagnostic.yml, nie modyfikuje niczego.
"""
import re
from auth import get_session
from config import BASE_URL

def main():
    session = get_session()
    slug = "tokusatsu-soccer"
    url = f"{BASE_URL}/user-team/view/{slug}"

    print(f"🔍 Pobieram: {url}")
    resp = session.get(url, timeout=30)
    html = resp.text

    print(f"Status: {resp.status_code}")
    print(f"Długość HTML: {len(html)}")
    print(f"Final URL: {resp.url}")
    print()

    # --- Wzorce JS/JSON ---
    patterns = [
        r"squad\.push",
        r"subs\.push",
        r"\$squad",
        r"\$subs",
        r"\.push\(",
        r'"name"\s*:\s*"',
        r"app\.Pitch",
        r"window\.__INITIAL_STATE__",
        r"__NEXT_DATA__",
        r"self\.__next_f",
        r'"id"\s*:\s*\d+',
        r"fcPitchSensor",
        r"data-players",
        r"data-squad",
        r"React",
        r"fetch\(",
    ]
    print("--- Wzorce regex ---")
    for p in patterns:
        matches = re.findall(p, html)
        if matches:
            print(f"  {p}: {len(matches)} trafień")
        else:
            print(f"  {p}: BRAK")

    # --- Tagi <script src> ---
    scripts = re.findall(r'<script[^>]*src="([^"]+)"[^>]*>', html)
    print(f"\n--- <script src> ({len(scripts)}) ---")
    for s in scripts[:25]:
        print(f"  {s}")

    # --- Fragmenty HTML wokół kluczowych słów ---
    for marker in ["self.__next_f", "__NEXT_DATA__", "player", "squad", "lineup", "roster", "Pitch"]:
        idx = html.find(marker)
        if idx > 0:
            snippet = html[max(0, idx - 80):idx + 600]
            # obetnij zeby nie bylo za duzo
            if len(snippet) > 700:
                snippet = snippet[:700] + "..."
            print(f"\n--- Fragment przy '{marker}' (offset {idx}) ---")
            print(snippet)

    # --- Nazwiska graczy (JSON) ---
    names = re.findall(r'"name"\s*:\s*"([^"]+)"', html)
    if names:
        print(f"\n--- Nazwiska graczy ({len(names)}) ---")
        for n in names[:15]:
            print(f"  {n}")
    else:
        print("\n--- Nazwiska graczy: BRAK (brak JSON z name) ---")

    # --- ID graczy ---
    ids = re.findall(r'"(?:id|playerId|player_id)"\s*:\s*(\d+)', html)
    if ids:
        print(f"\n--- ID graczy ({len(ids)}) ---")
        for i in ids[:15]:
            print(f"  {i}")

    # --- Wszystkie wywołania .push() ---
    pushes = re.findall(r'(\w+(?:\.\w+)*)\.push\(', html)
    if pushes:
        print(f"\n--- Wszystkie wywołania .push() ({len(pushes)}) ---")
        for p in sorted(set(pushes)):
            print(f"  {p}")

    # --- Szukaj inline <script> które mogą zawierać dane ---
    inline_scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    print(f"\n--- Inline <script> tagi: {len(inline_scripts)} ---")
    for i, s in enumerate(inline_scripts):
        size = len(s.strip())
        if size > 100:
            preview = s.strip()[:300]
            print(f"  [{i}] size={size}: {preview}...")

    # --- Sprawdź czy są tagi z id z danymi ---
    for tag_id in ["__NEXT_DATA__", "__NEXT", "initial-state", "app-data"]:
        m = re.search(rf'<[^>]*id="{tag_id}"[^>]*>(.*?)</', html, re.DOTALL)
        if m:
            content = m.group(1)[:500]
            print(f"\n--- tag id='{tag_id}' ---")
            print(content)

    print("\n✅ Diagnostyka zakończona")


if __name__ == "__main__":
    main()
