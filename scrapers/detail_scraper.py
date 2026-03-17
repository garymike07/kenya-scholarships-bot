"""
Deep scraper that follows opportunity URLs to extract full details:
deadline, eligibility, benefits, amount, host country, level.
"""
from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity, log
import re


DEADLINE_PATTERNS = [
    r"deadline[:\s]*([A-Za-z0-9\s,]+\d{4})",
    r"closing date[:\s]*([A-Za-z0-9\s,]+\d{4})",
    r"apply by[:\s]*([A-Za-z0-9\s,]+\d{4})",
    r"applications? close[:\s]*([A-Za-z0-9\s,]+\d{4})",
    r"due date[:\s]*([A-Za-z0-9\s,]+\d{4})",
]

AMOUNT_PATTERNS = [
    r"\$[\d,]+(?:\.\d{2})?",
    r"€[\d,]+(?:\.\d{2})?",
    r"£[\d,]+(?:\.\d{2})?",
    r"USD\s?[\d,]+",
    r"EUR\s?[\d,]+",
    r"GBP\s?[\d,]+",
    r"fully[- ]funded",
    r"full scholarship",
    r"full tuition",
]


def extract_deadline(text: str) -> str:
    for pattern in DEADLINE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def extract_amount(text: str) -> str:
    for pattern in AMOUNT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def extract_eligibility(text: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        lower = line.lower().strip()
        if any(kw in lower for kw in ["eligib", "who can apply", "requirements", "criteria", "qualif"]):
            chunk = "\n".join(lines[i:i+8])
            return chunk.strip()[:600]
    return ""


def extract_benefits(text: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        lower = line.lower().strip()
        if any(kw in lower for kw in ["benefit", "covers", "what is covered", "scholarship value", "award includes"]):
            chunk = "\n".join(lines[i:i+8])
            return chunk.strip()[:600]
    return ""


def extract_host_country(text: str) -> str:
    countries = [
        "USA", "United States", "UK", "United Kingdom", "Canada", "Germany",
        "Australia", "Japan", "Sweden", "France", "Netherlands", "Switzerland",
        "New Zealand", "Denmark", "Norway", "Finland", "Ireland", "Belgium",
        "Austria", "Italy", "Spain", "China", "Singapore", "South Korea",
        "Turkey", "Hungary", "Czech Republic", "Poland", "South Africa",
        "Malaysia", "Thailand", "Israel", "Qatar", "Saudi Arabia", "UAE",
    ]
    for c in countries:
        if c.lower() in text.lower():
            return c
    return ""


def extract_level(text: str) -> str:
    levels = []
    text_lower = text.lower()
    if "phd" in text_lower or "doctoral" in text_lower:
        levels.append("PhD")
    if "master" in text_lower or "postgraduate" in text_lower:
        levels.append("Masters")
    if "bachelor" in text_lower or "undergraduate" in text_lower:
        levels.append("Bachelors")
    if "fellowship" in text_lower:
        levels.append("Fellowship")
    return ", ".join(levels)


def scrape_detail(session, opp: Opportunity) -> Opportunity:
    """Visit the opportunity URL and extract full details."""
    try:
        import time, random
        time.sleep(1 + random.uniform(0, 1))

        resp = session.get(opp.url, timeout=20)
        if resp.status_code != 200:
            return opp

        soup = BeautifulSoup(resp.text, "lxml")

        for tag in soup.select("script, style, nav, header, footer, .sidebar, .menu, .ad, .advertisement"):
            tag.decompose()

        content = soup.select_one("article, .entry-content, .post-content, .single-content, main, .content")
        if not content:
            content = soup.body

        if not content:
            return opp

        text = content.get_text(separator="\n", strip=True)

        if not opp.description or len(opp.description) < 100:
            paragraphs = content.select("p")
            desc_parts = []
            for p in paragraphs[:6]:
                t = p.get_text(strip=True)
                if len(t) > 30:
                    desc_parts.append(t)
            if desc_parts:
                opp.description = " ".join(desc_parts)[:2000]

        if not opp.deadline:
            opp.deadline = extract_deadline(text)

        if not opp.amount:
            opp.amount = extract_amount(text)

        if not opp.eligibility:
            opp.eligibility = extract_eligibility(text)

        if not opp.benefits:
            opp.benefits = extract_benefits(text)

        if not opp.host_country:
            opp.host_country = extract_host_country(text)

        if not opp.level:
            opp.level = extract_level(text)

    except Exception as e:
        log.debug("Detail scrape failed for %s: %s", opp.url, e)

    return opp
