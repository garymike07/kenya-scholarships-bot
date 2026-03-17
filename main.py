import sys
import os
import asyncio
import logging
import concurrent.futures

sys.path.insert(0, os.path.dirname(__file__))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import SCRAPE_INTERVAL_MINUTES
from services.database import init_db
from services.scrape_engine import run_scrape_cycle
from services.telegram_bot import build_app, post_to_channel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "bot.log")),
    ],
)
log = logging.getLogger(__name__)

_scrape_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="scraper")


async def scheduled_job(app):
    log.info("Running scheduled scrape in background thread...")
    loop = asyncio.get_event_loop()
    new_count = await loop.run_in_executor(_scrape_executor, run_scrape_cycle)
    log.info("Background scrape done: %d new opportunities", new_count)
    await post_to_channel(app)


def main():
    log.info("Initializing database...")
    init_db()

    log.info("Starting Telegram bot (scrape will run in background)...")
    app = build_app()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_job, "interval",
        minutes=SCRAPE_INTERVAL_MINUTES,
        args=[app],
        id="scrape_cycle",
        max_instances=1,
    )

    async def post_init(application):
        scheduler.start()
        log.info("Scheduler started - scraping every %d minutes", SCRAPE_INTERVAL_MINUTES)
        # Run initial scrape in background thread so bot is responsive immediately
        loop = asyncio.get_event_loop()
        loop.run_in_executor(_scrape_executor, run_scrape_cycle)
        log.info("Initial scrape started in background - bot is ready for chat!")
        await post_to_channel(application)

    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
