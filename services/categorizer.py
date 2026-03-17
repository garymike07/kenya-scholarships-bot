from config import CATEGORIES
from scrapers.base import Opportunity


def categorize(opp: Opportunity) -> str:
    if opp.raw_categories:
        return opp.raw_categories[0]

    text = f"{opp.title} {opp.description} {opp.source}".lower()

    scores = {}
    for cat, keywords in CATEGORIES.items():
        scores[cat] = sum(1 for kw in keywords if kw in text)

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best

    return "business_grants"
