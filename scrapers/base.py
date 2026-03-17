from dataclasses import dataclass, field
from typing import Optional
import hashlib
import requests
import time
import random
import logging

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]


@dataclass
class Opportunity:
    title: str
    url: str
    source: str
    description: str = ""
    deadline: str = ""
    amount: str = ""
    category: str = ""
    summary: str = ""
    eligibility: str = ""
    host_country: str = ""
    level: str = ""
    benefits: str = ""
    raw_categories: list = field(default_factory=list)

    @property
    def uid(self) -> str:
        return hashlib.sha256(f"{self.source}:{self.url}".encode()).hexdigest()[:16]


class BaseScraper:
    name: str = "base"
    rate_delay: float = 1.5

    def get_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })
        return s

    def polite_get(self, session, url, **kwargs):
        time.sleep(self.rate_delay + random.uniform(0, 1))
        kwargs.setdefault("timeout", 30)
        resp = session.get(url, **kwargs)
        resp.raise_for_status()
        return resp

    def is_page_fresh(self, page_url: str) -> bool:
        """Check if this page was already scraped within the last hour."""
        from services.database import page_already_scraped
        return not page_already_scraped(self.name, page_url, max_age_hours=1)

    def mark_page_done(self, page_url: str, count: int = 0):
        from services.database import mark_page_scraped
        mark_page_scraped(self.name, page_url, count)

    def scrape(self) -> list[Opportunity]:
        raise NotImplementedError
