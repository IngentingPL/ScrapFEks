"""
discord_notify.py
Proste wysyłanie powiadomień Discord + wsparcie dla prognoz AI przed kolejką
(rabbti i Tlinf)
"""
import json
import os
import urllib.request
import urllib.error

WEBHOOK_TIMEOUT = 10


def _send_content(webhook_url: str, content: str) -> bool:
    data = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT)
        return True
    except urllib.error.URLError as e:
        print("Discord error:", e)
        return False


def _split_text(text: str, max_len: int = 1900):
    parts = []
    remaining = text.strip()
    while len(remaining) > max_len:
        cut = remaining.rfind("
", 0, max_len)
        if cut == -1:
            cut = max_len
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _send_ai_section(webhook_url: str, title: str, text: str):
    if not text:
        return
    parts = _split_text(text)
    for i, part in enumerate(parts, start=1):
        header = title if len(parts) == 1 else f"{title} ({i}/{len(parts)})"
        _send_content(webhook_url, f"{header}
{part}")


def send_pre_round(
    round_number: int,
    rabbti_text: str | None,
    tlinf_text: str | None,
):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("Brak DISCORD_WEBHOOK_URL")
        return

    _send_content(
        webhook_url,
        f"📊 **Fantasy Ekstraklasa — zapowiedź kolejki {round_number}**",
    )

    if rabbti_text:
        _send_ai_section(
            webhook_url,
            f"🔍 **rabbti — prognoza analityka przed K{round_number}**",
            rabbti_text,
        )

    if tlinf_text:
        _send_ai_section(
            webhook_url,
            f"🛋️ **Tlinf — prognoza kibica z kanapy przed K{round_number}**",
            tlinf_text,
        )
