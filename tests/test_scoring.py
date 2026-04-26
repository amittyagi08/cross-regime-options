from dataclasses import replace

from src.models import OptionCandidate
from src.scoring import score_option_candidate


BASE_CANDIDATE = OptionCandidate(
    ticker="NVDA",
    expiry="20260508",
    strike=510.0,
    right="C",
    bid=12.10,
    ask=12.70,
    mid=12.40,
    delta=0.60,
    gamma=0.02,
    theta=-0.05,
    vega=0.12,
    implied_vol=0.45,
    open_interest=500,
    dte=12,
    momentum_score=0.08,
    liquidity_score=0.0,
    total_score=0.0,
)


def test_good_delta_gets_higher_score():
    good = score_option_candidate(BASE_CANDIDATE)
    worse = score_option_candidate(replace(BASE_CANDIDATE, delta=0.80))

    assert good.total_score > worse.total_score


def test_wide_spread_reduces_score():
    tight = score_option_candidate(BASE_CANDIDATE)
    wide = score_option_candidate(replace(BASE_CANDIDATE, bid=10.00, ask=14.00, mid=12.00))

    assert tight.total_score > wide.total_score


def test_higher_theta_reduces_score():
    low_theta = score_option_candidate(BASE_CANDIDATE)
    high_theta = score_option_candidate(replace(BASE_CANDIDATE, theta=-0.20))

    assert low_theta.total_score > high_theta.total_score
