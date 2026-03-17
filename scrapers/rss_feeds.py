import requests
import re
from xml.etree import ElementTree
from .base import BaseScraper, Opportunity
import logging

log = logging.getLogger(__name__)

RSS_FEEDS = [
    ("https://www.scholars4dev.com/feed/", "scholars4dev-rss"),
    ("https://www.opportunitiesforafricans.com/feed/", "opportunitiesforafricans-rss"),
    ("https://beta.nsf.gov/rss/rss_www_funding.xml", "nsf.gov"),
]


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


class RSSFeedScraper(BaseScraper):
    name = "rss-feeds"

    def scrape(self) -> list[Opportunity]:
        results = []
        for feed_url, source in RSS_FEEDS:
            if not self.is_page_fresh(feed_url):
                log.debug("Skipping RSS %s (already scraped)", source)
                continue

            try:
                resp = requests.get(
                    feed_url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; GrantsBot/1.0)"},
                    timeout=30,
                )
                content_type = (resp.headers.get("content-type") or "").lower()
                if not any(kind in content_type for kind in ["xml", "rss", "atom"]):
                    log.warning("RSS feed %s returned non-feed content type: %s", feed_url, content_type)
                    self.mark_page_done(feed_url, 0)
                    continue
                root = ElementTree.fromstring(resp.content)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                items = root.findall(".//item") or root.findall(".//atom:entry", ns)
                count = 0
                for item in items:
                    title = item.findtext("title") or item.findtext("atom:title", namespaces=ns) or ""
                    link_el = item.find("link")
                    if link_el is not None and link_el.text:
                        link = link_el.text
                    else:
                        link_el = item.find("atom:link", ns)
                        link = link_el.get("href", "") if link_el is not None else ""
                    desc = item.findtext("description") or item.findtext("atom:summary", namespaces=ns) or ""
                    if not title:
                        continue
                    results.append(Opportunity(
                        title=title.strip(),
                        url=link.strip(),
                        source=source,
                        description=strip_tags(desc)[:500],
                    ))
                    count += 1
                self.mark_page_done(feed_url, count)
            except Exception as e:
                log.error("RSS feed %s error: %s", feed_url, e)
                self.mark_page_done(feed_url, 0)
        return results
