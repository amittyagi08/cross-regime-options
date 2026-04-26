from __future__ import annotations

import argparse
from dataclasses import asdict

import pandas as pd

from src.backtest.engine import SyntheticOptionsBacktestEngine
from src.config import load_config
from src.ibkr_client import IBKRClient
from src.models import OptionCandidate, MomentumSignal
from src.momentum import calculate_momentum
from src.option_filters import is_valid_call_candidate
from src.scoring import score_option_candidate
from src.utils import calculate_dte, ensure_parent_dir, load_universe
from src.yahoo_client import YahooClient


def main() -> None:
    args = parse_args()
    config = load_config()
    apply_cli_overrides(config, args)
    universe = load_universe()
    if args.mode == "backtest":
        run_backtest(universe, config)
        return

    data_provider = str(config.get("scanner", {}).get("data_provider", "ibkr")).lower()

    if data_provider == "yahoo":
        candidates = run_yahoo_scan(universe, config)
    elif data_provider == "ibkr":
        candidates = run_ibkr_scan(universe, config)
    else:
        raise ValueError("scanner.data_provider must be 'ibkr' or 'yahoo'")

    ranked = sorted(candidates, key=lambda candidate: candidate.total_score, reverse=True)
    print_ranked_contracts(ranked)
    save_ranked_contracts(ranked, config["output"]["ranked_contracts_path"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cross Regime Alpha Options Overlay")
    parser.add_argument("--mode", choices=["scan", "backtest"], default="scan")
    parser.add_argument("--start", help="Backtest start date, YYYY-MM-DD")
    parser.add_argument("--end", help="Backtest end date, YYYY-MM-DD")
    parser.add_argument("--capital", type=float, help="Backtest initial capital")
    parser.add_argument("--capital-per-trade", type=float, help="Backtest capital per trade")
    return parser.parse_args()


def apply_cli_overrides(config: dict, args: argparse.Namespace) -> None:
    backtest_config = config.setdefault("backtest", {})
    if args.start:
        backtest_config["start_date"] = args.start
    if args.end:
        backtest_config["end_date"] = args.end
    if args.capital is not None:
        backtest_config["initial_capital"] = args.capital
    if args.capital_per_trade is not None:
        backtest_config["capital_per_trade"] = args.capital_per_trade


def run_backtest(universe: list[str], config: dict) -> None:
    engine = SyntheticOptionsBacktestEngine(config)
    summary = engine.run(universe)
    output_config = config["output"]

    print("\nSynthetic Options Backtest Complete\n")
    print(f"Initial Capital: ${float(config['backtest']['initial_capital']):,.0f}")
    print(f"Total Trades: {summary['total_trades']}")
    print(f"Win Rate: {summary['win_rate'] * 100:.1f}%")
    print(f"Total PnL: ${summary['total_pnl']:,.0f}")
    print(f"Profit Factor: {summary['profit_factor']:.2f}")
    print(f"Max Drawdown: ${summary['max_drawdown']:,.0f}")
    print(f"Average Holding Days: {summary['average_holding_days']:.1f}")
    print("\nFiles saved:")
    print(f"- {output_config['backtest_trades_path']}")
    print(f"- {output_config['backtest_equity_curve_path']}")
    print(f"- {output_config['backtest_summary_path']}")


def run_ibkr_scan(universe: list[str], config: dict) -> list[OptionCandidate]:
    ibkr_config = config["ibkr"]
    client = IBKRClient(
        host=str(ibkr_config["host"]),
        port=int(ibkr_config["port"]),
        client_id=int(ibkr_config["client_id"]),
        market_data_type=str(ibkr_config.get("market_data_type", "delayed")),
        market_data_fallback_types=list(ibkr_config.get("market_data_fallback_types", ["delayed_frozen"])),
        market_data_generic_ticks=str(ibkr_config.get("market_data_generic_ticks", "")),
    )

    candidates: list[OptionCandidate] = []
    try:
        print("Scanner-only mode: order submission is disabled.")
        print(f"Connecting to IBKR at {client.host}:{client.port}...")
        client.connect()
        for ticker in universe:
            try:
                candidates.extend(scan_ticker_ibkr(client, ticker, config))
            except Exception as exc:
                print(f"[{ticker}] Skipping after error: {exc}")
    finally:
        client.disconnect()

    return candidates


def run_yahoo_scan(universe: list[str], config: dict) -> list[OptionCandidate]:
    client = YahooClient()
    candidates: list[OptionCandidate] = []
    print("Yahoo free-data mode: research/testing only; no IBKR connection or trading.")
    print("Greeks are approximate Black-Scholes estimates, not broker Greeks.")
    for ticker in universe:
        try:
            candidates.extend(scan_ticker_yahoo(client, ticker, config))
        except Exception as exc:
            print(f"[{ticker}] Skipping after error: {exc}")
    return candidates


def scan_ticker_ibkr(client: IBKRClient, ticker: str, config: dict) -> list[OptionCandidate]:
    print(f"[{ticker}] Pulling historical bars...")
    bars = client.get_historical_bars(ticker)
    signal = calculate_momentum(ticker, bars, config)
    if signal is None:
        print(f"[{ticker}] No positive momentum signal.")
        return []

    print(f"[{ticker}] Momentum score {signal.momentum_score:.3f}; pulling option chains...")
    chains = client.get_option_chain_definitions(ticker)
    if not chains:
        print(f"[{ticker}] No option chain definitions found.")
        return []

    option_contracts = _select_option_contracts(client, signal, chains, config)
    candidates: list[OptionCandidate] = []
    for option_contract in option_contracts:
        try:
            market_data = client.get_option_market_data(option_contract)
            if market_data.get("market_data_error"):
                print(f"[{ticker}] Market data unavailable: {market_data['market_data_error']}")
                continue
            candidate = _build_candidate(option_contract, signal, market_data)
            if not is_valid_call_candidate(candidate, config):
                continue
            candidates.append(score_option_candidate(candidate))
        except Exception as exc:
            print(f"[{ticker}] Skipping contract after error: {exc}")

    print(f"[{ticker}] Valid candidates: {len(candidates)}")
    return candidates


def scan_ticker_yahoo(client: YahooClient, ticker: str, config: dict) -> list[OptionCandidate]:
    print(f"[{ticker}] Pulling Yahoo historical bars...")
    bars = client.get_historical_bars(ticker)
    signal = calculate_momentum(ticker, bars, config)
    if signal is None:
        print(f"[{ticker}] No positive momentum signal.")
        return []

    print(f"[{ticker}] Momentum score {signal.momentum_score:.3f}; pulling Yahoo option chains...")
    raw_candidates = client.get_call_candidates(signal, config)
    candidates = [
        score_option_candidate(candidate)
        for candidate in raw_candidates
        if is_valid_call_candidate(candidate, config)
    ]
    print(f"[{ticker}] Valid candidates: {len(candidates)}")
    return candidates


def _select_option_contracts(client: IBKRClient, signal: MomentumSignal, chains, config: dict):
    strategy_config = config["strategy"]
    options_config = config["options"]
    min_dte = int(strategy_config["min_dte"])
    max_dte = int(strategy_config["max_dte"])
    strike_window_pct = float(options_config["strike_window_pct"])
    min_strike = signal.last_price * (1 - strike_window_pct)
    max_strike = signal.last_price * (1 + strike_window_pct)

    selected = []
    for chain in chains:
        expiries = sorted(expiry for expiry in chain.expirations if min_dte <= calculate_dte(expiry) <= max_dte)
        strikes = sorted(strike for strike in chain.strikes if min_strike <= float(strike) <= max_strike)
        for expiry in expiries:
            for strike in strikes:
                try:
                    selected.append(client.build_option_contract(signal.ticker, expiry, strike, "CALL"))
                except Exception as exc:
                    print(f"[{signal.ticker}] Could not build {expiry} {strike}C: {exc}")
    return selected


def _build_candidate(option_contract, signal: MomentumSignal, market_data: dict) -> OptionCandidate:
    return OptionCandidate(
        ticker=signal.ticker,
        expiry=option_contract.lastTradeDateOrContractMonth,
        strike=float(option_contract.strike),
        right=option_contract.right,
        bid=market_data.get("bid"),
        ask=market_data.get("ask"),
        mid=market_data.get("mid"),
        delta=market_data.get("delta"),
        gamma=market_data.get("gamma"),
        theta=market_data.get("theta"),
        vega=market_data.get("vega"),
        implied_vol=market_data.get("implied_vol"),
        open_interest=market_data.get("open_interest"),
        dte=calculate_dte(option_contract.lastTradeDateOrContractMonth),
        momentum_score=signal.momentum_score,
        liquidity_score=0.0,
        total_score=0.0,
    )


def print_ranked_contracts(candidates: list[OptionCandidate], limit: int = 10) -> None:
    print("\nTop Ranked Call Contracts\n")
    if not candidates:
        print("No valid contracts found.")
        return

    for index, candidate in enumerate(candidates[:limit], start=1):
        print(f"{index}. {candidate.ticker} {candidate.expiry} {candidate.strike:g}C")
        print(f"   Delta: {_fmt(candidate.delta)}")
        print(f"   Theta: {_fmt(candidate.theta)}")
        print(f"   Bid/Ask: {_fmt(candidate.bid)} / {_fmt(candidate.ask)}")
        print(f"   Momentum Score: {candidate.momentum_score:.3f}")
        print(f"   Total Score: {candidate.total_score:.2f}\n")


def save_ranked_contracts(candidates: list[OptionCandidate], output_path: str) -> None:
    ensure_parent_dir(output_path)
    columns = [
        "ticker",
        "expiry",
        "strike",
        "right",
        "bid",
        "ask",
        "mid",
        "delta",
        "gamma",
        "theta",
        "vega",
        "implied_vol",
        "open_interest",
        "dte",
        "momentum_score",
        "liquidity_score",
        "total_score",
    ]
    data = [asdict(candidate) for candidate in candidates]
    pd.DataFrame(data, columns=columns).to_csv(output_path, index=False)
    print(f"Saved ranked output to {output_path}")


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


if __name__ == "__main__":
    main()
