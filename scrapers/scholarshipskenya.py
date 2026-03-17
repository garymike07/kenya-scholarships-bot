from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity, log


class ScholarshipsKenyaScraper(BaseScraper):
    name = "scholarshipskenya.com"
    BASE = "https://www.scholarshipskenya.com"

    def scrape(self) -> list[Opportunity]:
        results = []
        session = self.get_session()

        for page_num in range(1, 50):
            url = self.BASE if page_num == 1 else f"{self.BASE}/page/{page_num}/"
            try:
                resp = self.polite_get(session, url)
                soup = BeautifulSoup(resp.text, "lxml")

                articles = soup.select("article, .post, .entry, .type-post")
                if not articles:
                    break

                for article in articles:
                    opp = self._parse_article(article)
                    if opp and not any(r.url == opp.url for r in results):
                        results.append(opp)

                if not soup.select("a.next, .next.page-numbers"):
                    break

            except Exception as e:
                log.error("scholarshipskenya page %d error: %s", page_num, e)
                break

        return results

    def _parse_article(self, article) -> Opportunity | None:
        title_el = article.select_one("h2 a, h3 a, .entry-title a")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        if not href or len(title) < 10:
            return None

        desc_el = article.select_one(".entry-content, .entry-summary, .entry-excerpt, p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        return Opportunity(
            title=title,
            url=href,
            source=self.name,
            description=description[:2000],
            raw_categories=["student_scholarships"],
        )
