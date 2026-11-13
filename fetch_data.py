#!/usr/bin/env python3
"""Fetch the public series the December page actually reads.

A failed source is recorded and skipped. This script does not open a
private snapshot.
"""
from __future__ import annotations

import csv
import io
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

SGT = timezone(timedelta(hours=8))
UA = {"User-Agent": "VortexRegimeMonitor/1.0", "Accept": "application/json,text/html,text/csv,*/*"}
CTX = ssl.create_default_context()

TICKERS = "SPY MSFT GOOGL AMZN NVDA SMH CRWV NBIS XLP GLD XLE CL=F BZ=F".split()
FRED = "DGS2 BAMLH0A0HYM2 SOFR ICSA PAYEMS CPILFESL".split()


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
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.5 * (attempt + 1))
    assert last is not None
    raise last


def save(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)


def trim_csv(raw: bytes, keep: int) -> bytes:
    lines = [ln for ln in raw.decode("utf-8", "replace").splitlines() if ln.strip()]
    if len(lines) > keep + 1:
        lines = [lines[0]] + lines[-keep:]
    return ("\n".join(lines) + "\n").encode()


def parse_index_table(html: str) -> list[dict]:
    cells = re.findall(r"<t[dh][^>]*>([^<]+)</t[dh]>", html)
    if "Date" not in cells:
        raise ValueError("index table has no Date column")
    cells = cells[cells.index("Date") + 1 :]
    rows = []
    for label, raw in zip(cells[0::2], cells[1::2]):
        day = datetime.strptime(label.strip(), "%b %d, %Y").date()
        rows.append({"date": day.isoformat(), "value": float(raw)})
    if len(rows) < 5:
        raise ValueError("index table is too short")
    return rows


def parse_treasury_csv(raw: bytes) -> list[tuple[str, str]]:
    text = raw.decode("utf-8", "replace")
    rows = []
    for line in csv.DictReader(io.StringIO(text)):
        stamp = (line.get("Date") or "").strip()
        value = (line.get("2 Yr") or "").strip()
        if not stamp or not value:
            continue
        day = datetime.strptime(stamp, "%m/%d/%Y").date()
        rows.append((day.isoformat(), f"{float(value):.2f}"))
    if len(rows) < 21:
        raise ValueError("treasury yield curve is too short")
    rows.sort()
    return rows


def parse_treasury_xml(raw: bytes) -> list[tuple[str, str]]:
    text = raw.decode("utf-8", "replace")
    rows = []
    for block in re.findall(r"<m:properties>(.*?)</m:properties>", text, flags=re.S):
        stamp = re.search(r"<d:NEW_DATE[^>]*>([^<]+)", block)
        value = re.search(r"<d:BC_2YEAR[^>]*>([^<]+)", block)
        if not stamp or not value:
            continue
        day = datetime.fromisoformat(stamp.group(1)[:10]).date()
        rows.append((day.isoformat(), f"{float(value.group(1)):.2f}"))
    if len(rows) < 21:
        raise ValueError("treasury yield xml is too short")
    rows.sort()
    return rows


def treasury_csv_bytes(rows: list[tuple[str, str]]) -> bytes:
    lines = ["date,value"] + [f"{day},{value}" for day, value in rows]
    return ("\n".join(lines) + "\n").encode()


def fetch_treasury_2y() -> bytes:
    csv_url = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        "daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve"
        "&field_tdr_date_value=2026&page&_format=csv"
    )
    xml_url = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2026"
    )
    try:
        return treasury_csv_bytes(parse_treasury_csv(get(csv_url, timeout=40)))
    except Exception:
        return treasury_csv_bytes(parse_treasury_xml(get(xml_url, timeout=40)))


def fetch_silicon() -> dict:
    pages = {
        "h100": "https://www.silicondata.com/products/silicon-index/h100",
        "b200": "https://www.silicondata.com/products/silicon-index/b200",
    }
    out = {"source": "Silicon Data public index pages", "fetched_at_sgt": now_sgt(), "series": {}}
    for key, url in pages.items():
        html = get(url, timeout=30).decode("utf-8", "replace")
        out["series"][key] = {"url": url, "rows": parse_index_table(html)}
    return out


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
            if not (payload.get("chart") or {}).get("result"):
                raise ValueError("empty Yahoo result")
            save(dest, raw)
            ok.append(f"yahoo {ticker}")
        except Exception as exc:  # noqa: BLE001
            failed.append({"id": f"yahoo {ticker}", "error": str(exc)[:180], "kept_existing": str(dest.exists())})
        time.sleep(0.15)

    for series in FRED:
        dest = DATA / f"f_{series}.csv"
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
        try:
            raw = trim_csv(get(url), 240 if series in ("PAYEMS", "CPILFESL") else 320)
            if raw.decode("utf-8", "replace").count("\n") < 3:
                raise ValueError("short FRED csv")
            save(dest, raw)
            ok.append(f"fred {series}")
        except Exception as exc:  # noqa: BLE001
            failed.append({"id": f"fred {series}", "error": str(exc)[:180], "kept_existing": str(dest.exists())})

    treasury_dest = DATA / "treasury_2y.csv"
    try:
        save(treasury_dest, fetch_treasury_2y())
        ok.append("treasury 2y")
    except Exception as exc:  # noqa: BLE001
        failed.append({"id": "treasury 2y", "error": str(exc)[:180], "kept_existing": str(treasury_dest.exists())})

    silicon_dest = DATA / "silicon_index.json"
    try:
        payload = fetch_silicon()
        save(silicon_dest, json.dumps(payload).encode())
        ok.append("silicon data index")
    except Exception as exc:  # noqa: BLE001
        failed.append({"id": "silicon data index", "error": str(exc)[:180], "kept_existing": str(silicon_dest.exists())})

    status = {"ran_at_sgt": now_sgt(), "user_agent": "VortexRegimeMonitor/1.0", "ok": ok, "failed": failed}
    save(DATA / "fetch_status.json", json.dumps(status, indent=2).encode())
    print(f"fetched {len(ok)} ok, {len(failed)} failed")
    for item in failed:
        print("FAIL", item["id"] + ":", item["error"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
