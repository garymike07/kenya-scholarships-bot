"""
Standalone script for GitHub Actions.
Runs one scrape cycle + posts new opportunities to Telegram channel.
No long-running process needed.
"""
import sys
import os
import signal
import asyncio
import logging

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

MAX_RUNTIME_SECONDS = 50 * 60  # 50 minutes safety margin


def timeout_handler(signum, frame):
    log.warning("Reached max runtime, moving to post phase...")
    raise TimeoutError("Max runtime reached")


async def main():
    from services.database import init_db
    from services.scrape_engine import run_scrape_cycle
    from services.telegram_bot import build_app, post_to_channel

    log.info("Initializing database...")
    init_db()

    log.info("Running scrape cycle...")
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(MAX_RUNTIME_SECONDS - 300)  # Leave 5 min for posting
    try:
        new_count = run_scrape_cycle()
        log.info("Scraped %d new opportunities", new_count)
    except TimeoutError:
        log.warning("Scrape cycle cut short by timeout, posting what we have...")
    finally:
        signal.alarm(0)

    log.info("Posting to Telegram channel...")
    app = build_app()
    async with app:
        await post_to_channel(app)

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
