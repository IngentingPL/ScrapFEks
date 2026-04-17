"""
scraper.py
Minimalny scraper uruchamiany z GitHub Actions.
Generuje prognozy Gemini (rabbti + Tlinf) i wysyła je na Discord przed kolejką.
Wersja odporna na 503: retry + fallback model + brak wywalenia workflow.
"""

import os
import time
import random
from typing import Optional, Tuple

import requests
from discord_notify import send_pre_round


def _extract_text(data: dict) -> str:
    for candidate in data.get("candidates", []):
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts)
        if text:
            return text.strip()
    return ""


def call_gemini(prompt: str, system: str, temperature: float) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "(Brak GEMINI_API_KEY — tekst testowy)"

    primary_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    fallback_model = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
    models_to_try = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models_to_try.append(fallback_model)

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 600,
        },
        "systemInstruction": {
            "parts": [{"text": system}],
        },
    }

    last_error = None

    for model in models_to_try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )

        for attempt in range(4):
            try:
                response = requests.post(url, json=payload, timeout=45)

                if response.status_code in (500, 503, 504, 429):
                    last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                    if attempt < 3:
                        wait_s = min(20, (2 ** attempt) + random.uniform(0.5, 1.5))
                        print(
                            f"Gemini chwilowo niedostępny dla modelu {model} "
                            f"(próba {attempt + 1}/4, czekam {wait_s:.1f}s)"
                        )
                        time.sleep(wait_s)
                        continue
                    break

                response.raise_for_status()
                data = response.json()
                text = _extract_text(data)
                if text:
                    return text
                last_error = f"Brak treści w odpowiedzi modelu {model}"
                break

            except requests.RequestException as e:
                last_error = str(e)
                if attempt < 3:
                    wait_s = min(20, (2 ** attempt) + random.uniform(0.5, 1.5))
                    print(
                        f"Gemini request error dla modelu {model} "
                        f"(próba {attempt + 1}/4, czekam {wait_s:.1f}s): {e}"
                    )
                    time.sleep(wait_s)
                    continue
                break

    print(f"Gemini niedostępny — używam fallback tekstowego. Ostatni błąd: {last_error}")
    return "(Gemini chwilowo niedostępny — prognoza AI nie została wygenerowana)"


def generate_pre_round_texts(round_number: int) -> Tuple[str, str]:
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
        "Daj 1 krótki akapit i 4–6 punktów. Ton spokojny, oparty na liczbach i trendach."
    )

    tlinf_prompt = (
        f"Napisz emocjonalną prognozę Fantasy Ekstraklasa przed kolejką {round_number}. "
        "Daj 1 krótki akapit i 4–6 punktów. Dodaj odważne i niszowe typy."
    )

    rabbti = call_gemini(rabbti_prompt, rabbti_system, temperature=0.5)
    tlinf = call_gemini(tlinf_prompt, tlinf_system, temperature=0.9)

    return rabbti, tlinf


def main() -> None:
    round_number = int(os.environ.get("NEXT_ROUND", "1"))

    try:
        rabbti_text, tlinf_text = generate_pre_round_texts(round_number)
    except Exception as e:
        print(f"Błąd generowania AI: {e}")
        rabbti_text = "(Nie udało się wygenerować prognozy rabbti)"
        tlinf_text = "(Nie udało się wygenerować prognozy Tlinf)"

    send_pre_round(
        round_number=round_number,
        rabbti_text=rabbti_text,
        tlinf_text=tlinf_text,
    )


if __name__ == "__main__":
    main()
