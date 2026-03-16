# Nexa — Setup Guide
Complete setup from zero to working app on Windows.

---

## What you need installed first
- Python 3.x ✅ (already installed)
- VS Code ⬜ — download from code.visualstudio.com
- Git ⬜ — download from git-scm.com/download/win  
- Android Studio ⬜ — download from developer.android.com/studio

---

## Part 1 — Run the backend locally (30 minutes)

### Step 1 — Download this folder
Place the entire `nexa_backend` folder on your Desktop.

### Step 2 — Open a terminal
Press `Windows + R` → type `cmd` → press Enter.
Navigate to the folder:
```
cd Desktop\nexa_backend
```

### Step 3 — Run the setup script
```
setup.bat
```
This installs everything automatically. You will see:
- Python dependencies installing (2–3 minutes)
- Playwright downloading Chromium browser (~150MB, 3–4 minutes)
- MongoDB connection test
- Server starting

When you see `Uvicorn running on http://0.0.0.0:8000` — the backend is live.

### Step 4 — Test it
Open your browser and go to:
```
http://localhost:8000/docs
```
You will see the Nexa API documentation with all endpoints. Try clicking `/api/health` → Execute — it should return `{"status": "ok"}`.

### Step 5 — Run the scraper (gets real Swiggy/Zomato prices)
Open a **second** terminal window (keep the first one running).
```
cd Desktop\nexa_backend
venv\Scripts\activate
python scraper/scheduler.py
```
The scraper will:
1. Open headless Chromium
2. Visit each restaurant on Swiggy and Zomato
3. Extract real menu prices
4. Save them to MongoDB Atlas
5. Repeat every 3 hours automatically

First run takes about 15–20 minutes for all restaurants.

### Step 6 — Connect the frontend
Open `nexa_final.html` in VS Code.
Find this line near the top of the `<script>` section:
```javascript
const API_BASE = '';   // '' = demo mode
```
Change it to:
```javascript
const API_BASE = 'http://localhost:8000';
```
Open `nexa_final.html` in Chrome. Food prices will now show real data with a green `● Live` badge.

---

## Part 2 — Deploy to Render (makes it live on the internet)

### Step 1 — Create GitHub repository
1. Go to github.com → New repository → name it `nexa`
2. Download Git from git-scm.com/download/win and install it
3. Open terminal in `nexa_backend` folder:
```
git init
git add .
git commit -m "Initial Nexa backend"
git remote add origin https://github.com/YourUsername/nexa.git
git push -u origin main
```
Note: `.env` is in `.gitignore` — your credentials are NOT pushed to GitHub.

### Step 2 — Deploy to Render
1. Go to render.com → Sign up with GitHub
2. New → Web Service → Connect your `nexa` repository
3. Render detects `render.yaml` automatically
4. Go to Environment tab → Add these variables manually (they were excluded from render.yaml for security):
   - `SWIGGY_SWR` → `2ovA1CPZejgI3CyOk2LrS1Ir7ewZLYw`
   - `SWIGGY_DEVICE_ID` → `acee8711-1771-2f8f-de75-76b1007615ca`
   - `SWIGGY_SESSION_TID` → `b7cffaaa726c66592ea269b0e26e09e81...` (full value from your .env)
   - `ZOMATO_PHPSESSID` → `f648656708e1b4cdd77c8a962ca654fc`
   - `ZOMATO_CSRF` → `517ef91ce8f18cde5de4cfdebae76a8a`
5. Click Deploy

Render will build and deploy in 5–8 minutes. Your API URL will be:
```
https://nexa-api.onrender.com
```

### Step 3 — Update the frontend
In `nexa_final.html`:
```javascript
const API_BASE = 'https://nexa-api.onrender.com';
```

### Step 4 — Deploy the frontend to Vercel
1. Go to vercel.com → Sign up with GitHub
2. New Project → Import your GitHub repo or upload `nexa_final.html` directly
3. Done. Your app is live at `https://nexa.vercel.app` (or similar)

---

## Part 3 — Android app (iQOO Z9 5G, Android 15)

### Step 1 — Install Android Studio
Download from developer.android.com/studio. Run the installer with all defaults.
First launch takes 15–20 minutes to download the Android SDK.

### Step 2 — Enable Developer Mode on your phone
1. Settings → About Phone → tap **Build Number** 7 times fast
2. You will see "You are now a developer!"
3. Go back → Developer Options → turn on **USB Debugging**
4. Plug your phone into your laptop with a USB cable
5. On your phone: tap **Allow** when asked "Allow USB debugging?"

### Step 3 — Open the Android project in Android Studio
1. Open Android Studio → Open → navigate to your `android_wrapper` folder
2. Wait for Gradle sync to complete (2–5 minutes)
3. You will see the project structure in the left panel

### Step 4 — Add the Accessibility Service files
Copy these two files into your project:

`NexaAccessibilityService.java` → into:
```
app/src/main/java/com/nexa/app/NexaAccessibilityService.java
```

`nexa_accessibility_service.xml` → create this folder and file:
```
app/src/main/res/xml/nexa_accessibility_service.xml
```

### Step 5 — Update AndroidManifest.xml
Open `app/src/main/AndroidManifest.xml`. 

Inside `<application>`, add:
```xml
<service
    android:name=".NexaAccessibilityService"
    android:exported="true"
    android:label="Nexa Price Tracker"
    android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE">
    <intent-filter>
        <action android:name="android.accessibilityservice.AccessibilityService" />
    </intent-filter>
    <meta-data
        android:name="android.accessibilityservice"
        android:resource="@xml/nexa_accessibility_service" />
</service>
```

Inside `<queries>`, add:
```xml
<package android:name="in.swiggy.android" />
<package android:name="com.application.zomato" />
<package android:name="com.ubercab" />
<package android:name="com.olacabs.customer" />
<package android:name="com.rapido.passenger" />
```

### Step 6 — Update API_BASE in the service
Open `NexaAccessibilityService.java` and change:
```java
private static final String API_BASE = "https://nexa-api.onrender.com";
```
to your actual Render URL.

### Step 7 — Update WebAppInterface.java
Add this method to `WebAppInterface.java`:
```java
@JavascriptInterface
public String getLocalPrices(String restaurantId) {
    // Called by JavaScript to get any locally-available prices
    // Returns JSON — future enhancement for offline mode
    return "{}";
}
```

### Step 8 — Build and install on your phone
1. In Android Studio: Run → Run 'app' (or press Shift+F10)
2. Select your iQOO Z9 5G from the device list
3. The app installs and opens on your phone

### Step 9 — Enable the Accessibility Service
On your phone:
1. Settings → Accessibility → Installed Services (or Downloaded Apps)
2. Find **Nexa** → tap it → turn on the toggle
3. Read the permission dialog → tap Allow

From now on, whenever you open Swiggy, Zomato, Uber, Ola, or Rapido normally, Nexa silently reads prices in the background and sends them to MongoDB.

---

## Part 4 — Refreshing expired cookies

Swiggy and Zomato session cookies expire every few weeks. When the scraper starts returning empty results:

### Swiggy cookies refresh
1. Open Chrome → go to swiggy.com → make sure you're logged in
2. Press F12 → Application → Cookies → swiggy.com
3. Find `__SWhr` → copy Value
4. Find `deviceId` → copy Value  
5. Find `_session_tid` → copy Value
6. Update your `.env` file with the new values
7. On Render: update the environment variables in the dashboard

### Zomato cookies refresh
1. Chrome → zomato.com → logged in
2. F12 → Application → Cookies → zomato.com
3. Find `PHPSESSID` → copy Value
4. Find `csrf` → copy Value
5. Update `.env` and Render environment variables

---

## Troubleshooting

**"MongoDB connection failed"**
→ Go to MongoDB Atlas → Network Access → Add `0.0.0.0/0` (Allow from anywhere)

**"No prices found" after running scraper**
→ Swiggy/Zomato changed their HTML structure. Open the restaurant URL in Chrome, press F12, go to Network tab, reload, look for the API call that returns menu JSON. The URL pattern has changed — share it and I'll update the scraper.

**"Scraper gets blocked after a few restaurants"**
→ Add `await asyncio.sleep(8)` (increase the delay) in the scraper loop. Also try refreshing your session cookies.

**Android: Accessibility Service not appearing in Settings**
→ Rebuild the app in Android Studio (Build → Clean Project → Rebuild Project) then reinstall.

**Render cold start (30-second delay on first request)**
→ This is normal on the free tier. The second request is instant. On demo day, open the app once before your presentation to warm up the server.

---

## File structure
```
nexa_backend/
├── .env                    ← your credentials (never commit this)
├── .gitignore
├── requirements.txt
├── render.yaml             ← Render deployment config
├── setup.bat               ← Windows: double-click to start everything
├── api/
│   └── main.py             ← FastAPI server
├── scraper/
│   ├── swiggy.py           ← Swiggy price scraper
│   ├── zomato.py           ← Zomato price scraper
│   └── scheduler.py        ← runs both every 3 hours
└── android/
    ├── NexaAccessibilityService.java
    └── nexa_accessibility_service.xml
```
