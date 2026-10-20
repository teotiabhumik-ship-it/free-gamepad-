"""
Auto-Update Manager for Remote Gamepad Receiver
===============================================
Checks GitHub Releases / version manifest for updates, downloads the new
executable with progress tracking, and safely replaces the running .exe
via a self-deleting helper batch script.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from typing import Callable, Dict, Optional, Tuple

APP_VERSION = "1.0.0"

# Default GitHub repository - User can change this in config.json or directly here
DEFAULT_CONFIG = {
    "github_repo": "user/remote-gamepad",
    "auto_check_on_startup": True,
    "check_interval_hours": 24,
    "custom_manifest_url": "",
}


def get_config_path() -> str:
    """Return path to user updater config."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "updater_config.json")


def load_config() -> dict:
    """Load or initialize updater configuration."""
    cfg_path = get_config_path()
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                config = dict(DEFAULT_CONFIG)
                config.update(loaded)
                return config
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    """Save updater configuration to disk."""
    cfg_path = get_config_path()
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


def parse_semver(ver: str) -> Tuple[int, ...]:
    """Parse semver string like '1.2.3' or 'v1.2.3' into tuple of integers."""
    clean = ver.strip().lstrip("vV")
    parts = []
    for p in clean.split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


class UpdateInfo:
    def __init__(
        self,
        latest_version: str,
        current_version: str,
        download_url: str,
        changelog: str = "",
        release_name: str = "",
        is_newer: bool = False,
    ):
        self.latest_version = latest_version
        self.current_version = current_version
        self.download_url = download_url
        self.changelog = changelog
        self.release_name = release_name
        self.is_newer = is_newer


class UpdateChecker:
    """Performs non-blocking update checks and executable replacement."""

    def __init__(self, current_version: str = APP_VERSION):
        self.current_version = current_version
        self.config = load_config()

    def check_async(self, on_result: Callable[[Optional[UpdateInfo], Optional[str]], None]) -> None:
        """Run update check in background thread."""
        thread = threading.Thread(target=self._run_check, args=(on_result,), daemon=True)
        thread.start()

    def _run_check(self, on_result: Callable[[Optional[UpdateInfo], Optional[str]], None]) -> None:
        try:
            info = self.check_sync()
            on_result(info, None)
        except Exception as e:
            on_result(None, str(e))

    def check_sync(self) -> UpdateInfo:
        """Fetch remote release data and compare versions."""
        custom_url = self.config.get("custom_manifest_url", "").strip()
        repo = self.config.get("github_repo", "").strip()

        # If custom URL is provided, try that first
        if custom_url:
            return self._fetch_from_manifest(custom_url)

        # Fallback to GitHub Releases API if repository is set
        if repo and repo != "user/remote-gamepad":
            api_url = f"https://api.github.com/repos/{repo}/releases/latest"
            headers = {"User-Agent": "RemoteGamepad-Updater", "Accept": "application/vnd.github.v3+json"}
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            latest_tag = data.get("tag_name", "0.0.0")
            body = data.get("body", "No changelog provided.")
            name = data.get("name", latest_tag)

            # Find .exe asset
            download_url = ""
            for asset in data.get("assets", []):
                aname = asset.get("name", "").lower()
                if aname.endswith(".exe"):
                    download_url = asset.get("browser_download_url", "")
                    break

            is_newer = parse_semver(latest_tag) > parse_semver(self.current_version)
            return UpdateInfo(
                latest_version=latest_tag,
                current_version=self.current_version,
                download_url=download_url,
                changelog=body,
                release_name=name,
                is_newer=is_newer,
            )

        # If repo is unconfigured or default, check local or fallback manifest
        raw_manifest_url = f"https://raw.githubusercontent.com/{repo}/main/version.json" if repo != "user/remote-gamepad" else ""
        if raw_manifest_url:
            return self._fetch_from_manifest(raw_manifest_url)

        # No remote repository configured yet
        return UpdateInfo(
            latest_version=self.current_version,
            current_version=self.current_version,
            download_url="",
            changelog="Configure your GitHub repository in updater_config.json to receive live updates.",
            release_name="Local Version",
            is_newer=False,
        )

    def _fetch_from_manifest(self, url: str) -> UpdateInfo:
        req = urllib.request.Request(url, headers={"User-Agent": "RemoteGamepad-Updater"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        latest_ver = data.get("version", "0.0.0")
        download_url = data.get("download_url", "")
        changelog = data.get("changelog", "")
        if isinstance(changelog, list):
            changelog = "\n• " + "\n• ".join(changelog)

        is_newer = parse_semver(latest_ver) > parse_semver(self.current_version)
        return UpdateInfo(
            latest_version=latest_ver,
            current_version=self.current_version,
            download_url=download_url,
            changelog=changelog,
            release_name=f"Version {latest_ver}",
            is_newer=is_newer,
        )

    def download_and_install_async(
        self,
        download_url: str,
        on_progress: Callable[[float], None],
        on_success: Callable[[], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Download executable and schedule self-replacement."""
        thread = threading.Thread(
            target=self._run_download_install,
            args=(download_url, on_progress, on_success, on_error),
            daemon=True,
        )
        thread.start()

    def _run_download_install(
        self,
        download_url: str,
        on_progress: Callable[[float], None],
        on_success: Callable[[], None],
        on_error: Callable[[str], None],
    ) -> None:
        if not download_url:
            on_error("No download URL provided in release.")
            return

        try:
            # Download to a temporary file
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, f"RemoteGamepad_new_{os.getpid()}.exe")

            req = urllib.request.Request(download_url, headers={"User-Agent": "RemoteGamepad-Updater"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(temp_file, "wb") as out_f:
                total_size = int(resp.headers.get("content-length", 0))
                downloaded = 0
                chunk_size = 65536

                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = (downloaded / total_size) * 100.0
                        on_progress(pct)

            on_progress(100.0)

            # Check if running as frozen PyInstaller executable
            if getattr(sys, "frozen", False):
                current_exe = sys.executable
                self._apply_windows_replacement(temp_file, current_exe)
                on_success()
            else:
                on_success()
                # If running from source, inform where the downloaded exe is
                print(f"[+] Downloaded updated executable to: {temp_file}")

        except Exception as exc:
            on_error(str(exc))

    def _apply_windows_replacement(self, new_exe: str, target_exe: str) -> None:
        """Generate a detached self-deleting batch file to replace target_exe once it exits."""
        bat_path = os.path.join(tempfile.gettempdir(), f"update_replace_{os.getpid()}.bat")
        script = f"""@echo off
timeout /t 1 /nobreak >nul
:retry
move /y "{new_exe}" "{target_exe}" >nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto retry
)
start "" "{target_exe}"
del "%~f0"
"""
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(script)

        # Launch batch script completely detached
        subprocess.Popen(
            ["cmd.exe", "/c", bat_path],
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            close_fds=True,
        )
