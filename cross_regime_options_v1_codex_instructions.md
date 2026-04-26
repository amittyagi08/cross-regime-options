# Codex Build Instructions: Cross Regime Alpha Options Overlay V1

## Goal

Build **V1 of Cross Regime Alpha Options Overlay**.

This system should:

1. Calculate momentum for a stock universe.
2. Pull option chains from Interactive Brokers using `ib_insync`.
3. Print option Greeks.
4. Rank the best **call contracts** based on:
   - underlying momentum
   - delta
   - theta
   - liquidity
   - bid/ask spread
   - days to expiry

This V1 must be **scanner-only**.  
Do **not** place live trades.  
Do **not** submit orders.  
Do **not** auto-execute anything.

---

## Repo Name

```text
cross-regime-options-overlay
```

---

## Suggested Repo Structure

```text
cross-regime-options-overlay/
│
├── README.md
├── requirements.txt
├── .env.example
├── config.yaml
│
├── data/
│   └── universe.csv
│
├── output/
│   └── ranked_contracts.csv
│
├── src/
│   ├── main.py
│   ├── config.py
│   ├── momentum.py
│   ├── ibkr_client.py
│   ├── option_filters.py
│   ├── scoring.py
│   ├── models.py
│   └── utils.py
│
└── tests/
    ├── test_momentum.py
    └── test_scoring.py
```

---

## Core Design

The system has three layers:

```text
Universe
  → Regime / momentum calculation
  → IBKR option chain pull
  → Greeks + liquidity filters
  → ranked call contract output
```

---

## V1 Scope

### Included

- Load ticker universe from CSV.
- Pull historical bars for each ticker.
- Calculate simple momentum score.
- Connect to IBKR TWS or Gateway.
- Pull option expiries and strikes.
- Request option market data.
- Extract Greeks if available.
- Filter call contracts.
- Score contracts.
- Print ranked results.
- Save ranked output to CSV.

### Excluded

- No order placement.
- No portfolio sizing engine.
- No automated execution.
- No live alerts.
- No database.
- No web UI.
- No backtesting engine yet.

---

## requirements.txt

Use:

```text
ib_insync
pandas
numpy
python-dotenv
PyYAML
```

Optional:

```text
rich
```

---

## .env.example

```text
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=11
```

Notes:

- `7497` is usually TWS paper trading.
- `7496` is often TWS live trading.
- V1 should default to paper trading port.

---

## config.yaml

```yaml
ibkr:
  host: "127.0.0.1"
  port: 7497
  client_id: 11

strategy:
  min_price: 20
  max_dte: 21
  min_dte: 7

momentum:
  lookback_days: 10
  volume_lookback_days: 10

options:
  option_type: "CALL"
  min_delta: 0.50
  max_delta: 0.70
  max_theta_abs: 0.20
  max_bid_ask_spread_pct: 0.08
  min_open_interest: 100
  strike_window_pct: 0.10

output:
  ranked_contracts_path: "output/ranked_contracts.csv"
```

---

## data/universe.csv

Create example:

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

---

## Data Models

Create `src/models.py`.

Use dataclasses.

```python
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class MomentumSignal:
    ticker: str
    last_price: float
    momentum_score: float
    return_5d: float
    return_10d: float
    volume_ratio: float


@dataclass
class OptionCandidate:
    ticker: str
    expiry: str
    strike: float
    right: str
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    delta: Optional[float]
    gamma: Optional[float]
    theta: Optional[float]
    vega: Optional[float]
    implied_vol: Optional[float]
    open_interest: Optional[int]
    dte: Optional[int]
    momentum_score: float
    liquidity_score: float
    total_score: float
```

---

## Momentum Logic

Create `src/momentum.py`.

Momentum should be simple in V1.

Use historical bars from IBKR.

Calculate:

```text
return_5d = close_today / close_5_days_ago - 1
return_10d = close_today / close_10_days_ago - 1
volume_ratio = latest_volume / average_volume_10d
momentum_score = (return_5d * 0.45) + (return_10d * 0.35) + ((volume_ratio - 1) * 0.20)
```

Add guardrails:

- If insufficient bars, skip ticker.
- If last price below `min_price`, skip ticker.
- If momentum score <= 0, skip ticker.

Function:

```python
def calculate_momentum(ticker: str, bars: pd.DataFrame, config: dict) -> MomentumSignal | None:
    ...
```

---

## IBKR Client

Create `src/ibkr_client.py`.

Use `ib_insync`.

Required functions:

```python
class IBKRClient:
    def __init__(self, host: str, port: int, client_id: int):
        ...

    def connect(self):
        ...

    def disconnect(self):
        ...

    def get_stock_contract(self, ticker: str):
        ...

    def get_historical_bars(self, ticker: str, duration: str = "30 D", bar_size: str = "1 day") -> pd.DataFrame:
        ...

    def get_option_chain_definitions(self, ticker: str):
        ...

    def build_option_contract(self, ticker: str, expiry: str, strike: float, right: str):
        ...

    def get_option_market_data(self, option_contract):
        ...
```

Implementation notes:

- Use `Stock(ticker, "SMART", "USD")`.
- Use `ib.qualifyContracts`.
- Use `reqHistoricalData`.
- Use `reqSecDefOptParams`.
- Use `Option`.
- Use `reqMktData`.
- Use a short sleep after market data request.
- Greeks may appear under:
  - `ticker.modelGreeks`
  - `ticker.bidGreeks`
  - `ticker.askGreeks`
  - `ticker.lastGreeks`

Prefer `modelGreeks` first.

Important:

- Do not place orders.
- Do not import or call `MarketOrder`, `LimitOrder`, or `placeOrder`.

---

## Option Filtering

Create `src/option_filters.py`.

Filter logic:

```text
Only CALL contracts
DTE between min_dte and max_dte
Strike within +/- strike_window_pct of underlying price
Delta between min_delta and max_delta
Abs(theta) <= max_theta_abs
Bid and ask must exist
Bid must be > 0
Ask must be > 0
Spread percentage <= max_bid_ask_spread_pct
Open interest >= min_open_interest, if available
```

Spread percentage:

```text
spread_pct = (ask - bid) / mid
mid = (bid + ask) / 2
```

If Greeks are missing, skip contract in V1.

---

## Scoring Logic

Create `src/scoring.py`.

Use this scoring function:

```text
liquidity_score = 1 - spread_pct
delta_score = 1 - abs(delta - 0.60)
theta_penalty = abs(theta)
iv_penalty = implied_vol * 0.10 if implied_vol exists else 0

total_score =
    momentum_score * 100
    + delta_score * 20
    + liquidity_score * 20
    - theta_penalty * 10
    - iv_penalty
```

Function:

```python
def score_option_candidate(candidate: OptionCandidate) -> OptionCandidate:
    ...
```

Sort descending by `total_score`.

---

## Main Script

Create `src/main.py`.

Flow:

```text
1. Load config.
2. Load universe CSV.
3. Connect to IBKR.
4. For each ticker:
   - Pull historical bars.
   - Calculate momentum signal.
   - If no valid momentum, skip.
   - Pull option chain definitions.
   - Select expiries within DTE range.
   - Select strikes within strike window.
   - Build call contracts.
   - Pull option market data.
   - Extract Greeks.
   - Apply filters.
   - Score candidate.
5. Sort all candidates by total score.
6. Print top contracts.
7. Save output/ranked_contracts.csv.
8. Disconnect IBKR.
```

CLI command:

```bash
python -m src.main
```

---

## Output Format

CSV columns:

```text
ticker,
expiry,
strike,
right,
bid,
ask,
mid,
delta,
gamma,
theta,
vega,
implied_vol,
open_interest,
dte,
momentum_score,
liquidity_score,
total_score
```

Console output example:

```text
Top Ranked Call Contracts

1. NVDA 20260508 510C
   Delta: 0.61
   Theta: -0.08
   Bid/Ask: 12.10 / 12.70
   Momentum Score: 0.082
   Total Score: 33.50

2. MU 20260508 120C
   Delta: 0.58
   Theta: -0.05
   Bid/Ask: 4.20 / 4.45
   Momentum Score: 0.061
   Total Score: 29.80
```

---

## README.md Requirements

README should include:

1. Project purpose.
2. Safety note: scanner only, no auto-trading.
3. Setup steps.
4. IBKR TWS/Gateway setup.
5. How to run.
6. Example output.
7. Future roadmap.

README safety language:

```text
This project is for research and educational use only. V1 does not place trades or provide financial advice. Options involve significant risk, including the risk of total premium loss.
```

---

## Coding Style

Use:

- clear function names
- type hints
- defensive error handling
- comments where needed
- no unnecessary complexity
- no live trading functions

Use logging or simple print statements for V1.

---

## Error Handling

Handle:

- IBKR not connected
- missing historical bars
- missing option chain
- missing Greeks
- missing bid/ask
- empty result set
- invalid config
- missing universe file

The script should not crash on one bad ticker.  
It should continue scanning the remaining universe.

---

## Tests

Create basic tests.

### tests/test_momentum.py

Test:

- positive momentum
- negative momentum
- insufficient data

### tests/test_scoring.py

Test:

- good delta gets higher score
- wide spread reduces score
- higher theta reduces score

---

## Future Roadmap

Do not build now, but mention in README:

### V2

- Add intraday 5-minute momentum trigger.
- Add VWAP reclaim logic.
- Add regime filter using SPY / QQQ / SMH.
- Add alerting to email or Slack.
- Add backtest using historical option data.

### V3

- Portfolio sizing engine.
- Trade journal.
- Broker-neutral adapter layer.
- Dashboard.
- Risk engine.

---

## Important Final Instruction

Build a clean V1 repo from these instructions.

Again:

- Scanner only.
- No order placement.
- No financial advice language.
- Focus on momentum + Greeks + liquidity ranking.
