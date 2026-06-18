"""
ai_client.py - wspólny klient API AI (DeepSeek + Gemini).
Używany przez newsletter.py i discord_notify.py, żeby nie powielać
tej samej logiki wywołania HTTP w dwóch miejscach.
"""
import json
import urllib.request
import urllib.error

DEEPSEEK_MODEL = "deepseek-chat"
GEMINI_MODEL = "gemini-2.5-flash"
DEEPSEEK_TIMEOUT = 30
GEMINI_TIMEOUT = 30
GEMINI_THINKING_BUDGET = 0
DEEPSEEK_HEADERS = {"Content-Type": "application/json"}
AI_TEMPERATURE = 0.7  # temperatura modeli AI - im wyżej, tym bardziej "kreatywne" odpowiedzi
ERROR_PREVIEW_LEN = 300  # ile znaków błędu HTTP pokazać w komunikacie


def call_deepseek(prompt: str, api_key: str, max_tokens: int = 1500) -> dict:
    """Wysyła prompt do DeepSeek API. Zwraca surowy JSON response."""
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": AI_TEMPERATURE,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={**DEEPSEEK_HEADERS, "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=DEEPSEEK_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek HTTP {e.code}: {body[:ERROR_PREVIEW_LEN]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"DeepSeek URL error: {e.reason}")


def call_gemini(prompt: str, api_key: str, max_tokens: int = 1500) -> dict:
    """Wysyła prompt do Gemini API. Zwraca surowy JSON response."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": AI_TEMPERATURE,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingBudget": GEMINI_THINKING_BUDGET},
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini HTTP {e.code}: {body[:ERROR_PREVIEW_LEN]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Gemini URL error: {e.reason}")
