from __future__ import annotations

from src.models import OptionCandidate


def score_option_candidate(candidate: OptionCandidate) -> OptionCandidate:
    if candidate.bid is None or candidate.ask is None or candidate.mid is None or candidate.mid <= 0:
        return candidate.with_scores(liquidity_score=0.0, total_score=float("-inf"))
    if candidate.delta is None or candidate.theta is None:
        return candidate.with_scores(liquidity_score=0.0, total_score=float("-inf"))

    spread_pct = (candidate.ask - candidate.bid) / candidate.mid
    liquidity_score = max(0.0, 1 - spread_pct)
    delta_score = 1 - abs(candidate.delta - 0.60)
    theta_penalty = abs(candidate.theta)
    iv_penalty = candidate.implied_vol * 0.10 if candidate.implied_vol is not None else 0

    total_score = (
        candidate.momentum_score * 100
        + delta_score * 20
        + liquidity_score * 20
        - theta_penalty * 10
        - iv_penalty
    )
    return candidate.with_scores(liquidity_score=float(liquidity_score), total_score=float(total_score))
