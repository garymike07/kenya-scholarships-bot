from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity, log


class AfterSchoolAfricaScraper(BaseScraper):
    name = "afterschoolafrica.com"
    BASE = "https://www.afterschoolafrica.com"

    PAGES = [
        "/category/scholarships/",
        "/category/scholarships/fully-funded-scholarships/",
        "/category/fellowships/",
        "/category/grants/",
    ]

    def scrape(self) -> list[Opportunity]:
        results = []
        session = self.get_session()

        for page_path in self.PAGES:
            try:
                for page_num in range(1, 50):
                    url = f"{self.BASE}{page_path}"
                    if page_num > 1:
                        url = f"{url}page/{page_num}/"

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

                    if not soup.select("a.next, .next.page-numbers"):
                        break

            except Exception as e:
                log.error("afterschoolafrica %s error: %s", page_path, e)

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
