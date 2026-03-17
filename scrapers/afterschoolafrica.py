from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity, log


class AfterSchoolAfricaScraper(BaseScraper):
    name = "afterschoolafrica.com"
    BASE = "https://www.afterschoolafrica.com"

    URLS = [
        "https://www.afterschoolafrica.com/?s=scholarship",
        "https://www.afterschoolafrica.com/fellowships/",
    ]

    def scrape(self) -> list[Opportunity]:
        results = []
        session = self.get_session()

        for url in self.URLS:
            try:
                if not self.is_page_fresh(url):
                    log.debug("Skipping %s (already scraped)", url)
                    continue

                resp = self.polite_get(session, url)
                soup = BeautifulSoup(resp.text, "lxml")
                articles = soup.select("article, .post, .entry, .type-post")

                if not articles:
                    self.mark_page_done(url, 0)
                    continue

                count = 0
                for article in articles:
                    opp = self._parse_article(article)
                    if opp and not any(r.url == opp.url for r in results):
                        results.append(opp)
                        count += 1

                self.mark_page_done(url, count)

            except Exception as e:
                log.error("afterschoolafrica %s error: %s", url, e)

        return results

    def _parse_article(self, article) -> Opportunity | None:
        title_el = article.select_one("h2 a, h3 a, .entry-title a")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        if not href or len(title) < 10:
            return None

        desc_el = article.select_one(".entry-content, .entry-summary, p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        category = "student_scholarships"
        if "grant" in title.lower():
            category = "nonprofit_funding"
        if "business" in title.lower() or "entrepreneur" in title.lower():
            category = "business_grants"

        return Opportunity(
            title=title,
            url=href,
            source=self.name,
            description=description[:2000],
            raw_categories=[category],
        )
