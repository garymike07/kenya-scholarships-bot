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
    handlers=[logging.StreamHandler()],
    force=True,
)
log = logging.getLogger(__name__)

_scrape_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="scraper")


async def run_scrape_and_post(app, label: str = "Scheduled"):
    log.info("%s scrape starting in background thread...", label)
    loop = asyncio.get_event_loop()
    new_count = await loop.run_in_executor(_scrape_executor, run_scrape_cycle)
    log.info("%s scrape done: %d new opportunities", label, new_count)
    await post_to_channel(app)


async def scheduled_job(app):
    await run_scrape_and_post(app, "Scheduled")


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
        asyncio.create_task(run_scrape_and_post(application, "Initial"))
        log.info("Initial scrape started in background - bot is ready for chat!")

    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
