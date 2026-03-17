import sys
import os
import asyncio
import logging

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


async def scheduled_job(app):
    log.info("Running scheduled scrape + post cycle")
    run_scrape_cycle()
    await post_to_channel(app)


def main():
    log.info("Initializing database...")
    init_db()

    log.info("Running initial scrape...")
    run_scrape_cycle()

    log.info("Starting Telegram bot...")
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
        await post_to_channel(application)

    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
