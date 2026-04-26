from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


DEFAULT_CONFIG_PATH = Path("config.yaml")


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    load_dotenv()
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    _require_sections(config, ["ibkr", "strategy", "momentum", "options", "output"])
    _apply_env_overrides(config)
    return config


def _require_sections(config: dict[str, Any], sections: list[str]) -> None:
    missing = [section for section in sections if section not in config]
    if missing:
        raise ValueError(f"Missing config section(s): {', '.join(missing)}")


def _apply_env_overrides(config: dict[str, Any]) -> None:
    ibkr = config.setdefault("ibkr", {})
    if os.getenv("IBKR_HOST"):
        ibkr["host"] = os.environ["IBKR_HOST"]
    if os.getenv("IBKR_PORT"):
        ibkr["port"] = int(os.environ["IBKR_PORT"])
    if os.getenv("IBKR_CLIENT_ID"):
        ibkr["client_id"] = int(os.environ["IBKR_CLIENT_ID"])
