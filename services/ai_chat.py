"""
AI engine with multi-account OpenRouter key rotation.
Each key gets all 26 free models. When one key is rate limited, it moves to the next.
Add more keys to OPENROUTER_API_KEYS in .env (comma-separated) for more capacity.
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
    "nvidia/nemotron-3-super-120b-a12b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "openai/gpt-oss-120b:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "minimax/minimax-m2.5:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "stepfun/step-3.5-flash:free",
    "openrouter/free",
    "arcee-ai/trinity-large-preview:free",
    "z-ai/glm-4.5-air:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "google/gemma-3-12b-it:free",
    "qwen/qwen3-coder:free",
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemma-3-4b-it:free",
    "qwen/qwen3-4b:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "arcee-ai/trinity-mini:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "google/gemma-3n-e4b-it:free",
    "google/gemma-3n-e2b-it:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
]

# Track rate limits per (key, model) pair
_rate_limited = {}
_lock = threading.Lock()

# Assign keys: first key = chat, second key = scraper, both fallback to each other
_chat_key_idx = 0
_scraper_key_idx = min(1, len(OPENROUTER_API_KEYS) - 1) if OPENROUTER_API_KEYS else 0

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


def _is_available(key: str, model: str) -> bool:
    return _rate_limited.get(f"{key}:{model}", 0) < time.time()


def _mark_limited(key: str, model: str):
    with _lock:
        _rate_limited[f"{key}:{model}"] = time.time() + 90
    log.warning("Rate limited key=...%s model=%s", key[-8:], model.split("/")[-1])


def _try_request_sync(key: str, model: str, messages: list, max_tokens: int, temperature: float) -> str | None:
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
            )
            if resp.status_code == 429:
                _mark_limited(key, model)
                return None
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            if content:
                return content.strip()
            _mark_limited(key, model)
    except Exception as e:
        log.error("AI error key=...%s model=%s: %s", key[-8:], model.split("/")[-1], e)
        _mark_limited(key, model)
    return None


async def _try_request_async(key: str, model: str, messages: list, max_tokens: int, temperature: float) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
            )
            if resp.status_code == 429:
                _mark_limited(key, model)
                return None
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            if content:
                return content.strip()
            _mark_limited(key, model)
    except Exception as e:
        log.error("AI error key=...%s model=%s: %s", key[-8:], model.split("/")[-1], e)
        _mark_limited(key, model)
    return None


async def async_chat_completion(messages: list[dict], max_tokens: int = 800) -> str:
    """Non-blocking AI for user chat. Tries primary chat key first, then all other keys."""
    if not OPENROUTER_API_KEYS:
        return "AI is not configured."

    # Build key order: chat key first, then all others
    key_order = [OPENROUTER_API_KEYS[_chat_key_idx]]
    for k in OPENROUTER_API_KEYS:
        if k not in key_order:
            key_order.append(k)

    for key in key_order:
        for model in FREE_MODELS:
            if not _is_available(key, model):
                continue
            result = await _try_request_async(key, model, messages, max_tokens, 0.7)
            if result:
                log.info("Chat response from key=...%s model=%s", key[-8:], model.split("/")[-1])
                return result
            await asyncio.sleep(0.3)

    return ("All AI models are cooling down right now. "
            "Please try again in about a minute -- I rotate through many models and accounts!")


def chat_completion(messages: list[dict], max_tokens: int = 800) -> str:
    """Blocking AI for scraper thread. Tries scraper key first, then all others."""
    if not OPENROUTER_API_KEYS:
        return ""

    key_order = [OPENROUTER_API_KEYS[_scraper_key_idx]]
    for k in OPENROUTER_API_KEYS:
        if k not in key_order:
            key_order.append(k)

    for key in key_order:
        for model in FREE_MODELS:
            if not _is_available(key, model):
                continue
            result = _try_request_sync(key, model, messages, max_tokens, 0.3)
            if result:
                log.info("Scraper response from key=...%s model=%s", key[-8:], model.split("/")[-1])
                return result
            time.sleep(0.5)

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
