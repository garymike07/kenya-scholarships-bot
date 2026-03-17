"""
AI conversational engine using Nvidia model via OpenRouter.
Handles natural language for both scholarship search and resume building.
"""
import httpx
import time
import logging
from config import OPENROUTER_API_KEY

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"
FALLBACK_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]

SYSTEM_PROMPT = """You are an AI assistant for a Telegram bot that helps Kenyan citizens with two things:

1. SCHOLARSHIPS: Finding scholarships, grants, and funding opportunities globally.
2. RESUMES: Writing ATS-optimized resumes that pass Applicant Tracking Systems.

When a user asks about scholarships, search help, or funding — guide them and suggest using the bot's scholarship features.

When a user wants to build/write/edit a resume — collect their information step by step:
- Full name
- Email and phone
- Professional summary / career objective
- Work experience (job title, company, dates, responsibilities)
- Education (degree, school, dates)
- Skills
- Target job title they're applying for

Be conversational, friendly, and helpful. Ask one or two questions at a time. Keep responses concise.
If the user's intent is unclear, ask what they'd like help with: scholarships or resume building.
Always respond in simple English."""


def chat_completion(messages: list[dict], max_tokens: int = 800) -> str:
    if not OPENROUTER_API_KEY:
        return "AI is not configured. Please set OPENROUTER_API_KEY."

    all_models = [MODEL] + FALLBACK_MODELS
    for model in all_models:
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
                    log.warning("Rate limited on %s", model)
                    time.sleep(3)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    return content.strip()
        except Exception as e:
            log.error("AI chat error on %s: %s", model, e)
            time.sleep(1)

    return "I'm temporarily unavailable. Please try again in a moment."


def generate_ats_resume(user_data: dict) -> str:
    """Generate an ATS-optimized resume using AI."""
    prompt = f"""Write a professional ATS-optimized resume based on this information. 
The resume MUST follow this exact structure for ATS compatibility:

FULL NAME (centered, uppercase)
Email | Phone | Location

PROFESSIONAL SUMMARY
(2-3 sentences summarizing qualifications for the target role)

WORK EXPERIENCE
Job Title — Company Name
Dates
• Achievement/responsibility using action verbs and metrics
• Achievement/responsibility using action verbs and metrics

EDUCATION
Degree — Institution Name
Dates

SKILLS
Skill 1, Skill 2, Skill 3 (relevant to target job)

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
Additional Info: {user_data.get('additional', '')}

IMPORTANT:
- Use strong action verbs (Led, Managed, Developed, Achieved, Implemented)
- Include metrics and numbers where possible
- Keep formatting clean with no tables, columns, or graphics (ATS can't read those)
- Tailor keywords to the target job
- Keep it to 1 page
- Write the complete resume now:"""

    messages = [
        {"role": "system", "content": "You are an expert resume writer. Write ATS-optimized resumes that pass Applicant Tracking Systems. Output ONLY the resume text, no explanations."},
        {"role": "user", "content": prompt},
    ]
    return chat_completion(messages, max_tokens=1500)


def improve_resume_section(section: str, target_job: str) -> str:
    """Improve a specific resume section."""
    messages = [
        {"role": "system", "content": "You are an ATS resume expert. Improve this resume section to be more ATS-friendly with strong action verbs and metrics."},
        {"role": "user", "content": f"Improve this resume section for a '{target_job}' application:\n\n{section}"},
    ]
    return chat_completion(messages, max_tokens=600)
