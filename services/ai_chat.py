"""
AI engine with multi-account OpenRouter key rotation.
Key 1 = chat, Key 2 = scraper, Key 3+ = overflow. All fallback to each other.
"""
import httpx
import asyncio
import time
import threading
import logging
from config import OPENROUTER_API_KEYS

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "qwen/qwen3-4b:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "google/gemma-3-12b-it:free",
    "google/gemma-3-4b-it:free",
    "google/gemma-3n-e4b-it:free",
    "google/gemma-3n-e2b-it:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "arcee-ai/trinity-large-preview:free",
    "arcee-ai/trinity-mini:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "z-ai/glm-4.5-air:free",
    "qwen/qwen3-coder:free",
]

# Rate limit tracking: key -> expiry time (entire key blocked)
_key_limited = {}
# Per (key:model) tracking for 404s / broken models
_broken = {}
_lock = threading.Lock()

# Scraper ONLY uses the last key; chat uses all keys (scraper can't starve chat)
_num_keys = len(OPENROUTER_API_KEYS)
_chat_key_idx = 0
_scraper_key_idx = max(0, _num_keys - 1)

SYSTEM_PROMPT = """You are an AI assistant inside a Telegram bot for Kenyan citizens. You help with TWO things:

1. SCHOLARSHIPS & GRANTS: Finding fully funded scholarships, grants, and funding opportunities worldwide for Kenyans.
2. ATS RESUMES: Writing professional resumes that pass Applicant Tracking Systems.

HOW TO BEHAVE:
- Be conversational, friendly, and helpful. No commands needed - just chat naturally.
- Keep responses concise and in simple English.
- When a user wants scholarships: ask what field, level (bachelors/masters/PhD), country preference, then search the database and show results.
- When a user wants a resume: collect their info step by step (name, email, phone, location, target job, summary, experience, education, skills). Ask 1-2 questions at a time.
- When you have enough resume info, respond with EXACTLY this tag on its own line: [GENERATE_RESUME]
- When the user wants to search scholarships, respond with EXACTLY: [SEARCH: keyword] where keyword is what to search for.
- When the user wants to see latest scholarships, respond with: [SHOW_LATEST]
- When the user wants to see a specific category, respond with: [SHOW_CATEGORY: student_scholarships] or [SHOW_CATEGORY: business_grants] or [SHOW_CATEGORY: nonprofit_funding]
- When the user asks about what you can do, explain both scholarship finding and resume building clearly.
- If the user greets you, greet back warmly and explain what you can do.
- Never mention commands like /start or /search. Everything is conversational.

IMPORTANT: You MUST use the tags above when appropriate. They trigger actions in the bot."""


def _key_available(key: str) -> bool:
    return _key_limited.get(key, 0) < time.time()


def _model_broken(key: str, model: str) -> bool:
    return _broken.get(f"{key}:{model}", 0) > time.time()


def _mark_key_limited(key: str, duration: int = 60):
    with _lock:
        _key_limited[key] = time.time() + duration
    log.warning("Key ...%s rate limited for %ds", key[-8:], duration)


def _mark_model_broken(key: str, model: str):
    with _lock:
        _broken[f"{key}:{model}"] = time.time() + 3600


def _get_key_order(primary_idx: int) -> list[str]:
    if not OPENROUTER_API_KEYS:
        return []
    order = [OPENROUTER_API_KEYS[primary_idx % len(OPENROUTER_API_KEYS)]]
    for k in OPENROUTER_API_KEYS:
        if k not in order:
            order.append(k)
    return order


async def async_chat_completion(messages: list[dict], max_tokens: int = 800) -> str:
    if not OPENROUTER_API_KEYS:
        return "AI is not configured."

    key_order = _get_key_order(_chat_key_idx)

    for key in key_order:
        if not _key_available(key):
            continue

        hits_429 = 0
        for model in FREE_MODELS:
            if _model_broken(key, model):
                continue
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        OPENROUTER_URL,
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.7},
                    )
                if resp.status_code == 429:
                    hits_429 += 1
                    if hits_429 >= 3:
                        _mark_key_limited(key, 60)
                        break
                    continue
                if resp.status_code == 402:
                    _mark_key_limited(key, 86400)
                    break
                if resp.status_code == 404:
                    _mark_model_broken(key, model)
                    continue
                if resp.status_code >= 400:
                    continue
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    log.info("Chat OK key=...%s model=%s", key[-8:], model.split("/")[-1])
                    return content.strip()
            except Exception as e:
                log.error("Chat error key=...%s model=%s: %s", key[-8:], model.split("/")[-1], e)
                continue

    return ("All AI models are cooling down. Please try again in about a minute!")


def chat_completion(messages: list[dict], max_tokens: int = 800) -> str:
    """Scraper AI -- uses ONLY its dedicated key, never touches chat keys."""
    if not OPENROUTER_API_KEYS:
        return ""

    key_order = [OPENROUTER_API_KEYS[_scraper_key_idx]]

    for key in key_order:
        if not _key_available(key):
            continue

        hits_429 = 0
        for model in FREE_MODELS:
            if _model_broken(key, model):
                continue
            try:
                with httpx.Client(timeout=30) as client:
                    resp = client.post(
                        OPENROUTER_URL,
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3},
                    )
                if resp.status_code == 429:
                    hits_429 += 1
                    if hits_429 >= 3:
                        _mark_key_limited(key, 60)
                        break
                    continue
                if resp.status_code == 402:
                    _mark_key_limited(key, 86400)
                    break
                if resp.status_code == 404:
                    _mark_model_broken(key, model)
                    continue
                if resp.status_code >= 400:
                    continue
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    log.info("Scraper OK key=...%s model=%s", key[-8:], model.split("/")[-1])
                    return content.strip()
            except Exception as e:
                log.error("Scraper error key=...%s model=%s: %s", key[-8:], model.split("/")[-1], e)
                continue

    return ""


async def async_generate_ats_resume(user_data: dict) -> str:
    ud = user_data
    prompt = f"""Write a professional ATS-optimized resume based on this information.
The resume MUST follow this exact structure:

FULL NAME (centered, uppercase)
Email | Phone | Location

PROFESSIONAL SUMMARY
(2-3 sentences summarizing qualifications)

WORK EXPERIENCE
Job Title - Company Name
Dates
* Achievement using action verbs and metrics

EDUCATION
Degree - Institution Name
Dates

SKILLS
Skill 1, Skill 2, Skill 3

---
User Information:
Name: {ud.get('name', 'Not provided')}
Email: {ud.get('email', 'Not provided')}
Phone: {ud.get('phone', 'Not provided')}
Location: {ud.get('location', 'Not provided')}
Target Job: {ud.get('target_job', 'Not provided')}
Summary: {ud.get('summary', 'Not provided')}
Work Experience: {ud.get('experience', 'Not provided')}
Education: {ud.get('education', 'Not provided')}
Skills: {ud.get('skills', 'Not provided')}

Rules:
- Use strong action verbs (Led, Managed, Developed, Achieved)
- Include metrics where possible
- No tables, columns, or graphics
- Tailor keywords to the target job
- Use - instead of em dashes
- Output ONLY the resume text, no explanations"""

    messages = [
        {"role": "system", "content": "You are an expert resume writer. Output ONLY the resume text."},
        {"role": "user", "content": prompt},
    ]
    return await async_chat_completion(messages, max_tokens=1500)


def generate_ats_resume(user_data: dict) -> str:
    ud = user_data
    prompt = f"""Write a professional ATS-optimized resume. Structure:
FULL NAME
Email | Phone | Location
PROFESSIONAL SUMMARY
WORK EXPERIENCE
EDUCATION
SKILLS

User: Name={ud.get('name','')}, Email={ud.get('email','')}, Phone={ud.get('phone','')},
Location={ud.get('location','')}, Target={ud.get('target_job','')},
Summary={ud.get('summary','')}, Experience={ud.get('experience','')},
Education={ud.get('education','')}, Skills={ud.get('skills','')}

Output ONLY the resume text."""
    messages = [
        {"role": "system", "content": "Expert resume writer. Output ONLY resume text."},
        {"role": "user", "content": prompt},
    ]
    return chat_completion(messages, max_tokens=1500)
