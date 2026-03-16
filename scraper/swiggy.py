"""
scraper/swiggy.py
─────────────────────────────────────────────────────────────────
Scrapes menu prices from Swiggy by intercepting the internal JSON
API call that Swiggy's own app makes when loading a restaurant page.
Much more reliable than HTML parsing — survives UI redesigns.

How it works:
  1. Opens the restaurant URL in a headless Chromium browser
  2. Attaches a network listener before navigation
  3. Swiggy's JS fires a request to /dapi/menu/pl?...
  4. We capture that JSON response directly
  5. Parse dishes, prices, categories from the structured data
  6. Store to MongoDB with timestamp
─────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import async_playwright, Response
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [SWIGGY] %(message)s')
log = logging.getLogger(__name__)

# ── MongoDB ───────────────────────────────────────────────
MONGO_URI = os.getenv('MONGO_URI')
DELIVERY_LAT = os.getenv('DELIVERY_LAT', '19.0543')
DELIVERY_LNG = os.getenv('DELIVERY_LNG', '72.8414')

# ── Restaurants to scrape ─────────────────────────────────
# Format: (display_name, swiggy_rest_id, swiggy_slug)
RESTAURANTS = [
    ('The Bombay Canteen',   '26095',  'the-bombay-canteen-lower-parel'),
    ('Mahesh Lunch Home',    '1234',   'mahesh-lunch-home-fort'),
    ('Swati Snacks',         '5678',   'swati-snacks-tardeo'),
    ('Chaitanya',            '9012',   'chaitanya-santacruz'),
    ('Tanjore Tiffin Room',  '3456',   'tanjore-tiffin-room-matunga'),
    ('Peshawri',             '7890',   'peshawri-juhu'),
    ('Britannia & Co.',      '2345',   'britannia-co-ballard-estate'),
    ('Trishna',              '6789',   'trishna-fort'),
    ('Cafe Mondegar',        '0123',   'cafe-mondegar-colaba'),
    ('Oh! Calcutta',         '4567',   'oh-calcutta-tardeo'),
    ('Bayroute',             '8901',   'bayroute-juhu'),
    ('O Pedro',              '2346',   'o-pedro-bkc'),
    ('Jamavar',              '6790',   'jamavar-lower-parel'),
    ('Dakshinayan',          '0124',   'dakshinayan-sion'),
    ('Cafe Madras',          '4568',   'cafe-madras-matunga'),
    ('Flurys',               '8902',   'flurys-fort'),
    ('Amar Juice Centre',    '2347',   'amar-juice-centre-vile-parle'),
    ('Taftoon',              '6791',   'taftoon-andheri-west'),
    ('Bastian',              '0125',   'bastian-bandra-west'),
    ('Mumbai Vada Pav Co.',  '4569',   'mumbai-vada-pav-co-dadar'),
    ('Anand Bhavan',         '8903',   'anand-bhavan-matunga'),
    ("Jimmy's Rolls",        '2348',   'jimmys-rolls-andheri-west'),
]


def make_swiggy_cookies() -> list[dict]:
    """Build cookie list from environment variables."""
    return [
        {'name': '__SWhr',        'value': os.getenv('SWIGGY_SWR', ''),         'domain': '.swiggy.com', 'path': '/'},
        {'name': 'deviceId',      'value': os.getenv('SWIGGY_DEVICE_ID', ''),   'domain': '.swiggy.com', 'path': '/'},
        {'name': '_session_tid',  'value': os.getenv('SWIGGY_SESSION_TID', ''), 'domain': '.swiggy.com', 'path': '/'},
        {'name': '_is_logged_in', 'value': '1',                                  'domain': '.swiggy.com', 'path': '/'},
    ]


def parse_menu_response(data: dict) -> list[dict]:
    """
    Parse Swiggy's internal menu API response into a flat list of dishes.
    Swiggy's response structure:
      data.data.cards → array of category cards
        each card.groupedCard.cardGroupMap.REGULAR.cards → items
          each item.card.card.info → dish info
    """
    dishes = []
    try:
        cards = (data.get('data', {})
                     .get('data', {})
                     .get('cards', []))
        for card in cards:
            # Navigate nested structure
            grouped = card.get('groupedCard', {})
            card_group = grouped.get('cardGroupMap', {})
            regular = card_group.get('REGULAR', {})
            sub_cards = regular.get('cards', [])

            for sub in sub_cards:
                info = (sub.get('card', {})
                            .get('card', {})
                            .get('info', {}))
                if not info or not info.get('name'):
                    continue

                # Extract price — Swiggy stores in paise (divide by 100)
                price_paise = (info.get('price') or
                               info.get('defaultPrice') or
                               info.get('finalPrice') or 0)
                price = round(price_paise / 100) if price_paise > 100 else price_paise

                if not price:
                    continue

                dishes.append({
                    'id':           info.get('id', ''),
                    'name':         info.get('name', ''),
                    'category':     info.get('category', 'Mains'),
                    'description':  info.get('description', ''),
                    'price':        price,
                    'is_veg':       info.get('itemAttribute', {}).get('vegClassifier') == 'VEG',
                    'image_url':    (info.get('imageId', '') and
                                    f"https://media-assets.swiggy.com/swiggy/image/upload/fl_lossy,f_auto,q_auto,h_208,w_300/{info['imageId']}"),
                    'available':    not info.get('inStock') == False,
                    'platform':     'swiggy',
                    'scraped_at':   datetime.now(timezone.utc).isoformat(),
                })
    except Exception as e:
        log.warning(f'parse_menu_response error: {e}')

    return dishes


async def scrape_restaurant(page, rest_id: str, slug: str, display_name: str) -> Optional[list]:
    """Scrape a single Swiggy restaurant by intercepting its menu API call."""
    captured = []

    async def handle_response(response: Response):
        """Capture the menu API JSON response."""
        if ('/dapi/menu/pl' in response.url or
                '/api/instamart/menu' in response.url):
            try:
                body = await response.json()
                captured.append(body)
            except Exception:
                pass

    page.on('response', handle_response)

    url = (f'https://www.swiggy.com/city/mumbai/{slug}-rest{rest_id}'
           f'?lat={DELIVERY_LAT}&lng={DELIVERY_LNG}')

    try:
        await page.goto(url, wait_until='networkidle', timeout=30000)
        # Give extra time for the menu API call to fire
        await asyncio.sleep(3)
    except Exception as e:
        log.warning(f'{display_name}: navigation failed — {e}')
        return None
    finally:
        page.remove_listener('response', handle_response)

    if not captured:
        log.warning(f'{display_name}: no menu API response captured')
        return None

    dishes = parse_menu_response(captured[0])
    log.info(f'{display_name}: {len(dishes)} dishes scraped')
    return dishes


async def save_to_mongo(db, rest_name: str, rest_id: str, dishes: list):
    """Upsert dishes into MongoDB. Append to price_history."""
    now = datetime.now(timezone.utc)

    # Upsert current prices (overwrite each scrape)
    for dish in dishes:
        await db.prices.update_one(
            {'restaurant_id': rest_id, 'dish_name': dish['name'], 'platform': 'swiggy'},
            {'$set': {
                'restaurant_id':   rest_id,
                'restaurant_name': rest_name,
                'dish_name':       dish['name'],
                'category':        dish['category'],
                'price':           dish['price'],
                'is_veg':          dish['is_veg'],
                'available':       dish.get('available', True),
                'image_url':       dish.get('image_url', ''),
                'platform':        'swiggy',
                'updated_at':      now,
            }},
            upsert=True
        )
        # Append to history — never deleted
        await db.price_history.insert_one({
            'restaurant_id':   rest_id,
            'restaurant_name': rest_name,
            'dish_name':       dish['name'],
            'price':           dish['price'],
            'platform':        'swiggy',
            'scraped_at':      now,
        })

    # Update restaurant last_scraped timestamp
    await db.restaurants.update_one(
        {'swiggy_id': rest_id},
        {'$set': {'last_scraped_swiggy': now, 'name': rest_name}},
        upsert=True
    )
    log.info(f'{rest_name}: saved {len(dishes)} dishes to MongoDB')


async def run_swiggy_scraper():
    """Main entry point — scrapes all restaurants sequentially."""
    log.info('Starting Swiggy scraper...')
    client = AsyncIOMotorClient(MONGO_URI)
    db = client['nexa']

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Linux; Android 15; iQOO Z9 5G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
            viewport={'width': 390, 'height': 844},
            locale='en-IN',
            timezone_id='Asia/Kolkata',
        )

        # Inject session cookies
        await context.add_cookies(make_swiggy_cookies())

        page = await context.new_page()

        # Block images/fonts to speed up scraping
        await page.route('**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}',
                         lambda r: r.abort())

        success = 0
        for display_name, rest_id, slug in RESTAURANTS:
            try:
                dishes = await scrape_restaurant(page, rest_id, slug, display_name)
                if dishes:
                    await save_to_mongo(db, display_name, rest_id, dishes)
                    success += 1
                # Polite delay between requests — avoid triggering rate limiting
                await asyncio.sleep(4)
            except Exception as e:
                log.error(f'{display_name}: unexpected error — {e}')

        await browser.close()

    client.close()
    log.info(f'Swiggy scraper complete. {success}/{len(RESTAURANTS)} restaurants scraped.')


if __name__ == '__main__':
    asyncio.run(run_swiggy_scraper())
