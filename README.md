# Codex Monitor

Codex Monitor is a small desktop service plus a full-screen Android app for watching Codex status from a phone on the same Wi-Fi.

## Structure

- `desktop/`: HTTP status API, web monitor, and state JSON location.
- `android/`: native Android source.
- `scripts/`: Windows helper scripts.
- `dist/`: prebuilt Android APK.

## Start The Desktop Service

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-codex-monitor-server.ps1
```

The service listens on:

- TCP `8767` for HTTP and `/api/status`.
- UDP `45777` for Android auto-discovery.

If Windows Firewall asks, allow Python on private networks.

## Install The Android App

Install:

```text
dist/codex-monitor-android.apk
```

Open the app on the same Wi-Fi as the computer. It broadcasts a discovery packet, remembers the desktop service it finds, and polls status every 2.5 seconds.

## Update Status

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-codex-status.ps1 -Status working -Title 工作中 -Task "正在处理任务" -FiveHourUsed 30 -FiveHourLimit 100 -WeeklyUsed 120 -WeeklyLimit 500
```

If you only know the remaining percentages shown by Codex, use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-codex-status.ps1 -Status working -Title 工作中 -Task "正在处理任务" -FiveHourRemainingPercent 42 -WeeklyRemainingPercent 84
```

Allowed statuses:

- `thinking`
- `working`
- `testing`
- `blocked`
- `done`

The runtime file `desktop/codex-status.json` is ignored by Git. `desktop/codex-status.example.json` is kept as an example.

Quota data uses Codex's two-window model:

- `five_hour`: the rolling 5-hour usage window.
- `weekly`: the weekly usage window.

## Build APK

This project uses the installed Android SDK directly, without Gradle:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-codex-mobile-apk.ps1
```

The APK is written to `dist/codex-monitor-android.apk`.
