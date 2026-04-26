# V2 Build Instructions: Synthetic Options Backtest Engine

## Goal

Build **V2 Backtest Engine** for Cross Regime Alpha Options Overlay.

This version should backtest the options strategy using:

- historical stock prices
- synthetic option pricing using Black-Scholes
- synthetic Greeks
- rule-based contract selection
- rule-based exits
- performance reporting

This avoids requiring paid historical options-chain data while still validating the strategy logic.

Black-Scholes is used here as an approximation for European-style pricing and Greeks; real listed U.S. equity options may differ because of American exercise, dividends, spreads, early exercise risk, and volatility surface behavior.

---

## Repo Structure Additions

Add:

```text
src/
├── backtest/
│   ├── __init__.py
│   ├── engine.py
│   ├── synthetic_options.py
│   ├── trade.py
│   ├── exits.py
│   ├── metrics.py
│   └── report.py
│
├── data_loader.py
└── volatility.py

output/
├── backtest_trades.csv
├── backtest_equity_curve.csv
└── backtest_summary.json
```

---

## V2 Scope

### Included

- Load historical daily price data.
- Calculate momentum signal.
- Generate synthetic call option candidates.
- Price options using Black-Scholes.
- Compute Greeks using Black-Scholes.
- Simulate entry and exit.
- Track trade PnL.
- Produce summary metrics.

### Excluded

- No real historical option-chain data.
- No live IBKR connection.
- No auto-trading.
- No order placement.
- No intraday execution yet.

---

## Update requirements.txt

Add if not already present:

```txt
scipy
pandas
numpy
yfinance
PyYAML
```

---

## Update config.yaml

Add:

```yaml
backtest:
  enabled: true
  start_date: "2025-01-01"
  end_date: "2026-04-26"
  initial_capital: 10000
  capital_per_trade: 1000
  max_positions: 3
  max_holding_days: 5

synthetic_options:
  min_dte: 14
  max_dte: 30
  target_delta: 0.60
  min_delta: 0.50
  max_delta: 0.70
  strike_step: 5
  risk_free_rate: 0.045
  dividend_yield: 0.0
  volatility_lookback_days: 20
  volatility_floor: 0.20
  volatility_ceiling: 1.20

entry:
  min_momentum_score: 0.05
  require_price_above_ema21: true
  require_price_above_sma50: true

exit:
  profit_target_pct: 0.40
  stop_loss_pct: -0.25
  max_holding_days: 5
  exit_on_close_below_ema21: true
```

---

## Data Input

Use daily OHLCV.

Required columns:

```text
date
open
high
low
close
volume
ticker
```

If using Yahoo Finance, normalize columns into lowercase names.

---

## 1. Create data_loader.py

Create `src/data_loader.py`.

Responsibilities:

- Load ticker universe from `data/universe.csv`.
- Download historical OHLCV using yfinance.
- Return one dataframe per ticker.
- Normalize columns.

Required function:

```python
def load_price_history(
    ticker: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    ...
```

Expected dataframe columns:

```text
date, open, high, low, close, volume, ticker
```

Add defensive checks:

- empty dataframe
- missing close
- missing volume
- insufficient history

---

## 2. Create volatility.py

Create `src/volatility.py`.

Purpose:

Estimate annualized historical volatility from daily returns.

Function:

```python
def estimate_historical_volatility(
    prices: pd.Series,
    lookback_days: int = 20,
    floor: float = 0.20,
    ceiling: float = 1.20,
) -> pd.Series:
    ...
```

Formula:

```text
daily_returns = close.pct_change()
rolling_std = daily_returns.rolling(lookback_days).std()
annualized_vol = rolling_std * sqrt(252)
```

Clamp output:

```python
vol = vol.clip(lower=floor, upper=ceiling)
```

---

## 3. Create synthetic_options.py

Create `src/backtest/synthetic_options.py`.

Purpose:

Generate synthetic call contracts and price them using Black-Scholes.

Use existing `black_scholes_call_greeks()` if already created in `src/greeks.py`.

Also add Black-Scholes call price function if missing:

```python
def black_scholes_call_price(
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> float:
    ...
```

Formula:

```python
d1 = (log(s / k) + (r - q + 0.5 * sigma ** 2) * t) / (sigma * sqrt(t))
d2 = d1 - sigma * sqrt(t)

price = (
    s * exp(-q * t) * norm.cdf(d1)
    - k * exp(-r * t) * norm.cdf(d2)
)
```

Create function:

```python
def generate_synthetic_call_candidates(
    ticker: str,
    trade_date: date,
    underlying_price: float,
    volatility: float,
    config: dict,
) -> list[OptionCandidate]:
    ...
```

Logic:

- Create expiries from `min_dte` to `max_dte`.
- Create strikes around current price using `strike_step`.
- Example strike range:
  - 85% to 115% of underlying price.
- Price each call using Black-Scholes.
- Compute Greeks.
- Keep only delta between `min_delta` and `max_delta`.
- Select candidate closest to target delta.
- Return candidates.

In synthetic mode:

- bid = synthetic_price * 0.995
- ask = synthetic_price * 1.005
- mid = synthetic_price
- open_interest = None
- implied_vol = historical volatility estimate
- data_source = `synthetic_backtest`

---

## 4. Create trade.py

Create `src/backtest/trade.py`.

Use dataclass:

```python
from dataclasses import dataclass
from datetime import date


@dataclass
class BacktestTrade:
    ticker: str
    entry_date: date
    exit_date: date | None
    expiry: str
    strike: float
    right: str
    contracts: int
    entry_underlying_price: float
    exit_underlying_price: float | None
    entry_option_price: float
    exit_option_price: float | None
    entry_delta: float
    entry_theta: float
    exit_reason: str | None
    pnl: float | None
    pnl_pct: float | None
    holding_days: int | None
```

---

## 5. Create exits.py

Create `src/backtest/exits.py`.

Function:

```python
def should_exit_trade(
    trade: BacktestTrade,
    current_date,
    current_underlying_price: float,
    current_option_price: float,
    current_close_below_ema21: bool,
    config: dict,
) -> tuple[bool, str]:
    ...
```

Exit rules:

1. Profit target.
2. Stop loss.
3. Max holding days.
4. Optional close below EMA21.

Return:

```python
(True, "profit_target")
(True, "stop_loss")
(True, "max_holding_days")
(True, "close_below_ema21")
(False, "")
```

---

## 6. Create engine.py

Create `src/backtest/engine.py`.

Main class:

```python
class SyntheticOptionsBacktestEngine:
    def __init__(self, config: dict):
        self.config = config
        self.trades = []
        self.equity_curve = []

    def run(self, universe: list[str]) -> dict:
        ...

    def run_ticker(self, ticker: str) -> list[BacktestTrade]:
        ...
```

Backtest flow per ticker:

```text
1. Load historical price data.
2. Calculate indicators:
   - EMA21
   - SMA50
   - SMA200 if enough data
   - momentum score
   - historical volatility
3. Iterate daily from start date after warmup.
4. Check entry rules.
5. If entry valid:
   - generate synthetic call candidates
   - pick best candidate by scoring function
   - calculate number of contracts using capital_per_trade
   - create BacktestTrade
6. For open trade:
   - reprice same option daily with updated underlying, volatility, and remaining DTE
   - apply exit rules
   - close trade if exit condition met
7. Save all closed trades.
```

Important simplification:

- V2 supports one open trade per ticker at a time.
- Do not allow overlapping trades for same ticker.
- Respect global `max_positions`.

---

## 7. Entry Rules

Use existing momentum logic where possible.

Entry condition:

```text
momentum_score >= min_momentum_score
AND close > EMA21 if required
AND close > SMA50 if required
AND no existing open trade for ticker
```

Momentum score should come from existing `calculate_momentum()` function.

If existing function requires a dataframe slice, pass data up to current date only.

---

## 8. Repricing Existing Trade

Each day after entry:

```python
remaining_dte = (expiry_date - current_date).days
t = max(remaining_dte, 1) / 365
current_option_price = black_scholes_call_price(
    s=current_underlying_price,
    k=trade.strike,
    t=t,
    r=risk_free_rate,
    sigma=current_volatility,
    q=dividend_yield,
)
```

If option reaches expiry:

```python
max(0, current_underlying_price - strike)
```

---

## 9. Contract Sizing

Use:

```python
contracts = int(capital_per_trade // (entry_option_price * 100))
```

If contracts < 1, skip trade.

PnL:

```python
pnl = (exit_option_price - entry_option_price) * 100 * contracts
pnl_pct = pnl / (entry_option_price * 100 * contracts)
```

---

## 10. Create metrics.py

Create `src/backtest/metrics.py`.

Function:

```python
def calculate_backtest_metrics(trades: list[BacktestTrade], initial_capital: float) -> dict:
    ...
```

Metrics:

```text
total_trades
winning_trades
losing_trades
win_rate
total_pnl
average_pnl
average_win
average_loss
profit_factor
max_drawdown
average_holding_days
best_trade
worst_trade
```

Profit factor:

```text
gross_profit / abs(gross_loss)
```

Handle divide-by-zero safely.

---

## 11. Create report.py

Create `src/backtest/report.py`.

Functions:

```python
def save_trades_csv(trades, path: str):
    ...

def save_equity_curve_csv(equity_curve, path: str):
    ...

def save_summary_json(summary: dict, path: str):
    ...
```

Save to:

```text
output/backtest_trades.csv
output/backtest_equity_curve.csv
output/backtest_summary.json
```

---

## 12. Add CLI Support

Update `src/main.py` or create `src/backtest_main.py`.

Preferred command:

```bash
python -m src.main --mode backtest --start 2025-01-01 --end 2026-04-26
```

CLI options:

```text
--mode scan/backtest
--start
--end
--capital
--capital-per-trade
```

---

## 13. Output Example

Console should print:

```text
Synthetic Options Backtest Complete

Initial Capital: $10,000
Total Trades: 42
Win Rate: 57.1%
Total PnL: $3,420
Profit Factor: 1.82
Max Drawdown: -$920
Average Holding Days: 3.2

Files saved:
- output/backtest_trades.csv
- output/backtest_equity_curve.csv
- output/backtest_summary.json
```

---

## 14. Tests

Add:

```text
tests/test_black_scholes_price.py
tests/test_backtest_exits.py
tests/test_backtest_metrics.py
```

Test cases:

### Black-Scholes price

- Call price positive.
- Higher underlying price increases call price.
- Higher volatility increases call price.

### Exits

- Profit target triggers.
- Stop loss triggers.
- Max holding days triggers.
- No exit when none triggered.

### Metrics

- Win rate correct.
- Profit factor correct.
- Handles no trades safely.

---

## 15. Safety Rules

Do not add order placement.

Do not call `placeOrder`.

Do not import `MarketOrder` or `LimitOrder`.

This remains research/backtest only.

---

## Acceptance Criteria

The V2 build is complete when:

1. Backtest runs from CLI.
2. It loads universe from `data/universe.csv`.
3. It downloads historical prices.
4. It computes momentum.
5. It estimates historical volatility.
6. It generates synthetic option contracts.
7. It prices options using Black-Scholes.
8. It applies entry and exit rules.
9. It saves trades, equity curve, and summary.
10. It never places trades.
