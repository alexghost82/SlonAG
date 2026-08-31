"""Canonical launcher — run as `python -m main` or `python main.py`."""
from __future__ import annotations

from main import main as _main


def main():
    _main()


if __name__ == "__main__":
    main()
