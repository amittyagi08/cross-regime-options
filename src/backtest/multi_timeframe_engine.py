from __future__ import annotations

from datetime import timedelta

import pandas as pd

from src.backtest.engine import _overtrading_metrics
from src.backtest.metrics import calculate_backtest_metrics
from src.backtest.report import save_equity_curve_csv, save_summary_json, save_trades_csv
from src.backtest.synthetic_options import generate_synthetic_call_candidates, reprice_synthetic_call
from src.backtest.trade import BacktestTrade
from src.data_loader import load_price_history
from src.indicators import add_ema, add_returns, add_sma, add_volume_ratio, add_vwap
from src.intraday_loader import load_intraday_history
from src.momentum import calculate_momentum
from src.utils import parse_ib_expiry
from src.timeframe import get_completed_intraday_context_as_of, get_daily_context_as_of
from src.volatility import estimate_historical_volatility


class MultiTimeframeSyntheticOptionsBacktestEngine:
    def __init__(self, config: dict):
        self.config = config
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[dict] = []
        self._open_metadata: dict[str, dict] = {}

    def run(self, universe: list[str]) -> dict:
        prepared = {ticker: self._prepare_ticker(ticker) for ticker in universe}
        prepared = {ticker: data for ticker, data in prepared.items() if data}
        initial_capital = float(self.config["backtest"]["initial_capital"])
        if not prepared:
            summary = calculate_backtest_metrics([], initial_capital)
            summary.update(_overtrading_metrics([]))
            self._save_outputs(summary)
            return summary

        regime_data = self._prepare_regime_data()
        events = sorted(
            (row["timestamp"], ticker, index)
            for ticker, data in prepared.items()
            for index, row in data["5m"].iterrows()
        )
        open_trades: dict[str, BacktestTrade] = {}
        realized_pnl = 0.0
        trades_today: dict = {}
        trades_week: dict[tuple[str, str], int] = {}
        last_trade_time: dict[str, pd.Timestamp] = {}

        for timestamp, ticker, index in events:
            data = prepared[ticker]
            row = data["5m"].iloc[index]
            if ticker in open_trades:
                realized_pnl += self._maybe_exit_trade(open_trades, ticker, row, data["60m"])

            if self._can_attempt_entry(open_trades, ticker, row, index, data, trades_today, trades_week, last_trade_time):
                trade = self._maybe_enter_trade(ticker, row, index, data, regime_data)
                if trade is not None:
                    open_trades[ticker] = trade
                    entry_ts = pd.Timestamp(row["timestamp"])
                    daily_context = get_daily_context_as_of(data["daily"], entry_ts)
                    self._open_metadata[ticker] = {
                        "entry_timestamp": entry_ts,
                        "entry_index": index,
                        "volatility": float(daily_context.get("volatility", self.config["synthetic_options"]["volatility_floor"])),
                    }
                    trades_today[entry_ts.date()] = trades_today.get(entry_ts.date(), 0) + 1
                    week_key = _week_key(entry_ts)
                    trades_week[(ticker, week_key)] = trades_week.get((ticker, week_key), 0) + 1
                    last_trade_time[ticker] = entry_ts

            self.equity_curve.append(
                {
                    "timestamp": timestamp,
                    "equity": initial_capital + realized_pnl,
                    "open_positions": len(open_trades),
                    "realized_pnl": realized_pnl,
                }
            )

        for ticker, trade in list(open_trades.items()):
            last_row = prepared[ticker]["5m"].iloc[-1]
            realized_pnl += self._close_trade(open_trades, ticker, last_row, "end_of_data")

        summary = calculate_backtest_metrics(self.trades, initial_capital)
        summary.update(_overtrading_metrics(self.trades))
        self._save_outputs(summary)
        return summary

    def run_ticker(self, ticker: str) -> list[BacktestTrade]:
        self.run([ticker])
        return self.trades

    def _prepare_ticker(self, ticker: str) -> dict[str, pd.DataFrame] | None:
        data_config = self.config.get("data", {})
        start_date = self.config["backtest"]["start_date"]
        end_date = self.config["backtest"]["end_date"]
        try:
            daily = load_price_history(ticker, start_date, end_date)
            bars_60m = load_intraday_history(ticker, data_config.get("intraday_60m_period", "730d"), "60m")
            bars_5m = load_intraday_history(ticker, data_config.get("intraday_5m_period", "60d"), "5m")
        except Exception as exc:
            print(f"[{ticker}] Could not load multi-timeframe data: {exc}")
            return None
        if daily.empty or bars_60m.empty or bars_5m.empty:
            print(f"[{ticker}] Missing daily, 60m, or 5m data for MTF backtest.")
            return None

        daily = self._prepare_daily(daily)
        bars_60m = self._prepare_intraday(bars_60m, "60m")
        bars_5m = self._prepare_intraday(bars_5m, "5m")
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)
        bars_60m = bars_60m[(bars_60m["timestamp"] >= start_ts) & (bars_60m["timestamp"] < end_ts)].reset_index(drop=True)
        bars_5m = bars_5m[(bars_5m["timestamp"] >= start_ts) & (bars_5m["timestamp"] < end_ts)].reset_index(drop=True)
        if bars_5m.empty:
            print(f"[{ticker}] 5-minute data unavailable in requested window; MTF ticker skipped.")
            return None
        return {"daily": daily, "60m": bars_60m, "5m": bars_5m}

    def _prepare_daily(self, daily: pd.DataFrame) -> pd.DataFrame:
        result = add_sma(add_sma(add_ema(daily, 21), 50), 200)
        vol_config = self.config["synthetic_options"]
        result["volatility"] = estimate_historical_volatility(
            result["close"],
            int(vol_config["volatility_lookback_days"]),
            float(vol_config["volatility_floor"]),
            float(vol_config["volatility_ceiling"]),
        )
        return result.dropna(subset=["ema21", "sma50", "volatility"]).reset_index(drop=True)

    def _prepare_intraday(self, bars: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        result = add_ema(bars, 21)
        result = add_vwap(result)
        result = add_volume_ratio(result, 20)
        if timeframe == "60m":
            lookback = int(self.config["timeframe_60m"]["momentum_lookback_bars"])
        else:
            lookback = int(self.config["timeframe_5m"]["breakout_lookback_bars"])
        result = add_returns(result, lookback)
        return result.dropna(subset=["ema21", "vwap", "volume_ratio", f"return_{lookback}"]).reset_index(drop=True)

    def _prepare_regime_data(self) -> dict[str, pd.DataFrame]:
        regime_config = self.config.get("regime", {})
        symbols = {
            "spy": regime_config.get("spy_symbol", "SPY"),
            "qqq": regime_config.get("qqq_symbol", "QQQ"),
            "smh": regime_config.get("smh_symbol", "SMH"),
        }
        data = {}
        for key, symbol in symbols.items():
            try:
                frame = load_price_history(symbol, self.config["backtest"]["start_date"], self.config["backtest"]["end_date"])
                data[key] = self._prepare_daily(frame) if not frame.empty else pd.DataFrame()
            except Exception:
                data[key] = pd.DataFrame()
        return data

    def _can_attempt_entry(
        self,
        open_trades: dict[str, BacktestTrade],
        ticker: str,
        row: pd.Series,
        index: int,
        data: dict[str, pd.DataFrame],
        trades_today: dict,
        trades_week: dict[tuple[str, str], int],
        last_trade_time: dict[str, pd.Timestamp],
    ) -> bool:
        backtest_config = self.config["backtest"]
        overtrading_config = self.config.get("overtrading", {})
        timestamp = pd.Timestamp(row["timestamp"])
        if index >= len(data["5m"]) - int(backtest_config.get("avoid_last_n_bars", 5)):
            return False
        if bool(backtest_config.get("one_trade_per_ticker", True)) and ticker in open_trades:
            return False
        if len(open_trades) >= int(backtest_config.get("max_positions", 3)):
            return False
        if trades_today.get(timestamp.date(), 0) >= int(overtrading_config.get("max_trades_per_day", 3)):
            return False
        week_key = _week_key(timestamp)
        if trades_week.get((ticker, week_key), 0) >= int(overtrading_config.get("max_trades_per_ticker_per_week", 2)):
            return False
        last_ts = last_trade_time.get(ticker)
        min_hours = float(overtrading_config.get("min_hours_between_trades_same_ticker", 24))
        if last_ts is not None and timestamp - last_ts < pd.Timedelta(hours=min_hours):
            return False
        return _is_tradeable_time(timestamp, self.config)

    def _maybe_enter_trade(
        self,
        ticker: str,
        row: pd.Series,
        index: int,
        data: dict[str, pd.DataFrame],
        regime_data: dict[str, pd.DataFrame],
    ) -> BacktestTrade | None:
        timestamp = pd.Timestamp(row["timestamp"])
        daily_context = get_daily_context_as_of(data["daily"], timestamp)
        context_60m = get_completed_intraday_context_as_of(data["60m"], timestamp)
        if not daily_context or not context_60m:
            return None
        signal_score = self._calculate_signal_score(ticker, data, index, daily_context, context_60m, timestamp, regime_data)
        scoring_config = self.config.get("mtf_scoring", {})
        if signal_score["total_score"] < float(scoring_config.get("entry_threshold", 60)):
            return None
        daily_momentum_score = signal_score["daily_momentum_score"] or 0.0

        next_row = data["5m"].iloc[index + 1]
        candidates = generate_synthetic_call_candidates(
            ticker=ticker,
            trade_date=pd.Timestamp(next_row["timestamp"]).date(),
            underlying_price=float(next_row["open"]),
            volatility=float(daily_context["volatility"]),
            momentum_score=daily_momentum_score,
            config=self.config,
        )
        if not candidates:
            return None
        selected = candidates[0]
        if selected.ask is None or selected.ask <= 0:
            return None
        size_multiplier = _position_size_multiplier(signal_score["total_score"], self.config)
        trade_capital = float(self.config["backtest"]["capital_per_trade"]) * size_multiplier
        contracts = int(trade_capital // (selected.ask * 100))
        if contracts < 1:
            return None
        trade = BacktestTrade(
            ticker=ticker,
            entry_date=pd.Timestamp(next_row["timestamp"]).date(),
            exit_date=None,
            expiry=selected.expiry,
            strike=selected.strike,
            right="C",
            contracts=contracts,
            entry_underlying_price=float(next_row["open"]),
            exit_underlying_price=None,
            entry_option_price=float(selected.ask),
            exit_option_price=None,
            entry_delta=float(selected.delta or 0),
            entry_theta=float(selected.theta or 0),
            exit_reason=None,
            pnl=None,
            pnl_pct=None,
            holding_days=None,
            entry_signal_score=float(signal_score["total_score"]),
            daily_score=float(signal_score["daily_score"]),
            score_60m=float(signal_score["score_60m"]),
            score_5m=float(signal_score["score_5m"]),
            position_size_multiplier=float(size_multiplier),
        )
        return trade

    def _calculate_signal_score(
        self,
        ticker: str,
        data: dict[str, pd.DataFrame],
        index: int,
        daily_context: dict,
        context_60m: dict,
        timestamp,
        regime_data: dict[str, pd.DataFrame],
    ) -> dict:
        daily_momentum_score = self._daily_momentum_score(ticker, data["daily"], daily_context)
        daily_score = self._daily_score(daily_momentum_score, daily_context, timestamp, regime_data)
        score_60m = self._sixty_minute_score(context_60m)
        score_5m = self._five_minute_score(data["5m"], index)
        return {
            "total_score": daily_score + score_60m + score_5m,
            "daily_score": daily_score,
            "score_60m": score_60m,
            "score_5m": score_5m,
            "daily_momentum_score": daily_momentum_score,
        }

    def _daily_filter_passes(
        self,
        daily_momentum_score: float | None,
        daily_context: dict,
        timestamp,
        regime_data: dict[str, pd.DataFrame],
    ) -> bool:
        daily_filter = self.config.get("daily_filter", {})
        if daily_momentum_score is None or daily_momentum_score < float(daily_filter.get("min_daily_momentum_score", 0.04)):
            return False
        if bool(daily_filter.get("require_close_above_sma50", True)) and daily_context["close"] <= daily_context["sma50"]:
            return False
        if bool(daily_filter.get("require_close_above_sma200", False)) and daily_context.get("sma200") and daily_context["close"] <= daily_context["sma200"]:
            return False
        if bool(daily_filter.get("require_ema21_above_sma50", False)) and daily_context["ema21"] <= daily_context["sma50"]:
            return False
        return self._regime_filter_passes(timestamp, regime_data)

    def _daily_score(
        self,
        daily_momentum_score: float | None,
        daily_context: dict,
        timestamp,
        regime_data: dict[str, pd.DataFrame],
    ) -> float:
        daily_filter = self.config.get("daily_filter", {})
        score = 0.0
        if daily_context["close"] > daily_context["sma50"]:
            score += 15
        if daily_momentum_score is not None and daily_momentum_score >= float(daily_filter.get("min_daily_momentum_score", 0.04)):
            score += 15
        if self._regime_filter_passes(timestamp, regime_data):
            score += 10
        return score

    def _daily_momentum_score(self, ticker: str, daily: pd.DataFrame, daily_context: dict) -> float | None:
        prior_daily = daily[daily["date"] <= daily_context["date"]].copy()
        signal = calculate_momentum(ticker, prior_daily, self.config)
        return signal.momentum_score if signal is not None else None

    def _regime_filter_passes(self, timestamp, regime_data: dict[str, pd.DataFrame]) -> bool:
        daily_filter = self.config.get("daily_filter", {})
        regime_config = self.config.get("regime", {})
        checks = [
            ("spy", daily_filter.get("use_spy_regime", True), regime_config.get("require_spy_above_sma50", True)),
            ("qqq", daily_filter.get("use_qqq_regime", True), regime_config.get("require_qqq_above_sma50", True)),
            ("smh", daily_filter.get("use_smh_regime", True), regime_config.get("require_smh_above_sma50", False)),
        ]
        for key, enabled, require_above_sma50 in checks:
            if not enabled:
                continue
            context = get_daily_context_as_of(regime_data.get(key, pd.DataFrame()), timestamp)
            if not context:
                return False
            if require_above_sma50 and context["close"] <= context["sma50"]:
                return False
        if bool(regime_config.get("require_qqq_momentum_positive", True)):
            qqq = regime_data.get("qqq", pd.DataFrame())
            context = get_daily_context_as_of(qqq, timestamp)
            if not context:
                return False
            signal = calculate_momentum("QQQ", qqq[qqq["date"] <= context["date"]], self.config)
            if signal is None or signal.momentum_score <= 0:
                return False
        return True

    def _sixty_minute_filter_passes(self, context: dict) -> bool:
        config = self.config.get("timeframe_60m", {})
        if not bool(config.get("enabled", True)):
            return True
        lookback = int(config.get("momentum_lookback_bars", 6))
        if bool(config.get("require_price_above_ema21", True)) and context["close"] <= context["ema21"]:
            return False
        if bool(config.get("require_positive_momentum", True)) and context.get(f"return_{lookback}", 0) <= float(config.get("min_60m_return", 0.005)):
            return False
        extension = (context["close"] - context["ema21"]) / context["ema21"]
        return extension <= float(config.get("avoid_if_extended_from_ema21_pct", 0.06))

    def _sixty_minute_score(self, context: dict) -> float:
        config = self.config.get("timeframe_60m", {})
        if not bool(config.get("enabled", True)):
            return 30.0
        lookback = int(config.get("momentum_lookback_bars", 6))
        score = 0.0
        if context["close"] > context["ema21"]:
            score += 10
        if context.get(f"return_{lookback}", 0) > 0:
            score += 10
        extension = (context["close"] - context["ema21"]) / context["ema21"]
        if extension <= float(config.get("avoid_if_extended_from_ema21_pct", 0.06)):
            score += 10
        return score

    def _five_minute_trigger_passes(self, bars_5m: pd.DataFrame, index: int) -> bool:
        config = self.config.get("timeframe_5m", {})
        if not bool(config.get("enabled", True)):
            return True
        row = bars_5m.iloc[index]
        prev = bars_5m.iloc[index - 1] if index > 0 else None
        lookback = int(config.get("breakout_lookback_bars", 6))
        if index < lookback:
            return False
        if bool(config.get("require_price_above_vwap", True)) and row["close"] <= row["vwap"]:
            return False
        if row["volume_ratio"] < float(config.get("min_volume_ratio", 1.2)):
            return False
        previous_high = bars_5m.iloc[index - lookback:index]["high"].max()
        breakout = row["close"] > previous_high and row[f"return_{lookback}"] > float(config.get("min_5m_return", 0.003))
        reclaim = prev is not None and prev["close"] < prev["vwap"] and row["close"] > row["vwap"] and row["close"] > prev["high"]
        trigger = str(config.get("entry_trigger", "breakout_or_vwap_reclaim"))
        if trigger == "breakout":
            return breakout
        if trigger == "vwap_reclaim":
            return reclaim
        return breakout or reclaim

    def _five_minute_score(self, bars_5m: pd.DataFrame, index: int) -> float:
        config = self.config.get("timeframe_5m", {})
        if not bool(config.get("enabled", True)):
            return 30.0
        if index <= 0:
            return 0.0
        row = bars_5m.iloc[index]
        prev = bars_5m.iloc[index - 1]
        lookback = int(config.get("breakout_lookback_bars", 6))
        if index < lookback:
            return 0.0
        previous_high = bars_5m.iloc[index - lookback:index]["high"].max()
        breakout = row["close"] > previous_high and row[f"return_{lookback}"] > float(config.get("min_5m_return", 0.003))
        reclaim = prev["close"] < prev["vwap"] and row["close"] > row["vwap"] and row["close"] > prev["high"]
        score = 0.0
        if breakout:
            score += 15
        if reclaim:
            score += 10
        if row["volume_ratio"] >= float(config.get("min_volume_ratio", 1.2)):
            score += 5
        return score

    def _maybe_exit_trade(
        self,
        open_trades: dict[str, BacktestTrade],
        ticker: str,
        row: pd.Series,
        bars_60m: pd.DataFrame,
    ) -> float:
        trade = open_trades[ticker]
        exit_price = self._exit_price(trade, row)
        reason = self._exit_reason(trade, row, bars_60m, exit_price)
        if reason:
            return self._close_trade(open_trades, ticker, row, reason)
        return 0.0

    def _exit_reason(self, trade: BacktestTrade, row: pd.Series, bars_60m: pd.DataFrame, exit_price: float) -> str:
        exit_config = self.config.get("exit", {})
        pnl_pct = (exit_price - trade.entry_option_price) / trade.entry_option_price
        if pnl_pct >= float(exit_config.get("profit_target_pct", 0.40)):
            return "profit_target"
        if pnl_pct <= float(exit_config.get("stop_loss_pct", -0.25)):
            return "stop_loss"
        if bool(exit_config.get("exit_on_5m_vwap_loss", True)) and row["close"] < row["vwap"]:
            return "5m_vwap_loss"
        context_60m = get_completed_intraday_context_as_of(bars_60m, row["timestamp"])
        if bool(exit_config.get("exit_on_60m_ema21_loss", True)) and context_60m and context_60m["close"] < context_60m["ema21"]:
            return "60m_ema21_loss"
        score_60m = self._sixty_minute_score(context_60m) if context_60m else 0.0
        score_5m = self._five_minute_score_from_row(row)
        current_score = score_60m + score_5m
        trade.exit_signal_score = float(current_score)
        if current_score < float(self.config.get("mtf_scoring", {}).get("early_exit_threshold", 40)):
            return "score_below_40"
        metadata = self._open_metadata.get(trade.ticker, {})
        bars_held = int(row.name) - int(metadata.get("entry_index", row.name))
        if bars_held >= int(exit_config.get("exit_if_no_followthrough_bars", 12)):
            if pnl_pct < float(exit_config.get("no_followthrough_min_profit_pct", 0.05)):
                return "no_followthrough"
        if (pd.Timestamp(row["timestamp"]).date() - trade.entry_date).days >= int(exit_config.get("max_holding_days", 5)):
            return "max_holding_days"
        return ""

    def _five_minute_score_from_row(self, row: pd.Series) -> float:
        config = self.config.get("timeframe_5m", {})
        score = 0.0
        if row["close"] > row["vwap"]:
            score += 10
        if row["volume_ratio"] >= float(config.get("min_volume_ratio", 1.2)):
            score += 5
        if row.get("close", 0) > row.get("ema21", float("inf")):
            score += 5
        return score

    def _close_trade(self, open_trades: dict[str, BacktestTrade], ticker: str, row: pd.Series, reason: str) -> float:
        trade = open_trades.pop(ticker)
        self._open_metadata.pop(ticker, None)
        exit_price = self._exit_price(trade, row)
        pnl = (exit_price - trade.entry_option_price) * 100 * trade.contracts
        basis = trade.entry_option_price * 100 * trade.contracts
        trade.exit_date = pd.Timestamp(row["timestamp"]).date()
        trade.exit_underlying_price = float(row["close"])
        trade.exit_option_price = float(exit_price)
        trade.exit_reason = reason
        trade.pnl = float(pnl)
        trade.pnl_pct = float(pnl / basis) if basis > 0 else 0.0
        trade.holding_days = (trade.exit_date - trade.entry_date).days
        self.trades.append(trade)
        return float(pnl)

    def _exit_price(self, trade: BacktestTrade, row: pd.Series) -> float:
        remaining_dte = (parse_ib_expiry(trade.expiry) - pd.Timestamp(row["timestamp"]).date()).days
        mid = reprice_synthetic_call(
            underlying_price=float(row["close"]),
            strike=trade.strike,
            remaining_dte=remaining_dte,
            volatility=self._current_volatility(trade.ticker),
            config=self.config,
        )
        return mid * 0.995

    def _current_volatility(self, ticker: str) -> float:
        metadata = self._open_metadata.get(ticker, {})
        return float(metadata.get("volatility", self.config["synthetic_options"].get("volatility_floor", 0.20)))

    def _save_outputs(self, summary: dict) -> None:
        output = self.config["output"]
        save_trades_csv(self.trades, output["mtf_backtest_trades_path"])
        save_equity_curve_csv(self.equity_curve, output["mtf_backtest_equity_curve_path"])
        save_summary_json(summary, output["mtf_backtest_summary_path"])


def _is_tradeable_time(timestamp: pd.Timestamp, config: dict) -> bool:
    tf_config = config.get("timeframe_5m", {})
    session_open = timestamp.replace(hour=9, minute=30, second=0, microsecond=0)
    session_close = timestamp.replace(hour=16, minute=0, second=0, microsecond=0)
    after_open = timestamp >= session_open + timedelta(minutes=int(tf_config.get("avoid_first_minutes", 10)))
    before_close = timestamp <= session_close - timedelta(minutes=int(tf_config.get("avoid_last_minutes", 20)))
    return after_open and before_close


def _week_key(timestamp: pd.Timestamp) -> str:
    calendar = timestamp.isocalendar()
    return f"{calendar.year}-W{calendar.week:02d}"


def _position_size_multiplier(total_score: float, config: dict) -> float:
    scoring_config = config.get("mtf_scoring", {})
    if total_score >= float(scoring_config.get("full_size_threshold", 75)):
        return 1.0
    if total_score >= float(scoring_config.get("entry_threshold", 60)):
        return float(scoring_config.get("half_size_multiplier", 0.5))
    return 0.0
