"""
Remote Gamepad Server
~~~~~~~~~~~~~~~~~~~~~
Receives touch inputs from a phone browser over WebSocket and feeds them
into a virtual Xbox 360 controller via ViGEmBus.  The virtual controller is
indistinguishable from a real one — every game, emulator, and browser
Gamepad-API tester will detect it.

Prerequisites:
  1. ViGEmBus driver installed  (https://github.com/nefarius/ViGEmBus/releases)
  2. pip install -r requirements.txt

Usage:
  python server.py            # start with virtual gamepad
  python server.py --dry-run  # start without ViGEmBus (UI testing only)
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from typing import Optional
from aiohttp import web

# ---------------------------------------------------------------------------
# Virtual Gamepad Setup
# ---------------------------------------------------------------------------
DRY_RUN = "--dry-run" in sys.argv
ENABLE_TUNNEL = "--tunnel" in sys.argv

USE_XBOX = "--xbox" in sys.argv
CONTROLLER_MODE = "xbox" if USE_XBOX else "dualshock"

gamepad = None
BUTTON_MAP = {}

if not DRY_RUN:
    import vgamepad as vg

    if CONTROLLER_MODE == "dualshock":
        # Create genuine Sony DualShock controller (VID: 0x054C Sony Corp)
        gamepad = vg.VDS4Gamepad()
        BUTTON_MAP = {
            # DualShock 2 buttons
            "cross":    vg.DS4_BUTTONS.DS4_BUTTON_CROSS,
            "circle":   vg.DS4_BUTTONS.DS4_BUTTON_CIRCLE,
            "square":   vg.DS4_BUTTONS.DS4_BUTTON_SQUARE,
            "triangle": vg.DS4_BUTTONS.DS4_BUTTON_TRIANGLE,
            "l1":       vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_LEFT,
            "r1":       vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_RIGHT,
            "l2":       vg.DS4_BUTTONS.DS4_BUTTON_TRIGGER_LEFT,
            "r2":       vg.DS4_BUTTONS.DS4_BUTTON_TRIGGER_RIGHT,
            "select":   vg.DS4_BUTTONS.DS4_BUTTON_SHARE,
            "start":    vg.DS4_BUTTONS.DS4_BUTTON_OPTIONS,
            "l3":       vg.DS4_BUTTONS.DS4_BUTTON_THUMB_LEFT,
            "r3":       vg.DS4_BUTTONS.DS4_BUTTON_THUMB_RIGHT,
            # Xbox aliases for compatibility
            "a":        vg.DS4_BUTTONS.DS4_BUTTON_CROSS,
            "b":        vg.DS4_BUTTONS.DS4_BUTTON_CIRCLE,
            "x":        vg.DS4_BUTTONS.DS4_BUTTON_SQUARE,
            "y":        vg.DS4_BUTTONS.DS4_BUTTON_TRIANGLE,
            "lb":       vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_LEFT,
            "rb":       vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_RIGHT,
            "lt":       vg.DS4_BUTTONS.DS4_BUTTON_TRIGGER_LEFT,
            "rt":       vg.DS4_BUTTONS.DS4_BUTTON_TRIGGER_RIGHT,
            "back":     vg.DS4_BUTTONS.DS4_BUTTON_SHARE,
            "ls":       vg.DS4_BUTTONS.DS4_BUTTON_THUMB_LEFT,
            "rs":       vg.DS4_BUTTONS.DS4_BUTTON_THUMB_RIGHT,
        }
        print("[+] Virtual Sony DualShock Controller created (VID: 0x054C Sony Corp)")
    else:
        # Xbox 360 controller mode
        gamepad = vg.VX360Gamepad()
        BUTTON_MAP = {
            "a": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
            "b": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
            "x": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
            "y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            "lb": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
            "rb": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
            "back": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
            "start": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
            "ls": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
            "rs": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
            "cross": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
            "circle": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
            "square": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
            "triangle": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
            "l1": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
            "r1": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
            "select": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
            "l3": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
            "r3": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
            "up": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
            "down": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
            "left": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
            "right": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
        }
        print("[+] Virtual Xbox 360 Controller created")
else:
    print("[!] Dry-run mode - no virtual gamepad (UI testing only)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_local_ip() -> str:
    """Return the LAN IP address of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def apply_state(data: dict) -> None:
    """Push a full gamepad-state snapshot to ViGEmBus."""
    if gamepad is None:
        return

    buttons = data.get("b", {})
    axes = data.get("a", {})

    # Digital buttons
    for name, vg_btn in BUTTON_MAP.items():
        if buttons.get(name):
            gamepad.press_button(button=vg_btn)
        elif name in buttons:
            gamepad.release_button(button=vg_btn)

    if CONTROLLER_MODE == "dualshock":
        # DualShock D-Pad mapping
        up = bool(buttons.get("up"))
        down = bool(buttons.get("down"))
        left = bool(buttons.get("left"))
        right = bool(buttons.get("right"))

        if up and right:
            dpad = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTHEAST
        elif up and left:
            dpad = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTHWEST
        elif down and right:
            dpad = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTHEAST
        elif down and left:
            dpad = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTHWEST
        elif up:
            dpad = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTH
        elif down:
            dpad = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTH
        elif left:
            dpad = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_WEST
        elif right:
            dpad = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_EAST
        else:
            dpad = vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NONE
        gamepad.directional_pad(direction=dpad)

        # PS / ANALOG button
        if buttons.get("analog"):
            gamepad.press_special_button(special_button=vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_PS)
        else:
            gamepad.release_special_button(special_button=vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_PS)

    # Analog sticks  (x: -1..1,  y: -1..1)
    lx_val = float(axes.get("lx", 0))
    ly_val = float(axes.get("ly", 0))
    rx_val = float(axes.get("rx", 0))
    ry_val = float(axes.get("ry", 0))

    if CONTROLLER_MODE == "dualshock":
        # In Sony DS4 HID reports: 0 = UP, 255 = DOWN (128 = center).
        # vgamepad's left_joystick_float does: 128 + round(y * 127), mapping +1 to 255 (DOWN).
        # Invert Y so that positive float (pushing stick up) correctly maps to UP in DS4.
        gamepad.left_joystick_float(x_value_float=lx_val, y_value_float=-ly_val)
        gamepad.right_joystick_float(x_value_float=rx_val, y_value_float=-ry_val)
    else:
        gamepad.left_joystick_float(x_value_float=lx_val, y_value_float=ly_val)
        gamepad.right_joystick_float(x_value_float=rx_val, y_value_float=ry_val)

    # Analog triggers (0..1)
    lt_val = float(axes.get("l2", axes.get("lt", 0)))
    rt_val = float(axes.get("r2", axes.get("rt", 0)))
    gamepad.left_trigger_float(value_float=lt_val)
    gamepad.right_trigger_float(value_float=rt_val)

    gamepad.update()


# ---------------------------------------------------------------------------
# HTTP + WebSocket Handlers
# ---------------------------------------------------------------------------
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


async def index_handler(request: web.Request) -> web.FileResponse:
    return web.FileResponse(
        os.path.join(STATIC_DIR, "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


active_client: Optional[web.WebSocketResponse] = None


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    global active_client
    peer = request.remote or "Unknown Phone"

    # STRICT 1-USER LIMIT: Reject secondary connection attempts
    if active_client is not None and not active_client.closed:
        print(f"[!] Blocked connection from {peer}: Gamepad in use (1 user limit)")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.close(code=4001, message=b"SESSION_FULL")
        return ws

    ws = web.WebSocketResponse(heartbeat=10)
    await ws.prepare(request)
    active_client = ws
    print(f"[+] Player 1 connected  ({peer})")

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    apply_state(data)
                except json.JSONDecodeError:
                    pass
                except Exception as exc:
                    print(f"[!] Error processing input: {exc}")
            elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                break
    finally:
        if active_client is ws:
            active_client = None
        # Reset all inputs on disconnect
        if gamepad is not None:
            gamepad.reset()
            gamepad.update()
        print(f"[-] Player 1 disconnected ({peer})")

    return ws


# ---------------------------------------------------------------------------
# App Bootstrap & Internet Tunneling
# ---------------------------------------------------------------------------
def start_ssh_tunnel(port: int) -> None:
    """Launch SSH reverse tunnel via localhost.run for public internet access."""
    print("[*] Starting Public Internet Tunnel via OpenSSH (localhost.run)...")
    cmd = [
        "ssh",
        "-T",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ConnectTimeout=10",
        "-R", f"80:localhost:{port}",
        "nokey@localhost.run",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            line_str = line.strip()
            if "tunneled with tls termination" in line_str:
                for p in line_str.split(","):
                    p = p.strip()
                    if p.startswith("https://"):
                        print()
                        print(f"[+] Public Internet URL:  {p}")
                        print("    (Share this URL to play across any network / 4G / 5G)")
                        print()
                        break
    except Exception as exc:
        print(f"[!] Internet tunnel error: {exc}")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/static/", STATIC_DIR)
    return app


if __name__ == "__main__":
    ip = get_local_ip()
    port = 8888

    print()
    print("[*] Remote Gamepad Server")
    print(f"[*] Local Wi-Fi:          http://{ip}:{port}")
    if ENABLE_TUNNEL:
        t = threading.Thread(target=start_ssh_tunnel, args=(port,), daemon=True)
        t.start()
    else:
        print("[*] To enable internet access from different networks: python server.py --tunnel")
    print()

    web.run_app(create_app(), host="0.0.0.0", port=port, print=None)
