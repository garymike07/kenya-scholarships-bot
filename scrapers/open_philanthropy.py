import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity
import logging

log = logging.getLogger(__name__)


class OpenPhilanthropyScraper(BaseScraper):
    name = "openphilanthropy.org"
    BASE = "https://www.openphilanthropy.org"

    def scrape(self) -> list[Opportunity]:
        results = []
        try:
            resp = requests.get(
                f"{self.BASE}/grants/",
                headers={"User-Agent": "Mozilla/5.0 (compatible; GrantsBot/1.0)"},
                timeout=30,
            )
            soup = BeautifulSoup(resp.text, "lxml")
            for item in soup.select(".grant, article, .card, tr, .listing-item"):
                title_el = item.select_one("a, h3, h2, .title, td:first-child")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if title_el.name != "a":
                    link = title_el.find("a")
                    if link:
                        href = link.get("href", "")
                if not title or len(title) < 5:
                    continue
                if href and not href.startswith("http"):
                    href = self.BASE + href
                amount_el = item.select_one(".amount, td:nth-child(2)")
                results.append(Opportunity(
                    title=title,
                    url=href or self.BASE,
                    source=self.name,
                    description="",
                    amount=amount_el.get_text(strip=True) if amount_el else "",
                    raw_categories=["nonprofit_funding"],
                ))
        except Exception as e:
            log.error("openphilanthropy scrape error: %s", e)
        return results
