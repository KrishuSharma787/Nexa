package com.nexa.app;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * NexaAccessibilityService
 * ─────────────────────────────────────────────────────────────────────────
 * Runs passively in the background. Whenever the user opens Swiggy, Zomato,
 * Uber, Ola, or Rapido, this service reads prices from the screen and sends
 * them to the Nexa API — without any automation or bot behaviour.
 *
 * The user enables this once:
 *   Settings → Accessibility → Installed apps → Nexa → Enable
 *
 * Data collected: dish names + prices, ride fares.
 * Data NOT collected: personal info, order history, payment details, login.
 * ─────────────────────────────────────────────────────────────────────────
 */
public class NexaAccessibilityService extends AccessibilityService {

    private static final String TAG = "NexaAccess";

    // Target app packages
    private static final String PKG_SWIGGY  = "in.swiggy.android";
    private static final String PKG_ZOMATO  = "com.application.zomato";
    private static final String PKG_UBER    = "com.ubercab";
    private static final String PKG_OLA     = "com.olacabs.customer";
    private static final String PKG_RAPIDO  = "com.rapido.passenger";

    // Replace with your deployed Render URL after deployment
    private static final String API_BASE    = "https://nexa-api.onrender.com";

    // Price pattern: ₹ followed by digits (e.g. ₹349, ₹1,200)
    private static final Pattern PRICE_PATTERN = Pattern.compile("₹\\s*([\\d,]+)");

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    // Local cache — avoids sending duplicate readings
    private final Map<String, Integer> lastSentPrices = new HashMap<>();

    // Current restaurant context
    private String currentRestaurantId = "";
    private String currentPlatform = "";

    // ── Accessibility Service Config ──────────────────────────

    @Override
    public void onServiceConnected() {
        AccessibilityServiceInfo info = new AccessibilityServiceInfo();
        info.flags =
            AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS |
            AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;
        info.eventTypes =
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED |
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED |
            AccessibilityEvent.TYPE_VIEW_SCROLLED;
        info.feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC;
        info.notificationTimeout = 300;
        info.packageNames = new String[]{
            PKG_SWIGGY, PKG_ZOMATO, PKG_UBER, PKG_OLA, PKG_RAPIDO
        };
        setServiceInfo(info);
        Log.i(TAG, "Nexa Accessibility Service connected");
    }

    // ── Main Event Handler ────────────────────────────────────

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null) return;
        String pkg = String.valueOf(event.getPackageName());

        switch (pkg) {
            case PKG_SWIGGY:
                currentPlatform = "swiggy";
                handleFoodApp(event);
                break;
            case PKG_ZOMATO:
                currentPlatform = "zomato";
                handleFoodApp(event);
                break;
            case PKG_UBER:
                handleRideApp(event, "Uber");
                break;
            case PKG_OLA:
                handleRideApp(event, "Ola");
                break;
            case PKG_RAPIDO:
                handleRideApp(event, "Rapido");
                break;
        }
    }

    // ── Food App Handling (Swiggy + Zomato) ──────────────────

    private void handleFoodApp(AccessibilityEvent event) {
        int type = event.getEventType();
        // Only process when screen content changes (user scrolling menu)
        if (type != AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED &&
            type != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
            type != AccessibilityEvent.TYPE_VIEW_SCROLLED) {
            return;
        }

        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;

        List<PriceReading> readings = new ArrayList<>();
        extractFoodPrices(root, readings, null);
        root.recycle();

        if (!readings.isEmpty()) {
            sendFoodPrices(readings);
        }
    }

    /**
     * Recursively traverse the view tree.
     * Looks for text nodes that match a price pattern and associates them
     * with nearby dish name nodes.
     */
    private void extractFoodPrices(AccessibilityNodeInfo node,
                                    List<PriceReading> results,
                                    String nearbyText) {
        if (node == null) return;

        CharSequence text = node.getText();
        String nodeText = text != null ? text.toString().trim() : "";

        // Check if this node contains a price
        Matcher priceMatcher = PRICE_PATTERN.matcher(nodeText);
        if (priceMatcher.find()) {
            String priceStr = priceMatcher.group(1).replace(",", "");
            try {
                int price = Integer.parseInt(priceStr);
                // Sanity check: food prices typically ₹30–₹5000
                if (price >= 30 && price <= 5000 && nearbyText != null && !nearbyText.isEmpty()) {
                    String cacheKey = currentPlatform + ":" + nearbyText;
                    Integer lastPrice = lastSentPrices.get(cacheKey);
                    // Only add if price changed or not seen before
                    if (lastPrice == null || lastPrice != price) {
                        results.add(new PriceReading(nearbyText, price, currentPlatform));
                        lastSentPrices.put(cacheKey, price);
                    }
                }
            } catch (NumberFormatException ignored) {}
        }

        // Recurse into children, passing this node's text as context
        String context = nodeText.length() > 3 && nodeText.length() < 80
                ? nodeText : nearbyText;

        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            extractFoodPrices(child, results, context);
            if (child != null) child.recycle();
        }
    }

    // ── Ride App Handling (Uber + Ola + Rapido) ──────────────

    private void handleRideApp(AccessibilityEvent event, String platform) {
        if (event.getEventType() != AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED &&
            event.getEventType() != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            return;
        }

        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;

        List<RideFareReading> fares = new ArrayList<>();
        extractRideFares(root, fares, platform, null);
        root.recycle();

        if (!fares.isEmpty()) {
            sendRideFares(fares);
        }
    }

    private void extractRideFares(AccessibilityNodeInfo node,
                                   List<RideFareReading> results,
                                   String platform,
                                   String nearbyLabel) {
        if (node == null) return;

        CharSequence text = node.getText();
        String nodeText = text != null ? text.toString().trim() : "";

        Matcher m = PRICE_PATTERN.matcher(nodeText);
        if (m.find() && nearbyLabel != null) {
            String priceStr = m.group(1).replace(",", "");
            try {
                int fare = Integer.parseInt(priceStr);
                // Ride fares: ₹30–₹3000
                if (fare >= 30 && fare <= 3000) {
                    results.add(new RideFareReading(platform, nearbyLabel, fare));
                }
            } catch (NumberFormatException ignored) {}
        }

        // Detect tier labels (Go, Mini, Premier, Auto, Bike, etc.)
        String tierHint = null;
        String lower = nodeText.toLowerCase();
        if (lower.contains("go") || lower.contains("mini") || lower.contains("micro")) {
            tierHint = "mini";
        } else if (lower.contains("premier") || lower.contains("prime plus")) {
            tierHint = "prime";
        } else if (lower.contains("auto")) {
            tierHint = "auto";
        } else if (lower.contains("bike")) {
            tierHint = "bike";
        } else if (lower.contains("xl") || lower.contains("suv")) {
            tierHint = "suv";
        } else if (lower.contains("black") || lower.contains("lux")) {
            tierHint = "luxury";
        } else if (lower.contains("sedan") || lower.contains("prime")) {
            tierHint = "sedan";
        }

        String context = tierHint != null ? tierHint : nearbyLabel;

        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            extractRideFares(child, results, platform, context);
            if (child != null) child.recycle();
        }
    }

    // ── API Reporting ─────────────────────────────────────────

    private void sendFoodPrices(final List<PriceReading> readings) {
        executor.execute(() -> {
            try {
                JSONArray arr = new JSONArray();
                for (PriceReading r : readings) {
                    JSONObject obj = new JSONObject();
                    obj.put("dish_name", r.dishName);
                    obj.put("price", r.price);
                    obj.put("platform", r.platform);
                    obj.put("restaurant_id", currentRestaurantId);
                    arr.put(obj);
                }
                JSONObject body = new JSONObject();
                body.put("prices", arr);
                body.put("source", "accessibility");

                postToApi("/api/prices/batch", body.toString());
                Log.d(TAG, "Sent " + readings.size() + " food prices to API");
            } catch (Exception e) {
                Log.w(TAG, "Failed to send food prices: " + e.getMessage());
            }
        });
    }

    private void sendRideFares(final List<RideFareReading> fares) {
        executor.execute(() -> {
            try {
                JSONArray arr = new JSONArray();
                for (RideFareReading r : fares) {
                    JSONObject obj = new JSONObject();
                    obj.put("platform", r.platform);
                    obj.put("tier", r.tier);
                    obj.put("fare", r.fare);
                    arr.put(obj);
                }
                JSONObject body = new JSONObject();
                body.put("fares", arr);
                body.put("source", "accessibility");

                postToApi("/api/rides/report", body.toString());
                Log.d(TAG, "Sent " + fares.size() + " ride fares to API");
            } catch (Exception e) {
                Log.w(TAG, "Failed to send ride fares: " + e.getMessage());
            }
        });
    }

    private void postToApi(String path, String jsonBody) throws Exception {
        URL url = new URL(API_BASE + path);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setDoOutput(true);
        conn.setConnectTimeout(5000);
        conn.setReadTimeout(5000);
        try (OutputStream os = conn.getOutputStream()) {
            os.write(jsonBody.getBytes(StandardCharsets.UTF_8));
        }
        int code = conn.getResponseCode();
        conn.disconnect();
        if (code >= 400) {
            Log.w(TAG, "API returned " + code + " for " + path);
        }
    }

    @Override
    public void onInterrupt() {
        Log.i(TAG, "Accessibility service interrupted");
    }

    @Override
    public void onDestroy() {
        executor.shutdown();
        super.onDestroy();
    }

    // ── Data Classes ──────────────────────────────────────────

    static class PriceReading {
        final String dishName;
        final int    price;
        final String platform;
        PriceReading(String dishName, int price, String platform) {
            this.dishName = dishName;
            this.price    = price;
            this.platform = platform;
        }
    }

    static class RideFareReading {
        final String platform;
        final String tier;
        final int    fare;
        RideFareReading(String platform, String tier, int fare) {
            this.platform = platform;
            this.tier     = tier;
            this.fare     = fare;
        }
    }
}
