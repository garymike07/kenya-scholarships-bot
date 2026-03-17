import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity
import logging

log = logging.getLogger(__name__)


class GrantsGovScraper(BaseScraper):
    name = "grants.gov"
    BASE = "https://www.grants.gov"
    API_URL = "https://www.grants.gov/grantsws/rest/opportunities/search/"

    def scrape(self) -> list[Opportunity]:
        api_url = self.API_URL
        if not self.is_page_fresh(api_url):
            log.debug("Skipping grants.gov API (already scraped)")
            return []

        results = []
        try:
            resp = requests.post(
                api_url,
                json={"keyword": "", "oppNum": "", "cfda": "", "rows": 250, "sortBy": "openDate|desc"},
                headers={"Content-Type": "application/json", "User-Agent": "GrantsBot/1.0"},
                timeout=30,
            )
            if resp.status_code != 200:
                self.mark_page_done(api_url, 0)
                if resp.status_code in {403, 404, 405}:
                    log.warning("grants.gov API unavailable (%s), skipping for now", resp.status_code)
                    return []
                log.warning("grants.gov API returned %s, trying HTML fallback", resp.status_code)
                return self._scrape_html()

            data = resp.json()
            for opp in data.get("oppHits", []):
                results.append(Opportunity(
                    title=opp.get("title", ""),
                    url=f"{self.BASE}/search-results-detail/{opp.get('id', '')}",
                    source=self.name,
                    description=opp.get("synopsis", opp.get("description", "")),
                    deadline=opp.get("closeDate", ""),
                    amount=opp.get("awardCeiling", ""),
                ))
            self.mark_page_done(api_url, len(results))
        except Exception as e:
            log.error("grants.gov scrape error: %s", e)
            return self._scrape_html()
        return results

    def _scrape_html(self) -> list[Opportunity]:
        html_url = f"{self.BASE}/search-grants.html"
        if not self.is_page_fresh(html_url):
            return []

        results = []
        try:
            resp = requests.get(
                html_url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; GrantsBot/1.0)"},
                timeout=30,
            )
            soup = BeautifulSoup(resp.text, "lxml")
            for item in soup.select(".grant-result, .usa-card, [class*='opportunity']"):
                title_el = item.select_one("h3, h4, a, .title")
                if not title_el:
                    continue
                link = title_el.get("href") or (title_el.find("a") or {}).get("href", "")
                if link and not link.startswith("http"):
                    link = self.BASE + link
                desc_el = item.select_one("p, .description, .synopsis")
                results.append(Opportunity(
                    title=title_el.get_text(strip=True),
                    url=link or self.BASE,
                    source=self.name,
                    description=desc_el.get_text(strip=True) if desc_el else "",
                ))
            self.mark_page_done(html_url, len(results))
        except Exception as e:
            log.error("grants.gov HTML fallback error: %s", e)
        return results
