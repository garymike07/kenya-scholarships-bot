import httpx
import time
import logging
from config import OPENROUTER_API_KEY

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]
_model_idx = 0
_rate_limited_until = 0


def summarize_opportunity(title: str, description: str, amount: str = "", deadline: str = "") -> str:
    global _model_idx, _rate_limited_until

    fallback = description[:300] if description else title

    if not OPENROUTER_API_KEY:
        return fallback

    if time.time() < _rate_limited_until:
        return fallback

    prompt = f"""Summarize this funding opportunity in 2-3 simple sentences that anyone can understand.
Include: what it's for, who can apply, how much money, and any deadline.

Title: {title}
Description: {description[:1000]}
Amount: {amount or 'Not specified'}
Deadline: {deadline or 'Not specified'}

Write a clear, simple summary:"""

    time.sleep(2)

    for attempt in range(len(MODELS)):
        model = MODELS[(_model_idx + attempt) % len(MODELS)]
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 200,
                        "temperature": 0.3,
                    },
                )
                if resp.status_code == 429:
                    log.warning("Rate limited on %s, trying next model...", model)
                    _model_idx = (_model_idx + 1) % len(MODELS)
                    time.sleep(5)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                _model_idx = (_model_idx + attempt) % len(MODELS)
                if content:
                    return content.strip()
                return fallback
        except Exception as e:
            log.error("Summarization error on %s: %s", model, e)
            time.sleep(2)

    _rate_limited_until = time.time() + 300
    log.warning("All models rate limited, pausing summarization for 5 minutes")
    return fallback
