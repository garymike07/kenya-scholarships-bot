"""
AI engine with 29 free OpenRouter models and automatic rotation on rate limits.
"""
import httpx
import time
import logging
from config import OPENROUTER_API_KEY

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

FREE_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "google/gemma-3-4b-it:free",
    "google/gemma-3n-e4b-it:free",
    "google/gemma-3n-e2b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "qwen/qwen3-coder:free",
    "qwen/qwen3-4b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "minimax/minimax-m2.5:free",
    "stepfun/step-3.5-flash:free",
    "arcee-ai/trinity-large-preview:free",
    "arcee-ai/trinity-mini:free",
    "z-ai/glm-4.5-air:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "openrouter/free",
]

_model_idx = 0
_rate_limited_models = {}

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


def _get_next_model() -> str | None:
    global _model_idx
    now = time.time()
    tried = 0
    while tried < len(FREE_MODELS):
        model = FREE_MODELS[_model_idx % len(FREE_MODELS)]
        blocked_until = _rate_limited_models.get(model, 0)
        if now > blocked_until:
            return model
        _model_idx = (_model_idx + 1) % len(FREE_MODELS)
        tried += 1
    return FREE_MODELS[0]


def _mark_rate_limited(model: str):
    global _model_idx
    _rate_limited_models[model] = time.time() + 120
    _model_idx = (_model_idx + 1) % len(FREE_MODELS)
    log.warning("Rate limited on %s, rotating to next model", model)


def chat_completion(messages: list[dict], max_tokens: int = 800) -> str:
    if not OPENROUTER_API_KEY:
        return "AI is not configured. Please set OPENROUTER_API_KEY."

    attempts = 0
    max_attempts = min(len(FREE_MODELS), 10)

    while attempts < max_attempts:
        model = _get_next_model()
        if not model:
            break
        attempts += 1
        try:
            with httpx.Client(timeout=60) as client:
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
                        "temperature": 0.7,
                    },
                )
                if resp.status_code == 429:
                    _mark_rate_limited(model)
                    time.sleep(1)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    log.info("AI response from %s", model)
                    return content.strip()
                _mark_rate_limited(model)
        except Exception as e:
            log.error("AI error on %s: %s", model, e)
            _mark_rate_limited(model)
            time.sleep(0.5)

    return "I'm temporarily busy. Please try again in a minute — I'll be right back!"


def generate_ats_resume(user_data: dict) -> str:
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
* Achievement using action verbs and metrics

EDUCATION
Degree - Institution Name
Dates

SKILLS
Skill 1, Skill 2, Skill 3

---
User Information:
Name: {user_data.get('name', 'Not provided')}
Email: {user_data.get('email', 'Not provided')}
Phone: {user_data.get('phone', 'Not provided')}
Location: {user_data.get('location', 'Not provided')}
Target Job: {user_data.get('target_job', 'Not provided')}
Summary: {user_data.get('summary', 'Not provided')}
Work Experience: {user_data.get('experience', 'Not provided')}
Education: {user_data.get('education', 'Not provided')}
Skills: {user_data.get('skills', 'Not provided')}

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
    return chat_completion(messages, max_tokens=1500)
