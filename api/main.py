"""
api/main.py
─────────────────────────────────────────────────────────────────
FastAPI backend for Nexa.
Serves scraped Swiggy/Zomato prices to the frontend.

Endpoints:
  GET  /api/restaurants           list all restaurants
  GET  /api/restaurants/:id/menu  menu with latest prices
  GET  /api/rides/estimate        formula-based fare estimate
  POST /api/prices/confirm        user-reported price confirmation
  GET  /api/health                health check for Render
─────────────────────────────────────────────────────────────────
"""

import os
import math
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title='Nexa API',
    description='Real-time price comparison for rides and food delivery in Mumbai',
    version='1.0.0'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],   # Tighten to your Vercel domain in production
    allow_methods=['*'],
    allow_headers=['*'],
)

# ── Database ──────────────────────────────────────────────
MONGO_URI = os.getenv('MONGO_URI')
client: Optional[AsyncIOMotorClient] = None
db = None


@app.on_event('startup')
async def startup():
    global client, db
    client = AsyncIOMotorClient(MONGO_URI)
    db = client['nexa']
    log.info('Connected to MongoDB Atlas')
    # Create indexes for fast queries
    await db.prices.create_index([('restaurant_id', 1), ('platform', 1)])
    await db.prices.create_index([('dish_name', 'text')])
    await db.price_history.create_index([('restaurant_id', 1), ('dish_name', 1), ('scraped_at', -1)])


@app.on_event('shutdown')
async def shutdown():
    if client:
        client.close()


# ── Static restaurant list (matches frontend RESTS array) ─
RESTAURANTS_STATIC = [
    {'id': '26095',               'name': 'The Bombay Canteen',    'cuisine': 'Modern Indian',        'area': 'Lower Parel',   'rating': 4.6, 'p2': 1800, 'sw': True, 'zm': True,  'veg': False},
    {'id': 'masque-mahalaxmi',    'name': 'Masque',                'cuisine': 'Fine Dining',          'area': 'Mahalaxmi',     'rating': 4.8, 'p2': 4000, 'sw': False,'zm': True,  'veg': False},
    {'id': '1234',                'name': 'Mahesh Lunch Home',     'cuisine': 'Mangalorean Seafood',  'area': 'Fort',          'rating': 4.5, 'p2': 1600, 'sw': True, 'zm': True,  'veg': False},
    {'id': '5678',                'name': 'Swati Snacks',          'cuisine': 'Gujarati Street Food', 'area': 'Tardeo',        'rating': 4.7, 'p2': 600,  'sw': True, 'zm': False, 'veg': True},
    {'id': '9012',                'name': 'Chaitanya',             'cuisine': 'Malvani Seafood',      'area': 'Santacruz',     'rating': 4.4, 'p2': 1200, 'sw': True, 'zm': True,  'veg': False},
    {'id': '3456',                'name': 'Tanjore Tiffin Room',   'cuisine': 'South Indian',         'area': 'Matunga',       'rating': 4.5, 'p2': 900,  'sw': True, 'zm': True,  'veg': False},
    {'id': '7890',                'name': 'Peshawri',              'cuisine': 'North Indian',         'area': 'Juhu',          'rating': 4.6, 'p2': 2800, 'sw': True, 'zm': True,  'veg': False},
    {'id': '2345',                'name': 'Britannia & Co.',       'cuisine': 'Parsi',                'area': 'Ballard Estate','rating': 4.8, 'p2': 800,  'sw': True, 'zm': False, 'veg': False},
    {'id': '6789',                'name': 'Trishna',               'cuisine': 'Seafood',              'area': 'Fort',          'rating': 4.7, 'p2': 2200, 'sw': True, 'zm': True,  'veg': False},
    {'id': 'aaswad-dadar-west',   'name': 'Aaswad',                'cuisine': 'Maharashtrian',        'area': 'Dadar',         'rating': 4.6, 'p2': 400,  'sw': False,'zm': True,  'veg': True},
    {'id': '4569',                'name': 'Mumbai Vada Pav Co.',   'cuisine': 'Street Food',          'area': 'Dadar',         'rating': 4.3, 'p2': 200,  'sw': True, 'zm': True,  'veg': True},
    {'id': '8903',                'name': 'Anand Bhavan',          'cuisine': 'South Indian',         'area': 'Matunga',       'rating': 4.4, 'p2': 300,  'sw': True, 'zm': True,  'veg': True},
    {'id': '2348',                'name': "Jimmy's Rolls",         'cuisine': 'Street Food',          'area': 'Andheri West',  'rating': 4.2, 'p2': 280,  'sw': True, 'zm': False, 'veg': False},
]


# ── Fare formula ──────────────────────────────────────────
FARE_FORMULAS = {
    'bike':   {'uber': (20,8,1.0),  'ola': (20,7,.75),  'rapido': (20,7,.75)},
    'auto':   {'uber': (30,10,1.0), 'ola': (28,9,.9),   'rapido': (25,9,.85)},
    'mini':   {'uber': (50,12,1.5), 'ola': (45,11,1.25),'rapido': (38,10,1.1)},
    'sedan':  {'uber': (55,14,1.75),'ola': (55,13,1.6), 'rapido': (48,12,1.4)},
    'prime':  {'uber': (65,16,2.0), 'ola': (65,15,1.9), 'rapido': (55,13,1.6)},
    'suv':    {'uber': (80,20,2.5), 'ola': (80,18,2.3), 'rapido': (70,17,2.1)},
    'luxury': {'uber': (100,17,2.0),'ola': (120,24,3.0)},
}


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)) * 1.3


# ── Endpoints ─────────────────────────────────────────────

@app.get('/api/health')
async def health():
    return {'status': 'ok', 'time': datetime.now(timezone.utc).isoformat()}


@app.get('/api/restaurants')
async def get_restaurants(
    cuisine: Optional[str] = None,
    platform: Optional[str] = None,
    veg: Optional[bool] = None,
):
    """Return restaurant list, optionally filtered."""
    result = RESTAURANTS_STATIC
    if cuisine:
        result = [r for r in result if cuisine.lower() in r['cuisine'].lower()]
    if platform == 'swiggy':
        result = [r for r in result if r['sw']]
    elif platform == 'zomato':
        result = [r for r in result if r['zm']]
    if veg is not None:
        result = [r for r in result if r['veg'] == veg]
    return {'restaurants': result, 'total': len(result)}


@app.get('/api/restaurants/{restaurant_id}/menu')
async def get_menu(restaurant_id: str):
    """
    Return menu for a restaurant with latest scraped prices.
    Merges Swiggy and Zomato prices into a unified dish list.
    """
    # Fetch latest prices from both platforms
    swiggy_cursor = db.prices.find(
        {'restaurant_id': restaurant_id, 'platform': 'swiggy'},
        {'_id': 0}
    )
    zomato_cursor = db.prices.find(
        {'restaurant_id': restaurant_id, 'platform': 'zomato'},
        {'_id': 0}
    )

    swiggy_dishes = {d['dish_name']: d async for d in swiggy_cursor}
    zomato_dishes = {d['dish_name']: d async for d in zomato_cursor}

    # Merge by dish name
    all_names = set(swiggy_dishes) | set(zomato_dishes)
    merged = []
    for name in all_names:
        sw = swiggy_dishes.get(name)
        zm = zomato_dishes.get(name)
        base = sw or zm
        merged.append({
            'name':       name,
            'category':   base.get('category', 'Mains'),
            'is_veg':     base.get('is_veg', False),
            'image_url':  base.get('image_url', ''),
            'available':  base.get('available', True),
            'sw':         sw['price'] if sw else None,
            'zm':         zm['price'] if zm else None,
            'updated_at': base.get('updated_at', '').isoformat() if hasattr(base.get('updated_at', ''), 'isoformat') else str(base.get('updated_at', '')),
        })

    # Sort by category then name
    merged.sort(key=lambda x: (x['category'], x['name']))

    if not merged:
        raise HTTPException(status_code=404, detail='No prices found for this restaurant. Run the scraper first.')

    # Find the most recent update time
    updated_at = None
    for d in (list(swiggy_dishes.values()) + list(zomato_dishes.values())):
        t = d.get('updated_at')
        if t and (not updated_at or t > updated_at):
            updated_at = t

    return {
        'restaurant_id': restaurant_id,
        'dishes':        merged,
        'total':         len(merged),
        'updated_at':    updated_at.isoformat() if updated_at and hasattr(updated_at, 'isoformat') else None,
        'source':        'live',
    }


@app.get('/api/rides/estimate')
async def estimate_rides(
    pickup_lat:  float = Query(...),
    pickup_lng:  float = Query(...),
    drop_lat:    float = Query(...),
    drop_lng:    float = Query(...),
    tier:        str   = Query('mini'),
):
    """Formula-based fare estimate across all platforms for a tier."""
    km = haversine_km(pickup_lat, pickup_lng, drop_lat, drop_lng)
    mn = round(km * 3.5)
    formulas = FARE_FORMULAS.get(tier, FARE_FORMULAS['mini'])

    fares = []
    plat_names = {'uber': 'Uber', 'ola': 'Ola', 'rapido': 'Rapido'}
    for plat, (base, per_km, per_mn) in formulas.items():
        fare = round(base + km * per_km + mn * per_mn)
        fares.append({'platform': plat_names[plat], 'fare': fare})

    fares.sort(key=lambda x: x['fare'])
    return {
        'tier':    tier,
        'km':      round(km, 1),
        'minutes': mn,
        'fares':   fares,
        'source':  'formula',
    }


@app.get('/api/prices/history/{restaurant_id}/{dish_name}')
async def price_history(restaurant_id: str, dish_name: str, platform: str = 'swiggy', days: int = 7):
    """Return price history for a dish — used for trend charts."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cursor = db.price_history.find(
        {
            'restaurant_id': restaurant_id,
            'dish_name':     dish_name,
            'platform':      platform,
            'scraped_at':    {'$gte': cutoff},
        },
        {'_id': 0, 'price': 1, 'scraped_at': 1}
    ).sort('scraped_at', 1)
    history = [
        {'price': d['price'], 'date': d['scraped_at'].isoformat()}
        async for d in cursor
    ]
    return {'dish': dish_name, 'platform': platform, 'history': history}


class PriceConfirmation(BaseModel):
    restaurant_id: str
    dish_name:     str
    platform:      str
    actual_price:  float
    reported_at:   Optional[str] = None


@app.post('/api/prices/confirm')
async def confirm_price(body: PriceConfirmation):
    """Accept user-reported actual checkout prices for crowdsourced accuracy."""
    await db.price_confirmations.insert_one({
        'restaurant_id': body.restaurant_id,
        'dish_name':     body.dish_name,
        'platform':      body.platform,
        'actual_price':  body.actual_price,
        'reported_at':   body.reported_at or datetime.now(timezone.utc).isoformat(),
    })
    return {'status': 'confirmed', 'message': 'Price reported. Thank you.'}


@app.get('/api/search')
async def search(q: str = Query(..., min_length=2)):
    """Full-text search across dish names in MongoDB."""
    cursor = db.prices.find(
        {'$text': {'$search': q}},
        {'score': {'$meta': 'textScore'}, '_id': 0}
    ).sort([('score', {'$meta': 'textScore'})]).limit(20)
    results = [d async for d in cursor]
    return {'results': results, 'query': q}
