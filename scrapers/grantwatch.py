import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity
import logging

log = logging.getLogger(__name__)


class GrantWatchScraper(BaseScraper):
    name = "grantwatch.com"
    BASE = "https://www.grantwatch.com"

    def scrape(self) -> list[Opportunity]:
        results = []
        urls = [
            f"{self.BASE}/cat/8/business-grants.html",
            f"{self.BASE}/cat/1/grants-by-state.html",
            f"{self.BASE}/cat/22/nonprofit-grants.html",
        ]
        for url in urls:
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; GrantsBot/1.0)"},
                    timeout=30,
                )
                soup = BeautifulSoup(resp.text, "lxml")
                for item in soup.select("a[href*='grant'], .grant-listing, .grant-item, li a, h3 a, h2 a"):
                    title = item.get_text(strip=True)
                    href = item.get("href", "")
                    if not title or len(title) < 10:
                        continue
                    if not href.startswith("http"):
                        href = self.BASE + href
                    results.append(Opportunity(
                        title=title,
                        url=href,
                        source=self.name,
                        description="",
                    ))
            except Exception as e:
                log.error("grantwatch scrape error: %s", e)
        return results
