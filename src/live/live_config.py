from __future__ import annotations


def live_config(config: dict) -> dict:
    return config.setdefault("live", {})


def assert_live_safety(config: dict) -> None:
    allow_order_placement = bool(live_config(config).get("allow_order_placement", False))
    if allow_order_placement:
        raise ValueError("V5 live dashboard requires live.allow_order_placement=false")
