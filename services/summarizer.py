import logging
from services.ai_chat import chat_completion

log = logging.getLogger(__name__)


def summarize_opportunity(title: str, description: str, amount: str = "", deadline: str = "") -> str:
    fallback = description[:300] if description else title

    if not description or len(description) < 30:
        return fallback

    prompt = f"""Summarize this funding opportunity in 2-3 simple sentences that anyone can understand.
Include: what it's for, who can apply, how much money, and any deadline.

Title: {title}
Description: {description[:1000]}
Amount: {amount or 'Not specified'}
Deadline: {deadline or 'Not specified'}

Write a clear, simple summary:"""

    messages = [{"role": "user", "content": prompt}]
    result = chat_completion(messages, max_tokens=200)

    if "temporarily" in result.lower() and "busy" in result.lower():
        return fallback
    return result
