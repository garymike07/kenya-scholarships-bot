from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity, log


class ScholarshipsAdsScraper(BaseScraper):
    name = "scholarshipsads.com"
    BASE = "https://www.scholarshipsads.com"

    PAGES = [
        "/tag/scholarships-in-kenya/",
        "/tag/scholarships-for-african-students/",
        "/tag/fully-funded-scholarships/",
        "/blog/fully-funded-scholarships-for-kenyan-students-march2026",
    ]

    def scrape(self) -> list[Opportunity]:
        results = []
        session = self.get_session()

        for page_path in self.PAGES:
            try:
                url = f"{self.BASE}{page_path}" if not page_path.startswith("http") else page_path
                resp = self.polite_get(session, url)
                soup = BeautifulSoup(resp.text, "lxml")

                for article in soup.select("article, .post, .entry, .type-post, .blog-item, .card"):
                    opp = self._parse_article(article)
                    if opp and not any(r.url == opp.url for r in results):
                        results.append(opp)

                for link in soup.select("a[href*='scholarship'], a[href*='fully-funded']"):
                    href = link.get("href", "")
                    title = link.get_text(strip=True)
                    if href and title and len(title) > 15 and not any(r.url == href for r in results):
                        if not href.startswith("http"):
                            href = self.BASE + href
                        results.append(Opportunity(
                            title=title,
                            url=href,
                            source=self.name,
                            raw_categories=["student_scholarships"],
                        ))

            except Exception as e:
                log.error("scholarshipsads %s error: %s", page_path, e)

        return results

    def _parse_article(self, article) -> Opportunity | None:
        title_el = article.select_one("h2 a, h3 a, .entry-title a, a.title")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        if not href or len(title) < 10:
            return None
        if not href.startswith("http"):
            href = self.BASE + href

        desc_el = article.select_one(".entry-content, .entry-summary, p, .excerpt")
        description = desc_el.get_text(strip=True) if desc_el else ""

        return Opportunity(
            title=title,
            url=href,
            source=self.name,
            description=description[:2000],
            raw_categories=["student_scholarships"],
        )
