import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity
import logging

log = logging.getLogger(__name__)


class ScholarshipsComScraper(BaseScraper):
    name = "scholarships.com"
    BASE = "https://www.scholarships.com"

    def scrape(self) -> list[Opportunity]:
        results = []
        urls = [
            f"{self.BASE}/financial-aid/college-scholarships/scholarships-by-type/",
            f"{self.BASE}/financial-aid/college-scholarships/",
        ]
        for url in urls:
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; GrantsBot/1.0)"},
                    timeout=30,
                )
                soup = BeautifulSoup(resp.text, "lxml")
                for item in soup.select("a[href*='scholarship']"):
                    title = item.get_text(strip=True)
                    href = item.get("href", "")
                    if not title or len(title) < 15 or not href:
                        continue
                    if not href.startswith("http"):
                        href = self.BASE + href
                    skip_words = ["log in", "sign up", "search", "calculator", "educator", "resource", "college search"]
                    if any(sw in title.lower() for sw in skip_words):
                        continue
                    if "/scholarship" not in href.lower():
                        continue
                    results.append(Opportunity(
                        title=title,
                        url=href,
                        source=self.name,
                        description="",
                        raw_categories=["student_scholarships"],
                    ))
            except Exception as e:
                log.error("scholarships.com scrape error: %s", e)
        return results
