from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity, log


class ScholarshipsAdsScraper(BaseScraper):
    name = "scholarshipsads.com"
    BASE = "https://www.scholarshipsads.com"

    SEARCH_URLS = [
        "https://www.scholarshipsads.com/search?keyword=kenya",
        "https://www.scholarshipsads.com/search?keyword=fully%20funded",
        "https://www.scholarshipsads.com/search?keyword=masters",
    ]

    def scrape(self) -> list[Opportunity]:
        results = []
        session = self.get_session()

        for url in self.SEARCH_URLS:
            try:
                if not self.is_page_fresh(url):
                    log.debug("Skipping %s (already scraped)", url)
                    continue

                resp = self.polite_get(session, url)
                soup = BeautifulSoup(resp.text, "lxml")

                count = 0
                for link in soup.select("h3 a"):
                    href = link.get("href", "")
                    title = link.get_text(strip=True)
                    if not href or not title or len(title) < 15:
                        continue
                    if not href.startswith("http"):
                        href = self.BASE + href
                    if "/blog/categories/" in href or "/category/" in href:
                        continue
                    if not any(r.url == href for r in results):
                        parent = link.find_parent(["div", "article", "section", "li"])
                        description = parent.get_text(" ", strip=True)[:500] if parent else ""
                        results.append(Opportunity(
                            title=title,
                            url=href,
                            source=self.name,
                            description=description,
                            raw_categories=["student_scholarships"],
                        ))
                        count += 1

                self.mark_page_done(url, count)

            except Exception as e:
                log.error("scholarshipsads %s error: %s", url, e)

        return results
