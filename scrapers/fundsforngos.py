from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity, log


class FundsForNGOsScraper(BaseScraper):
    name = "fundsforngos.org"
    BASE = "https://www2.fundsforngos.org"

    PAGES = [
        "/category/latest-funds-for-ngos/",
        "/tag/kenya/",
        "/tag/africa/",
        "/tag/scholarships/",
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

                    articles = soup.select("article, .post, .entry, .listing-item, .type-post")
                    if not articles:
                        break

                    for article in articles[:20]:
                        title_el = article.select_one("h2 a, h3 a, .entry-title a, a.title")
                        if not title_el:
                            continue
                        href = title_el.get("href", "")
                        if not href.startswith("http"):
                            href = self.BASE + href
                        title = title_el.get_text(strip=True)
                        if not title or len(title) < 10:
                            continue

                        desc_el = article.select_one("p, .entry-summary, .excerpt, .entry-content")
                        desc = desc_el.get_text(strip=True) if desc_el else ""

                        if any(r.url == href for r in results):
                            continue

                        results.append(Opportunity(
                            title=title,
                            url=href,
                            source=self.name,
                            description=desc[:2000],
                            raw_categories=["nonprofit_funding"],
                        ))

                    if not soup.select("a.next, .next.page-numbers"):
                        break

            except Exception as e:
                log.error("fundsforngos %s error: %s", page_path, e)

        return results
