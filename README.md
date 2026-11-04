# Polymarket BTC 5m study

Pipeline for studying the relationship between the state of a Polymarket
Bitcoin Up/Down 5-minute market at time `X` and its final outcome.

The collector uses public Gamma and CLOB endpoints; no account, VPN, login,
email code, or trading permission is required. It stores raw API responses so
the analysis can be reproduced when Polymarket changes its market rules.

## Quick start

```bash
python -m polymarket_study.collect \
  --start-date 2026-09-01 \
  --end-date 2026-09-02 \
  --out data/raw

python -m polymarket_study.analyze \
  --input data/raw \
  --output data/analysis
```

The first command downloads market metadata and the historical UP/DOWN price
series. The analysis samples configurable observation times after market
start, estimates conditional win rates by price bucket, and backtests fixed
stake and Kelly-fraction strategies with conservative executable prices.

Use a small date range first. The full series contains many 5-minute markets
and can require a substantial number of public API requests.

## Important methodology

The final label is taken from the resolved market metadata, not reconstructed
from Binance/Coinbase. The resolution description is also saved per market,
because the BTC settlement rule has changed over time. A price-history point
is a traded-price observation; it is not automatically an executable ask. The
first version therefore reports both a trade-price backtest and a conservative
spread haircut, and does not claim live profitability.
