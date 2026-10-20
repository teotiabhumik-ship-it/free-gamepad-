# 🎮 Remote Gamepad — Complete Project

## Overview

Two standalone apps that turn your Android phone into an authentic **DualShock 2** wireless controller for your Windows PC (ideal for PCSX2, RetroArch, modern PC games, and emulator testing).

```
┌──────────────────┐    WebSocket     ┌───────────────────────┐
│  ANDROID APP     │  ──────────────► │  WINDOWS APP          │
│  (APK)           │  Wi-Fi / JSON    │  (EXE)                │
│                  │                  │                       │
│  DualShock 2 UI  │                  │  GUI + Server         │
│  △ ○ ✕ □, D-Pad  │                  │  ViGEmBus → Virtual   │
│  Symmetrical     │                  │  Controller           │
│  Dual Sticks     │                  │  (DualShock 2 / X360) │
│  L1/L2, R1/R2    │                  │                       │
│  ANALOG + LED    │                  │                       │
└──────────────────┘                  └───────────────────────┘
                                         ↓ detected by:
                                       • gamepad-tester.com
                                       • PCSX2 (PS2 emulator)
                                       • RetroArch, DuckStation, Dolphin
                                       • Any XInput / Steam game
```

### 🎮 DualShock 2 Button Mapping Matrix

| DualShock 2 Control | PC / XInput Equivalent | Default Keyboard Test Key |
|---|---|---|
| **△ (Triangle)** | Y Button (Top) | `I` |
| **○ (Circle)** | B Button (Right) | `K` |
| **✕ (Cross)** | A Button (Bottom) | `J` or `Space` |
| **□ (Square)** | X Button (Left) | `U` |
| **D-Pad (▲ ▼ ◀ ▶)** | D-Pad Directional Prongs | `W` `S` `A` `D` / Arrows |
| **L1 / R1** | Left / Right Bumpers (LB / RB) | `Q` / `E` |
| **L2 / R2** | Left / Right Triggers (LT / RT) | `1` / `3` |
| **Left Stick** | Left Analog Stick (`lx`, `ly`) | Drag Left Stick |
| **Right Stick** | Right Analog Stick (`rx`, `ry`) | Drag Right Stick |
| **L3 / R3** | Left / Right Stick Click | Quick tap on stick |
| **SELECT / START** | Back / Start | `Backspace` / `Enter` |
| **TURBO** | Action Button Rapid Fire Toggle | Tap TURBO button |
| **AUTO ○** | Repeatedly presses O / Circle key | Tap AUTO ○ button / `T` |
| **ANALOG** | Analog Mode Toggle (Red LED) | Tap ANALOG button |

## Project Structure

```
remote-gamepad/
├── pc/                     ← WINDOWS RECEIVER APP
│   ├── app.py              # Tkinter GUI + WebSocket server + ViGEmBus
│   ├── requirements.txt    # Python dependencies
│   └── build.bat           # PyInstaller → standalone .exe
│
├── android/                ← ANDROID CONTROLLER APP
│   ├── app/src/main/
│   │   ├── java/com/remotepad/
│   │   │   ├── ConnectActivity.kt    # IP input screen
│   │   │   └── GamepadActivity.kt    # Fullscreen gamepad
│   │   ├── assets/gamepad.html       # Touch controller UI
│   │   ├── res/                      # Layouts, themes, drawables
│   │   └── AndroidManifest.xml
│   ├── build.gradle.kts
│   └── settings.gradle.kts
│
└── static/index.html       ← Browser fallback (no app needed)
```

---

## 🖥️ Windows App — Setup & Build

### Prerequisites
1. **ViGEmBus driver** — [download here](https://github.com/nefarius/ViGEmBus/releases)
2. **Python 3.8+**

### Run from source
```bash
cd pc
pip install -r requirements.txt
python app.py
```

### Build standalone .exe
```bash
cd pc
build.bat
```
→ Produces `dist/RemoteGamepad.exe`

### Features
- Dark-themed GUI with your IP address in large text
- QR code for quick phone connection
- Live connection log
- Start/Stop server toggle
- Auto-fallback to dry-run mode if ViGEmBus isn't installed

---

## 📱 Android App — Setup & Build

### Option A: Android Studio (recommended)
1. Open `android/` folder in Android Studio
2. Sync Gradle
3. Run on device or Build → Generate Signed APK

### Option B: Command line
```bash
cd android
./gradlew assembleDebug
# APK at: app/build/outputs/apk/debug/app-debug.apk
```

### Features
- Connection screen with IP/port input (remembers last used)
- Full-screen landscape gamepad with native WebView
- Multi-touch D-pad, ABXY, analog sticks, triggers, shoulders
- Haptic feedback, auto-reconnect, screen wake lock

---

## 🌐 Internet Access (Different Networks / 4G / 5G)

If your PC and phone are on **different networks** (e.g. phone is on 4G/5G mobile data, or on a different Wi-Fi network), the built-in **Internet Tunnel** forwards the port securely over public HTTPS/WSS:

1. In the **Windows Receiver GUI**, click **"🌐 Start Tunnel"** (or run `python app.py --tunnel` / `python server.py --tunnel`).
2. A public secure URL is generated instantly (e.g., `https://<unique-subdomain>.lhr.life`).
3. Toggle the QR code button from **[📶 Local]** to **[🌐 Internet]**.
4. Scan the QR code with any smartphone or open the URL anywhere in the world!
5. **No router port forwarding, no VPN, and no third-party account required** — utilizes Windows' built-in OpenSSH client.

---

## 🔒 Strict 1-User Limit (Player 1 Exclusive)

To prevent multiple devices from interfering with your gameplay controls:
- **Single Active Player:** The server strictly allows only **one connected device** as Player 1.
- **Session Full Rejection:** If a second device attempts to connect while a player is active, the server automatically rejects it with WebSocket close code `4001` (`SESSION_FULL`).
- **User-Friendly Overlay:** The rejected phone receives an immediate notification: *"🔒 Controller In Use — Another player is connected to this PC"*, with a manual *"🔄 Try Again"* button to prevent reconnect spam.
- **Host Kick Button:** The PC host GUI includes a **"🚫 Kick Player"** button to immediately disconnect any connected controller if needed (sending code `4000` `KICKED_BY_HOST`).

---

## 🔌 How to Connect

### Method A: Local Wi-Fi (Lowest Latency)
1. Start the **Windows app** (`python app.py` or `python server.py`)
2. Keep the QR mode on **[📶 Local]**
3. Open `http://<pc-ip>:8888` on your phone browser or use the Android app.

### Method B: Public Internet (Across Any Network)
1. Start the **Windows app** with tunnel enabled (`python app.py --tunnel` or click **"Start Tunnel"**)
2. Switch QR mode to **[🌐 Internet]**
3. Scan the QR code or open `https://<id>.lhr.life` on your phone from any Wi-Fi or mobile data network.
4. Press buttons → verified on [gamepad-tester.com](https://gamepad-tester.com) or in any game/emulator.

---

## 🚀 Publishing Updates & Auto-Updating (Windows App + Web Controller)

### How It Works:
1. **Windows App (1-Click Auto-Updater):**
   - The Windows app (`RemoteGamepadReceiver.exe`) checks for updates automatically on startup (or when clicking `v1.0.0 🔄` in the footer).
   - When you publish an update, everyone running the Windows app sees an in-app banner:
     `🚀 Update Available: v1.1.0! [⚡ Update Now] [📜 What's New]`
   - Clicking **Update Now** automatically downloads the new `.exe`, swaps it, and restarts the app with zero manual installation!

2. **Web Controller (Instant Zero-Install Mobile Updates):**
   - The web controller (`static/index.html`) is served directly by the Windows app.
   - When the Windows app updates, **every phone connected automatically receives the latest controller layout and features instantly**.
   - Includes full **PWA (Progressive Web App)** support: users can tap **"Add to Home Screen"** or **"Install App"** in Chrome/Safari to get a full-screen, landscape controller icon on their phone home screen without any browser address bar!

### How You Publish an Update:
1. **Set your GitHub repository** in [pc/updater_config.json](file:///C:/Users/bhumi/.gemini/antigravity/scratch/remote-gamepad/pc/updater_config.json):
   ```json
   {
     "github_repo": "your-username/remote-gamepad",
     "auto_check_on_startup": true
   }
   ```
2. **Build the updated `.exe`**:
   - Double-click [pc/build.bat](file:///C:/Users/bhumi/.gemini/antigravity/scratch/remote-gamepad/pc/build.bat).
   - Produces `pc/dist/RemoteGamepadReceiver.exe`.
3. **Publish to GitHub Releases**:
   - Create a new Release on your GitHub repository (e.g. tag `v1.1.0`).
   - Attach `RemoteGamepadReceiver.exe` to the release assets.
   - (Optional) Update [version.json](file:///C:/Users/bhumi/.gemini/antigravity/scratch/remote-gamepad/version.json) in your repository with the new version and changelog.
4. **All users automatically receive the update notification on launch!**
