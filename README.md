# Cross Regime Options Research

Research toolkit for testing a momentum-driven options overlay with free market data and synthetic option pricing.

This project is for research and educational use only. It does not place trades, automate execution, or provide financial advice. Options involve significant risk, including the risk of total premium loss.

## What It Does

- Loads a ticker universe from CSV.
- Calculates short-term momentum from daily price and volume data.
- Scans listed option chains from free Yahoo data.
- Estimates call Greeks with Black-Scholes formulas.
- Ranks call candidates by momentum, delta, theta, liquidity, spread, and days to expiry.
- Runs daily and multi-timeframe synthetic options backtests using Black-Scholes repricing.
- Saves scanner and backtest outputs to CSV/JSON files.

## Research Assumptions

The scanner and backtest use approximations. Yahoo option data can be delayed, incomplete, or revised. Black-Scholes pricing and Greeks are closed-form estimates and may differ from real listed U.S. equity options because of American exercise, dividends, spreads, early exercise risk, liquidity, and volatility surface behavior.

Use results as strategy research inputs, not trade instructions.

## Setup

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Configure Universe

Edit `data/universe.csv`:

```csv
ticker
NVDA
MU
AAPL
AMD
MSFT
QQQ
SMH
```

## Run Scanner

```bash
python -m src.main --mode scan
```

The scanner writes:

- `output/ranked_contracts.csv`

## Run V5 Live Validation Dashboard

V5 exposes the V4.1 sector-rotation and risk-control logic as a read-only live validation workflow. It does not place orders, does not include execution buttons, and keeps `live.allow_order_placement` set to `false`.

Run one live scan:

```bash
python -m src.main --mode live-scan
```

Save one live snapshot:

```bash
python -m src.main --mode live-snapshot
```

Start the local FastAPI dashboard:

```bash
python -m src.main --mode live-dashboard
```

Then open:

```text
http://127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/health
```

V5 files:

- `output/live_signal_snapshot.json`
- `output/live_signal_snapshot.csv`
- `output/live_dashboard_log.jsonl`
- `data/validation_journal.csv`

Yahoo live validation data may be delayed or incomplete. Validate bid/ask, Greeks, spread, liquidity, and chart setup in the broker platform before any manual trade.

## Run Backtests

```bash
python -m src.main --mode backtest --backtest-mode daily --start 2025-01-01 --end 2026-04-26
```

```bash
python -m src.main --mode backtest --backtest-mode multi_timeframe --start 2025-01-01 --end 2026-04-26
```

```bash
python -m src.main --mode backtest --backtest-mode compare --start 2025-01-01 --end 2026-04-26
```

Sector rotation with a weekly dynamic universe:

```bash
python -m src.main --mode backtest --backtest-mode sector_rotation --start 2021-01-01 --end 2026-04-26
```

Compare static daily versus sector rotation:

```bash
python -m src.main --mode backtest --backtest-mode compare_sector --start 2021-01-01 --end 2026-04-26
```

V4.1 sector rotation with risk controls:

```bash
python -m src.main --mode backtest --backtest-mode sector_rotation_risk --start 2021-01-01 --end 2026-04-26
```

Compare V4 sector rotation versus V4.1 risk-controlled sector rotation:

```bash
python -m src.main --mode backtest --backtest-mode compare_risk --start 2021-01-01 --end 2026-04-26
```

Optional capital overrides:

```bash
python -m src.main --mode backtest --backtest-mode compare --capital 10000 --capital-per-trade 1000
```

Sector rotation overrides:

```bash
python -m src.main --mode backtest --backtest-mode sector_rotation --top-sectors 3 --top-stocks-per-sector 5
```

Daily backtest files:

- `output/daily_backtest_trades.csv`
- `output/daily_backtest_equity_curve.csv`
- `output/daily_backtest_summary.json`

Multi-timeframe backtest files:

- `output/mtf_backtest_trades.csv`
- `output/mtf_backtest_equity_curve.csv`
- `output/mtf_backtest_summary.json`

Comparison files:

- `output/comparison_summary.csv`
- `output/comparison_summary.json`

Sector rotation files:

- `output/sector_scores.csv`
- `output/weekly_universes.csv`
- `output/sector_rotation_backtest_trades.csv`
- `output/sector_rotation_backtest_equity_curve.csv`
- `output/sector_rotation_backtest_summary.json`
- `output/sector_comparison_summary.csv`
- `output/sector_comparison_summary.json`

V4.1 risk-control files:

- `output/sector_rotation_risk_backtest_trades.csv`
- `output/sector_rotation_risk_backtest_equity_curve.csv`
- `output/sector_rotation_risk_backtest_summary.json`
- `output/risk_events.csv`
- `output/risk_comparison_summary.csv`
- `output/risk_comparison_summary.json`

The daily backtest preserves the original V2 daily-only logic. The multi-timeframe backtest uses prior completed daily context, latest completed 60-minute context, and completed 5-minute bars for timing. Synthetic option entry is modeled at the next available 5-minute bar open.


## Configuration

Core settings live in `config.yaml`.

Useful sections:

- `scanner`: data provider for scanner mode.
- `strategy`: minimum price and days-to-expiry bounds.
- `momentum`: lookback windows for momentum scoring.
- `options`: option candidate filters.
- `synthetic_options`: Black-Scholes pricing assumptions.
- `entry`: backtest entry rules.
- `exit`: backtest exit rules.
- `daily_filter`: daily trend and regime filters.
- `regime`: market regime symbols and requirements.
- `timeframe_60m`: 60-minute confirmation settings.
- `timeframe_5m`: 5-minute trigger settings.
- `overtrading`: trade frequency controls.
- `sector_rotation`: weekly dynamic-universe settings.
- `sector_scoring`: sector momentum and relative-strength weights.
- `stock_scoring`: within-sector stock ranking weights.
- `risk_controls`: V4.1 entry blocking, stop, pause, cooldown, and sizing controls.
- `profit_management`: V4.1 partial-profit and runner management.
- `risk_reporting`: V4.1 risk event output settings.
- `live`: V5 data provider, refresh, and snapshot settings. `allow_order_placement` must remain `false`.
- `live_options`: V5 live-only option filters and fallback quote validation settings.
- `dashboard`: V5 dashboard display settings.
- `manual_validation`: V5 manual validation journal settings.
- `output`: output file paths.

For private local settings, create `config.local.yaml` or use `.env`; both are ignored by git.

## Tests

```bash
python -m pytest -q
```

## Safety

This repository is positioned as a research and backtesting project. Generated results are informational and should be independently verified before any real-world use.

Sensitive local files such as `.env`, `.env.*`, local config variants, generated reports, virtual environments, caches, and local connection scratch files are excluded by `.gitignore`.

## Azure Deployment Notes

Option A: Azure App Service

- Deploy the FastAPI app and run `python -m src.main --mode live-dashboard`.
- Use Azure App Settings for environment variables.
- Use Key Vault for any future secrets.
- Keep `ALLOW_ORDER_PLACEMENT=false`.

Option B: Azure Container Apps

- Build a container image for the FastAPI app.
- Push it to Azure Container Registry.
- Deploy the image to Azure Container Apps.
- Use Azure Storage for snapshots/logs if persistent storage is needed.

Suggested production environment variables:

```text
APP_ENV=production
DATA_PROVIDER=yahoo
ALLOW_ORDER_PLACEMENT=false
REFRESH_MINUTES=15
```

## Roadmap

- Add richer regime filters using broad market and sector ETFs.
- Add transaction-cost and slippage assumptions.
- Add walk-forward validation.
- Add parameter sensitivity reports.
- Add charted equity curve and drawdown reports.
