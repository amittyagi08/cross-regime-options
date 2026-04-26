from __future__ import annotations

from src.models import OptionCandidate


def is_valid_call_candidate(candidate: OptionCandidate, config: dict) -> bool:
    options_config = config.get("options", {})
    strategy_config = config.get("strategy", {})

    if candidate.right.upper() not in {"C", "CALL"}:
        return False
    if candidate.dte is None:
        return False
    if not int(strategy_config.get("min_dte", 0)) <= candidate.dte <= int(strategy_config.get("max_dte", 999)):
        return False
    if any(value is None for value in [candidate.bid, candidate.ask, candidate.mid, candidate.delta, candidate.theta]):
        return False
    if candidate.bid <= 0 or candidate.ask <= 0 or candidate.mid <= 0:
        return False

    min_delta = float(options_config.get("min_delta", 0.0))
    max_delta = float(options_config.get("max_delta", 1.0))
    if not min_delta <= candidate.delta <= max_delta:
        return False

    if abs(candidate.theta) > float(options_config.get("max_theta_abs", 999)):
        return False

    spread_pct = (candidate.ask - candidate.bid) / candidate.mid
    if spread_pct > float(options_config.get("max_bid_ask_spread_pct", 1.0)):
        return False

    min_open_interest = options_config.get("min_open_interest")
    if candidate.open_interest is not None and min_open_interest is not None:
        if candidate.open_interest < int(min_open_interest):
            return False

    return True
