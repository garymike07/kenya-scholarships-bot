import logging
from services.ai_chat import chat_completion

log = logging.getLogger(__name__)


def summarize_opportunity(title: str, description: str, amount: str = "", deadline: str = "") -> str:
    fallback = description[:300] if description else title

    if not description or len(description) < 30:
        return fallback

    prompt = f"""Summarize this funding opportunity in 2-3 simple sentences.
Title: {title}
Description: {description[:500]}
Amount: {amount or 'Not specified'}
Deadline: {deadline or 'Not specified'}
Write a clear summary:"""

    messages = [{"role": "user", "content": prompt}]
    result = chat_completion(messages, max_tokens=150)

    if not result:
        return fallback
    return result
