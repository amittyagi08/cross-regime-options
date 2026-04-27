from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from src.backtest.engine import SyntheticOptionsBacktestEngine, _overtrading_metrics
from src.backtest.metrics import calculate_backtest_metrics
from src.backtest.report import save_equity_curve_csv, save_summary_json, save_trades_csv
from src.data_loader import load_price_history
from src.sector_rotation.rebalance import get_effective_rebalance_date, get_rebalance_dates
from src.sector_rotation.report import save_sector_scores, save_weekly_universes
from src.sector_rotation.sector_config import load_sector_etfs, load_sector_map
from src.sector_rotation.sector_scoring import calculate_sector_scores
from src.sector_rotation.stock_scoring import calculate_stock_scores
from src.sector_rotation.universe_builder import build_weekly_universe


class SectorRotationBacktestEngine(SyntheticOptionsBacktestEngine):
    def __init__(self, config: dict):
        super().__init__(config, output_prefix="sector_rotation")
        self.sector_scores = pd.DataFrame()
        self.weekly_universes = pd.DataFrame()
        self._ticker_metadata: dict[str, dict] = {}

    def run(self, universe: list[str] | None = None) -> dict:
        del universe
        sector_etfs = load_sector_etfs()
        sector_map = load_sector_map()
        tickers = sorted(sector_map["ticker"].unique())
        sector_etf_symbols = sorted(sector_etfs["etf"].unique())
        start_date = self.config["backtest"]["start_date"]
        end_date = self.config["backtest"]["end_date"]
        warmup_start = (pd.Timestamp(start_date) - pd.Timedelta(days=460)).strftime("%Y-%m-%d")

        stock_frames = {ticker: self._prepare_history_range(ticker, warmup_start, end_date) for ticker in tickers}
        stock_frames = {ticker: frame for ticker, frame in stock_frames.items() if not frame.empty}
        etf_frames_by_symbol = {symbol: self._prepare_history_range(symbol, warmup_start, end_date) for symbol in sector_etf_symbols}
        etf_frames_by_symbol = {symbol: frame for symbol, frame in etf_frames_by_symbol.items() if not frame.empty}
        if bool(self.config["sector_rotation"].get("include_benchmark_symbols", True)):
            for symbol in [
                self.config["sector_rotation"].get("benchmark_symbol", "SPY"),
                self.config["sector_rotation"].get("growth_benchmark_symbol", "QQQ"),
            ]:
                if symbol in etf_frames_by_symbol:
                    stock_frames[symbol] = etf_frames_by_symbol[symbol]
        sector_frames = {
            row["sector"]: etf_frames_by_symbol.get(row["etf"], pd.DataFrame())
            for row in sector_etfs.to_dict("records")
            if row["sector"] not in {"Market", "Growth"}
        }
        sector_frames = {sector: frame for sector, frame in sector_frames.items() if not frame.empty}
        benchmark = etf_frames_by_symbol.get(self.config["sector_rotation"].get("benchmark_symbol", "SPY"), pd.DataFrame())
        if not stock_frames or not sector_frames or benchmark.empty:
            summary = calculate_backtest_metrics([], float(self.config["backtest"]["initial_capital"]))
            summary.update(_overtrading_metrics([]))
            self._save_outputs(summary)
            return summary

        weekly_universe_by_date = self._build_weekly_universes(sector_map, sector_frames, stock_frames, benchmark)
        if not weekly_universe_by_date:
            summary = calculate_backtest_metrics([], float(self.config["backtest"]["initial_capital"]))
            summary.update(_overtrading_metrics([]))
            self._save_outputs(summary)
            return summary

        frames = {
            ticker: frame[(frame["date"] >= pd.Timestamp(start_date).date()) & (frame["date"] <= pd.Timestamp(end_date).date())].reset_index(drop=True)
            for ticker, frame in stock_frames.items()
        }
        all_dates = sorted({row_date for frame in frames.values() for row_date in frame["date"].tolist()})
        open_trades = {}
        initial_capital = float(self.config["backtest"]["initial_capital"])
        realized_pnl = 0.0

        for current_date in all_dates:
            active_universe = weekly_universe_by_date.get(self._active_week_start(current_date, weekly_universe_by_date), pd.DataFrame())
            active_tickers = set(active_universe["ticker"].tolist()) if not active_universe.empty else set()
            for ticker, frame in frames.items():
                rows = frame[frame["date"] <= current_date]
                if rows.empty or rows.iloc[-1]["date"] != current_date:
                    continue
                row = rows.iloc[-1]
                if ticker in open_trades:
                    realized_pnl += self._maybe_exit_trade(open_trades, ticker, row)
                if ticker in active_tickers and ticker not in open_trades and len(open_trades) < int(self.config["backtest"]["max_positions"]):
                    self._ticker_metadata[ticker] = _metadata_for_ticker(active_universe, ticker)
                    trade = self._maybe_enter_trade(ticker, rows)
                    if trade is not None:
                        metadata = self._ticker_metadata.get(ticker, {})
                        trade.sector = metadata.get("sector")
                        trade.sector_etf = metadata.get("sector_etf")
                        trade.sector_score = metadata.get("sector_score")
                        trade.stock_score = metadata.get("stock_score")
                        open_trades[ticker] = trade

            self.equity_curve.append(
                {
                    "date": current_date,
                    "equity": initial_capital + realized_pnl,
                    "open_positions": len(open_trades),
                    "realized_pnl": realized_pnl,
                    "active_universe_size": len(active_tickers),
                }
            )

        for ticker, trade in list(open_trades.items()):
            frame = frames[ticker]
            if not frame.empty:
                realized_pnl += self._close_trade(open_trades, ticker, frame.iloc[-1], "end_of_backtest")

        summary = calculate_backtest_metrics(self.trades, initial_capital)
        summary.update(_overtrading_metrics(self.trades))
        summary["trades_per_sector"] = _trades_per_sector(self.trades)
        self._save_outputs(summary)
        return summary

    def _prepare_history_range(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            frame = load_price_history(ticker, start_date, end_date)
        except Exception as exc:
            print(f"[{ticker}] Could not load price history: {exc}")
            return pd.DataFrame()
        if len(frame) < 64:
            return pd.DataFrame()
        frame = frame.copy()
        frame["ema21"] = frame["close"].ewm(span=21, adjust=False).mean()
        frame["sma50"] = frame["close"].rolling(50).mean()
        frame["sma200"] = frame["close"].rolling(200).mean()
        from src.volatility import estimate_historical_volatility

        synthetic_config = self.config["synthetic_options"]
        frame["volatility"] = estimate_historical_volatility(
            frame["close"],
            lookback_days=int(synthetic_config["volatility_lookback_days"]),
            floor=float(synthetic_config["volatility_floor"]),
            ceiling=float(synthetic_config["volatility_ceiling"]),
        )
        return frame.dropna(subset=["ema21", "sma50", "volatility"]).reset_index(drop=True)

    def _build_weekly_universes(
        self,
        sector_map: pd.DataFrame,
        sector_frames: dict[str, pd.DataFrame],
        stock_frames: dict[str, pd.DataFrame],
        benchmark: pd.DataFrame,
    ) -> dict:
        start_date = self.config["backtest"]["start_date"]
        end_date = self.config["backtest"]["end_date"]
        frequency = self.config["sector_rotation"].get("rebalance_frequency", "W-MON")
        rebalance_targets = get_rebalance_dates(start_date, end_date, frequency)
        all_sector_scores = []
        all_weekly_universes = []
        weekly_by_date = {}
        reference = benchmark

        for target in rebalance_targets:
            effective = get_effective_rebalance_date(reference, target)
            if effective is None:
                continue
            as_of = _prior_trading_day(reference, effective)
            if as_of is None:
                continue
            sector_scores = calculate_sector_scores(sector_frames, benchmark, as_of, self.config)
            if sector_scores.empty:
                continue
            selected_sectors = sector_scores.loc[sector_scores["selected"], "sector"].tolist()
            stock_scores = calculate_stock_scores(stock_frames, sector_frames, sector_map, selected_sectors, as_of, self.config)
            weekly = build_weekly_universe(effective, sector_scores, stock_scores, self.config)
            if bool(self.config["sector_rotation"].get("include_benchmark_symbols", True)):
                weekly = _append_benchmarks(weekly, effective, self.config)
            all_sector_scores.append(sector_scores)
            all_weekly_universes.append(weekly)
            weekly_by_date[effective] = weekly

        self.sector_scores = pd.concat(all_sector_scores, ignore_index=True) if all_sector_scores else pd.DataFrame()
        self.weekly_universes = pd.concat(all_weekly_universes, ignore_index=True) if all_weekly_universes else pd.DataFrame()
        return weekly_by_date

    def _active_week_start(self, current_date, weekly_universe_by_date: dict):
        candidates = [date for date in weekly_universe_by_date if date <= current_date]
        return max(candidates) if candidates else None

    def _save_outputs(self, summary: dict) -> None:
        output = self.config["output"]
        save_trades_csv(self.trades, output["sector_rotation_backtest_trades_path"])
        save_equity_curve_csv(self.equity_curve, output["sector_rotation_backtest_equity_curve_path"])
        save_summary_json(summary, output["sector_rotation_backtest_summary_path"])
        save_sector_scores(self.sector_scores, output["sector_scores_path"])
        save_weekly_universes(self.weekly_universes, output["weekly_universes_path"])


def _prior_trading_day(frame: pd.DataFrame, effective_date):
    prior = frame[frame["date"] < effective_date]
    if prior.empty:
        return None
    return prior.iloc[-1]["date"]


def _metadata_for_ticker(active_universe: pd.DataFrame, ticker: str) -> dict:
    rows = active_universe[active_universe["ticker"] == ticker]
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


def _append_benchmarks(weekly: pd.DataFrame, effective, config: dict) -> pd.DataFrame:
    rotation = config["sector_rotation"]
    benchmarks = [
        ("Market", rotation.get("benchmark_symbol", "SPY")),
        ("Growth", rotation.get("growth_benchmark_symbol", "QQQ")),
    ]
    rows = [
        {
            "week_start": effective,
            "sector": sector,
            "sector_etf": ticker,
            "sector_score": None,
            "sector_rank": None,
            "ticker": ticker,
            "stock_score": None,
            "stock_rank_within_sector": None,
        }
        for sector, ticker in benchmarks
    ]
    return pd.concat([weekly, pd.DataFrame(rows)], ignore_index=True)


def _trades_per_sector(trades) -> dict:
    result = {}
    for trade in trades:
        sector = trade.sector or "Unknown"
        result[sector] = result.get(sector, 0) + 1
    return result
