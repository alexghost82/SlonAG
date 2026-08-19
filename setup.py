"""Install Slon runtime dependencies for the current OS."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REQUIREMENTS_WINDOWS = "requirements-windows.txt"
REQUIREMENTS_MACOS = "requirements-macos.txt"
REQUIREMENTS_LINUX = "requirements-linux.txt"
REQUIREMENTS_BASE = "requirements-base.txt"


def requirements_file_for_os(system_name: str | None = None) -> str:
    """Map a sys.platform-like name to the matching requirements filename."""
    name = (system_name if system_name is not None else sys.platform).lower()
    if name.startswith("win"):
        return REQUIREMENTS_WINDOWS
    if name == "darwin":
        return REQUIREMENTS_MACOS
    if name.startswith("linux"):
        return REQUIREMENTS_LINUX
    return REQUIREMENTS_BASE


def main() -> None:
    root = Path(__file__).resolve().parent
    req_name = requirements_file_for_os()
    req_path = root / req_name
    print(f"Installing requirements from {req_name}...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_path)],
        check=True,
    )

    print("Installing Playwright browsers...")
    subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)

    print("\n✅ Setup complete! Run 'python main.py' to start Slon.")


if __name__ == "__main__":
    main()
