# Nexa — Mumbai Price Intelligence

A price comparison platform that shows Uber, Ola, and Rapido fares and Swiggy vs Zomato menu prices side by side — so you never overpay before booking a ride or placing a food order.

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688.svg)](https://fastapi.tiangolo.com)
[![Android](https://img.shields.io/badge/Android-Java-orange.svg)](https://developer.android.com)

---

## What it does

- **Ride comparison** — compare fares across 7 vehicle tiers (Bike to Luxury) on Uber, Ola, and Rapido for 50+ Mumbai locations
- **Food comparison** — see Swiggy and Zomato prices for the same dish side by side, with post-discount totals calculated automatically
- **Smart cart** — add dishes, compare what you actually pay after platform discounts, order directly from the app
- **Live prices** — a Playwright scraper pulls real menu prices from Swiggy and Zomato every 3 hours and stores them in MongoDB

---

## Project structure

```
nexa/
├── api/
│   └── main.py                        FastAPI server — 7 endpoints
├── scraper/
│   ├── swiggy.py                      Intercepts Swiggy's internal menu API
│   ├── zomato.py                      Intercepts Zomato's internal menu API
│   └── scheduler.py                   Runs both scrapers every 3 hours
├── android/
│   ├── NexaAccessibilityService.java  Reads live prices from platform apps
│   └── nexa_accessibility_service.xml Android service config
├── frontend/
│   └── nexa_final.html                Single-file SPA — the full web app
├── requirements.txt
├── render.yaml                        Render deployment config
├── setup.bat                          Windows one-click local setup
└── README.md
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Database | MySQL 8 — 9 tables, 3 views, 2 stored procedures |
| Web frontend | Vanilla HTML / CSS / JavaScript — single-file SPA |
| Backend API | Python, FastAPI, Motor (async MongoDB driver) |
| Scraper | Python, Playwright (intercepts internal API calls) |
| Database (production) | MongoDB Atlas — prices, price history, confirmations |
| Android | Java, WebView, @JavascriptInterface, AccessibilityService |
| Deployment | Vercel (frontend), Render (API + scraper) |

---

## Local setup (Windows)

**Requirements:** Python 3.11, Git

```bash
# 1. Clone the repo
git clone https://github.com/KrishuSharma787/nexa.git
cd nexa

# 2. Add your .env file (see .env.example)

# 3. Run the setup script
setup.bat
```

The setup script:
- Creates a Python 3.11 virtual environment
- Installs all dependencies
- Downloads Playwright Chromium
- Tests your MongoDB connection
- Starts the FastAPI server at `http://localhost:8000`

**To run the scraper** (separate terminal window):
```bash
venv\Scripts\activate
python scraper\scheduler.py
```

---

## Environment variables

Create a `.env` file in the root folder. See `.env.example` for the full list. Required keys:

```
MONGO_URI=mongodb+srv://...
DELIVERY_LAT=19.0543
DELIVERY_LNG=72.8414
DELIVERY_PINCODE=400057
SWIGGY_SWR=...
SWIGGY_DEVICE_ID=...
SWIGGY_SESSION_TID=...
ZOMATO_PHPSESSID=...
ZOMATO_CSRF=...
```

> **Never commit your `.env` file.** It is listed in `.gitignore`.

---

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/restaurants` | List all restaurants |
| GET | `/api/restaurants/{id}/menu` | Menu with live scraped prices |
| GET | `/api/rides/estimate` | Formula-based fare estimate |
| GET | `/api/prices/history/{id}/{dish}` | 7-day price trend for a dish |
| POST | `/api/prices/confirm` | User-reported price confirmation |
| GET | `/api/search` | Full-text dish search |

Full interactive docs available at `/docs` when the server is running.

---

## How the scraper works

Both Swiggy and Zomato load menu data by making internal JSON API calls when a restaurant page opens. Instead of parsing HTML — which breaks every time the UI is redesigned — the scraper uses Playwright to intercept these network requests and capture the structured JSON response directly.

```python
async def handle_response(response: Response):
    if '/dapi/menu/pl' in response.url:
        data = await response.json()
        # extract dishes from structured JSON
```

Prices are stored in two MongoDB collections:
- `prices` — current price per dish, overwritten each scrape
- `price_history` — every price ever seen, never deleted (used for trend charts)

---

## Android app

The Android project wraps `nexa_final.html` in a WebView and adds:

- **`@JavascriptInterface` bridge** — JavaScript calls `window.Android.openAppIntent()` to open Uber, Ola, Rapido, Swiggy, or Zomato directly at the right destination
- **Deep link support** — `?view=travel` and `?view=food` URL params map to Android deep links
- **Accessibility Service** — passively reads prices from Swiggy, Zomato, Uber, Ola, and Rapido screens when the user browses those apps normally, sending price data to the API without any automation

---

## Deployment

**Frontend** — deploy `frontend/nexa_final.html` to Vercel. Auto-deploys on every push.

**Backend** — `render.yaml` is included for one-click Render deployment. Add environment variables in the Render dashboard (not in code).

After deploying, update `API_BASE` in `nexa_final.html`:
```javascript
const API_BASE = 'https://your-render-url.onrender.com';
```

---

## Database schema (MySQL)

| Table | Rows | Purpose |
|---|---|---|
| `users` | — | Registered users |
| `locations` | 100 | Mumbai GPS landmarks |
| `routes` | 50 | Pre-computed origin-destination pairs |
| `ride_prices` | 50 | Formula-based fare estimates per route |
| `restaurants` | 33 | Real Mumbai restaurants |
| `dishes` | 900+ | Menu items per restaurant |
| `platform_prices` | 900+ | Swiggy and Zomato prices per dish |
| `discounts` | 7 | Tiered discount rules |
| `orders` | — | Order history |

Key design decisions:
- `platform_prices` uses nullable columns to enforce platform exclusivity — a `NULL` Zomato price means the dish is unavailable there
- `optimal_cart_pricing` view uses correlated subqueries against the `discounts` table to compute post-discount totals in real time
- `price_history` in MongoDB is append-only — every scrape adds a new document, enabling trend analysis

---

## License

MIT — see [LICENSE](LICENSE)

---

## Author

Krisna Sharma · [github.com/KrishuSharma787](https://github.com/KrishuSharma787)
