"""
api/main.py
─────────────────────────────────────────────────────────────────
FastAPI backend for Nexa.

Endpoints:
  GET  /api/health
  GET  /api/restaurants
  GET  /api/restaurants/:id/menu
  GET  /api/rides/estimate
  GET  /api/prices/history/:id/:dish
  POST /api/prices/confirm
  POST /api/prices/batch
  POST /api/rides/report
  POST /api/restaurants/report
  GET  /api/search
─────────────────────────────────────────────────────────────────
"""

import os
import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title='Nexa API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

MONGO_URI = os.getenv('MONGO_URI')
client: Optional[AsyncIOMotorClient] = None
db = None


@app.on_event('startup')
async def startup():
    global client, db
    client = AsyncIOMotorClient(MONGO_URI)
    db = client['nexa']
    log.info('Connected to MongoDB Atlas')
    try:
        await db.prices.create_index([('restaurant_id', 1), ('platform', 1)])
        await db.prices.create_index([('dish_name', 'text')])
        await db.price_history.create_index([('restaurant_id', 1), ('dish_name', 1), ('scraped_at', -1)])
        await db.restaurants.create_index([('swiggy_id', 1)])
        await db.restaurants.create_index([('zomato_slug', 1)])
        await db.restaurants.create_index([('slug', 1)])
    except Exception as e:
        log.warning(f'Index warning: {e}')


@app.on_event('shutdown')
async def shutdown():
    if client:
        client.close()


RESTAURANTS_STATIC = [
    {'id': '26095',             'name': 'The Bombay Canteen',  'cuisine': 'Modern Indian',       'area': 'Lower Parel',  'rating': 4.6, 'p2': 1800, 'sw': True,  'zm': True,  'veg': False},
    {'id': '1234',              'name': 'Mahesh Lunch Home',   'cuisine': 'Mangalorean Seafood', 'area': 'Fort',         'rating': 4.5, 'p2': 1600, 'sw': True,  'zm': True,  'veg': False},
    {'id': '5678',              'name': 'Swati Snacks',        'cuisine': 'Gujarati',            'area': 'Tardeo',       'rating': 4.7, 'p2': 600,  'sw': True,  'zm': False, 'veg': True},
    {'id': '9012',              'name': 'Chaitanya',           'cuisine': 'Malvani Seafood',     'area': 'Santacruz',    'rating': 4.4, 'p2': 1200, 'sw': True,  'zm': True,  'veg': False},
    {'id': '7890',              'name': 'Peshawri',            'cuisine': 'North Indian',        'area': 'Juhu',         'rating': 4.6, 'p2': 2800, 'sw': True,  'zm': True,  'veg': False},
    {'id': '6789',              'name': 'Trishna',             'cuisine': 'Seafood',             'area': 'Fort',         'rating': 4.7, 'p2': 2200, 'sw': True,  'zm': True,  'veg': False},
    {'id': 'aaswad-dadar-west', 'name': 'Aaswad',             'cuisine': 'Maharashtrian',       'area': 'Dadar',        'rating': 4.6, 'p2': 400,  'sw': False, 'zm': True,  'veg': True},
    {'id': '4569',              'name': 'Mumbai Vada Pav Co.', 'cuisine': 'Street Food',         'area': 'Dadar',        'rating': 4.3, 'p2': 200,  'sw': True,  'zm': True,  'veg': True},
    {'id': '8903',              'name': 'Anand Bhavan',        'cuisine': 'South Indian',        'area': 'Matunga',      'rating': 4.4, 'p2': 300,  'sw': True,  'zm': True,  'veg': True},
    {'id': '2348',              'name': "Jimmy's Rolls",       'cuisine': 'Street Food',         'area': 'Andheri West', 'rating': 4.2, 'p2': 280,  'sw': True,  'zm': False, 'veg': False},
]

FARE_FORMULAS = {
    'bike':   {'uber': (20,8,1.0),   'ola': (20,7,.75),   'rapido': (20,7,.75)},
    'auto':   {'uber': (30,10,1.0),  'ola': (28,9,.9),    'rapido': (25,9,.85)},
    'mini':   {'uber': (50,12,1.5),  'ola': (45,11,1.25), 'rapido': (38,10,1.1)},
    'sedan':  {'uber': (55,14,1.75), 'ola': (55,13,1.6),  'rapido': (48,12,1.4)},
    'prime':  {'uber': (65,16,2.0),  'ola': (65,15,1.9),  'rapido': (55,13,1.6)},
    'suv':    {'uber': (80,20,2.5),  'ola': (80,18,2.3),  'rapido': (70,17,2.1)},
    'luxury': {'uber': (100,17,2.0), 'ola': (120,24,3.0)},
}
PLAT_NAMES = {'uber': 'Uber', 'ola': 'Ola', 'rapido': 'Rapido'}


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)) * 1.3


class PriceConfirmation(BaseModel):
    restaurant_id: str
    dish_name:     str
    platform:      str
    actual_price:  float
    reported_at:   Optional[str] = None

class PriceBatch(BaseModel):
    prices: List[dict]
    source: str = 'accessibility'

class RideReport(BaseModel):
    fares:  List[dict]
    source: str = 'accessibility'

class RestaurantReport(BaseModel):
    slug:      str
    name:      str
    platform:  str = ''
    on_swiggy: bool = False
    on_zomato: bool = False
    cuisine:   str = ''
    area:      str = 'Mumbai'
    rating:    float = 0
    image_url: str = ''


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'time': datetime.now(timezone.utc).isoformat()}


@app.get('/api/restaurants')
async def get_restaurants(
    cuisine:  Optional[str]  = None,
    platform: Optional[str]  = None,
    veg:      Optional[bool] = None,
):
    mongo_rests = []
    try:
        async for r in db.restaurants.find({}, {'_id': 0}):
            rest_id = (r.get('slug') or r.get('swiggy_id') or
                       r.get('zomato_slug') or r.get('id', ''))
            mongo_rests.append({
                'id':        rest_id,
                'name':      r.get('name', ''),
                'cuisine':   r.get('cuisine', ''),
                'area':      r.get('area', ''),
                'rating':    r.get('rating', 0),
                'p2':        r.get('price_for_two', 0),
                'sw':        r.get('on_swiggy', 'swiggy_id' in r or r.get('platform') == 'swiggy'),
                'zm':        r.get('on_zomato', 'zomato_slug' in r or r.get('platform') == 'zomato'),
                'veg':       r.get('veg', False),
                'image_url': r.get('image_url', ''),
            })
    except Exception as e:
        log.warning(f'MongoDB restaurants failed: {e}')

    result = mongo_rests if mongo_rests else RESTAURANTS_STATIC

    if cuisine:
        result = [r for r in result if cuisine.lower() in r.get('cuisine','').lower()]
    if platform == 'swiggy':
        result = [r for r in result if r.get('sw')]
    elif platform == 'zomato':
        result = [r for r in result if r.get('zm')]
    if veg is not None:
        result = [r for r in result if r.get('veg') == veg]

    return {'restaurants': result, 'total': len(result), 'source': 'live' if mongo_rests else 'demo'}


@app.get('/api/restaurants/{restaurant_id}/menu')
async def get_menu(restaurant_id: str):
    swiggy_dishes = {d['dish_name']: d async for d in db.prices.find(
        {'restaurant_id': restaurant_id, 'platform': 'swiggy'}, {'_id': 0})}
    zomato_dishes = {d['dish_name']: d async for d in db.prices.find(
        {'restaurant_id': restaurant_id, 'platform': 'zomato'}, {'_id': 0})}

    all_names = set(swiggy_dishes) | set(zomato_dishes)
    if not all_names:
        raise HTTPException(status_code=404,
            detail='No prices found. Browse this restaurant on Swiggy/Zomato with Nexa active.')

    merged = []
    for name in all_names:
        sw   = swiggy_dishes.get(name)
        zm   = zomato_dishes.get(name)
        base = sw or zm
        upd  = base.get('updated_at')
        merged.append({
            'name':       name,
            'category':   base.get('category', 'Mains'),
            'is_veg':     base.get('is_veg', False),
            'image_url':  base.get('image_url', ''),
            'available':  base.get('available', True),
            'sw':         sw['price'] if sw else None,
            'zm':         zm['price'] if zm else None,
            'updated_at': upd.isoformat() if hasattr(upd, 'isoformat') else str(upd or ''),
        })

    merged.sort(key=lambda x: (x['category'], x['name']))
    updated_at = None
    for d in list(swiggy_dishes.values()) + list(zomato_dishes.values()):
        t = d.get('updated_at')
        if t and (not updated_at or t > updated_at):
            updated_at = t

    return {
        'restaurant_id': restaurant_id,
        'dishes':        merged,
        'total':         len(merged),
        'updated_at':    updated_at.isoformat() if hasattr(updated_at, 'isoformat') else None,
        'source':        'live',
    }


@app.get('/api/rides/estimate')
async def estimate_rides(
    pickup_lat: float = Query(...),
    pickup_lng: float = Query(...),
    drop_lat:   float = Query(...),
    drop_lng:   float = Query(...),
    tier:       str   = Query('mini'),
):
    km = haversine_km(pickup_lat, pickup_lng, drop_lat, drop_lng)
    mn = round(km * 3.5)
    formulas = FARE_FORMULAS.get(tier, FARE_FORMULAS['mini'])

    real_fares = {}
    try:
        async for f in db.ride_fares.find({'tier': tier}, {'_id': 0}):
            real_fares[f['platform'].lower()] = f['fare']
    except Exception:
        pass

    fares = []
    for plat, (base, per_km, per_mn) in formulas.items():
        formula_fare = round(base + km * per_km + mn * per_mn)
        real_fare    = real_fares.get(plat.lower())
        fares.append({
            'platform': PLAT_NAMES.get(plat, plat),
            'fare':     real_fare if real_fare else formula_fare,
            'source':   'live' if real_fare else 'formula',
        })

    fares.sort(key=lambda x: x['fare'])
    return {'tier': tier, 'km': round(km, 1), 'minutes': mn, 'fares': fares}


@app.get('/api/prices/history/{restaurant_id}/{dish_name}')
async def price_history(restaurant_id: str, dish_name: str, platform: str = 'swiggy', days: int = 7):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cursor = db.price_history.find(
        {'restaurant_id': restaurant_id, 'dish_name': dish_name,
         'platform': platform, 'scraped_at': {'$gte': cutoff}},
        {'_id': 0, 'price': 1, 'scraped_at': 1}
    ).sort('scraped_at', 1)
    history = [{'price': d['price'], 'date': d['scraped_at'].isoformat()} async for d in cursor]
    return {'dish': dish_name, 'platform': platform, 'history': history}


@app.post('/api/prices/confirm')
async def confirm_price(body: PriceConfirmation):
    await db.price_confirmations.insert_one({
        'restaurant_id': body.restaurant_id,
        'dish_name':     body.dish_name,
        'platform':      body.platform,
        'actual_price':  body.actual_price,
        'reported_at':   body.reported_at or datetime.now(timezone.utc).isoformat(),
    })
    return {'status': 'confirmed'}


@app.post('/api/prices/batch')
async def batch_prices(body: PriceBatch):
    now = datetime.now(timezone.utc)
    saved = 0
    for item in body.prices:
        dish_name = item.get('dish_name', '').strip()
        price     = item.get('price')
        platform  = item.get('platform', 'unknown')
        rest_id   = item.get('restaurant_id', 'unknown')
        if not dish_name or not price:
            continue
        try:
            price = float(price)
            if not (10 <= price <= 10000):
                continue
        except (TypeError, ValueError):
            continue
        await db.prices.update_one(
            {'dish_name': dish_name, 'platform': platform, 'restaurant_id': rest_id},
            {'$set': {'dish_name': dish_name, 'price': price, 'platform': platform,
                      'restaurant_id': rest_id, 'source': 'accessibility', 'updated_at': now}},
            upsert=True
        )
        await db.price_history.insert_one({
            'dish_name': dish_name, 'price': price, 'platform': platform,
            'restaurant_id': rest_id, 'scraped_at': now,
        })
        saved += 1
    log.info(f'Batch prices: {saved}/{len(body.prices)} saved')
    return {'status': 'ok', 'saved': saved}


@app.post('/api/rides/report')
async def report_rides(body: RideReport):
    now = datetime.now(timezone.utc)
    saved = 0
    for fare in body.fares:
        platform = fare.get('platform', '').strip()
        tier     = fare.get('tier', '').strip()
        amount   = fare.get('fare')
        if not platform or not tier or not amount:
            continue
        try:
            amount = float(amount)
            if not (10 <= amount <= 5000):
                continue
        except (TypeError, ValueError):
            continue
        await db.ride_fares.update_one(
            {'platform': platform, 'tier': tier},
            {'$set': {'platform': platform, 'tier': tier, 'fare': amount,
                      'source': 'accessibility', 'updated_at': now}},
            upsert=True
        )
        saved += 1
    log.info(f'Ride fares: {saved}/{len(body.fares)} saved')
    return {'status': 'ok', 'saved': saved}


@app.post('/api/restaurants/report')
async def report_restaurant(body: RestaurantReport):
    """Save restaurant detected by Accessibility Service."""
    now = datetime.now(timezone.utc)
    await db.restaurants.update_one(
        {'slug': body.slug},
        {'$set': {
            'slug':       body.slug,
            'name':       body.name,
            'on_swiggy':  body.on_swiggy,
            'on_zomato':  body.on_zomato,
            'cuisine':    body.cuisine,
            'area':       body.area,
            'rating':     body.rating,
            'image_url':  body.image_url,
            'updated_at': now,
            'source':     'accessibility',
        }},
        upsert=True
    )
    log.info(f'Restaurant saved: {body.name}')
    return {'status': 'ok', 'saved': body.name}


@app.get('/api/search')
async def search(q: str = Query(..., min_length=2)):
    try:
        cursor = db.prices.find(
            {'$text': {'$search': q}},
            {'score': {'$meta': 'textScore'}, '_id': 0}
        ).sort([('score', {'$meta': 'textScore'})]).limit(20)
        results = [d async for d in cursor]
    except Exception:
        cursor = db.prices.find(
            {'dish_name': {'$regex': q, '$options': 'i'}}, {'_id': 0}
        ).limit(20)
        results = [d async for d in cursor]
    return {'results': results, 'query': q}
