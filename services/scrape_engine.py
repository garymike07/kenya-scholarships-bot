import time
import logging
from scrapers.scholars4dev import Scholars4DevScraper
from scrapers.opportunitiesforafricans import OpportunitiesForAfricansScraper
from scrapers.scholarshipskenya import ScholarshipsKenyaScraper
from scrapers.afterschoolafrica import AfterSchoolAfricaScraper
from scrapers.scholarshipsads import ScholarshipsAdsScraper
from scrapers.advance_africa import AdvanceAfricaScraper
from scrapers.fundsforngos import FundsForNGOsScraper
from scrapers.grants_gov import GrantsGovScraper
from scrapers.open_philanthropy import OpenPhilanthropyScraper
from scrapers.rss_feeds import RSSFeedScraper
from scrapers.detail_scraper import scrape_detail
from services.summarizer import summarize_opportunity
from services.categorizer import categorize
from services.database import opportunity_exists, save_opportunity

log = logging.getLogger(__name__)

ALL_SCRAPERS = [
    Scholars4DevScraper(),
    OpportunitiesForAfricansScraper(),
    ScholarshipsKenyaScraper(),
    AfterSchoolAfricaScraper(),
    ScholarshipsAdsScraper(),
    AdvanceAfricaScraper(),
    FundsForNGOsScraper(),
    GrantsGovScraper(),
    OpenPhilanthropyScraper(),
    RSSFeedScraper(),
]

def run_scrape_cycle():
    log.info("Starting scrape cycle with %d scrapers...", len(ALL_SCRAPERS))
    new_count = 0

    for scraper in ALL_SCRAPERS:
        log.info("Scraping %s...", scraper.name)
        try:
            opps = scraper.scrape()
            log.info("Found %d opportunities from %s", len(opps), scraper.name)

            for opp in opps:
                if opportunity_exists(opp.uid):
                    continue

                opp.category = categorize(opp)

                if opp.url.startswith("http"):
                    try:
                        session = scraper.get_session()
                        opp = scrape_detail(session, opp)
                    except Exception as e:
                        log.debug("Detail scrape failed for %s: %s", opp.url, e)

                if opp.description and len(opp.description) > 30:
                    opp.summary = summarize_opportunity(
                        opp.title, opp.description, opp.amount, opp.deadline
                    )
                else:
                    opp.summary = opp.title

                save_opportunity({
                    "uid": opp.uid,
                    "title": opp.title,
                    "url": opp.url,
                    "source": opp.source,
                    "description": opp.description,
                    "summary": opp.summary,
                    "category": opp.category,
                    "amount": opp.amount,
                    "deadline": opp.deadline,
                    "eligibility": opp.eligibility,
                    "host_country": opp.host_country,
                    "level": opp.level,
                    "benefits": opp.benefits,
                    "posted_at": time.time(),
                })
                new_count += 1

        except Exception as e:
            log.error("Scraper %s failed: %s", scraper.name, e)

    log.info("Scrape cycle complete. %d new opportunities.", new_count)
    return new_count
