"""
scraper/zomato.py
─────────────────────────────────────────────────────────────────
Scrapes menu prices from Zomato by intercepting the internal JSON
API call Zomato fires when loading the order page.

Zomato's menu endpoint pattern:
  GET /webroutes/getPage?...  (initial page data, contains menu)
  GET /webroutes/menu/...     (direct menu endpoint on some routes)

We capture whichever fires and parse the menu items from it.
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
logging.basicConfig(level=logging.INFO, format='%(asctime)s [ZOMATO] %(message)s')
log = logging.getLogger(__name__)

MONGO_URI     = os.getenv('MONGO_URI')
DELIVERY_LAT  = os.getenv('DELIVERY_LAT', '19.0543')
DELIVERY_LNG  = os.getenv('DELIVERY_LNG', '72.8414')

# ── Restaurants on Zomato ─────────────────────────────────
# Format: (display_name, zomato_url_slug)
RESTAURANTS = [
    ('The Bombay Canteen',  'thebombaycanteen'),
    ('Masque',              'masque-mahalaxmi'),
    ('Mahesh Lunch Home',   'mahesh-lunch-home-fort'),
    ('Chaitanya',           'chaitanya-santacruz-west'),
    ('Masala Library',      'masala-library-by-jiggs-kalra-bkc'),
    ('Tanjore Tiffin Room', 'tanjore-tiffin-room-matunga'),
    ('Peshawri',            'peshawri-itc-maratha-andheri-east'),
    ('Trishna',             'trishna-fort'),
    ('Oh! Calcutta',        'oh-calcutta-tardeo'),
    ('Wasabi by Morimoto',  'wasabi-by-morimoto-colaba'),
    ('Cafe Mondegar',       'cafe-mondegar-colaba'),
    ('O Pedro',             'o-pedro-bkc'),
    ('Ekaa',                'ekaa-marine-lines'),
    ('Jamavar',             'jamavar-lower-parel'),
    ('Leopold Cafe',        'leopold-cafe-bar-colaba'),
    ('The Table',           'the-table-colaba'),
    ('Flurys',              'flurys-fort'),
    ('Kyani & Co.',         'kyani-and-co-dhobitalao'),
    ('Taftoon',             'taftoon-bar-and-kitchen-andheri-west'),
    ('Bastian',             'bastian-seafood-bandra-west'),
    ('Aaswad',              'aaswad-dadar-west'),
    ('Shree Thaker',        'shree-thaker-bhojanalay-kalbadevi'),
    ('Anand Bhavan',        'anand-bhavan-matunga'),
    ('Mumbai Vada Pav Co.', 'mumbai-vada-pav-co-dadar'),
]


def make_zomato_headers() -> dict:
    """Headers that make requests look like a real browser session."""
    return {
        'accept':           'application/json, text/plain, */*',
        'accept-language':  'en-IN,en;q=0.9',
        'x-zomato-csrft':   os.getenv('ZOMATO_CSRF', ''),
        'cookie':           (
            f'PHPSESSID={os.getenv("ZOMATO_PHPSESSID", "")}; '
            f'csrf={os.getenv("ZOMATO_CSRF", "")};'
        ),
        'referer':          'https://www.zomato.com/',
    }


def parse_zomato_menu(data: dict) -> list[dict]:
    """
    Parse Zomato's getPage response into a flat dish list.
    Zomato's structure varies — we try multiple known paths.
    """
    dishes = []
    now = datetime.now(timezone.utc).isoformat()

    def search_for_menus(obj, depth=0):
        """Recursively search JSON for menu item arrays."""
        if depth > 8 or not isinstance(obj, dict):
            return
        # Common Zomato menu item keys
        for key in ('menu', 'menuList', 'items', 'categories', 'sections'):
            if key in obj:
                val = obj[key]
                if isinstance(val, list):
                    for item in val:
                        extract_dish(item)
                elif isinstance(val, dict):
                    search_for_menus(val, depth + 1)
        for v in obj.values():
            if isinstance(v, dict):
                search_for_menus(v, depth + 1)

    def extract_dish(item):
        if not isinstance(item, dict):
            return
        name = item.get('name') or item.get('item_name') or item.get('title')
        if not name:
            return
        price = (item.get('price') or item.get('item_price') or
                 item.get('display_price') or item.get('cost') or 0)
        try:
            price = float(str(price).replace('₹', '').replace(',', '').strip())
        except (ValueError, TypeError):
            return
        if not price:
            return
        dishes.append({
            'name':       name,
            'category':   item.get('category', item.get('type', 'Mains')),
            'price':      round(price),
            'is_veg':     item.get('item_tag') == 'veg' or item.get('is_veg', False),
            'available':  not item.get('is_available') == False,
            'image_url':  item.get('thumb_image', item.get('image', '')),
            'platform':   'zomato',
            'scraped_at': now,
        })
        # Recurse into sub-items / variants
        for sub_key in ('items', 'menuItems', 'subCategories'):
            if sub_key in item and isinstance(item[sub_key], list):
                for sub in item[sub_key]:
                    extract_dish(sub)

    search_for_menus(data)
    return dishes


async def scrape_restaurant(page, slug: str, display_name: str) -> Optional[list]:
    """Scrape a single Zomato restaurant."""
    captured = []

    async def handle_response(response: Response):
        url = response.url
        # Capture JSON responses from Zomato's internal routes
        if ('zomato.com/webroutes' in url or
                'zomato.com/api' in url or
                'webroutes/getPage' in url):
            try:
                ct = response.headers.get('content-type', '')
                if 'json' in ct:
                    body = await response.json()
                    captured.append(body)
            except Exception:
                pass

    page.on('response', handle_response)
    url = f'https://www.zomato.com/{slug}/order'

    try:
        await page.goto(url, wait_until='networkidle', timeout=35000)
        await asyncio.sleep(3)
    except Exception as e:
        log.warning(f'{display_name}: navigation failed — {e}')
        return None
    finally:
        page.remove_listener('response', handle_response)

    all_dishes = []
    for response_data in captured:
        dishes = parse_zomato_menu(response_data)
        all_dishes.extend(dishes)

    # Deduplicate by name
    seen = set()
    unique = []
    for d in all_dishes:
        if d['name'] not in seen:
            seen.add(d['name'])
            unique.append(d)

    log.info(f'{display_name}: {len(unique)} dishes scraped')
    return unique if unique else None


async def save_to_mongo(db, rest_name: str, slug: str, dishes: list):
    """Upsert current prices, append to history."""
    now = datetime.now(timezone.utc)
    for dish in dishes:
        await db.prices.update_one(
            {'restaurant_id': slug, 'dish_name': dish['name'], 'platform': 'zomato'},
            {'$set': {
                'restaurant_id':   slug,
                'restaurant_name': rest_name,
                'dish_name':       dish['name'],
                'category':        dish['category'],
                'price':           dish['price'],
                'is_veg':          dish['is_veg'],
                'available':       dish.get('available', True),
                'image_url':       dish.get('image_url', ''),
                'platform':        'zomato',
                'updated_at':      now,
            }},
            upsert=True
        )
        await db.price_history.insert_one({
            'restaurant_id':   slug,
            'restaurant_name': rest_name,
            'dish_name':       dish['name'],
            'price':           dish['price'],
            'platform':        'zomato',
            'scraped_at':      now,
        })
    await db.restaurants.update_one(
        {'zomato_slug': slug},
        {'$set': {'last_scraped_zomato': now, 'name': rest_name}},
        upsert=True
    )
    log.info(f'{rest_name}: saved {len(dishes)} dishes to MongoDB')


async def run_zomato_scraper():
    """Main entry point."""
    log.info('Starting Zomato scraper...')
    client = AsyncIOMotorClient(MONGO_URI)
    db = client['nexa']

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Linux; Android 15; iQOO Z9 5G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
            viewport={'width': 390, 'height': 844},
            locale='en-IN',
            timezone_id='Asia/Kolkata',
            extra_http_headers=make_zomato_headers(),
        )
        await context.add_cookies([
            {'name': 'PHPSESSID', 'value': os.getenv('ZOMATO_PHPSESSID', ''), 'domain': '.zomato.com', 'path': '/'},
            {'name': 'csrf',      'value': os.getenv('ZOMATO_CSRF', ''),      'domain': '.zomato.com', 'path': '/'},
        ])

        page = await context.new_page()
        await page.route('**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}',
                         lambda r: r.abort())

        success = 0
        for display_name, slug in RESTAURANTS:
            try:
                dishes = await scrape_restaurant(page, slug, display_name)
                if dishes:
                    await save_to_mongo(db, display_name, slug, dishes)
                    success += 1
                await asyncio.sleep(5)
            except Exception as e:
                log.error(f'{display_name}: unexpected error — {e}')

        await browser.close()

    client.close()
    log.info(f'Zomato scraper complete. {success}/{len(RESTAURANTS)} restaurants scraped.')


if __name__ == '__main__':
    asyncio.run(run_zomato_scraper())
