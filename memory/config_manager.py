import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def config_exists() -> bool:
    return get_gemini_key() is not None


def save_api_keys(gemini_api_key: str) -> None:
    from config.secrets import set_secret

    set_secret("gemini_api_key", gemini_api_key.strip())


def load_api_keys() -> dict:
    key = get_gemini_key()
    return {"gemini_api_key": key} if key is not None else {}


def get_gemini_key() -> str | None:
    from config.secrets import get_secret

    return get_secret("gemini_api_key")


def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)
