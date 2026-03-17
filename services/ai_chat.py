"""
AI engine with separate model pools for chat (priority) and scraper (background).
"""
import httpx
import asyncio
import time
import threading
import logging
from config import OPENROUTER_API_KEY

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Chat gets the best models -- these are reserved for user-facing interactions
CHAT_MODELS = [
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

# Scraper uses a small subset so it doesn't exhaust all models
SCRAPER_MODELS = [
    "qwen/qwen3-4b:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "google/gemma-3-4b-it:free",
    "google/gemma-3n-e4b-it:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
    "arcee-ai/trinity-mini:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "google/gemma-3n-e2b-it:free",
]

_chat_idx = 0
_scraper_idx = 0
_rate_limited = {}
_lock = threading.Lock()

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


def _get_next_model(models: list, idx_name: str) -> tuple[str | None, int]:
    global _chat_idx, _scraper_idx
    now = time.time()
    with _lock:
        idx = _chat_idx if idx_name == "chat" else _scraper_idx
        for _ in range(len(models)):
            model = models[idx % len(models)]
            if _rate_limited.get(model, 0) < now:
                return model, idx
            idx = (idx + 1) % len(models)
        if idx_name == "chat":
            _chat_idx = idx
        else:
            _scraper_idx = idx
    return None, idx


def _mark_limited(model: str, idx_name: str):
    global _chat_idx, _scraper_idx
    with _lock:
        _rate_limited[model] = time.time() + 90
        if idx_name == "chat":
            _chat_idx = (_chat_idx + 1) % len(CHAT_MODELS)
        else:
            _scraper_idx = (_scraper_idx + 1) % len(SCRAPER_MODELS)
    log.warning("Rate limited %s, rotating", model)


async def async_chat_completion(messages: list[dict], max_tokens: int = 800) -> str:
    """Non-blocking AI for Telegram bot handlers. Uses CHAT_MODELS pool."""
    if not OPENROUTER_API_KEY:
        return "AI is not configured."

    for attempt in range(min(len(CHAT_MODELS), 15)):
        model, _ = _get_next_model(CHAT_MODELS, "chat")
        if not model:
            await asyncio.sleep(2)
            model, _ = _get_next_model(CHAT_MODELS, "chat")
            if not model:
                model = CHAT_MODELS[0]

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.7,
                    },
                )
                if resp.status_code == 429:
                    _mark_limited(model, "chat")
                    await asyncio.sleep(1)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    log.info("Chat AI response from %s", model)
                    return content.strip()
                _mark_limited(model, "chat")
        except Exception as e:
            log.error("Chat AI error on %s: %s", model, e)
            _mark_limited(model, "chat")
            await asyncio.sleep(0.5)

    return ("I couldn't connect to the AI right now. All models are busy. "
            "Please wait a minute and try again -- I have 26 models rotating!")


def chat_completion(messages: list[dict], max_tokens: int = 800) -> str:
    """Blocking AI for scraper thread. Uses SCRAPER_MODELS pool."""
    if not OPENROUTER_API_KEY:
        return ""

    for attempt in range(len(SCRAPER_MODELS)):
        model, _ = _get_next_model(SCRAPER_MODELS, "scraper")
        if not model:
            time.sleep(10)
            model, _ = _get_next_model(SCRAPER_MODELS, "scraper")
            if not model:
                return ""

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
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.3,
                    },
                )
                if resp.status_code == 429:
                    _mark_limited(model, "scraper")
                    time.sleep(5)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    log.info("Scraper AI response from %s", model)
                    return content.strip()
                _mark_limited(model, "scraper")
        except Exception as e:
            log.error("Scraper AI error on %s: %s", model, e)
            _mark_limited(model, "scraper")
            time.sleep(2)

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
    """Blocking version for non-async contexts."""
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
