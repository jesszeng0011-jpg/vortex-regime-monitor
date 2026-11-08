# Vortex Regime Monitor

Public market and regime monitor for GitHub Pages. Each rebuild answers three questions:

1. Which box are we in, and does the market agree?
2. Which leg is closest to its red line?
3. What changed since the prior print, and does that change ADD, HOLD, or CUT?

ADD, HOLD, and CUT are research labels for eligibility. They are not instructions.

This repository has no fund book data. Book P&L is not in this repo. There are no position sizes, venue shares, or private snapshots.

## Run locally

```bash
python3 fetch_data.py
python3 build.py
```

Open `index.html`. It is self-contained: the page does not fetch data at runtime.

`fetch_data.py` uses the User-Agent `VortexRegimeMonitor/1.0`. If a source fails, that series is left missing and the page shows an em dash in grey. The script does not stop the other sources, and it does not read a private file.

`build.py` writes `index.html` and the public snapshots under `data/`. It reads `data/judgment.json` and does not rewrite it.

## Refresh market data

The GitHub Actions workflow **Refresh market data** runs at 07:30 SGT, Monday through Friday. The cron is `30 23 * * 0-4` UTC (Sunday through Thursday). You can also run it by hand: Actions → Refresh market data → Run workflow.

The workflow fetches, rebuilds, and commits `index.html` and `data/` only when something changed. It restores these hand-entered files before the commit, so a run cannot overwrite them:

- `data/judgment.json` — Jess's 8 Nov 2026 probabilities (B 40, D-money 25, F 15, C 10, A 7, E 3). D-demand was not assigned.
- `data/manual.json` — dated rules notes (signed bans, Texas status).
- `data/changelog.json` — the rebuild log.

## Data

Public sources only:

- Yahoo Finance daily prices
- FRED: DGS2, BAMLH0A0HYM2, BAMLC0A0CM, SOFR, RPONTSYD, ICSA, PAYEMS, UNRATE, CPILFESL
- `data/btcusdt_funding.json` — Binance BTCUSDT perpetual funding
- `data/usde.json` — DefiLlama USDe circulating supply

Dec meeting odds stay blank when CME FedWatch does not return a parseable probability. CDS, unsecured bond yields, rent prints, and the loan-auction price stay blank until a real print is loaded. The page does not fill those with a remembered number.
