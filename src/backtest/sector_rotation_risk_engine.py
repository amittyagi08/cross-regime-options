from __future__ import annotations

from collections import Counter

import pandas as pd

from src.backtest.engine import _overtrading_metrics
from src.backtest.metrics import calculate_backtest_metrics
from src.backtest.report import save_equity_curve_csv, save_summary_json, save_trades_csv
from src.sector_rotation.report import save_sector_scores, save_weekly_universes
from src.backtest.sector_rotation_engine import SectorRotationBacktestEngine
from src.backtest.trade import BacktestTrade
from src.risk.exposure_controls import can_open_new_trade, get_position_size_multiplier
from src.risk.loss_controls import should_exit_no_followthrough, should_pause_after_loss_cluster
from src.risk.profit_management import (
    should_exit_runner,
    should_take_partial_profit,
    update_runner_trailing_stop,
)
from src.risk.risk_config import get_risk_config
from src.risk.risk_report import save_risk_events
from src.risk.risk_state import RiskState


class SectorRotationRiskBacktestEngine(SectorRotationBacktestEngine):
    def __init__(self, config: dict):
        super().__init__(config)
        self.output_prefix = "sector_rotation_risk"
        self.risk_state = RiskState()
        self.risk_cfg = get_risk_config(config)
        self.profit_cfg = config.get("profit_management", {})
        self.risk_reporting_cfg = config.get("risk_reporting", {})
        self._blocked_trades = 0
        self._risk_exit_counts: Counter[str] = Counter()
        self._pause_events = 0
        self._position_size_reduction_count = 0

    def run(self, universe: list[str] | None = None) -> dict:
        del universe
        sector_etfs = self._load_sector_etfs()
        sector_map = self._load_sector_map()
        tickers = sorted(sector_map["ticker"].unique())
        sector_etf_symbols = sorted(sector_etfs["etf"].unique())
        start_date = self.config["backtest"]["start_date"]
        end_date = self.config["backtest"]["end_date"]
        warmup_start = (pd.Timestamp(start_date) - pd.Timedelta(days=460)).strftime("%Y-%m-%d")

        stock_frames = {ticker: self._prepare_history_range(ticker, warmup_start, end_date) for ticker in tickers}
        stock_frames = {ticker: frame for ticker, frame in stock_frames.items() if not frame.empty}
        etf_frames_by_symbol = {symbol: self._prepare_history_range(symbol, warmup_start, end_date) for symbol in sector_etf_symbols}
        etf_frames_by_symbol = {symbol: frame for symbol, frame in etf_frames_by_symbol.items() if not frame.empty}

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
        open_trades: dict[str, BacktestTrade] = {}
        initial_capital = float(self.config["backtest"]["initial_capital"])
        realized_pnl = 0.0
        peak_equity = initial_capital

        for current_date in all_dates:
            self.risk_state.reset_weekly_counters_if_needed(current_date)
            self.risk_state.reset_monthly_counters_if_needed(current_date)

            active_universe = weekly_universe_by_date.get(self._active_week_start(current_date, weekly_universe_by_date), pd.DataFrame())
            tradable_rows = active_universe[active_universe.get("is_tradable", True) == True] if not active_universe.empty else active_universe
            active_tickers = set(tradable_rows["ticker"].tolist()) if not tradable_rows.empty else set()

            paused_now, pause_reason = should_pause_after_loss_cluster(self.risk_state, current_date, self.risk_cfg)
            if paused_now and pause_reason == "loss_cluster_pause":
                self._pause_events += 1
                self.risk_state.record_risk_event(
                    date=current_date,
                    ticker=None,
                    sector=None,
                    event_type="system_paused",
                    reason=pause_reason,
                    trade_id=None,
                    pnl=None,
                    drawdown=None,
                    details=f"pause_until={self.risk_state.pause_until}",
                )

            current_equity = initial_capital + realized_pnl
            peak_equity = max(peak_equity, current_equity)
            current_drawdown_pct = ((current_equity - peak_equity) / peak_equity) if peak_equity > 0 else 0.0
            size_multiplier = get_position_size_multiplier(current_drawdown_pct, self.risk_cfg)
            if size_multiplier < 1.0:
                self._position_size_reduction_count += 1

            for ticker, frame in frames.items():
                rows = frame[frame["date"] <= current_date]
                if rows.empty or rows.iloc[-1]["date"] != current_date:
                    continue
                row = rows.iloc[-1]

                if ticker in open_trades:
                    pnl_delta = self._maybe_exit_trade_risk(open_trades, ticker, row)
                    realized_pnl += pnl_delta

                if ticker not in active_tickers or ticker in open_trades:
                    continue

                metadata = self._metadata_for_ticker(active_universe, ticker)
                sector = str(metadata.get("sector") or "Unknown")
                allowed, block_reason = can_open_new_trade(
                    ticker=ticker,
                    sector=sector,
                    current_date=current_date,
                    risk_state=self.risk_state,
                    open_trades=list(open_trades.values()),
                    config=self.risk_cfg,
                )
                if not allowed:
                    self._blocked_trades += 1
                    self.risk_state.record_risk_event(
                        date=current_date,
                        ticker=ticker,
                        sector=sector,
                        event_type="trade_blocked",
                        reason=block_reason,
                        trade_id=None,
                        pnl=None,
                        drawdown=current_drawdown_pct,
                        details="",
                    )
                    continue

                self._ticker_metadata[ticker] = metadata
                trade = self._maybe_enter_trade_risk(ticker, rows, size_multiplier)
                if trade is None:
                    continue

                trade.sector = metadata.get("sector")
                trade.sector_etf = metadata.get("sector_etf")
                trade.sector_score = metadata.get("sector_score")
                trade.stock_score = metadata.get("stock_score")
                open_trades[ticker] = trade
                self.risk_state.record_trade_open(ticker, trade.sector, current_date)

            self.equity_curve.append(
                {
                    "date": current_date,
                    "equity": initial_capital + realized_pnl,
                    "open_positions": len(open_trades),
                    "realized_pnl": realized_pnl,
                    "active_universe_size": len(active_tickers),
                    "risk_paused": self.risk_state.is_paused(current_date),
                }
            )

        for ticker, trade in list(open_trades.items()):
            frame = frames[ticker]
            if not frame.empty:
                realized_pnl += self._close_trade_risk(open_trades, ticker, frame.iloc[-1], "end_of_backtest")

        summary = calculate_backtest_metrics(self.trades, initial_capital)
        summary.update(_overtrading_metrics(self.trades))
        summary["trades_per_sector"] = self._trades_per_sector(self.trades)
        summary.update(self._risk_summary_metrics(summary))
        self._save_outputs(summary)
        return summary

    def _maybe_enter_trade_risk(self, ticker: str, rows: pd.DataFrame, size_multiplier: float) -> BacktestTrade | None:
        trade = self._maybe_enter_trade(ticker, rows)
        if trade is None:
            return None
        capital_multiplier = max(0.05, min(1.0, float(size_multiplier)))
        if capital_multiplier < 1.0:
            base_contracts = max(1, trade.contracts)
            resized = max(1, int(base_contracts * capital_multiplier))
            trade.contracts = resized
            trade.position_size_multiplier = capital_multiplier
            trade.risk_size_multiplier = capital_multiplier
        trade.remaining_contracts = trade.contracts
        trade.highest_option_price = trade.entry_option_price
        return trade

    def _maybe_exit_trade_risk(self, open_trades: dict[str, BacktestTrade], ticker: str, row: pd.Series) -> float:
        trade = open_trades[ticker]
        current_option_price = self._reprice_trade(trade, row)
        current_close_below_ema21 = bool(row["close"] < row["ema21"])
        current_date = row["date"]

        if bool(self.profit_cfg.get("enabled", True)):
            take_partial, _ = should_take_partial_profit(trade, current_option_price, self.profit_cfg)
            if take_partial:
                self._take_partial_profit(trade, current_option_price, current_date)

        update_runner_trailing_stop(trade, current_option_price, self.profit_cfg)

        stop_loss_pct = float(self.risk_cfg.get("stop_loss_pct", -0.18))
        pnl_pct_open = (current_option_price - trade.entry_option_price) / trade.entry_option_price if trade.entry_option_price > 0 else 0.0
        if pnl_pct_open <= stop_loss_pct:
            return self._close_trade_risk(open_trades, ticker, row, "stop_loss")

        exit_nf, nf_reason = should_exit_no_followthrough(trade, current_date, current_option_price, self.risk_cfg)
        if exit_nf:
            return self._close_trade_risk(open_trades, ticker, row, nf_reason)

        runner_exit, runner_reason = should_exit_runner(trade, current_option_price, current_date, self.profit_cfg)
        if runner_exit:
            return self._close_trade_risk(open_trades, ticker, row, runner_reason)

        exit_cfg = self.config.get("exit", {})
        if bool(exit_cfg.get("exit_on_close_below_ema21", True)) and current_close_below_ema21:
            return self._close_trade_risk(open_trades, ticker, row, "close_below_ema21")

        if (current_date - trade.entry_date).days >= int(exit_cfg.get("max_holding_days", 5)):
            return self._close_trade_risk(open_trades, ticker, row, "max_holding_days")

        return 0.0

    def _take_partial_profit(self, trade: BacktestTrade, current_option_price: float, current_date) -> None:
        if trade.partial_profit_taken:
            return
        current_contracts = int(trade.remaining_contracts or trade.contracts or 0)
        if current_contracts < 1:
            return

        if current_contracts < 2:
            trade.partial_profit_taken = True
            trade.partial_exit_date = current_date
            trade.partial_exit_price = current_option_price
            return

        partial_contracts = current_contracts // 2
        pnl = (current_option_price - trade.entry_option_price) * 100 * partial_contracts
        trade.partial_pnl += float(pnl)
        trade.remaining_contracts = current_contracts - partial_contracts
        trade.partial_profit_taken = True
        trade.partial_exit_date = current_date
        trade.partial_exit_price = current_option_price
        trade.highest_option_price = current_option_price
        trade.runner_stop_price = current_option_price * (1.0 - float(self.profit_cfg.get("runner_trailing_stop_pct", 0.25)))

        self.risk_state.record_risk_event(
            date=current_date,
            ticker=trade.ticker,
            sector=trade.sector,
            event_type="partial_profit",
            reason="partial_profit",
            trade_id=f"{trade.ticker}:{trade.entry_date}",
            pnl=float(pnl),
            drawdown=None,
            details=f"partial_contracts={partial_contracts}",
        )

    def _close_trade_risk(self, open_trades: dict[str, BacktestTrade], ticker: str, row: pd.Series, reason: str) -> float:
        trade = open_trades.pop(ticker)
        exit_option_price = self._reprice_trade(trade, row)
        remaining = int(trade.remaining_contracts if trade.remaining_contracts is not None else trade.contracts)
        pnl_remaining = (exit_option_price - trade.entry_option_price) * 100 * remaining
        pnl = float(trade.partial_pnl + pnl_remaining)
        basis = trade.entry_option_price * 100 * max(1, trade.contracts)

        trade.exit_date = row["date"]
        trade.exit_underlying_price = float(row["close"])
        trade.exit_option_price = float(exit_option_price)
        trade.exit_reason = reason
        trade.risk_exit_reason = reason
        trade.pnl = pnl
        trade.pnl_pct = float(pnl / basis) if basis > 0 else 0.0
        trade.holding_days = (trade.exit_date - trade.entry_date).days
        self.trades.append(trade)

        self.risk_state.record_trade_close(trade.ticker, trade.sector, trade.exit_date, pnl)
        self._risk_exit_counts[reason] += 1

        if reason in {"runner_trailing_stop", "runner_max_holding", "no_followthrough"}:
            self.risk_state.record_risk_event(
                date=trade.exit_date,
                ticker=trade.ticker,
                sector=trade.sector,
                event_type="runner_exit" if reason.startswith("runner_") else "no_followthrough_exit",
                reason=reason,
                trade_id=f"{trade.ticker}:{trade.entry_date}",
                pnl=pnl,
                drawdown=None,
                details="",
            )

        return pnl

    def _risk_summary_metrics(self, summary: dict) -> dict:
        losses = [float(t.pnl or 0.0) for t in self.trades if (t.pnl or 0.0) < 0]
        wins = [float(t.pnl or 0.0) for t in self.trades if (t.pnl or 0.0) > 0]
        max_dd = float(summary.get("max_drawdown", 0.0))
        total_pnl = float(summary.get("total_pnl", 0.0))

        return {
            "risk_controlled_total_trades": int(summary.get("total_trades", 0)),
            "blocked_trades": self._blocked_trades,
            "pause_events": self._pause_events,
            "no_followthrough_exits": int(self._risk_exit_counts.get("no_followthrough", 0)),
            "stop_loss_exits": int(self._risk_exit_counts.get("stop_loss", 0)),
            "partial_profit_exits": len([t for t in self.trades if t.partial_profit_taken]),
            "runner_exits": int(self._risk_exit_counts.get("runner_trailing_stop", 0) + self._risk_exit_counts.get("runner_max_holding", 0)),
            "ticker_cooldown_blocks": len([e for e in self.risk_state.risk_events if e.get("reason") == "ticker_cooldown"]),
            "sector_limit_blocks": len([e for e in self.risk_state.risk_events if str(e.get("reason", "")).startswith("sector_")]),
            "position_size_reduction_count": self._position_size_reduction_count,
            "max_consecutive_losses": self._max_consecutive_losses(),
            "average_loss_after_controls": (sum(losses) / len(losses)) if losses else 0.0,
            "average_win_after_controls": (sum(wins) / len(wins)) if wins else 0.0,
            "return_to_drawdown_ratio": (total_pnl / abs(max_dd)) if max_dd < 0 else 0.0,
        }

    def _max_consecutive_losses(self) -> int:
        best = 0
        run = 0
        for trade in self.trades:
            if (trade.pnl or 0.0) < 0:
                run += 1
                best = max(best, run)
            else:
                run = 0
        return best

    def _save_outputs(self, summary: dict) -> None:
        output = self.config["output"]
        save_trades_csv(self.trades, output["sector_rotation_risk_backtest_trades_path"])
        save_equity_curve_csv(self.equity_curve, output["sector_rotation_risk_backtest_equity_curve_path"])
        save_summary_json(summary, output["sector_rotation_risk_backtest_summary_path"])
        save_sector_scores(self.sector_scores, output["sector_scores_path"])
        save_weekly_universes(self.weekly_universes, output["weekly_universes_path"])
        if bool(self.risk_reporting_cfg.get("save_risk_events", True)):
            save_risk_events(self.risk_state.risk_events, self.risk_reporting_cfg.get("risk_events_path", "output/risk_events.csv"))

    def _load_sector_etfs(self):
        from src.sector_rotation.sector_config import load_sector_etfs

        return load_sector_etfs()

    def _load_sector_map(self):
        from src.sector_rotation.sector_config import load_sector_map

        return load_sector_map()

    def _metadata_for_ticker(self, active_universe: pd.DataFrame, ticker: str) -> dict:
        rows = active_universe[active_universe["ticker"] == ticker]
        if rows.empty:
            return {}
        return rows.iloc[0].to_dict()

    def _trades_per_sector(self, trades) -> dict:
        out: dict[str, int] = {}
        for trade in trades:
            sector = trade.sector or "Unknown"
            out[sector] = out.get(sector, 0) + 1
        return out

