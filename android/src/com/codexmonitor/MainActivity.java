package com.codexmonitor;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.net.wifi.WifiManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final int DISCOVERY_PORT = 45777;
    private static final String DISCOVERY_MESSAGE = "CODEX_MONITOR_DISCOVER_V1";
    private static final String PREFS = "codex_monitor";
    private static final String PREF_BASE_URL = "base_url";

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private SharedPreferences prefs;
    private String baseUrl = "";
    private boolean discovering = false;

    private TextView connectionText;
    private TextView titleText;
    private TextView taskText;
    private TextView fiveHourQuotaText;
    private TextView fiveHourDetailText;
    private TextView weeklyQuotaText;
    private TextView weeklyDetailText;
    private TextView logText;
    private RingView fiveHourRingView;
    private RingView weeklyRingView;

    private final Runnable pollRunnable = new Runnable() {
        @Override
        public void run() {
            pollStatus();
            ui.postDelayed(this, 2500);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN, WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        baseUrl = prefs.getString(PREF_BASE_URL, "");
        buildUi();
        if (TextUtils.isEmpty(baseUrl)) {
            discoverServer();
        } else {
            setConnection("\u6b63\u5728\u8fde\u63a5 " + baseUrl);
            pollStatus();
            discoverServer();
        }
        ui.post(pollRunnable);
    }

    @Override
    protected void onDestroy() {
        ui.removeCallbacksAndMessages(null);
        worker.shutdownNow();
        super.onDestroy();
    }

    private void buildUi() {
        int pad = dp(18);
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Color.rgb(11, 13, 16));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root, new ScrollView.LayoutParams(-1, -2));

        TextView appTitle = text("Codex Monitor", 34, Color.WHITE, true);
        root.addView(appTitle);

        connectionText = text("\u5bfb\u627e\u7535\u8111\u7aef\u670d\u52a1...", 14, Color.rgb(148, 163, 184), false);
        connectionText.setPadding(0, dp(8), 0, dp(18));
        root.addView(connectionText);

        titleText = text("\u540c\u6b65\u4e2d", 54, Color.WHITE, true);
        titleText.setSingleLine(false);
        root.addView(titleText);

        taskText = text("\u7b49\u5f85\u72b6\u6001...", 19, Color.rgb(215, 225, 238), false);
        taskText.setPadding(0, dp(8), 0, dp(18));
        root.addView(taskText);

        TextView quotaTitle = text("\u989d\u5ea6", 18, Color.rgb(148, 163, 184), true);
        quotaTitle.setPadding(0, 0, 0, dp(8));
        root.addView(quotaTitle);

        fiveHourRingView = new RingView(this);
        fiveHourQuotaText = text("--%", 34, Color.WHITE, true);
        fiveHourDetailText = text("\u5269\u4f59 --", 14, Color.rgb(148, 163, 184), false);
        root.addView(quotaBlock("\u0035 \u5c0f\u65f6\u9650\u989d", fiveHourRingView, fiveHourQuotaText, fiveHourDetailText));

        weeklyRingView = new RingView(this);
        weeklyQuotaText = text("--%", 34, Color.WHITE, true);
        weeklyDetailText = text("\u5269\u4f59 --", 14, Color.rgb(148, 163, 184), false);
        root.addView(quotaBlock("\u5468\u9650\u989d", weeklyRingView, weeklyQuotaText, weeklyDetailText));

        Button rescan = new Button(this);
        rescan.setText("\u91cd\u65b0\u641c\u7d22\u7535\u8111");
        rescan.setTextColor(Color.rgb(7, 16, 12));
        rescan.setBackgroundColor(Color.rgb(56, 217, 150));
        rescan.setAllCaps(false);
        rescan.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                discoverServer();
            }
        });
        root.addView(rescan, new LinearLayout.LayoutParams(-1, dp(48)));

        logText = text("", 14, Color.rgb(215, 225, 238), false);
        logText.setPadding(0, dp(18), 0, 0);
        root.addView(logText);

        setContentView(scroll);
    }

    private LinearLayout quotaBlock(String label, RingView ring, TextView percent, TextView detail) {
        LinearLayout block = new LinearLayout(this);
        block.setOrientation(LinearLayout.HORIZONTAL);
        block.setGravity(Gravity.CENTER_VERTICAL);
        block.setPadding(dp(14), dp(12), dp(14), dp(12));
        block.setBackgroundColor(Color.rgb(21, 25, 31));

        LinearLayout.LayoutParams blockParams = new LinearLayout.LayoutParams(-1, -2);
        blockParams.setMargins(0, 0, 0, dp(10));
        block.setLayoutParams(blockParams);

        LinearLayout.LayoutParams ringParams = new LinearLayout.LayoutParams(dp(92), dp(92));
        ringParams.setMargins(0, 0, dp(14), 0);
        block.addView(ring, ringParams);

        LinearLayout texts = new LinearLayout(this);
        texts.setOrientation(LinearLayout.VERTICAL);
        TextView labelView = text(label, 16, Color.rgb(215, 225, 238), true);
        texts.addView(labelView);
        percent.setPadding(0, dp(2), 0, 0);
        texts.addView(percent);
        detail.setPadding(0, dp(2), 0, 0);
        texts.addView(detail);
        block.addView(texts, new LinearLayout.LayoutParams(0, -2, 1));
        return block;
    }

    private TextView text(String value, int sp, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sp);
        view.setTextColor(color);
        view.setIncludeFontPadding(true);
        if (bold) {
            view.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        }
        return view;
    }

    private void discoverServer() {
        if (discovering) return;
        discovering = true;
        setConnection("\u6b63\u5728\u540c\u4e00 Wi-Fi \u5185\u641c\u7d22\u7535\u8111...");
        worker.submit(new Runnable() {
            @Override
            public void run() {
            WifiManager.MulticastLock lock = null;
            try {
                WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                if (wifi != null) {
                    lock = wifi.createMulticastLock("codex-monitor-discovery");
                    lock.setReferenceCounted(false);
                    lock.acquire();
                }
                DatagramSocket socket = new DatagramSocket();
                socket.setBroadcast(true);
                socket.setSoTimeout(1000);
                byte[] message = DISCOVERY_MESSAGE.getBytes(StandardCharsets.UTF_8);
                InetAddress broadcast = InetAddress.getByName("255.255.255.255");
                for (int attempt = 0; attempt < 5; attempt++) {
                    DatagramPacket packet = new DatagramPacket(message, message.length, broadcast, DISCOVERY_PORT);
                    socket.send(packet);
                    try {
                        byte[] buffer = new byte[2048];
                        DatagramPacket response = new DatagramPacket(buffer, buffer.length);
                        socket.receive(response);
                        String host = response.getAddress().getHostAddress();
                        String json = new String(response.getData(), 0, response.getLength(), StandardCharsets.UTF_8);
                        JSONObject object = new JSONObject(json);
                        if ("codex-monitor".equals(object.optString("app"))) {
                            int port = object.optInt("httpPort", 8767);
                            String found = "http://" + host + ":" + port;
                            baseUrl = found;
                            prefs.edit().putString(PREF_BASE_URL, found).apply();
                            setConnection("\u5df2\u8fde\u63a5 " + found);
                            socket.close();
                            discovering = false;
                            pollStatus();
                            return;
                        }
                    } catch (Exception ignored) {
                    }
                }
                socket.close();
                discovering = false;
                setConnection("\u6ca1\u627e\u5230\u7535\u8111\u7aef\uff0c\u8bf7\u786e\u8ba4\u670d\u52a1\u5df2\u542f\u52a8");
            } catch (Exception ex) {
                discovering = false;
                setConnection("\u641c\u7d22\u5931\u8d25: " + ex.getMessage());
            } finally {
                if (lock != null && lock.isHeld()) {
                    lock.release();
                }
            }
            }
        });
    }

    private void pollStatus() {
        if (TextUtils.isEmpty(baseUrl)) return;
        worker.submit(new Runnable() {
            @Override
            public void run() {
            try {
                JSONObject json = fetchJson(baseUrl + "/api/status");
                renderStatus(json);
            } catch (Exception ex) {
                setConnection("\u8fde\u63a5\u4e2d\u65ad\uff0c\u6b63\u5728\u91cd\u65b0\u641c\u7d22...");
                discoverServer();
            }
            }
        });
    }

    private JSONObject fetchJson(String url) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(1500);
        connection.setReadTimeout(1500);
        connection.setRequestMethod("GET");
        try (InputStream stream = connection.getInputStream();
             BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            StringBuilder builder = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line);
            }
            return new JSONObject(builder.toString());
        } finally {
            connection.disconnect();
        }
    }

    private void renderStatus(JSONObject json) {
        JSONObject fiveHour = quotaFor(json, "five_hour", 0, 100, "messages");
        JSONObject weekly = quotaFor(json, "weekly", 0, 500, "messages");
        int fiveHourUsed = fiveHour.optInt("used", 0);
        int fiveHourLimit = Math.max(1, fiveHour.optInt("limit", 100));
        int fiveHourRemaining = Math.max(0, fiveHourLimit - fiveHourUsed);
        int fiveHourPercent = Math.round((fiveHourRemaining * 100f) / fiveHourLimit);
        String fiveHourUnit = fiveHour.optString("unit", "messages");
        int weeklyUsed = weekly.optInt("used", 0);
        int weeklyLimit = Math.max(1, weekly.optInt("limit", 500));
        int weeklyRemaining = Math.max(0, weeklyLimit - weeklyUsed);
        int weeklyPercent = Math.round((weeklyRemaining * 100f) / weeklyLimit);
        String weeklyUnit = weekly.optString("unit", "messages");
        String title = json.optString("title", json.optString("status", "Working"));
        String task = json.optString("task", "");
        JSONArray log = json.optJSONArray("log");
        StringBuilder logs = new StringBuilder();
        if (log != null) {
            for (int i = 0; i < Math.min(5, log.length()); i++) {
                JSONObject item = log.optJSONObject(i);
                if (item != null) {
                    logs.append("\u2022 ").append(item.optString("text", "")).append("\n");
                }
            }
        }
        ui.post(new Runnable() {
            @Override
            public void run() {
            setConnection("\u5df2\u8fde\u63a5 " + baseUrl);
            titleText.setText(title);
            taskText.setText(task);
            fiveHourQuotaText.setText(String.format(Locale.US, "%d%%", fiveHourPercent));
            fiveHourDetailText.setText("\u5269\u4f59 " + fiveHourRemaining + " " + fiveHourUnit + " / \u4e0a\u9650 " + fiveHourLimit);
            fiveHourRingView.setPercent(fiveHourPercent);
            weeklyQuotaText.setText(String.format(Locale.US, "%d%%", weeklyPercent));
            weeklyDetailText.setText("\u5269\u4f59 " + weeklyRemaining + " " + weeklyUnit + " / \u4e0a\u9650 " + weeklyLimit);
            weeklyRingView.setPercent(weeklyPercent);
            logText.setText(logs.toString());
            }
        });
    }

    private JSONObject quotaFor(JSONObject json, String id, int fallbackUsed, int fallbackLimit, String fallbackUnit) {
        JSONArray quotas = json.optJSONArray("quotas");
        if (quotas != null) {
            for (int i = 0; i < quotas.length(); i++) {
                JSONObject item = quotas.optJSONObject(i);
                if (item != null && id.equals(item.optString("id"))) {
                    return item;
                }
            }
        }
        JSONObject legacy = json.optJSONObject("quota");
        if (legacy != null) {
            return legacy;
        }
        JSONObject fallback = new JSONObject();
        try {
            fallback.put("used", fallbackUsed);
            fallback.put("limit", fallbackLimit);
            fallback.put("unit", fallbackUnit);
        } catch (Exception ignored) {
        }
        return fallback;
    }

    private void setConnection(String value) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                connectionText.setText(value);
            }
        });
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    public static class RingView extends View {
        private final Paint back = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint front = new Paint(Paint.ANTI_ALIAS_FLAG);
        private int percent = 0;

        public RingView(Context context) {
            super(context);
            back.setColor(Color.argb(38, 255, 255, 255));
            back.setStyle(Paint.Style.STROKE);
            front.setColor(Color.rgb(56, 217, 150));
            front.setStyle(Paint.Style.STROKE);
            front.setStrokeCap(Paint.Cap.ROUND);
        }

        public void setPercent(int value) {
            percent = Math.max(0, Math.min(100, value));
            invalidate();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float stroke = Math.max(14f, getWidth() * 0.08f);
            back.setStrokeWidth(stroke);
            front.setStrokeWidth(stroke);
            float pad = stroke / 2f + 4f;
            canvas.drawArc(pad, pad, getWidth() - pad, getHeight() - pad, 0, 360, false, back);
            canvas.drawArc(pad, pad, getWidth() - pad, getHeight() - pad, -90, percent * 3.6f, false, front);
        }
    }
}
