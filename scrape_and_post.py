"""
Standalone script for GitHub Actions.
Runs one scrape cycle + posts new opportunities to Telegram channel.
No long-running process needed.
"""
import sys
import os
import asyncio
import logging

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


async def main():
    from services.database import init_db
    from services.scrape_engine import run_scrape_cycle
    from services.telegram_bot import build_app, post_to_channel

    log.info("Initializing database...")
    init_db()

    log.info("Running scrape cycle...")
    new_count = run_scrape_cycle()
    log.info("Scraped %d new opportunities", new_count)

    log.info("Posting to Telegram channel...")
    app = build_app()
    async with app:
        await post_to_channel(app)

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
