"""
scraper/scheduler.py
─────────────────────────────────────────────────────────────────
Runs Swiggy and Zomato scrapers every 3 hours.
Run this on your laptop while developing:
    python scraper/scheduler.py

On Render, this is the background worker process.
─────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from swiggy import run_swiggy_scraper
from zomato import run_zomato_scraper

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [SCHEDULER] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

INTERVAL_HOURS = int(os.getenv('SCRAPE_INTERVAL_HOURS', '3'))


async def run_all_scrapers():
    """Run Swiggy then Zomato sequentially."""
    log.info(f'=== Scrape cycle started at {datetime.now().strftime("%H:%M:%S")} ===')
    try:
        await run_swiggy_scraper()
    except Exception as e:
        log.error(f'Swiggy scraper failed: {e}')
    try:
        await run_zomato_scraper()
    except Exception as e:
        log.error(f'Zomato scraper failed: {e}')
    log.info('=== Scrape cycle complete ===')


async def main():
    # Run once immediately on startup
    log.info('Running initial scrape on startup...')
    await run_all_scrapers()

    # Then schedule every N hours
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_all_scrapers,
        'interval',
        hours=INTERVAL_HOURS,
        id='nexa_scraper',
    )
    scheduler.start()
    log.info(f'Scheduler running. Next scrape in {INTERVAL_HOURS} hours.')

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info('Scheduler stopped.')


if __name__ == '__main__':
    asyncio.run(main())
