#!/usr/bin/env python3
"""
Playwright browser installation script.

This script installs the Chromium browser required for JavaScript-heavy site
rendering. It checks if Chromium is already installed to avoid re-downloading.
"""

import subprocess
import sys
from pathlib import Path


def get_playwright_browsers_path() -> Path:
    """
    Get the path where Playwright stores browsers.

    Returns:
        Path to Playwright browsers directory
    """
    # Playwright stores browsers in ~/.cache/ms-playwright on Linux/macOS
    # and in ~/AppData/Local/ms-playwright on Windows
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local" / "ms-playwright"
    else:
        base = Path.home() / ".cache" / "ms-playwright"
    return base


def is_chromium_installed() -> bool:
    """
    Check if Chromium browser is already installed.

    Returns:
        True if Chromium appears to be installed, False otherwise
    """
    browsers_path = get_playwright_browsers_path()

    if not browsers_path.exists():
        return False

    # Look for chromium directories (e.g., chromium-1140 or similar)
    chromium_dirs = list(browsers_path.glob("chromium-*"))

    if not chromium_dirs:
        return False

    # Verify at least one has the chrome executable or INSTALLATION_COMPLETE marker
    for chromium_dir in chromium_dirs:
        # Check for INSTALLATION_COMPLETE marker (modern Playwright)
        installation_marker = chromium_dir / "INSTALLATION_COMPLETE"
        if installation_marker.exists():
            return True

        # Check for chrome binary based on platform (fallback for older versions)
        if sys.platform == "win32":
            chrome_patterns = ["chrome-win", "chrome-win64"]
            exe_name = "chrome.exe"
        elif sys.platform == "darwin":
            # macOS uses app bundle structure
            for mac_dir in ["chrome-mac", "chrome-mac-arm64", "chrome-mac-x64"]:
                chrome_exe = (
                    chromium_dir
                    / mac_dir
                    / "Chromium.app"
                    / "Contents"
                    / "MacOS"
                    / "Chromium"
                )
                if chrome_exe.exists():
                    return True
            continue
        else:  # Linux
            chrome_patterns = ["chrome-linux", "chrome-linux64"]
            exe_name = "chrome"

        if sys.platform != "darwin":
            for pattern in chrome_patterns:
                chrome_exe = chromium_dir / pattern / exe_name
                if chrome_exe.exists():
                    return True

    return False


def install_chromium() -> int:
    """
    Install Chromium browser using playwright CLI.

    Returns:
        Exit code from playwright install command
    """
    print("Installing Chromium browser for Playwright...")

    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=False,  # Let output stream to console
    )

    return result.returncode


def main() -> int:
    """
    Main entry point: check and install Chromium if needed.

    Returns:
        0 on success, non-zero on failure
    """
    if is_chromium_installed():
        print("Chromium is already installed. Skipping download.")
        return 0

    return install_chromium()


if __name__ == "__main__":
    sys.exit(main())
