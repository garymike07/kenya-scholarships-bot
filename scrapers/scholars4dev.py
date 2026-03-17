from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity, log


class Scholars4DevScraper(BaseScraper):
    name = "scholars4dev.com"
    BASE = "https://www.scholars4dev.com"

    PAGES = [
        "/tag/scholarships-for-kenyans/",
        "/category/country/africa-scholarships/",
        "/category/country/developing-country-scholarships/",
        "/category/level/masters-scholarships/",
        "/category/level/phd-scholarships/",
        "/category/level/undergraduate-scholarships/",
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

                    resp = self.polite_get(session, url)
                    soup = BeautifulSoup(resp.text, "lxml")
                    articles = soup.select("article, .post, .entry")

                    if not articles:
                        break

                    for article in articles:
                        opp = self._parse_article(article)
                        if opp and not any(r.url == opp.url for r in results):
                            results.append(opp)

                    if not soup.select("a.next, .nav-previous a, .next.page-numbers"):
                        break

            except Exception as e:
                log.error("scholars4dev %s error: %s", page_path, e)

        return results

    def _parse_article(self, article) -> Opportunity | None:
        title_el = article.select_one("h2 a, h3 a, .entry-title a")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        if not href:
            return None

        desc_el = article.select_one(".entry-content, .entry-summary, p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        deadline = ""
        level = ""
        host_country = ""
        for line in description.split("\n"):
            line_lower = line.lower().strip()
            if "deadline" in line_lower:
                deadline = line.strip()
            if "study in" in line_lower:
                host_country = line.strip().replace("Study in:", "").strip()
            if any(w in line_lower for w in ["masters", "phd", "bachelor", "undergraduate", "postgraduate"]):
                level = line.strip()

        return Opportunity(
            title=title,
            url=href,
            source=self.name,
            description=description[:2000],
            deadline=deadline,
            host_country=host_country,
            level=level,
            raw_categories=["student_scholarships"],
        )
