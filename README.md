# Vortex Regime Monitor

Public page for the 8 Nov 2026 December memo. It shows the box, the action, six legs, the December checklist, the next 14 days, the prices those rules use, and what moved versus the stored snapshot.

This repository does not carry fund-book figures.

## Run locally

```bash
python3 fetch_data.py
python3 build.py
```

Open `index.html`. The page does not fetch data when you open it.

`fetch_data.py` keeps going when a source fails. A missing print stays blank on the page.

## Refresh

**Refresh market data** runs at 07:30 SGT, Monday through Friday (`30 23 * * 0-4` UTC), and can also be started by hand.

**Refresh after a catalyst** is a separate manual run, for rebuilding after a print without waiting for the next morning.

Both restore these files before the commit:

- `data/judgment.json` — Jess's 8 Nov 2026 weights
- `data/manual.json` — dated hand entries
- `data/changelog.json` — the stored log

The refresh does not invent lights, weights, or fund-book figures.
