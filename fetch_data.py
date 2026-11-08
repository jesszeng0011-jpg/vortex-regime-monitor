#!/usr/bin/env python3
"""Fetch public market inputs for the Vortex regime monitor.

This script reads and writes public series only. It does not look for a
private snapshot, and a missing source does not stop the others.
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

SGT = timezone(timedelta(hours=8))
UA = {"User-Agent": "VortexRegimeMonitor/1.0", "Accept": "application/json,text/csv,*/*"}
CTX = ssl.create_default_context()

TICKERS = (
    "SPY QQQ IWM SMH XLE XLP TLT "
    "NVDA MSFT AMZN GOOGL META "
    "EQIX DLR VST CIFR HUT IREN WULF RIOT "
    "CRWV NBIS MSTR STRC CAT GEV APLD CORZ SPCX "
    "^NDX BTC-USD CL=F BZ=F"
).split()

# ICSA is weekly. The rest of this list is daily. Monthly series follow.
FRED_DAILY = "DGS2 BAMLH0A0HYM2 BAMLC0A0CM SOFR RPONTSYD ICSA".split()
FRED_MONTHLY = "PAYEMS UNRATE CPILFESL".split()


def yahoo_name(ticker: str) -> str:
    return "y_" + ticker.replace("^", "%5E").replace("=", "%3D") + ".json"


def now_sgt() -> str:
    return datetime.now(SGT).replace(microsecond=0).isoformat()


def get(url: str, timeout: int = 45, retries: int = 2) -> bytes:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 — keep going source by source
            last = exc
            time.sleep(0.6 * (attempt + 1))
    assert last is not None
    raise last


def save(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)


def trim_csv(raw: bytes, keep: int) -> bytes:
    text = raw.decode("utf-8", "replace").strip()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= keep + 1:
        return (text + "\n").encode()
    kept = [lines[0]] + lines[-(keep):]
    return ("\n".join(kept) + "\n").encode()


def slim_usde(payload: dict) -> dict:
    tokens = []
    for row in (payload.get("tokens") or [])[-120:]:
        circulating = row.get("circulating") or {}
        value = circulating.get("peggedUSD")
        if row.get("date") is None or value is None:
            continue
        tokens.append({"date": row.get("date"), "circulating_usd": value})
    if len(tokens) < 2:
        raise ValueError("USDe series is too short")
    return {
        "symbol": "USDe",
        "source": "DefiLlama stablecoin 146",
        "tokens": tokens,
    }


def main() -> int:
    ok: list[str] = []
    failed: list[dict[str, str]] = []

    for ticker in TICKERS:
        dest = DATA / yahoo_name(ticker)
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            + urllib.parse.quote(ticker)
            + "?range=6mo&interval=1d&includeAdjustedClose=true"
        )
        try:
            raw = get(url)
            payload = json.loads(raw)
            result = (payload.get("chart") or {}).get("result")
            if not result:
                raise ValueError("empty Yahoo result")
            save(dest, raw)
            ok.append(f"yahoo {ticker}")
        except Exception as exc:  # noqa: BLE001
            failed.append({
                "id": f"yahoo {ticker}",
                "error": str(exc),
                "kept_existing": str(dest.exists()),
            })
        time.sleep(0.15)

    for series in FRED_DAILY + FRED_MONTHLY:
        dest = DATA / f"f_{series}.csv"
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
        try:
            raw = get(url)
            keep = 180 if series in FRED_MONTHLY else 320
            raw = trim_csv(raw, keep)
            lines = raw.decode("utf-8", "replace").strip().splitlines()
            if len(lines) < 3:
                raise ValueError("short FRED csv")
            save(dest, raw)
            ok.append(f"fred {series}")
        except Exception as exc:  # noqa: BLE001
            failed.append({
                "id": f"fred {series}",
                "error": str(exc),
                "kept_existing": str(dest.exists()),
            })

    funding_dest = DATA / "btcusdt_funding.json"
    try:
        raw = get("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=100")
        payload = json.loads(raw)
        if not isinstance(payload, list) or not payload:
            raise ValueError("empty funding history")
        save(funding_dest, json.dumps(payload).encode())
        ok.append("binance btcusdt funding")
    except Exception as exc:  # noqa: BLE001
        failed.append({
            "id": "binance btcusdt funding",
            "error": str(exc),
            "kept_existing": str(funding_dest.exists()),
        })

    usde_dest = DATA / "usde.json"
    try:
        raw = get("https://stablecoins.llama.fi/stablecoin/146", timeout=60)
        payload = json.loads(raw)
        slim = slim_usde(payload)
        save(usde_dest, json.dumps(slim).encode())
        ok.append("defillama usde")
    except Exception as exc:  # noqa: BLE001
        failed.append({
            "id": "defillama usde",
            "error": str(exc),
            "kept_existing": str(usde_dest.exists()),
        })

    # CME FedWatch is a scripted page. If no parseable probability comes back,
    # leave the series missing so the page shows an em dash.
    hike_dest = DATA / "dec_hike_odds.json"
    hike_urls = [
        "https://www.cmegroup.com/CmeWS/mvc/quotes/future/305/G",
    ]
    hike_error = "no parseable Dec meeting probability"
    for url in hike_urls:
        try:
            raw = get(url, timeout=20, retries=0)
            parsed = json.loads(raw)
            if not isinstance(parsed, (dict, list)):
                raise ValueError("unexpected payload")
            hike_error = "payload had no identified Dec hike probability"
        except Exception as exc:  # noqa: BLE001
            hike_error = str(exc)
    if hike_dest.exists():
        hike_dest.unlink()
    failed.append({
        "id": "cme dec hike odds",
        "error": hike_error,
        "kept_existing": "False",
    })

    status = {
        "ran_at_sgt": now_sgt(),
        "user_agent": "VortexRegimeMonitor/1.0",
        "ok": ok,
        "failed": failed,
    }
    save(DATA / "fetch_status.json", json.dumps(status, indent=2).encode())
    print(f"fetched {len(ok)} ok, {len(failed)} failed")
    for item in failed:
        print("FAIL", item["id"] + ":", item["error"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
