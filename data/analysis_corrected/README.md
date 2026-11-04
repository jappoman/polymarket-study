# Corrected timestamp study

The BTC 5-minute slug suffix is the closing boundary. For example,
`btc-updown-5m-1791762900` is the round ending at that Unix timestamp, so the
round starts at `suffix - 300`.

All observations in this directory use that correction. The earlier reports
under `data/analysis/` used the suffix as the opening boundary and must not be
used as evidence of profitability.

With the corrected timestamps, the previously selected rule (90 seconds,
follow the previous-minute BTC move, threshold 0.02%, price cap 0.55) loses in
all seven periods under a 4-cent haircut plus 1-cent fee; see
`old_rule_check.json`. A fresh walk-forward grid also fails its three-period
out-of-sample block (`signal_grid_walkforward.json` and
`signal_grid_walkforward_cost01.json`).

The L2 checks use actual best asks from public order-book archives, but the
results are not yet a robust validation: one archive covers only 862 markets
and another only 43, and the apparent edge changes materially between them.
