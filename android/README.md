# 🎮 Remote Gamepad - Android Controller App

A native Android (Kotlin) virtual Xbox 360 controller client for [Remote Gamepad Server](../server.py). Transforms your Android smartphone into a responsive, low-latency wireless gamepad over local Wi-Fi.

---

## 📱 Features

- **Connect Screen (`ConnectActivity`)**:
  - Dark-themed UI (`#0f0f1a` background, `#1a1a2e` surfaces)
  - Remembers the last used PC IP address and port using Android `SharedPreferences`
  - Instant validation and status feedback
- **Controller Screen (`GamepadActivity`)**:
  - Immersive sticky fullscreen (hides status & navigation bars, swipe to reveal transiently)
  - Keeps display awake (`FLAG_KEEP_SCREEN_ON`)
  - WebChromeClient routes console output and error traces directly to Android Logcat (`GamepadWeb` tag)
  - Graceful back button handling: terminates WebSocket connection cleanly and returns to the connect screen
- **Self-Contained Controller Engine (`assets/gamepad.html`)**:
  - Full multi-touch support via Touch API and `document.elementFromPoint()`
  - Coalesced ~60fps transmission via `requestAnimationFrame`
  - Exponential backoff auto-reconnect (500ms initial up to 5000ms max)
  - Haptic feedback on button triggers (`navigator.vibrate`)
  - Analog dual sticks with radial clamping, normalized coordinate space (`-1.0` to `1.0`), inverted Y axis
  - L3 / R3 stick-click detection on quick taps
  - Keyboard fallback support for desktop testing

---

## 🛠️ Project Structure

```
android/
├── build.gradle.kts                   # Root build configuration (AGP 8.2.2, Kotlin 1.9.22)
├── settings.gradle.kts                # Project & repository resolution settings
├── gradle.properties                  # AndroidX & JVM memory settings
├── README.md                          # Documentation & build instructions
└── app/
    ├── build.gradle.kts               # Module build file (compileSdk 34, minSdk 24, targetSdk 34)
    └── src/
        └── main/
            ├── AndroidManifest.xml    # App manifest with permissions & activity definitions
            ├── assets/
            │   └── gamepad.html       # Mobile-optimized touch gamepad interface
            ├── java/com/remotepad/
            │   ├── ConnectActivity.kt # IP/Port entry & connection launcher
            │   └── GamepadActivity.kt # Fullscreen WebView gamepad container
            └── res/
                ├── drawable/          # Vector icons, inputs, and button drawables
                ├── layout/
                │   └── activity_connect.xml
                ├── mipmap-anydpi-v26/ # Adaptive launcher icons
                └── values/
                    ├── colors.xml     # Gamepad & dark theme color definitions
                    ├── strings.xml    # Text resources
                    └── themes.xml     # Material DayNight NoActionBar theme
```

---

## 🚀 How to Build & Run

### Prerequisites
- **Android Studio** (Hedgehog 2023.1.1, Iguana, or newer recommended)
- **Android SDK** with API level 34 (`Android 14`) installed
- **JDK 17** (bundled with modern Android Studio)
- Physical Android phone or emulator running Android 7.0 (API 24) or higher

### Method 1: Build in Android Studio
1. Open Android Studio.
2. Select **File -> Open...** and browse to:
   ```
   C:\Users\bhumi\.gemini\antigravity\scratch\remote-gamepad\android
   ```
3. Allow Gradle to sync dependencies.
4. Connect your Android phone via USB with **USB Debugging** enabled in Developer Options (or launch an Android Emulator).
5. Select the `app` run configuration and click **Run (Shift + F10)**.
6. To generate a release or debug APK file:
   - Go to **Build -> Build Bundle(s) / APK(s) -> Build APK(s)**.
   - Once completed, click **locate** in the popup to find `app-debug.apk`.

### Method 2: Command Line (Gradle)
If you have the Android SDK and Gradle installed:
```bash
cd C:\Users\bhumi\.gemini\antigravity\scratch\remote-gamepad\android

# Build Debug APK
./gradlew assembleDebug

# Output APK path:
# app/build/outputs/apk/debug/app-debug.apk

# Install directly to a connected device:
./gradlew installDebug
```

---

## 🎮 How to Use with the PC Server

1. **Start the PC Gamepad Server**:
   Ensure ViGEmBus and Python dependencies are installed on the PC, then start `server.py`:
   ```bash
   cd C:\Users\bhumi\.gemini\antigravity\scratch\remote-gamepad
   python server.py
   ```
   The server will print its local LAN IP address (e.g., `192.168.1.42`) and start listening on port `8888`.

2. **Connect from the Android App**:
   - Ensure your Android phone is connected to the **same Wi-Fi network** as the PC.
   - Launch **Remote Gamepad** on your phone.
   - Enter your PC's IP address (e.g., `192.168.1.42`) and port (`8888`).
   - Tap **CONNECT**.

3. **Play**:
   - The phone switches into landscape fullscreen mode with the touch gamepad.
   - Windows recognizes the virtual Xbox 360 controller immediately.
   - Press the Android hardware back button to disconnect and return to the connection screen at any time.
