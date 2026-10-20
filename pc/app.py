"""
Remote Gamepad Receiver
=======================
Standalone Windows receiver application for remote touch-screen gamepad.
Feeds virtual Xbox 360 controller inputs via ViGEmBus, hosts WebSocket/HTTP
server on port 8888, and provides a modern Tkinter GUI with QR code.
"""

import argparse
import asyncio
import datetime
import json
import os
import queue
import random
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional, Set

from aiohttp import web

try:
    from updater import UpdateChecker, APP_VERSION, UpdateInfo
except ImportError:
    try:
        from pc.updater import UpdateChecker, APP_VERSION, UpdateInfo
    except ImportError:
        APP_VERSION = "1.0.0"
        UpdateChecker = None
        UpdateInfo = None

try:
    from driver_installer import DriverInstaller, is_vigembus_installed
except ImportError:
    try:
        from pc.driver_installer import DriverInstaller, is_vigembus_installed
    except ImportError:
        DriverInstaller = None
        is_vigembus_installed = lambda: False

# ---------------------------------------------------------------------------
# CLI Arguments & Configuration
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Remote Gamepad Receiver")
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Skip ViGEmBus virtual controller creation (UI and networking only)",
)
parser.add_argument(
    "--port",
    type=int,
    default=8888,
    help="Server port number (default: 8888)",
)
parser.add_argument(
    "--controller",
    choices=["dualshock", "xbox"],
    default="dualshock",
    help="Virtual controller type: 'dualshock' (Sony PS2/PS4) or 'xbox' (Xbox 360). Default: dualshock",
)
parser.add_argument(
    "--tunnel",
    action="store_true",
    help="Start public internet tunnel automatically on launch",
)
cli_args, _ = parser.parse_known_args()

DEFAULT_PORT = cli_args.port
CLI_DRY_RUN = cli_args.dry_run
CLI_CONTROLLER = cli_args.controller
CLI_START_TUNNEL = cli_args.tunnel

# ---------------------------------------------------------------------------
# Path Resolution (Handles Development, Normal Exec, and PyInstaller One-File)
# ---------------------------------------------------------------------------
def get_base_dir() -> str:
    """Return the base directory of the running script or PyInstaller bundle."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return getattr(sys, "_MEIPASS")
    return os.path.dirname(os.path.abspath(__file__))


def get_static_dir() -> str:
    """Locate the static folder containing index.html."""
    base = get_base_dir()

    # PyInstaller bundle directory
    bundled_static = os.path.join(base, "static")
    if os.path.isdir(bundled_static):
        return bundled_static

    # Relative to pc folder in project structure: ../static
    parent_static = os.path.abspath(os.path.join(base, "..", "static"))
    if os.path.isdir(parent_static):
        return parent_static

    # Direct child ./static
    local_static = os.path.join(base, "static")
    if os.path.isdir(local_static):
        return local_static

    return parent_static


STATIC_DIR = get_static_dir()

# ---------------------------------------------------------------------------
# Network Helper
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


# ---------------------------------------------------------------------------
# Virtual Gamepad Controller (ViGEmBus / vgamepad)
# ---------------------------------------------------------------------------
class GamepadController:
    """Manages virtual DualShock (VDS4Gamepad) or Xbox 360 controller via vgamepad."""

    def __init__(self, mode: str = "dualshock", force_dry_run: bool = False):
        self.gamepad = None
        self.button_map = {}
        self.is_active = False
        self.mode = mode
        self.force_dry_run = force_dry_run
        self.warning_msg: Optional[str] = None
        self.status_text = ""
        self._init_controller(self.mode)

    def _init_controller(self, mode: str) -> None:
        """Initialize or switch virtual controller driver."""
        self.reset()
        self.gamepad = None
        self.mode = mode

        if self.force_dry_run:
            self.status_text = "Dry-run mode (--dry-run CLI flag)"
            self.warning_msg = "Running in Dry-Run mode: ViGEmBus controller disabled."
            self.is_active = False
            return

        try:
            import vgamepad as vg

            self.vg = vg
            if self.mode == "dualshock":
                # Authentic Sony DualShock (VID: 0x054C Sony Corp, PID: 0x05C4)
                self.gamepad = vg.VDS4Gamepad()
                self.button_map = {
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
                    # Xbox aliases
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
                self.status_text = "Sony DualShock Controller (VID: 0x054C Sony Corp)"
            else:
                # Xbox 360 mode
                self.gamepad = vg.VX360Gamepad()
                self.button_map = {
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
                self.status_text = "Virtual Xbox 360 Controller Active"

            self.is_active = True
            self.warning_msg = None
        except ImportError:
            self.is_active = False
            self.status_text = "vgamepad not installed (Dry-run)"
            self.warning_msg = "vgamepad module is not installed. Running in Dry-Run mode."
        except Exception as exc:
            self.is_active = False
            self.status_text = "ViGEmBus driver not detected (Dry-run)"
            self.warning_msg = f"ViGEmBus driver error: {exc}. Running in Dry-Run mode."

    def is_driver_missing(self) -> bool:
        """Return True if controller failed to initialize due to missing ViGEmBus driver."""
        return (
            not self.is_active
            and not self.force_dry_run
            and self.warning_msg is not None
            and "ViGEmBus" in self.warning_msg
        )

    def retry_init(self) -> bool:
        """Attempt to re-initialize the virtual controller."""
        self._init_controller(self.mode)
        return self.is_active

    def set_mode(self, new_mode: str) -> None:
        """Switch between 'dualshock' and 'xbox' controller."""
        if new_mode != self.mode:
            self._init_controller(new_mode)

    def apply_state(self, data: dict) -> None:
        """Push gamepad snapshot to virtual controller."""
        if not self.is_active or self.gamepad is None:
            return

        buttons = data.get("b", {})
        axes = data.get("a", {})

        # Digital Buttons
        for name, vg_btn in self.button_map.items():
            if buttons.get(name):
                self.gamepad.press_button(button=vg_btn)
            elif name in buttons:
                self.gamepad.release_button(button=vg_btn)

        if self.mode == "dualshock":
            # DualShock Directional Pad (8 directions)
            up = bool(buttons.get("up"))
            down = bool(buttons.get("down"))
            left = bool(buttons.get("left"))
            right = bool(buttons.get("right"))

            if up and right:
                dpad = self.vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTHEAST
            elif up and left:
                dpad = self.vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTHWEST
            elif down and right:
                dpad = self.vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTHEAST
            elif down and left:
                dpad = self.vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTHWEST
            elif up:
                dpad = self.vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTH
            elif down:
                dpad = self.vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTH
            elif left:
                dpad = self.vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_WEST
            elif right:
                dpad = self.vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_EAST
            else:
                dpad = self.vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NONE
            self.gamepad.directional_pad(direction=dpad)

            # PS / ANALOG button
            if buttons.get("analog"):
                self.gamepad.press_special_button(special_button=self.vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_PS)
            else:
                self.gamepad.release_special_button(special_button=self.vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_PS)

        # Analog Sticks (lx, ly, rx, ry in range -1.0 .. 1.0)
        try:
            lx = float(axes.get("lx", 0.0))
            ly = float(axes.get("ly", 0.0))
            rx = float(axes.get("rx", 0.0))
            ry = float(axes.get("ry", 0.0))
            if self.mode == "dualshock":
                # In Sony DS4 HID reports: 0 = UP, 255 = DOWN (128 = center).
                # vgamepad's left_joystick_float does: 128 + round(y * 127), mapping +1 to 255 (DOWN).
                # We invert Y so that positive float (pushing stick up) correctly maps to UP in DS4.
                self.gamepad.left_joystick_float(x_value_float=lx, y_value_float=-ly)
                self.gamepad.right_joystick_float(x_value_float=rx, y_value_float=-ry)
            else:
                self.gamepad.left_joystick_float(x_value_float=lx, y_value_float=ly)
                self.gamepad.right_joystick_float(x_value_float=rx, y_value_float=ry)
        except (ValueError, TypeError):
            pass

        # Analog Triggers (lt / l2, rt / r2 in range 0.0 .. 1.0)
        try:
            lt = float(axes.get("l2", axes.get("lt", 0.0)))
            rt = float(axes.get("r2", axes.get("rt", 0.0)))
            self.gamepad.left_trigger_float(value_float=lt)
            self.gamepad.right_trigger_float(value_float=rt)
        except (ValueError, TypeError):
            pass

        self.gamepad.update()

    def reset(self) -> None:
        """Reset all buttons and sticks to default zero position."""
        if self.is_active and self.gamepad is not None:
            try:
                self.gamepad.reset()
                self.gamepad.update()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Internet Reverse Tunnel (localhost.run over OpenSSH)
# ---------------------------------------------------------------------------
class TunnelManager:
    """Manages an automatic public SSH reverse tunnel to expose localhost to any network."""

    def __init__(self, local_port: int = 8888, event_queue: Optional[queue.Queue] = None, port: Optional[int] = None):
        self.local_port = port if port is not None else local_port
        self.event_queue = event_queue if event_queue is not None else queue.Queue()
        self.proc: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_tunnel, daemon=True, name="TunnelThread")
        self._thread.start()

    def stop(self) -> None:
        self.is_running = False
        self._stop_event.set()
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None
        self.public_url = None
        self.event_queue.put(("tunnel_status", False, None))

    def _run_tunnel(self) -> None:
        self.event_queue.put(("log", "[*] Starting Internet Tunnel via OpenSSH (localhost.run)..."))
        cmd = [
            "ssh",
            "-T",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=30",
            "-o", "ConnectTimeout=10",
            "-R", f"80:localhost:{self.local_port}",
            "nokey@localhost.run",
        ]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self.event_queue.put(("log", f"[!] Could not launch ssh: {e}"))
            self.event_queue.put(("tunnel_status", False, None))
            self.is_running = False
            return

        url_found = False
        start_time = time.time()

        while self.is_running and not self._stop_event.is_set():
            line = self.proc.stdout.readline()
            if not line:
                break
            line_str = line.strip()

            if not url_found and "tunneled with tls termination" in line_str:
                parts = line_str.split(",")
                for p in parts:
                    p = p.strip()
                    if p.startswith("https://"):
                        self.public_url = p
                        url_found = True
                        self.event_queue.put(("tunnel_status", True, self.public_url))
                        self.event_queue.put(("log", f"[+] Public Internet URL: {self.public_url}"))
                        break

            if not url_found and (time.time() - start_time > 20):
                self.event_queue.put(("log", "[!] Tunnel connection timed out waiting for public URL"))
                break

        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None

        self.is_running = False
        if not self._stop_event.is_set():
            self.event_queue.put(("tunnel_status", False, None))
            self.event_queue.put(("log", "[*] Internet tunnel stopped"))


# ---------------------------------------------------------------------------
# Background Asyncio Server (aiohttp HTTP + WebSocket)
# ---------------------------------------------------------------------------
class ServerThread(threading.Thread):
    """Runs aiohttp server on a dedicated background asyncio event loop."""

    def __init__(
        self,
        port: int,
        gamepad_ctrl: GamepadController,
        event_queue: queue.Queue,
    ):
        super().__init__(daemon=True, name="AiohttpServerThread")
        self.port = port
        self.gamepad_ctrl = gamepad_ctrl
        self.event_queue = event_queue

        self.loop = asyncio.new_event_loop()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.active_client: Optional[web.WebSocketResponse] = None
        self.connected_clients: Set[web.WebSocketResponse] = set()
        self.is_running = False
        self._stop_requested = threading.Event()

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start_server(self) -> None:
        """Schedule starting the aiohttp server."""
        if not self.is_running:
            asyncio.run_coroutine_threadsafe(self._async_start(), self.loop)

    def stop_server(self) -> None:
        """Schedule stopping the aiohttp server."""
        if self.is_running:
            asyncio.run_coroutine_threadsafe(self._async_stop(), self.loop)

    def kick_active_client(self) -> None:
        """Disconnect the active player from host GUI."""
        if self.active_client and not self.active_client.closed:
            asyncio.run_coroutine_threadsafe(self._async_kick(), self.loop)

    async def _async_kick(self) -> None:
        if self.active_client and not self.active_client.closed:
            await self.active_client.close(code=4000, message=b"KICKED_BY_HOST")
            self.active_client = None
            self.event_queue.put(("client_count", 0))
            self.event_queue.put(("active_peer", None))
            self.event_queue.put(("log", "[*] Active player was disconnected by host"))
            self.gamepad_ctrl.reset()

    def shutdown(self) -> None:
        """Completely shutdown the server and stop the event loop."""
        fut = asyncio.run_coroutine_threadsafe(self._async_stop(), self.loop)
        try:
            fut.result(timeout=3.0)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)

    async def _async_start(self) -> None:
        try:
            app = web.Application()
            app.router.add_get("/", self._handle_index)
            app.router.add_get("/ws", self._handle_websocket)

            # Serve static directory if available
            if os.path.isdir(STATIC_DIR):
                app.router.add_static("/static/", STATIC_DIR)

            self.runner = web.AppRunner(app)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, host="0.0.0.0", port=self.port)
            await self.site.start()

            self.is_running = True
            self.event_queue.put(
                ("server_status", True, f"Server running on port {self.port}")
            )
            self.event_queue.put(
                ("log", f"Server started at http://0.0.0.0:{self.port}")
            )
        except Exception as exc:
            self.is_running = False
            self.event_queue.put(
                ("server_status", False, f"Failed to start: {exc}")
            )
            self.event_queue.put(("log", f"Error starting server: {exc}"))

    async def _async_stop(self) -> None:
        if not self.is_running and self.runner is None:
            return

        # Close all active client connections
        clients = list(self.connected_clients)
        self.connected_clients.clear()
        for ws in clients:
            try:
                await ws.close(code=1000, message=b"Server stopped")
            except Exception:
                pass

        self.gamepad_ctrl.reset()

        if self.runner is not None:
            try:
                await self.runner.cleanup()
            except Exception:
                pass
            self.runner = None
            self.site = None

        self.is_running = False
        self.event_queue.put(("server_status", False, "Server stopped"))
        self.event_queue.put(("client_count", 0))
        self.event_queue.put(("log", "Server stopped"))

    async def _handle_index(self, request: web.Request) -> web.StreamResponse:
        index_file = os.path.join(STATIC_DIR, "index.html")
        if os.path.isfile(index_file):
            return web.FileResponse(
                index_file,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        return web.Response(
            text=(
                "<html><body style='background:#1a1a2e;color:#e0e0e0;font-family:sans-serif;padding:30px;'>"
                "<h2>Remote Gamepad Receiver</h2>"
                f"<p>Static file not found at: <code>{index_file}</code></p>"
                "</body></html>"
            ),
            content_type="text/html",
            status=404,
        )

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        peer = request.remote or "Unknown Phone"

        # STRICT LIMIT TO ONE USER: Reject any second connection attempt!
        if self.active_client is not None and not self.active_client.closed:
            self.event_queue.put(
                ("log", f"[!] Blocked connection from {peer}: Gamepad in use (1 user limit)")
            )
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.close(code=4001, message=b"SESSION_FULL")
            return ws

        ws = web.WebSocketResponse(heartbeat=10)
        await ws.prepare(request)

        self.active_client = ws
        self.connected_clients.add(ws)
        self.event_queue.put(("client_count", 1))
        self.event_queue.put(("active_peer", peer))
        self.event_queue.put(("log", f"[+] Player 1 connected from {peer}"))

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        self.gamepad_ctrl.apply_state(data)
                    except json.JSONDecodeError:
                        pass
                    except Exception as e:
                        self.event_queue.put(
                            ("log", f"[!] Input error from {peer}: {e}")
                        )
                elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    break
        finally:
            if self.active_client is ws:
                self.active_client = None
            self.connected_clients.discard(ws)
            self.event_queue.put(("client_count", 0))
            self.event_queue.put(("active_peer", None))
            self.event_queue.put(
                ("log", f"[-] Player 1 disconnected ({peer})")
            )
            self.gamepad_ctrl.reset()

        return ws


# ---------------------------------------------------------------------------
# Modern Tkinter GUI (Dark Theme)
# ---------------------------------------------------------------------------
class ReceiverApp:
    """Tkinter dark-themed GUI for the Remote Gamepad Receiver."""

    # Color Palette
    COLOR_BG = "#1a1a2e"
    COLOR_CARD = "#16213e"
    COLOR_CARD_BORDER = "#0f3460"
    COLOR_TEXT = "#e0e0e0"
    COLOR_TEXT_MUTED = "#9a9ab0"
    COLOR_ACCENT = "#4e54c8"
    COLOR_GREEN = "#2ecc40"
    COLOR_RED = "#ff4136"
    COLOR_WARN = "#ffb703"
    COLOR_WARN_BG = "#382d12"
    COLOR_LOG_BG = "#0d1117"

    def __init__(self, root: tk.Tk, dry_run: bool = False, port: int = DEFAULT_PORT, controller_mode: str = CLI_CONTROLLER):
        self.root = root
        self.port = port
        self.dry_run = dry_run
        self.controller_mode = controller_mode
        self.local_ip = get_local_ip()
        self.event_queue: queue.Queue = queue.Queue()
        self.connected_count = 0
        self.qr_photo_ref = None  # Prevent GC of PhotoImage
        self.tunnel_manager = TunnelManager(local_port=self.port, event_queue=self.event_queue)
        self.tunnel_url: Optional[str] = None
        self.qr_mode = "local"
        self.active_peer: Optional[str] = None

        # Auto-Updater
        self.update_checker = UpdateChecker(current_version=APP_VERSION) if UpdateChecker else None
        self.pending_update: Optional[UpdateInfo] = None
        self.is_downloading_update = False

        # Automated Driver Installer
        self.driver_installer = DriverInstaller() if DriverInstaller else None
        self.driver_banner: Optional[tk.Frame] = None
        self.driver_install_btn: Optional[tk.Button] = None
        self.driver_status_lbl: Optional[tk.Label] = None

        # Initialize Gamepad controller as Sony DualShock by default
        self.gamepad_ctrl = GamepadController(mode=self.controller_mode, force_dry_run=self.dry_run)

        # Configure Main Window
        self.root.title(f"🎮 Remote Gamepad Receiver v{APP_VERSION}")
        self.root.geometry("540x750")
        self.root.minsize(500, 680)
        self.root.configure(bg=self.COLOR_BG)

        # Apply ttk Styles
        self._setup_styles()

        # Build UI layout
        self._build_ui()

        # Start background server
        self.server_thread = ServerThread(
            port=self.port,
            gamepad_ctrl=self.gamepad_ctrl,
            event_queue=self.event_queue,
        )
        self.server_thread.start()
        self.server_thread.start_server()

        # Auto-start tunnel if specified via CLI
        if CLI_START_TUNNEL:
            self.tunnel_manager.start()

        # Handle window closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Start event polling
        self.root.after(50, self.process_queue)

        # Silent background update check on startup (after 1.5s)
        if self.update_checker and self.update_checker.config.get("auto_check_on_startup", True):
            self.root.after(1500, lambda: self.trigger_update_check(silent=True))

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=self.COLOR_BG, foreground=self.COLOR_TEXT)
        style.configure("TFrame", background=self.COLOR_BG)
        style.configure("Card.TFrame", background=self.COLOR_CARD)
        style.configure(
            "TButton",
            font=("Segoe UI", 10, "bold"),
            background=self.COLOR_CARD_BORDER,
            foreground="#ffffff",
            borderwidth=0,
            padding=6,
        )
        style.map(
            "TButton",
            background=[("active", "#1b4d89"), ("disabled", "#2a2a3e")],
            foreground=[("disabled", "#666677")],
        )
        style.configure(
            "Action.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#e94560",
            foreground="#ffffff",
            padding=6,
        )
        style.map(
            "Action.TButton",
            background=[("active", "#ff6b81"), ("disabled", "#33222e")],
        )

    def _build_ui(self) -> None:
        main_container = tk.Frame(self.root, bg=self.COLOR_BG, padx=16, pady=12)
        main_container.pack(fill="both", expand=True)

        # --- 1. Header Frame ---
        header_frame = tk.Frame(main_container, bg=self.COLOR_BG)
        header_frame.pack(fill="x", pady=(0, 6))

        title_lbl = tk.Label(
            header_frame,
            text=f"🎮 Remote Gamepad Receiver  v{APP_VERSION}",
            font=("Segoe UI", 16, "bold"),
            fg="#ffffff",
            bg=self.COLOR_BG,
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = tk.Label(
            header_frame,
            text="Turn any smartphone into a virtual PlayStation / Xbox controller",
            font=("Segoe UI", 9),
            fg=self.COLOR_TEXT_MUTED,
            bg=self.COLOR_BG,
        )
        subtitle_lbl.pack(anchor="w", pady=(1, 4))

        # --- In-App Auto-Update Banner (Hidden until update detected) ---
        self.update_banner = tk.Frame(
            main_container,
            bg="#162942",
            highlightbackground="#00d4ff",
            highlightthickness=1,
            padx=10,
            pady=8,
        )

        update_top = tk.Frame(self.update_banner, bg="#162942")
        update_top.pack(fill="x")

        self.update_banner_lbl = tk.Label(
            update_top,
            text="",
            font=("Segoe UI", 9, "bold"),
            fg="#00d4ff",
            bg="#162942",
            anchor="w",
        )
        self.update_banner_lbl.pack(side="left", fill="x", expand=True)

        self.update_dismiss_btn = tk.Button(
            update_top,
            text="✕",
            font=("Segoe UI", 8),
            bg="#162942",
            fg="#9a9ab0",
            activebackground="#203a5e",
            activeforeground="#ffffff",
            relief="flat",
            cursor="hand2",
            command=self.dismiss_update_banner,
        )
        self.update_dismiss_btn.pack(side="right")

        self.update_actions = tk.Frame(self.update_banner, bg="#162942")
        self.update_actions.pack(fill="x", pady=(6, 2))

        self.update_now_btn = tk.Button(
            self.update_actions,
            text="⚡ Update Now",
            font=("Segoe UI", 9, "bold"),
            bg="#2ecc40",
            fg="#ffffff",
            activebackground="#44dc56",
            activeforeground="#ffffff",
            relief="flat",
            padx=10,
            pady=3,
            cursor="hand2",
            command=self.start_download_update,
        )
        self.update_now_btn.pack(side="left", padx=(0, 8))

        self.update_notes_btn = tk.Button(
            self.update_actions,
            text="📜 What's New",
            font=("Segoe UI", 8),
            bg=self.COLOR_CARD_BORDER,
            fg="#ffffff",
            activebackground="#1b4d89",
            activeforeground="#ffffff",
            relief="flat",
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.show_changelog_modal,
        )
        self.update_notes_btn.pack(side="left")

        self.update_pbar = ttk.Progressbar(
            self.update_banner,
            orient="horizontal",
            mode="determinate",
            length=200,
        )

        # Driver Warning / 1-Click Install Banner (if dry-run or ViGEmBus missing)
        self.driver_banner = None
        if self.gamepad_ctrl.warning_msg:
            self.driver_banner = tk.Frame(
                main_container,
                bg=self.COLOR_WARN_BG,
                highlightbackground=self.COLOR_WARN,
                highlightthickness=1,
                padx=10,
                pady=8,
            )
            self.driver_banner.pack(fill="x", pady=(0, 10))

            warn_top = tk.Frame(self.driver_banner, bg=self.COLOR_WARN_BG)
            warn_top.pack(fill="x")

            warn_lbl = tk.Label(
                warn_top,
                text=f"⚠️ {self.gamepad_ctrl.warning_msg}",
                font=("Segoe UI", 9, "bold"),
                fg=self.COLOR_WARN,
                bg=self.COLOR_WARN_BG,
                wraplength=340,
                justify="left",
            )
            warn_lbl.pack(side="left", anchor="w")

            if self.gamepad_ctrl.is_driver_missing() and self.driver_installer:
                self.driver_install_btn = tk.Button(
                    warn_top,
                    text="📥 Install Driver (1-Click)",
                    font=("Segoe UI", 9, "bold"),
                    bg=self.COLOR_ACCENT,
                    fg="#ffffff",
                    activebackground="#6066d8",
                    activeforeground="#ffffff",
                    relief="flat",
                    padx=10,
                    pady=4,
                    cursor="hand2",
                    command=self._install_driver_clicked,
                )
                self.driver_install_btn.pack(side="right", padx=(8, 0))

                self.driver_status_lbl = tk.Label(
                    self.driver_banner,
                    text="Required for Windows games to detect controller inputs. No restart required.",
                    font=("Segoe UI", 8),
                    fg=self.COLOR_TEXT_MUTED,
                    bg=self.COLOR_WARN_BG,
                )
                self.driver_status_lbl.pack(anchor="w", pady=(4, 0))

        # --- 2. Connection Card (IP, Port, URL, QR Code) ---
        self.card = tk.Frame(
            main_container,
            bg=self.COLOR_CARD,
            highlightbackground=self.COLOR_CARD_BORDER,
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        self.card.pack(fill="x", pady=(0, 10))

        card = self.card

        card_content = tk.Frame(card, bg=self.COLOR_CARD)
        card_content.pack(fill="x")

        # Left Column: IP, Port, URL text
        left_col = tk.Frame(card_content, bg=self.COLOR_CARD)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        ip_caption = tk.Label(
            left_col,
            text="PC LOCAL IP ADDRESS",
            font=("Segoe UI", 8, "bold"),
            fg=self.COLOR_TEXT_MUTED,
            bg=self.COLOR_CARD,
        )
        ip_caption.pack(anchor="w")

        # LARGE PROMINENT IP ADDRESS
        self.ip_lbl = tk.Label(
            left_col,
            text=self.local_ip,
            font=("Consolas", 24, "bold"),
            fg="#00ffff",
            bg=self.COLOR_CARD,
        )
        self.ip_lbl.pack(anchor="w", pady=(2, 4))

        port_lbl = tk.Label(
            left_col,
            text=f"PORT: {self.port}",
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg=self.COLOR_CARD,
        )
        port_lbl.pack(anchor="w")

        url_text = f"http://{self.local_ip}:{self.port}"
        url_frame = tk.Frame(left_col, bg=self.COLOR_CARD)
        url_frame.pack(anchor="w", pady=(8, 4))

        self.url_lbl = tk.Label(
            url_frame,
            text=url_text,
            font=("Segoe UI", 9, "underline"),
            fg="#93c5fd",
            bg=self.COLOR_CARD,
            cursor="hand2",
        )
        self.url_lbl.pack(side="left")

        copy_btn = tk.Button(
            url_frame,
            text="📋 Copy",
            font=("Segoe UI", 8),
            bg=self.COLOR_CARD_BORDER,
            fg="#ffffff",
            activebackground="#1b4d89",
            activeforeground="#ffffff",
            relief="flat",
            padx=6,
            pady=1,
            command=self.copy_url_to_clipboard,
        )
        copy_btn.pack(side="left", padx=8)

        help_lbl = tk.Label(
            left_col,
            text="Connect phone to the same Wi-Fi network and scan QR code or open URL in browser.",
            font=("Segoe UI", 8),
            fg=self.COLOR_TEXT_MUTED,
            bg=self.COLOR_CARD,
            wraplength=260,
            justify="left",
        )
        help_lbl.pack(anchor="w", pady=(4, 0))

        # Right Column: QR Code Canvas
        right_col = tk.Frame(card_content, bg=self.COLOR_CARD)
        right_col.pack(side="right", padx=(4, 0))

        self.qr_canvas = tk.Canvas(
            right_col,
            width=140,
            height=140,
            bg="#ffffff",
            highlightthickness=2,
            highlightbackground="#3a3a5c",
        )
        self.qr_canvas.pack()

        qr_caption = tk.Label(
            right_col,
            text="Scan with Camera",
            font=("Segoe UI", 8),
            fg=self.COLOR_TEXT_MUTED,
            bg=self.COLOR_CARD,
        )
        qr_caption.pack(pady=(2, 2))

        # QR Mode Switcher: Local Wi-Fi vs Internet Tunnel
        qr_switch_frame = tk.Frame(right_col, bg=self.COLOR_CARD)
        qr_switch_frame.pack(pady=(2, 0))

        self.qr_lan_btn = tk.Button(
            qr_switch_frame,
            text="📶 Local",
            font=("Segoe UI", 8, "bold"),
            bg="#4e54c8",
            fg="#ffffff",
            relief="flat",
            padx=6,
            pady=1,
            cursor="hand2",
            command=lambda: self.set_qr_mode("local"),
        )
        self.qr_lan_btn.pack(side="left", padx=2)

        self.qr_tunnel_btn = tk.Button(
            qr_switch_frame,
            text="🌐 Internet",
            font=("Segoe UI", 8),
            bg=self.COLOR_CARD_BORDER,
            fg=self.COLOR_TEXT_MUTED,
            relief="flat",
            padx=6,
            pady=1,
            cursor="hand2",
            command=lambda: self.set_qr_mode("tunnel"),
        )
        self.qr_tunnel_btn.pack(side="left", padx=2)

        self._render_qr_code(url_text)

        # --- Internet Tunnel Section (Forward Port Across Networks) ---
        tunnel_divider = tk.Frame(card, bg=self.COLOR_CARD_BORDER, height=1)
        tunnel_divider.pack(fill="x", pady=(10, 8))

        tunnel_container = tk.Frame(card, bg=self.COLOR_CARD)
        tunnel_container.pack(fill="x")

        tunnel_top = tk.Frame(tunnel_container, bg=self.COLOR_CARD)
        tunnel_top.pack(fill="x")

        tk.Label(
            tunnel_top,
            text="🌐 PUBLIC INTERNET TUNNEL (4G / 5G / DIFFERENT NETWORKS)",
            font=("Segoe UI", 8, "bold"),
            fg="#00d4ff",
            bg=self.COLOR_CARD,
        ).pack(side="left")

        tunnel_row = tk.Frame(tunnel_container, bg=self.COLOR_CARD)
        tunnel_row.pack(fill="x", pady=(4, 0))

        self.tunnel_status_lbl = tk.Label(
            tunnel_row,
            text="Status: Offline (Click 'Start Tunnel' to open public URL)",
            font=("Segoe UI", 8),
            fg=self.COLOR_TEXT_MUTED,
            bg=self.COLOR_CARD,
            anchor="w",
        )
        self.tunnel_status_lbl.pack(side="left", fill="x", expand=True)

        self.tunnel_copy_btn = tk.Button(
            tunnel_row,
            text="📋 Copy URL",
            font=("Segoe UI", 8),
            bg=self.COLOR_CARD_BORDER,
            fg="#666677",
            relief="flat",
            padx=6,
            pady=2,
            state="disabled",
            command=self.copy_tunnel_url,
        )
        self.tunnel_copy_btn.pack(side="right", padx=(6, 0))

        self.tunnel_toggle_btn = tk.Button(
            tunnel_row,
            text="🌐 Start Tunnel",
            font=("Segoe UI", 8, "bold"),
            bg=self.COLOR_ACCENT,
            fg="#ffffff",
            activebackground="#6066d8",
            activeforeground="#ffffff",
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            command=self.toggle_tunnel,
        )
        self.tunnel_toggle_btn.pack(side="right")

        # --- 3. Status Bar, Player 1 & Server Controls ---
        status_bar = tk.Frame(
            main_container,
            bg=self.COLOR_CARD,
            highlightbackground=self.COLOR_CARD_BORDER,
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        status_bar.pack(fill="x", pady=(0, 10))

        status_left = tk.Frame(status_bar, bg=self.COLOR_CARD)
        status_left.pack(side="left", fill="y")

        # Server status indicator
        self.server_status_lbl = tk.Label(
            status_left,
            text="● Server Running",
            font=("Segoe UI", 10, "bold"),
            fg=self.COLOR_GREEN,
            bg=self.COLOR_CARD,
        )
        self.server_status_lbl.pack(anchor="w")

        # Player 1 connection status (Strict 1-User Limit)
        self.clients_lbl = tk.Label(
            status_left,
            text="🎮 Player 1: Waiting for connection...",
            font=("Segoe UI", 9),
            fg=self.COLOR_TEXT_MUTED,
            bg=self.COLOR_CARD,
        )
        self.clients_lbl.pack(anchor="w", pady=(2, 0))

        # Status Right buttons (Kick Player & Stop/Start Server)
        status_right = tk.Frame(status_bar, bg=self.COLOR_CARD)
        status_right.pack(side="right", fill="y")

        self.kick_btn = tk.Button(
            status_right,
            text="🚫 Kick Player",
            font=("Segoe UI", 9, "bold"),
            bg="#3a1e28",
            fg="#775566",
            relief="flat",
            padx=10,
            pady=5,
            state="disabled",
            cursor="hand2",
            command=self.kick_player,
        )
        self.kick_btn.pack(side="left", padx=(0, 8))

        # Toggle Button
        self.toggle_btn = tk.Button(
            status_right,
            text="■ Stop Server",
            font=("Segoe UI", 10, "bold"),
            bg="#e94560",
            fg="#ffffff",
            activebackground="#ff6b81",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=5,
            cursor="hand2",
            command=self.toggle_server,
        )
        self.toggle_btn.pack(side="left")

        # --- 4. Activity Log ---
        log_header = tk.Frame(main_container, bg=self.COLOR_BG)
        log_header.pack(fill="x", pady=(0, 4))

        log_title = tk.Label(
            log_header,
            text="Activity & Connection Log",
            font=("Segoe UI", 9, "bold"),
            fg=self.COLOR_TEXT_MUTED,
            bg=self.COLOR_BG,
        )
        log_title.pack(side="left")

        clear_btn = tk.Button(
            log_header,
            text="Clear Log",
            font=("Segoe UI", 8),
            bg=self.COLOR_BG,
            fg=self.COLOR_TEXT_MUTED,
            activebackground=self.COLOR_CARD,
            activeforeground="#ffffff",
            relief="flat",
            command=self.clear_log,
        )
        clear_btn.pack(side="right")

        log_container = tk.Frame(
            main_container,
            bg=self.COLOR_LOG_BG,
            highlightbackground=self.COLOR_CARD_BORDER,
            highlightthickness=1,
        )
        log_container.pack(fill="both", expand=True, pady=(0, 6))

        self.log_text = tk.Text(
            log_container,
            bg=self.COLOR_LOG_BG,
            fg="#d1d5db",
            insertbackground="#ffffff",
            font=("Consolas", 9),
            wrap="word",
            relief="flat",
            padx=8,
            pady=8,
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            log_container, orient="vertical", command=self.log_text.yview
        )
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.configure(state="disabled")

        # Controller info footer
        footer_frame = tk.Frame(main_container, bg=self.COLOR_BG)
        footer_frame.pack(fill="x")

        self.ctrl_status_lbl = tk.Label(
            footer_frame,
            text=f"Controller: {self.gamepad_ctrl.status_text}",
            font=("Segoe UI", 8),
            fg=self.COLOR_GREEN if self.gamepad_ctrl.is_active else self.COLOR_WARN,
            bg=self.COLOR_BG,
        )
        self.ctrl_status_lbl.pack(side="left")

        # In-App Update Checker Button
        self.update_status_btn = tk.Button(
            footer_frame,
            text=f"v{APP_VERSION} 🔄",
            font=("Segoe UI", 8),
            bg=self.COLOR_BG,
            fg=self.COLOR_TEXT_MUTED,
            activebackground=self.COLOR_CARD,
            activeforeground="#00d4ff",
            relief="flat",
            cursor="hand2",
            command=lambda: self.trigger_update_check(silent=False),
        )
        self.update_status_btn.pack(side="left", padx=(10, 0))

        # Emulation Mode Switcher (Sony DualShock vs Xbox 360)
        mode_frame = tk.Frame(footer_frame, bg=self.COLOR_BG)
        mode_frame.pack(side="right")

        tk.Label(
            mode_frame,
            text="Emulation:",
            font=("Segoe UI", 8),
            fg=self.COLOR_TEXT_MUTED,
            bg=self.COLOR_BG,
        ).pack(side="left", padx=(0, 4))

        mode_text = "🎮 DualShock (Sony)" if self.gamepad_ctrl.mode == "dualshock" else "🎮 Xbox 360"
        mode_fg = "#2979ff" if self.gamepad_ctrl.mode == "dualshock" else "#2ecc40"

        self.mode_btn = tk.Button(
            mode_frame,
            text=mode_text,
            font=("Segoe UI", 8, "bold"),
            bg="#212330",
            fg=mode_fg,
            activebackground="#2c3044",
            activeforeground="#ffffff",
            relief="flat",
            padx=8,
            pady=1,
            cursor="hand2",
            command=self.toggle_controller_mode,
        )
        self.mode_btn.pack(side="left")

    def toggle_controller_mode(self) -> None:
        """Switch between Sony DualShock and Xbox 360 emulation."""
        new_mode = "xbox" if self.gamepad_ctrl.mode == "dualshock" else "dualshock"
        self.gamepad_ctrl.set_mode(new_mode)
        self.ctrl_status_lbl.config(
            text=f"Controller: {self.gamepad_ctrl.status_text}",
            fg=self.COLOR_GREEN if self.gamepad_ctrl.is_active else self.COLOR_WARN,
        )
        if new_mode == "dualshock":
            self.mode_btn.config(text="🎮 DualShock (Sony)", fg="#2979ff")
        else:
            self.mode_btn.config(text="🎮 Xbox 360", fg="#2ecc40")
        self._log_event(f"[*] Virtual controller switched to: {self.gamepad_ctrl.status_text}")

    def _render_qr_code(self, url: str) -> None:
        """Generate and render QR code onto Canvas using qrcode and PIL."""
        self.qr_canvas.delete("all")
        try:
            import qrcode
            from PIL import Image, ImageTk

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=4,
                border=2,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#111111", back_color="#ffffff")
            img = img.resize((140, 140), Image.Resampling.LANCZOS)

            self.qr_photo_ref = ImageTk.PhotoImage(img)
            self.qr_canvas.create_image(70, 70, image=self.qr_photo_ref)
        except Exception as exc:
            self.qr_canvas.create_text(
                70,
                70,
                text=f"QR Code\nUnavailable\n\n({exc})",
                fill="#111111",
                font=("Segoe UI", 8),
                justify="center",
            )

    def append_log(self, message: str) -> None:
        """Append timestamped line to the activity log."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", formatted)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def copy_url_to_clipboard(self) -> None:
        url = f"http://{self.local_ip}:{self.port}"
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.append_log(f"Copied connection URL to clipboard: {url}")

    def toggle_tunnel(self) -> None:
        """Start or stop the public internet SSH reverse tunnel."""
        if self.tunnel_manager.is_running:
            self.tunnel_toggle_btn.configure(text="Stopping...", state="disabled")
            self.tunnel_manager.stop()
        else:
            self.tunnel_toggle_btn.configure(text="Connecting...", state="disabled")
            self.tunnel_manager.start()

    def kick_player(self) -> None:
        """Disconnect the active connected player."""
        self.server_thread.kick_active_client()

    def copy_tunnel_url(self) -> None:
        """Copy the public internet tunnel URL to clipboard."""
        if self.tunnel_url:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.tunnel_url)
            self.append_log(f"Copied Internet Tunnel URL to clipboard: {self.tunnel_url}")

    def set_qr_mode(self, mode: str) -> None:
        """Switch QR code view between Local Wi-Fi and Public Internet Tunnel."""
        self.qr_mode = mode
        if mode == "tunnel":
            self.qr_lan_btn.config(bg=self.COLOR_CARD_BORDER, fg=self.COLOR_TEXT_MUTED, font=("Segoe UI", 8))
            self.qr_tunnel_btn.config(bg="#4e54c8", fg="#ffffff", font=("Segoe UI", 8, "bold"))
            if self.tunnel_url:
                self._render_qr_code(self.tunnel_url)
            else:
                self.qr_canvas.delete("all")
                self.qr_canvas.create_text(
                    70, 70,
                    text="Tunnel not running\n\nClick 'Start Tunnel'\nbelow to activate",
                    fill="#111111",
                    font=("Segoe UI", 8),
                    justify="center",
                )
        else:
            self.qr_lan_btn.config(bg="#4e54c8", fg="#ffffff", font=("Segoe UI", 8, "bold"))
            self.qr_tunnel_btn.config(bg=self.COLOR_CARD_BORDER, fg=self.COLOR_TEXT_MUTED, font=("Segoe UI", 8))
            local_url = f"http://{self.local_ip}:{self.port}"
            self._render_qr_code(local_url)

    def toggle_server(self) -> None:
        """Start or stop the aiohttp server."""
        if self.server_thread.is_running:
            self.toggle_btn.configure(text="Stopping...", state="disabled")
            self.server_thread.stop_server()
        else:
            self.toggle_btn.configure(text="Starting...", state="disabled")
            self.server_thread.start_server()

    def process_queue(self) -> None:
        """Poll thread-safe event queue for updates from background server."""
        try:
            while True:
                event = self.event_queue.get_nowait()
                kind = event[0]

                if kind == "log":
                    self.append_log(event[1])

                elif kind == "tunnel_status":
                    is_active = event[1]
                    url = event[2]
                    self.tunnel_url = url
                    if is_active and url:
                        self.tunnel_status_lbl.configure(
                            text=f"Online: {url}", fg="#00ffff"
                        )
                        self.tunnel_toggle_btn.configure(
                            text="■ Stop Tunnel",
                            bg="#e94560",
                            activebackground="#ff6b81",
                            state="normal",
                        )
                        self.tunnel_copy_btn.configure(
                            state="normal",
                            bg=self.COLOR_CARD_BORDER,
                            fg="#ffffff",
                        )
                        if self.qr_mode == "tunnel":
                            self._render_qr_code(url)
                    else:
                        self.tunnel_status_lbl.configure(
                            text="Status: Offline (Click 'Start Tunnel' to open public URL)",
                            fg=self.COLOR_TEXT_MUTED,
                        )
                        self.tunnel_toggle_btn.configure(
                            text="🌐 Start Tunnel",
                            bg=self.COLOR_ACCENT,
                            activebackground="#6066d8",
                            state="normal",
                        )
                        self.tunnel_copy_btn.configure(
                            state="disabled",
                            bg=self.COLOR_CARD_BORDER,
                            fg="#666677",
                        )
                        if self.qr_mode == "tunnel":
                            self.set_qr_mode("local")

                elif kind == "active_peer":
                    peer = event[1]
                    self.active_peer = peer
                    if peer:
                        self.clients_lbl.configure(
                            text=f"🎮 Player 1: {peer} (Connected)",
                            fg=self.COLOR_GREEN,
                        )
                        self.kick_btn.configure(
                            state="normal",
                            bg="#e94560",
                            fg="#ffffff",
                            activebackground="#ff6b81",
                        )
                    else:
                        self.clients_lbl.configure(
                            text="🎮 Player 1: Waiting for connection...",
                            fg=self.COLOR_TEXT_MUTED,
                        )
                        self.kick_btn.configure(
                            state="disabled",
                            bg="#3a1e28",
                            fg="#775566",
                        )

                elif kind == "client_count":
                    count = event[1]
                    self.connected_count = count

                elif kind == "server_status":
                    is_running = event[1]
                    msg = event[2]
                    if is_running:
                        self.server_status_lbl.configure(
                            text="● Server Running", fg=self.COLOR_GREEN
                        )
                        self.toggle_btn.configure(
                            text="■ Stop Server",
                            bg="#e94560",
                            activebackground="#ff6b81",
                            state="normal",
                        )
                    else:
                        self.server_status_lbl.configure(
                            text="○ Server Stopped", fg=self.COLOR_RED
                        )
                        self.toggle_btn.configure(
                            text="▶ Start Server",
                            bg="#2ecc40",
                            activebackground="#44dc56",
                            state="normal",
                        )

                elif kind == "update_check_result":
                    info, error, silent = event[1], event[2], event[3]
                    self.update_status_btn.config(text=f"v{APP_VERSION} 🔄")
                    if info and info.is_newer:
                        self.show_update_banner(info)
                        self.append_log(f"[+] Update available: {info.latest_version} (Current: v{APP_VERSION})")
                    elif not silent:
                        if error:
                            self.append_log(f"[!] Update check error: {error}")
                            messagebox.showerror("Update Check", f"Could not check for updates:\n{error}")
                        else:
                            self.append_log(f"[*] Up to date (v{APP_VERSION})")
                            messagebox.showinfo("Up to Date", f"You are already running the latest version: v{APP_VERSION}")

                elif kind == "update_progress":
                    pct = event[1]
                    self.update_pbar['value'] = pct
                    self.update_banner_lbl.config(text=f"Downloading update... {pct:.0f}%")

                elif kind == "update_complete":
                    self.is_downloading_update = False
                    self.update_banner_lbl.config(text="Update ready! Restarting application...")
                    self.append_log("[+] Update downloaded successfully!")
                    messagebox.showinfo("Update Ready", "Update downloaded successfully!\n\nThe application will now restart with the new version.")
                    self.on_close()
                    sys.exit(0)

                elif kind == "update_error":
                    self.is_downloading_update = False
                    err = event[1]
                    self.update_pbar.pack_forget()
                    self.update_now_btn.config(text="⚡ Update Now", state="normal")
                    self.update_notes_btn.config(state="normal")
                    self.append_log(f"[!] Update failed: {err}")
                    messagebox.showerror("Update Failed", f"Failed to download update:\n{err}")

                elif kind == "driver_status":
                    status_text = event[1]
                    if self.driver_status_lbl:
                        self.driver_status_lbl.config(text=status_text)
                    self.append_log(f"[*] Driver setup: {status_text}")

                elif kind == "driver_complete":
                    success = event[1]
                    msg = event[2]
                    self.append_log(f"[*] Driver setup result: {msg}")
                    if success:
                        self.gamepad_ctrl.retry_init()
                        if self.gamepad_ctrl.is_active:
                            self.ctrl_status_lbl.config(
                                text=f"Controller: {self.gamepad_ctrl.status_text}",
                                fg=self.COLOR_GREEN,
                            )
                            if self.driver_banner:
                                self.driver_banner.destroy()
                                self.driver_banner = None
                            messagebox.showinfo(
                                "Driver Installed",
                                "ViGEmBus driver has been installed successfully!\n\nYour virtual PlayStation / Xbox controller is now active and ready for your PC games.",
                            )
                        else:
                            messagebox.showwarning(
                                "Driver Installed",
                                "ViGEmBus was installed, but controller detection requires an app restart.\nPlease close and restart Remote Gamepad.",
                            )
                    else:
                        if self.driver_install_btn:
                            self.driver_install_btn.config(state="normal", text="📥 Install Driver (1-Click)")
                        if self.driver_status_lbl:
                            self.driver_status_lbl.config(text=f"Error: {msg}", fg="#ff6b81")
                        messagebox.showerror("Driver Installation", f"Could not install ViGEmBus automatically:\n\n{msg}")

        except queue.Empty:
            pass
        finally:
            self.root.after(50, self.process_queue)

    def trigger_update_check(self, silent: bool = False) -> None:
        """Trigger an asynchronous update check."""
        if not self.update_checker:
            if not silent:
                messagebox.showinfo("Updater", "Updater module is not loaded.")
            return

        self.update_status_btn.config(text=f"v{APP_VERSION} (Checking...)")
        if not silent:
            self.append_log("[*] Checking for updates...")

        def on_result(info: Optional[UpdateInfo], error: Optional[str]) -> None:
            self.event_queue.put(("update_check_result", info, error, silent))

        self.update_checker.check_async(on_result)

    def show_update_banner(self, info: UpdateInfo) -> None:
        """Surface the prominent in-app update notification banner."""
        self.pending_update = info
        self.update_banner_lbl.config(
            text=f"🚀 Update Available: {info.latest_version} (Current: v{APP_VERSION})"
        )
        self.update_now_btn.config(text="⚡ Update Now", state="normal")
        self.update_notes_btn.config(state="normal")
        self.update_pbar.pack_forget()
        self.update_banner.pack(fill="x", pady=(0, 10), before=self.card)

    def dismiss_update_banner(self) -> None:
        """Dismiss the update banner for current session."""
        self.update_banner.pack_forget()

    def show_changelog_modal(self) -> None:
        """Show release notes / changelog in a modal window."""
        if not self.pending_update:
            return
        modal = tk.Toplevel(self.root)
        modal.title(f"Release Notes - {self.pending_update.latest_version}")
        modal.geometry("460x390")
        modal.minsize(400, 300)
        modal.configure(bg=self.COLOR_BG)
        modal.transient(self.root)
        modal.grab_set()

        hdr = tk.Label(
            modal,
            text=f"What's New in {self.pending_update.latest_version}",
            font=("Segoe UI", 12, "bold"),
            fg="#ffffff",
            bg=self.COLOR_BG,
        )
        hdr.pack(anchor="w", padx=16, pady=(16, 8))

        txt_frame = tk.Frame(
            modal,
            bg=self.COLOR_LOG_BG,
            highlightbackground=self.COLOR_CARD_BORDER,
            highlightthickness=1,
        )
        txt_frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        txt = tk.Text(
            txt_frame,
            bg=self.COLOR_LOG_BG,
            fg="#d1d5db",
            font=("Consolas", 9),
            wrap="word",
            padx=10,
            pady=10,
            relief="flat",
        )
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", self.pending_update.changelog or "No release notes provided.")
        txt.config(state="disabled")

        btn_row = tk.Frame(modal, bg=self.COLOR_BG)
        btn_row.pack(fill="x", padx=16, pady=(0, 16))

        tk.Button(
            btn_row,
            text="Close",
            font=("Segoe UI", 9),
            bg=self.COLOR_CARD_BORDER,
            fg="#ffffff",
            relief="flat",
            padx=14,
            pady=4,
            cursor="hand2",
            command=modal.destroy,
        ).pack(side="right")

    def start_download_update(self) -> None:
        """Download and install the new update."""
        if not self.pending_update or not self.pending_update.download_url:
            messagebox.showwarning(
                "Update",
                "No direct executable download link found for this release.\nPlease visit your GitHub releases page.",
            )
            return

        if self.is_downloading_update:
            return
        self.is_downloading_update = True

        self.update_now_btn.config(text="Downloading...", state="disabled")
        self.update_notes_btn.config(state="disabled")
        self.update_pbar['value'] = 0
        self.update_pbar.pack(fill="x", pady=(6, 2))
        self.append_log(f"[*] Downloading update from {self.pending_update.download_url}...")

        def on_prog(pct: float) -> None:
            self.event_queue.put(("update_progress", pct))

        def on_succ() -> None:
            self.event_queue.put(("update_complete",))

        def on_err(err: str) -> None:
            self.event_queue.put(("update_error", err))

        self.update_checker.download_and_install_async(
            self.pending_update.download_url,
            on_progress=on_prog,
            on_success=on_succ,
            on_error=on_err,
        )

    def _install_driver_clicked(self) -> None:
        """Trigger 1-click background installation of ViGEmBus driver."""
        if not self.driver_installer or self.driver_installer.is_busy:
            return

        if self.driver_install_btn:
            self.driver_install_btn.config(state="disabled", text="Installing...")
        if self.driver_status_lbl:
            self.driver_status_lbl.config(text="Starting driver setup...", fg="#ffffff")
        self.append_log("[*] Starting automated ViGEmBus driver installation...")

        def on_status(msg: str):
            self.event_queue.put(("driver_status", msg))

        def on_complete(success: bool, msg: str):
            self.event_queue.put(("driver_complete", success, msg))

        self.driver_installer.install_in_background(on_status=on_status, on_complete=on_complete)

    def on_close(self) -> None:
        """Gracefully shutdown background server thread, tunnel, and close Tkinter."""
        try:
            self.tunnel_manager.stop()
        except Exception:
            pass
        try:
            self.server_thread.shutdown()
        except Exception:
            pass
        self.root.destroy()


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main():
    root = tk.Tk()
    app = ReceiverApp(
        root=root,
        dry_run=CLI_DRY_RUN,
        port=DEFAULT_PORT,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
