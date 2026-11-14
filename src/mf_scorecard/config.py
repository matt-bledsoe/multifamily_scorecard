"""Load project configuration from ``config.toml`` at the repo root."""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.toml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def repo_path(relative: str) -> Path:
    """Resolve a config path relative to the repo root."""
    return REPO_ROOT / relative
