from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity, log


class ScholarshipsKenyaScraper(BaseScraper):
    name = "scholarshipskenya.com"
    BASE = "https://www.scholarshipskenya.com"

    def scrape(self) -> list[Opportunity]:
        results = []
        session = self.get_session()
        next_url = self.BASE
        seen_pages = set()

        while next_url and next_url not in seen_pages:
            url = next_url
            seen_pages.add(url)
            try:
                if not self.is_page_fresh(url):
                    log.debug("Skipping %s (already scraped)", url)
                    break

                resp = self.polite_get(session, url)
                soup = BeautifulSoup(resp.text, "lxml")

                articles = soup.select("article, .post, .entry, .type-post")
                if not articles:
                    self.mark_page_done(url, 0)
                    break

                count = 0
                for article in articles:
                    opp = self._parse_article(article)
                    if opp and not any(r.url == opp.url for r in results):
                        results.append(opp)
                        count += 1

                self.mark_page_done(url, count)

                next_link = soup.select_one("a.next, .next.page-numbers")
                next_url = next_link.get("href", "") if next_link else ""
                if not next_url:
                    break

            except Exception as e:
                log.error("scholarshipskenya %s error: %s", url, e)
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
