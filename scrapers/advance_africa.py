from bs4 import BeautifulSoup
from .base import BaseScraper, Opportunity, log


class AdvanceAfricaScraper(BaseScraper):
    name = "advance-africa.com"
    BASE = "https://www.advance-africa.com"

    PAGES = [
        "/Scholarships-for-Kenyans.html",
        "/Kenya-Commonwealth-Scholarships.html",
        "/Scholarships-for-African-Students.html",
        "/Scholarships-in-USA.html",
        "/Scholarships-in-UK.html",
        "/Scholarships-in-Canada.html",
        "/Scholarships-in-Germany.html",
        "/Scholarships-in-Australia.html",
    ]

    def scrape(self) -> list[Opportunity]:
        results = []
        session = self.get_session()

        for page_path in self.PAGES:
            try:
                url = f"{self.BASE}{page_path}"
                resp = self.polite_get(session, url)
                soup = BeautifulSoup(resp.text, "lxml")

                for link in soup.select("a[href]"):
                    href = link.get("href", "")
                    title = link.get_text(strip=True)

                    if not title or len(title) < 15:
                        continue

                    skip = ["home", "contact", "about", "privacy", "sitemap", "menu", "navigation"]
                    if any(s in title.lower() for s in skip):
                        continue

                    if not href.startswith("http"):
                        href = self.BASE + "/" + href.lstrip("/")

                    if any(r.url == href for r in results):
                        continue

                    parent = link.find_parent(["li", "p", "div", "td"])
                    desc = ""
                    if parent:
                        desc = parent.get_text(strip=True)[:500]

                    host = ""
                    for country in ["USA", "UK", "Canada", "Germany", "Australia", "Japan", "Sweden", "France", "Netherlands"]:
                        if country.lower() in page_path.lower() or country.lower() in title.lower():
                            host = country
                            break

                    results.append(Opportunity(
                        title=title,
                        url=href,
                        source=self.name,
                        description=desc,
                        host_country=host,
                        raw_categories=["student_scholarships"],
                    ))

            except Exception as e:
                log.error("advance-africa %s error: %s", page_path, e)

        return results
