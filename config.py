import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID", "0"))
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "grants.db")
SCRAPE_INTERVAL_MINUTES = 60

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
