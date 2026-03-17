import os
from dotenv import load_dotenv

load_dotenv()

def _load_openrouter_keys() -> list[str]:
    keys = []
    plural = os.getenv("OPENROUTER_API_KEYS", "")
    singular = os.getenv("OPENROUTER_API_KEY", "")

    if plural:
        keys.extend(k.strip() for k in plural.split(",") if k.strip())
    if singular:
        keys.extend(k.strip() for k in singular.split(",") if k.strip())

    deduped = []
    seen = set()
    for key in keys:
        if key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped


OPENROUTER_API_KEYS = _load_openrouter_keys()
OPENROUTER_API_KEY = OPENROUTER_API_KEYS[0] if OPENROUTER_API_KEYS else ""
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID", "0"))
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "grants.db")
SCRAPE_INTERVAL_MINUTES = 60

CONVEX_SITE_URL = os.getenv("CONVEX_SITE_URL", "").rstrip("/")
SITE_URL = os.getenv("SITE_URL", "").rstrip("/")

SERVICES = {
    "scholarship_finder": {
        "name": "ScholarshipFinder Pro",
        "tagline": "AI-powered scholarship & grant finder",
        "access_prefix": "scholarship",
    },
    "resume_builder": {
        "name": "ResumeBuilder AI",
        "tagline": "ATS-optimized resume builder",
        "access_prefix": "resume",
    },
}

CATEGORIES = {
    "business_grants": [
        "business", "startup", "entrepreneur", "sme", "small business",
        "innovation", "commerce", "enterprise", "seed fund", "venture",
    ],
    "student_scholarships": [
        "scholarship", "student", "tuition", "fellowship", "academic",
        "university", "college", "education", "graduate", "masters",
        "phd", "undergraduate", "doctoral", "postgraduate", "study abroad",
        "fully funded", "bursary",
    ],
    "nonprofit_funding": [
        "nonprofit", "non-profit", "ngo", "charity", "community",
        "social", "humanitarian", "civil society", "development",
        "foundation", "grant for organization",
    ],
}

FREE_DAILY_LIMIT = 3
PREMIUM_PRICE = "$9.99/month"
