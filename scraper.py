"""
scraper.py
Minimalny scraper uruchamiany z GitHub Actions.
Generuje prognozy Gemini (rabbti + Tlinf) i wysyła je na Discord przed kolejką.
"""
import os
import requests
from discord_notify import send_pre_round


def call_gemini(prompt: str, system: str, temperature: float) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "(Brak GEMINI_API_KEY — tekst testowy)"

    model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 600,
        },
        "systemInstruction": {"parts": [{"text": system}]},
    }

    r = requests.post(url, json=payload, timeout=40)
    r.raise_for_status()
    data = r.json()

    for cand in data.get("candidates", []):
        parts = cand.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        if text:
            return text.strip()

    return "(Brak treści z Gemini)"


def generate_pre_round_texts(round_number: int):
    rabbti_system = (
        "Jesteś rabbti — doświadczonym analitykiem Ekstraklasy. "
        "Opierasz się na liczbach, trendach i chłodnej ocenie ryzyka."
    )

    tlinf_system = (
        "Jesteś Tlinf — kibicem z kanapy. "
        "Lubisz niszowe, kontrowersyjne pomysły i szybkie emocje."
    )

    rabbti_prompt = (
        f"Napisz analityczną prognozę Fantasy Ekstraklasa przed kolejką {round_number}. "
        "4–6 punktów, spokojny ton, liczby i trendy."
    )

    tlinf_prompt = (
        f"Napisz emocjonalną prognozę Fantasy Ekstraklasa przed kolejką {round_number}. "
        "4–6 punktów, odważne i niszowe typy."
    )

    rabbti = call_gemini(rabbti_prompt, rabbti_system, temperature=0.5)
    tlinf = call_gemini(tlinf_prompt, tlinf_system, temperature=0.9)

    return rabbti, tlinf


def main():
    round_number = int(os.environ.get("NEXT_ROUND", "1"))

    rabbti_text, tlinf_text = generate_pre_round_texts(round_number)

    send_pre_round(
        round_number=round_number,
        rabbti_text=rabbti_text,
        tlinf_text=tlinf_text,
    )


if __name__ == "__main__":
    main()
