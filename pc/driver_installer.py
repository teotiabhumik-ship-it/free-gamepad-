"""
ViGEmBus Driver Installer Helper
================================
Detects and automates the installation of the Nefarius ViGEmBus virtual
gamepad driver on Windows so end users do not have to install dependencies manually.
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from typing import Callable, Optional

logger = logging.getLogger(__name__)

VIGEMBUS_DOWNLOAD_URL = (
    "https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/"
    "ViGEmBus_1.22.0_x64_x86_arm64.exe"
)


def is_vigembus_installed() -> bool:
    """
    Check if the ViGEmBus driver service is installed in the Windows registry.
    Returns True if installed, False otherwise.
    """
    if sys.platform != "win32":
        return False

    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\ViGEmBus",
        )
        key.Close()
        return True
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.debug("winreg check failed: %s", exc)
        return False


class DriverInstaller:
    """Manages downloading and installing the ViGEmBus driver with progress reporting."""

    def __init__(self):
        self._is_busy = False

    @property
    def is_busy(self) -> bool:
        return self._is_busy

    def install_in_background(
        self,
        on_status: Callable[[str], None],
        on_complete: Callable[[bool, str], None],
    ) -> None:
        """
        Run the driver installation in a background thread to prevent GUI freezing.
        """
        if self._is_busy:
            return

        self._is_busy = True
        thread = threading.Thread(
            target=self._run_install,
            args=(on_status, on_complete),
            daemon=True,
        )
        thread.start()

    def _run_install(
        self,
        on_status: Callable[[str], None],
        on_complete: Callable[[bool, str], None],
    ) -> None:
        try:
            # 1. Check if already installed
            if is_vigembus_installed():
                on_status("ViGEmBus is already installed.")
                on_complete(True, "ViGEmBus driver is already installed.")
                return

            # 2. Try winget first if available on Windows 10/11
            winget_path = shutil.which("winget")
            if winget_path:
                on_status("Installing ViGEmBus via Windows Package Manager (winget)...")
                try:
                    cmd = [
                        winget_path,
                        "install",
                        "--id",
                        "ViGEm.ViGEmBus",
                        "-e",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ]
                    # Create process with CREATE_NO_WINDOW if on Windows
                    creationflags = 0x08000000 if sys.platform == "win32" else 0
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        creationflags=creationflags,
                        timeout=120,
                    )
                    time.sleep(2)
                    if is_vigembus_installed():
                        on_complete(True, "ViGEmBus installed successfully via winget!")
                        return
                except Exception as w_exc:
                    logger.debug("winget installation attempt failed: %s", w_exc)

            # 3. Fallback: Download official signed installer directly from GitHub
            on_status("Downloading ViGEmBus installer from GitHub...")
            temp_dir = tempfile.gettempdir()
            installer_path = os.path.join(temp_dir, "ViGEmBus_Setup.exe")

            def report_progress(block_num, block_size, total_size):
                if total_size > 0:
                    percent = min(100, int(block_num * block_size * 100 / total_size))
                    on_status(f"Downloading ViGEmBus driver... {percent}%")

            urllib.request.urlretrieve(
                VIGEMBUS_DOWNLOAD_URL,
                installer_path,
                reporthook=report_progress,
            )

            on_status("Running installer... Please accept the Windows UAC prompt.")
            # Run the installer executable
            process = subprocess.Popen([installer_path, "/passive"])
            process.wait(timeout=180)

            # Wait a moment for driver service registration
            for _ in range(10):
                time.sleep(1)
                if is_vigembus_installed():
                    break

            if is_vigembus_installed():
                on_complete(True, "ViGEmBus driver installed successfully!")
            else:
                on_complete(
                    False,
                    "Installation completed, but ViGEmBus service was not detected. A system restart may be required.",
                )

        except Exception as exc:
            logger.error("Driver installation failed: %s", exc)
            on_complete(False, f"Installation error: {exc}")
        finally:
            self._is_busy = False
