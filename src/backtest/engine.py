from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.backtest.exits import should_exit_trade
from src.backtest.metrics import calculate_backtest_metrics
from src.backtest.report import save_equity_curve_csv, save_summary_json, save_trades_csv
from src.backtest.synthetic_options import generate_synthetic_call_candidates, reprice_synthetic_call
from src.backtest.trade import BacktestTrade
from src.data_loader import load_price_history
from src.momentum import calculate_momentum
from src.scoring import score_option_candidate
from src.utils import parse_ib_expiry
from src.volatility import estimate_historical_volatility


class SyntheticOptionsBacktestEngine:
    def __init__(self, config: dict, output_prefix: str = "backtest"):
        self.config = config
        self.output_prefix = output_prefix
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[dict] = []

    def run(self, universe: list[str]) -> dict:
        frames = {
            ticker: self._prepare_history(ticker)
            for ticker in universe
        }
        frames = {ticker: frame for ticker, frame in frames.items() if not frame.empty}
        if not frames:
            summary = calculate_backtest_metrics([], float(self.config["backtest"]["initial_capital"]))
            summary.update(_overtrading_metrics([]))
            self._save_outputs(summary)
            return summary

        all_dates = sorted({row_date for frame in frames.values() for row_date in frame["date"].tolist()})
        open_trades: dict[str, BacktestTrade] = {}
        initial_capital = float(self.config["backtest"]["initial_capital"])
        realized_pnl = 0.0

        for current_date in all_dates:
            for ticker, frame in frames.items():
                rows = frame[frame["date"] <= current_date]
                if rows.empty or rows.iloc[-1]["date"] != current_date:
                    continue

                row = rows.iloc[-1]
                if ticker in open_trades:
                    realized_pnl += self._maybe_exit_trade(open_trades, ticker, row)

                if ticker not in open_trades and len(open_trades) < int(self.config["backtest"]["max_positions"]):
                    trade = self._maybe_enter_trade(ticker, rows)
                    if trade is not None:
                        open_trades[ticker] = trade

            self.equity_curve.append(
                {
                    "date": current_date,
                    "equity": initial_capital + realized_pnl,
                    "open_positions": len(open_trades),
                    "realized_pnl": realized_pnl,
                }
            )

        for ticker, trade in list(open_trades.items()):
            frame = frames[ticker]
            last_row = frame.iloc[-1]
            realized_pnl += self._close_trade(open_trades, ticker, last_row, "end_of_backtest")

        summary = calculate_backtest_metrics(self.trades, initial_capital)
        summary.update(_overtrading_metrics(self.trades))
        self._save_outputs(summary)
        return summary

    def run_ticker(self, ticker: str) -> list[BacktestTrade]:
        frame = self._prepare_history(ticker)
        if frame.empty:
            return []
        open_trades: dict[str, BacktestTrade] = {}
        for _, row in frame.iterrows():
            rows = frame[frame["date"] <= row["date"]]
            if ticker in open_trades:
                self._maybe_exit_trade(open_trades, ticker, row)
            if ticker not in open_trades:
                trade = self._maybe_enter_trade(ticker, rows)
                if trade is not None:
                    open_trades[ticker] = trade
        if ticker in open_trades:
            self._close_trade(open_trades, ticker, frame.iloc[-1], "end_of_backtest")
        return self.trades

    def _prepare_history(self, ticker: str) -> pd.DataFrame:
        backtest_config = self.config["backtest"]
        try:
            frame = load_price_history(ticker, backtest_config["start_date"], backtest_config["end_date"])
        except Exception as exc:
            print(f"[{ticker}] Could not load price history: {exc}")
            return pd.DataFrame()
        if len(frame) < 60:
            print(f"[{ticker}] Insufficient history for backtest.")
            return pd.DataFrame()

        frame = frame.copy()
        frame["ema21"] = frame["close"].ewm(span=21, adjust=False).mean()
        frame["sma50"] = frame["close"].rolling(50).mean()
        frame["sma200"] = frame["close"].rolling(200).mean()
        synthetic_config = self.config["synthetic_options"]
        frame["volatility"] = estimate_historical_volatility(
            frame["close"],
            lookback_days=int(synthetic_config["volatility_lookback_days"]),
            floor=float(synthetic_config["volatility_floor"]),
            ceiling=float(synthetic_config["volatility_ceiling"]),
        )
        return frame.dropna(subset=["ema21", "sma50", "volatility"]).reset_index(drop=True)

    def _maybe_enter_trade(self, ticker: str, rows: pd.DataFrame) -> BacktestTrade | None:
        row = rows.iloc[-1]
        entry_config = self.config.get("daily_strategy", self.config.get("entry", {}))
        signal = calculate_momentum(ticker, rows, self.config)
        if signal is None:
            return None
        if signal.momentum_score < float(entry_config.get("min_momentum_score", 0.05)):
            return None
        if bool(entry_config.get("require_price_above_ema21", True)) and row["close"] <= row["ema21"]:
            return None
        if bool(entry_config.get("require_price_above_sma50", True)) and row["close"] <= row["sma50"]:
            return None

        candidates = generate_synthetic_call_candidates(
            ticker=ticker,
            trade_date=row["date"],
            underlying_price=float(row["close"]),
            volatility=float(row["volatility"]),
            momentum_score=signal.momentum_score,
            config=self.config,
        )
        if not candidates:
            return None

        scored = sorted(
            (score_option_candidate(candidate) for candidate in candidates),
            key=lambda candidate: candidate.total_score,
            reverse=True,
        )
        selected = scored[0]
        if selected.mid is None or selected.mid <= 0:
            return None

        capital_per_trade = float(self.config["backtest"]["capital_per_trade"])
        contracts = int(capital_per_trade // (selected.mid * 100))
        if contracts < 1:
            return None

        return BacktestTrade(
            ticker=ticker,
            entry_date=row["date"],
            exit_date=None,
            expiry=selected.expiry,
            strike=selected.strike,
            right=selected.right,
            contracts=contracts,
            entry_underlying_price=float(row["close"]),
            exit_underlying_price=None,
            entry_option_price=float(selected.mid),
            exit_option_price=None,
            entry_delta=float(selected.delta or 0),
            entry_theta=float(selected.theta or 0),
            exit_reason=None,
            pnl=None,
            pnl_pct=None,
            holding_days=None,
        )

    def _maybe_exit_trade(self, open_trades: dict[str, BacktestTrade], ticker: str, row: pd.Series) -> float:
        trade = open_trades[ticker]
        current_option_price = self._reprice_trade(trade, row)
        should_exit, reason = should_exit_trade(
            trade=trade,
            current_date=row["date"],
            current_underlying_price=float(row["close"]),
            current_option_price=current_option_price,
            current_close_below_ema21=bool(row["close"] < row["ema21"]),
            config=self.config,
        )
        if should_exit:
            return self._close_trade(open_trades, ticker, row, reason)
        return 0.0

    def _close_trade(
        self,
        open_trades: dict[str, BacktestTrade],
        ticker: str,
        row: pd.Series,
        reason: str,
    ) -> float:
        trade = open_trades.pop(ticker)
        exit_option_price = self._reprice_trade(trade, row)
        pnl = (exit_option_price - trade.entry_option_price) * 100 * trade.contracts
        basis = trade.entry_option_price * 100 * trade.contracts

        trade.exit_date = row["date"]
        trade.exit_underlying_price = float(row["close"])
        trade.exit_option_price = float(exit_option_price)
        trade.exit_reason = reason
        trade.pnl = float(pnl)
        trade.pnl_pct = float(pnl / basis) if basis > 0 else 0.0
        trade.holding_days = (trade.exit_date - trade.entry_date).days
        self.trades.append(trade)
        return float(pnl)

    def _reprice_trade(self, trade: BacktestTrade, row: pd.Series) -> float:
        remaining_dte = (parse_ib_expiry(trade.expiry) - row["date"]).days
        return reprice_synthetic_call(
            underlying_price=float(row["close"]),
            strike=trade.strike,
            remaining_dte=remaining_dte,
            volatility=float(row["volatility"]),
            config=self.config,
        )

    def _save_outputs(self, summary: dict) -> None:
        output_config = self.config["output"]
        trades_path = output_config.get(f"{self.output_prefix}_backtest_trades_path", output_config["backtest_trades_path"])
        equity_path = output_config.get(
            f"{self.output_prefix}_backtest_equity_curve_path",
            output_config["backtest_equity_curve_path"],
        )
        summary_path = output_config.get(f"{self.output_prefix}_backtest_summary_path", output_config["backtest_summary_path"])
        save_trades_csv(self.trades, trades_path)
        save_equity_curve_csv(self.equity_curve, equity_path)
        save_summary_json(summary, summary_path)


def _overtrading_metrics(trades: list[BacktestTrade]) -> dict:
    if not trades:
        return {
            "trades_per_day": {},
            "trades_per_week": {},
            "trades_per_ticker": {},
            "average_trades_per_day": 0.0,
            "max_trades_in_one_day": 0,
            "max_trades_in_one_week": 0,
            "return_per_trade": 0.0,
            "pnl_per_day": 0.0,
        }

    trades_per_day: dict[str, int] = {}
    trades_per_week: dict[str, int] = {}
    trades_per_ticker: dict[str, int] = {}
    for trade in trades:
        day_key = trade.entry_date.isoformat()
        week_key = f"{trade.entry_date.isocalendar().year}-W{trade.entry_date.isocalendar().week:02d}"
        trades_per_day[day_key] = trades_per_day.get(day_key, 0) + 1
        trades_per_week[week_key] = trades_per_week.get(week_key, 0) + 1
        trades_per_ticker[trade.ticker] = trades_per_ticker.get(trade.ticker, 0) + 1

    total_pnl = sum(float(trade.pnl or 0) for trade in trades)
    days = max(1, (max(trade.exit_date or trade.entry_date for trade in trades) - min(trade.entry_date for trade in trades)).days)
    return {
        "trades_per_day": trades_per_day,
        "trades_per_week": trades_per_week,
        "trades_per_ticker": trades_per_ticker,
        "average_trades_per_day": len(trades) / max(1, len(trades_per_day)),
        "max_trades_in_one_day": max(trades_per_day.values()),
        "max_trades_in_one_week": max(trades_per_week.values()),
        "return_per_trade": total_pnl / len(trades),
        "pnl_per_day": total_pnl / days,
    }
