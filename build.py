#!/usr/bin/env python3
"""Build a self-contained Vortex Regime Monitor page from public series.

Conclusions (market-implied box, leg lights, ADD/HOLD/CUT, closest red line,
and the three largest moves) are computed here. The page does not fetch.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "index.html"

SGT = ZoneInfo("Asia/Singapore")
NY = ZoneInfo("America/New_York")
DASH = "\u2014"

HOLIDAYS = {
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
    date(2027, 1, 1),
    date(2027, 1, 18),
}

BOX_TITLE = {
    "A": "Cooling expansion",
    "B": "Sticky but viable",
    "C": "Inflation squeeze",
    "D": "AI retrenchment",
    "D_money": "AI retrenchment, money",
    "D_demand": "AI retrenchment, demand",
    "E": "Broad break",
    "F": "Blocked buildout",
}
CHECK_ORDER = ["A", "C", "D", "E", "F"]

TICKERS = (
    "SPY QQQ IWM SMH XLE XLP TLT NVDA MSFT AMZN GOOGL META EQIX DLR VST "
    "CIFR HUT IREN WULF RIOT CRWV NBIS MSTR STRC CAT GEV APLD CORZ SPCX "
    "^NDX BTC-USD CL=F BZ=F"
).split()


def esc(value) -> str:
    return escape(str(value), quote=True)


def round_tenth(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in HOLIDAYS


def prev_trading_day(day: date) -> date:
    day = day - timedelta(days=1)
    while not is_trading_day(day):
        day = day - timedelta(days=1)
    return day


def latest_completed_session(now: datetime) -> date:
    ny = now.astimezone(NY)
    day = ny.date()
    close = datetime(day.year, day.month, day.day, 16, 0, tzinfo=NY)
    if is_trading_day(day) and ny >= close:
        return day
    return prev_trading_day(day)


def trading_lag(obs: date, latest: date) -> int:
    if obs >= latest:
        return 0
    count = 0
    day = obs
    while day < latest:
        day += timedelta(days=1)
        if is_trading_day(day):
            count += 1
    return count


def weekly_stale(obs: date, now: datetime) -> bool:
    return (now.astimezone(SGT).date() - obs).days > 8


def _add_month(year: int, month: int, step: int = 1) -> tuple[int, int]:
    month += step
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    return year, month


def first_friday(year: int, month: int) -> date:
    day = date(year, month, 1)
    while day.weekday() != 4:
        day += timedelta(days=1)
    return day


def release_dt(kind: str, year: int, month: int) -> datetime:
    """When the print for a data-month is due, in SGT."""
    if kind == "cpi" and (year, month) == (2026, 10):
        return datetime(2026, 11, 10, 21, 30, tzinfo=SGT)
    if kind == "cpi" and (year, month) == (2026, 11):
        return datetime(2026, 12, 10, 21, 30, tzinfo=SGT)
    if kind == "jobs" and (year, month) == (2026, 11):
        return datetime(2026, 12, 4, 21, 30, tzinfo=SGT)
    ny, nm = _add_month(year, month, 1)
    if kind == "jobs":
        day = first_friday(ny, nm)
        return datetime(day.year, day.month, day.day, 21, 30, tzinfo=SGT)
    # CPI fallback when the brief does not name the morning: the 12th, 21:30 SGT.
    return datetime(ny, nm, 12, 21, 30, tzinfo=SGT)


def latest_released_month(now: datetime, kind: str) -> date:
    year, month = now.astimezone(SGT).year, now.astimezone(SGT).month
    for _ in range(36):
        if release_dt(kind, year, month) <= now:
            return date(year, month, 1)
        year, month = _add_month(year, month, -1)
    return date(year, month, 1)


def monthly_stale(obs: date, now: datetime, kind: str) -> bool:
    expected = latest_released_month(now, kind)
    return (obs.year, obs.month) < (expected.year, expected.month)


def manual_stale(asof: datetime, now: datetime) -> bool:
    latest = latest_completed_session(now)
    asof_day = asof.astimezone(SGT).date()
    if asof_day >= latest:
        return False
    return trading_lag(asof_day, latest) > 1


def fmt_dt(moment: datetime) -> str:
    moment = moment.astimezone(SGT)
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{moment.day} {months[moment.month - 1]} {moment.year}, {moment.hour:02d}:{moment.minute:02d} SGT"


def fmt_day(day: date) -> str:
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{day.day} {months[day.month - 1]} {day.year}"


def fmt_px(value: float, ticker: str) -> str:
    if ticker in ("BTC-USD", "^NDX"):
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def fmt_pct(frac: float) -> str:
    pct = frac * 100
    digits = 1 if abs(pct) >= 0.15 else 2
    return f"{pct:+.{digits}f}%"


def fmt_pp(frac: float) -> str:
    pct = frac * 100
    digits = 1 if abs(pct) >= 0.15 else 2
    return f"{pct:+.{digits}f}pp"


def fmt_bp(change_pp: float) -> str:
    bp = change_pp * 100
    if abs(bp) >= 9.5:
        return f"{bp:+.0f}bp"
    return f"{bp:+.1f}bp"


def yahoo_name(ticker: str) -> str:
    return "y_" + ticker.replace("^", "%5E").replace("=", "%3D") + ".json"


def load_json(path: Path):
    return json.loads(path.read_text())


def load_fred(path: Path) -> list[tuple[date, float]]:
    rows = []
    lines = path.read_text().splitlines()
    for line in lines[1:]:
        if "," not in line:
            continue
        day, raw = line.split(",", 1)
        if raw in ("", "."):
            continue
        rows.append((date.fromisoformat(day), float(raw)))
    return rows


def load_fred_decimal(path: Path) -> list[tuple[date, Decimal]]:
    rows = []
    for line in path.read_text().splitlines()[1:]:
        if "," not in line:
            continue
        day, raw = line.split(",", 1)
        if raw in ("", "."):
            continue
        rows.append((date.fromisoformat(day), Decimal(raw)))
    return rows


def load_yahoo(path: Path) -> dict | None:
    try:
        result = load_json(path)["chart"]["result"][0]
    except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
    meta = result.get("meta") or {}
    indicators = result.get("indicators") or {}
    adj = (indicators.get("adjclose") or [{}])[0].get("adjclose")
    close = (indicators.get("quote") or [{}])[0].get("close")
    series = adj if adj and any(value is not None for value in adj) else close
    if not series:
        return None
    dedup: dict[date, dict] = {}
    for stamp, value in zip(result.get("timestamp") or [], series):
        if stamp is None or value is None:
            continue
        session = datetime.fromtimestamp(int(stamp), NY).date()
        dedup[session] = {"session": session, "close": float(value), "ts": int(stamp)}
    bars = [dedup[key] for key in sorted(dedup)]
    if not bars:
        return None
    return {
        "symbol": meta.get("symbol") or path.name,
        "high52": meta.get("fiftyTwoWeekHigh"),
        "bars": bars,
        "source": "Yahoo Finance",
    }


def load_usde(path: Path) -> list[dict]:
    payload = load_json(path)
    points = []
    for row in payload.get("tokens") or []:
        if "circulating_usd" in row:
            value = row["circulating_usd"]
        else:
            value = (row.get("circulating") or {}).get("peggedUSD")
        if row.get("date") is None or value is None:
            continue
        points.append({"ts": int(row["date"]), "value": float(value)})
    points.sort(key=lambda item: item["ts"])
    return points


def load_funding(path: Path) -> list[dict]:
    rows = []
    for row in load_json(path):
        rows.append({
            "ts": int(row["fundingTime"]) // 1000,
            "rate": float(row["fundingRate"]),
        })
    rows.sort(key=lambda item: item["ts"])
    return rows


def shifted(rows, offset: int):
    if offset <= 0:
        return rows
    if len(rows) <= offset:
        return rows[:0]
    return rows[:-offset]


def tip(text: str, detail: str, kind: str = "") -> str:
    classes = "tip"
    if text == DASH:
        classes += " na"
    elif kind:
        classes += " " + kind
    clean = " ".join(str(detail).split())
    return f'<span class="{classes}" tabindex="0" data-tip="{esc(clean)}">{esc(text)}</span>'


def spark(values: list[float], width: int = 78, height: int = 22) -> str:
    vals = [value for value in values if value is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    points = []
    last = len(vals) - 1
    for index, value in enumerate(vals):
        x = 1 + index * (width - 2) / last
        y = height - 1 - (value - lo) / span * (height - 2)
        points.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'aria-hidden="true"><polyline fill="none" stroke="currentColor" stroke-width="1.25" '
        f'points="{" ".join(points)}"/></svg>'
    )


def meter(value: float, lo: float, hi: float, caption: str, yellow=None, red=None, status: str = "") -> str:
    span = hi - lo or 1

    def pct(level: float) -> float:
        return max(0.0, min(100.0, (level - lo) / span * 100))

    marks = []
    if yellow is not None:
        marks.append(f'<i class="mark y" style="left:{pct(yellow):.2f}%"></i>')
    if red is not None:
        marks.append(f'<i class="mark r" style="left:{pct(red):.2f}%"></i>')
    dot_kind = {"yellow": "warn", "red": "bad", "stale": "grey", "missing": "grey"}.get(status, "")
    dot = f'<i class="dot {dot_kind}" style="left:{pct(value):.2f}%"></i>'
    return (
        f'<div class="meter"><div class="track">{"".join(marks)}{dot}</div>'
        f'<div class="scale">{esc(caption)}</div></div>'
    )


def implied_box(states: list[tuple[str, str]]) -> str:
    scores = {box: 0 for box in CHECK_ORDER}
    for box, state in states:
        if state == "lit" and box in scores:
            scores[box] += 1
    best = max(scores.values()) if scores else 0
    if best == 0:
        return "B"
    winners = [box for box in CHECK_ORDER if scores[box] == best]
    if len(winners) == 1:
        return winners[0]
    return "tie:" + "/".join(winners)


def disagrees(current: str, implied: str) -> bool:
    if implied.startswith("tie:"):
        return current not in implied.split(":", 1)[1].split("/")
    return current != implied


def check_tally(checks: list[dict]) -> str:
    buckets = {box: 0 for box in CHECK_ORDER}
    for check in checks:
        if check["state"] == "lit" and check["box"] in buckets:
            buckets[check["box"]] += 1
    return " · ".join(f"{box} {buckets[box]} lit" for box in CHECK_ORDER)


def implied_label(code: str) -> str:
    if code.startswith("tie:"):
        return "Tie " + " / ".join(code.split(":", 1)[1].split("/"))
    return code


def leg_light(flags: list[tuple[str, bool]], required_missing: bool) -> str:
    keys = []
    for key, deteriorating in flags:
        if deteriorating and key not in keys:
            keys.append(key)
    if keys:
        return "red" if len(keys) >= 2 else "yellow"
    if required_missing:
        return "missing"
    return "green"


def action_of(lights: list[tuple[str, str]]) -> tuple[str, list[str], list[str]]:
    deteriorating = [name for name, light in lights if light in ("yellow", "red")]
    grey = [name for name, light in lights if light in ("stale", "missing")]
    if len(deteriorating) >= 2:
        return "CUT", deteriorating, grey
    if len(deteriorating) == 1 or grey:
        return "HOLD", deteriorating, grey
    return "ADD", deteriorating, grey


def pick_closest(candidates: list[dict]) -> dict | None:
    usable = [item for item in candidates if item.get("frac") is not None]
    if not usable:
        return None
    return min(usable, key=lambda item: (item["frac"], item["name"]))


def pearson(xs: list[float], ys: list[float]) -> float | None:
    count = len(xs)
    if count < 2 or count != len(ys):
        return None
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    dy = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def self_check() -> None:
    now = datetime(2026, 11, 8, 22, 0, tzinfo=SGT)
    assert latest_completed_session(now) == date(2026, 11, 6)
    assert trading_lag(date(2026, 11, 6), date(2026, 11, 6)) == 0
    assert trading_lag(date(2026, 11, 5), date(2026, 11, 6)) == 1
    assert trading_lag(date(2026, 11, 4), date(2026, 11, 6)) == 2
    assert weekly_stale(date(2026, 10, 31), now) is False
    assert weekly_stale(date(2026, 10, 31), datetime(2026, 11, 9, 12, tzinfo=SGT)) is True
    assert latest_released_month(now, "cpi") == date(2026, 9, 1)
    assert latest_released_month(now, "jobs") == date(2026, 10, 1)
    assert monthly_stale(date(2026, 9, 1), now, "cpi") is False
    assert monthly_stale(date(2026, 8, 1), now, "cpi") is True
    assert manual_stale(datetime(2026, 11, 8, 21, 0, tzinfo=SGT), now) is False
    aug = (Decimal("337.765") / Decimal("336.789") - 1) * 100
    sep = (Decimal("338.896") / Decimal("337.765") - 1) * 100
    assert round_tenth(aug) == Decimal("0.3")
    assert round_tenth(sep) == Decimal("0.3")
    assert implied_box([("A", "unlit"), ("C", "stale")]) == "B"
    assert implied_box([("A", "lit"), ("A", "lit"), ("C", "lit")]) == "A"
    assert implied_box([("A", "lit"), ("C", "lit")]) == "tie:A/C"
    assert disagrees("B", "A") is True
    assert disagrees("B", "B") is False
    assert disagrees("A", "tie:A/C") is False
    assert leg_light([("oil", True), ("oil", True)], False) == "yellow"
    assert leg_light([("oil", True), ("core", True)], False) == "red"
    assert leg_light([("oil", False)], True) == "missing"
    assert action_of([("Inflation", "red"), ("Growth", "green")])[0] == "HOLD"
    assert action_of([("Inflation", "yellow"), ("Growth", "yellow")])[0] == "CUT"
    assert action_of([("Inflation", "green"), ("AI money", "missing")])[0] == "HOLD"
    assert action_of([("Inflation", "green"), ("Growth", "green")])[0] == "ADD"
    chosen = pick_closest([
        {"name": "Brent", "frac": 0.02},
        {"name": "Claims", "frac": 0.2},
        {"name": "Core", "frac": None},
    ])
    assert chosen is not None and chosen["name"] == "Brent"
    assert pick_closest([{"name": "Core", "frac": -0.01}, {"name": "Brent", "frac": 0.02}])["name"] == "Core"


def failure_note(status: dict | None, needle: str) -> str:
    if not status:
        return ""
    for item in status.get("failed") or []:
        if needle in str(item.get("id", "")):
            err = " ".join(str(item.get("error", "")).split())[:160]
            return f" Latest refresh failed ({err})."
    return ""


def series_stale(bars: list[dict], now: datetime, crypto: bool = False) -> bool:
    if not bars:
        return True
    if crypto:
        last = datetime.fromtimestamp(bars[-1]["ts"], SGT).date()
        return (now.astimezone(SGT).date() - last).days > 1
    latest = latest_completed_session(now)
    return trading_lag(bars[-1]["session"], latest) > 1


def fred_stale(rows, now: datetime, weekly: bool = False) -> bool:
    if not rows:
        return True
    if weekly:
        return weekly_stale(rows[-1][0], now)
    return trading_lag(rows[-1][0], latest_completed_session(now)) > 1


def window_returns(quotes: dict, tickers: list[str], n: int = 20, offset: int = 0):
    maps = []
    for ticker in tickers:
        series = quotes.get(ticker)
        if not series:
            return None
        bars = shifted(series["bars"], offset)
        maps.append({bar["session"]: bar["close"] for bar in bars})
    dates = set(maps[0])
    for item in maps[1:]:
        dates &= set(item)
    ordered = sorted(dates)
    if len(ordered) < n + 1:
        return None
    start, end = ordered[-(n + 1)], ordered[-1]
    out = {}
    for ticker, mapping in zip(tickers, maps):
        if not mapping[start]:
            return None
        out[ticker] = mapping[end] / mapping[start] - 1
    return {"start": start, "end": end, "ret": out}


def aligned_returns(quotes: dict, left: str, right: str, offset: int = 0):
    if left not in quotes or right not in quotes:
        return None
    left_bars = shifted(quotes[left]["bars"], offset)
    right_bars = shifted(quotes[right]["bars"], offset)
    left_map = {bar["session"]: bar["close"] for bar in left_bars}
    right_map = {bar["session"]: bar["close"] for bar in right_bars}
    dates = sorted(set(left_map) & set(right_map))
    xs, ys = [], []
    for older, newer in zip(dates, dates[1:]):
        if left_map[older] and right_map[older]:
            xs.append(left_map[newer] / left_map[older] - 1)
            ys.append(right_map[newer] / right_map[older] - 1)
    return xs, ys, dates


def funding_is_stale(last_ts: int, now: datetime) -> bool:
    last = datetime.fromtimestamp(last_ts, timezone.utc)
    utc = now.astimezone(timezone.utc)
    slot_hour = (utc.hour // 8) * 8
    slot = utc.replace(hour=slot_hour, minute=0, second=0, microsecond=0)
    if (utc - slot).total_seconds() < 15 * 60:
        slot = slot - timedelta(hours=8)
    return last < slot - timedelta(minutes=5)


def build_checks(bundle: dict, offset: int, apply_stale: bool) -> list[dict]:
    quotes = bundle["quotes"]
    now = bundle["now"]
    checks = []

    def add(box: str, name: str, state: str, detail: str, source: str) -> None:
        checks.append({
            "box": box,
            "name": name,
            "state": state,
            "detail": detail,
            "source": source,
        })

    def stale_or(tickers: list[str], computed_missing: bool) -> bool:
        if computed_missing:
            return True
        if not apply_stale:
            return False
        for ticker in tickers:
            series = quotes.get(ticker)
            crypto = ticker == "BTC-USD"
            if series is None or series_stale(series["bars"], now, crypto=crypto):
                return True
        return False

    growth = window_returns(quotes, ["SMH", "IWM", "SPY"], 20, offset)
    if stale_or(["SMH", "IWM", "SPY"], growth is None):
        add("A", "SMH and IWM versus SPY", "stale",
            "Both must beat SPY by more than 3pp over 20 trading days. A required price is missing or old.",
            "Yahoo Finance. Equal session window. Threshold is a starting proposal.")
    else:
        smh = growth["ret"]["SMH"] - growth["ret"]["SPY"]
        iwm = growth["ret"]["IWM"] - growth["ret"]["SPY"]
        lit = smh > 0.03 and iwm > 0.03
        add("A", "SMH and IWM versus SPY", "lit" if lit else "unlit",
            f"SMH {fmt_pp(smh)}, IWM {fmt_pp(iwm)} versus SPY. Line: both above +3pp. "
            f"Window {fmt_day(growth['start'])} to {fmt_day(growth['end'])}.",
            "Yahoo Finance adjusted or regular close. Excess return, not a price difference.")

    dgs = shifted(bundle["dgs2"], offset)
    dgs_bad = len(dgs) < 21 or (apply_stale and fred_stale(bundle["dgs2"], now))
    if dgs_bad:
        add("A", "2-year yield", "stale",
            "Line: the 2-year yield falls more than 25bp over 20 trading-day observations. The series is missing or old.",
            "FRED DGS2. Not a Treasury bill or 10-year yield.")
    else:
        change = dgs[-1][1] - dgs[-21][1]
        lit = change < -0.25
        add("A", "2-year yield", "lit" if lit else "unlit",
            f"Change {fmt_bp(change)} from {dgs[-21][1]:.2f}% ({fmt_day(dgs[-21][0])}) "
            f"to {dgs[-1][1]:.2f}% ({fmt_day(dgs[-1][0])}). Line: a fall of more than 25bp.",
            "FRED DGS2, percent. 20 observations back, not a calendar guess.")

    energy = window_returns(quotes, ["XLE", "QQQ"], 20, offset)
    if stale_or(["XLE", "QQQ"], energy is None):
        add("C", "XLE versus QQQ", "stale",
            "Line: XLE beats QQQ by more than 5pp over 20 trading days. A required price is missing or old.",
            "Yahoo Finance.")
    else:
        excess = energy["ret"]["XLE"] - energy["ret"]["QQQ"]
        add("C", "XLE versus QQQ", "lit" if excess > 0.05 else "unlit",
            f"XLE excess versus QQQ {fmt_pp(excess)}. Line: more than +5pp. "
            f"Window {fmt_day(energy['start'])} to {fmt_day(energy['end'])}.",
            "Yahoo Finance. Relative return, not a price difference.")

    corr_pair = aligned_returns(quotes, "SPY", "TLT", offset)
    corr_stale = (
        corr_pair is None
        or len(corr_pair[0]) < 60
        or stale_or(["SPY", "TLT"], False)
    )
    if corr_stale:
        add("C", "SPY and TLT correlation", "stale",
            "Line: 60-day correlation of daily simple returns above +0.3. The pair is missing, short, or old.",
            "Yahoo Finance. Sixty paired daily simple returns.")
    else:
        xs, ys, dates = corr_pair
        corr = pearson(xs[-60:], ys[-60:])
        if corr is None:
            add("C", "SPY and TLT correlation", "stale",
                "The 60-day correlation could not be computed.",
                "Yahoo Finance.")
        else:
            add("C", "SPY and TLT correlation", "lit" if corr > 0.3 else "unlit",
                f"Correlation {corr:+.2f} over the last 60 paired daily simple returns, "
                f"ending {fmt_day(dates[-1])}. Line: above +0.3.",
                "Yahoo Finance closes. Window is 60 returns, which needs 61 shared sessions.")

    d_names = ["XLP", "SPY", "NVDA", "SMH", "MSFT", "AMZN", "GOOGL", "META"]
    demand = window_returns(quotes, d_names, 20, offset)
    if stale_or(d_names, demand is None):
        add("D", "Defensive tape and supplier lag", "stale",
            "Line: XLP beats SPY by more than 3pp AND suppliers lag spenders by more than 5pp. An input is missing or old.",
            "Suppliers: equal-weight NVDA and SMH. Spenders: equal-weight MSFT, AMZN, GOOGL, META.")
    else:
        defensive = demand["ret"]["XLP"] - demand["ret"]["SPY"]
        suppliers = (demand["ret"]["NVDA"] + demand["ret"]["SMH"]) / 2
        spenders = sum(demand["ret"][name] for name in ("MSFT", "AMZN", "GOOGL", "META")) / 4
        lag = spenders - suppliers
        lit = defensive > 0.03 and lag > 0.05
        add("D", "Defensive tape and supplier lag", "lit" if lit else "unlit",
            f"XLP versus SPY {fmt_pp(defensive)}. Spenders minus suppliers {fmt_pp(lag)}. "
            f"Line: XLP excess above +3pp and supplier lag above 5pp. "
            f"Window {fmt_day(demand['start'])} to {fmt_day(demand['end'])}.",
            "Equal-weight 20-session simple returns. A negative supplier gap means suppliers lagged. Not a price difference.")

    add("D", "CRWV unsecured yield", "stale",
        "Line: the CRWV unsecured bond yield rises 150bp. No public print is loaded, so the check does not count.",
        "No live unsecured 2031 or 2032 yield was fetched. Nothing is filled in from memory.")

    hy = shifted(bundle["hy"], offset)
    hy_bad = len(hy) < 21 or (apply_stale and fred_stale(bundle["hy"], now))
    if hy_bad:
        add("E", "HY OAS widening", "stale",
            "Line: HY OAS widens more than 50bp over 20 observations. The series is missing or old.",
            "FRED BAMLH0A0HYM2, percent.")
    else:
        change = hy[-1][1] - hy[-21][1]
        add("E", "HY OAS widening", "lit" if change > 0.50 else "unlit",
            f"Change {fmt_bp(change)} from {hy[-21][1]:.2f}% ({fmt_day(hy[-21][0])}) "
            f"to {hy[-1][1]:.2f}% ({fmt_day(hy[-1][0])}). Line: a widening of more than 50bp.",
            "FRED BAMLH0A0HYM2. 20 observations.")

    stress = window_returns(quotes, ["TLT", "SPY"], 20, offset)
    if stale_or(["TLT", "SPY"], stress is None):
        add("E", "TLT up and SPY down", "stale",
            "Line: TLT up while SPY is down more than 5% over 20 trading days. A price is missing or old.",
            "Yahoo Finance.")
    else:
        lit = stress["ret"]["TLT"] > 0 and stress["ret"]["SPY"] < -0.05
        add("E", "TLT up and SPY down", "lit" if lit else "unlit",
            f"TLT {fmt_pct(stress['ret']['TLT'])}, SPY {fmt_pct(stress['ret']['SPY'])}. "
            f"Line: TLT positive and SPY below -5%. Window {fmt_day(stress['start'])} to {fmt_day(stress['end'])}.",
            "Yahoo Finance 20-session simple returns.")

    power = window_returns(quotes, ["EQIX", "DLR", "VST"], 20, offset)
    if stale_or(["EQIX", "DLR", "VST"], power is None):
        add("F", "Listed capacity versus VST", "stale",
            "Line: equal-weight EQIX and DLR beat VST by more than 5pp. An input is missing or old.",
            "Yahoo Finance. Relative return, not a price difference.")
    else:
        capacity = (power["ret"]["EQIX"] + power["ret"]["DLR"]) / 2
        excess = capacity - power["ret"]["VST"]
        add("F", "Listed capacity versus VST", "lit" if excess > 0.05 else "unlit",
            f"EQIX and DLR minus VST {fmt_pp(excess)}. Line: more than +5pp. "
            f"Window {fmt_day(power['start'])} to {fmt_day(power['end'])}.",
            "Equal-weight 20-session return of EQIX and DLR, minus VST.")

    hosts = ["CIFR", "HUT", "IREN", "WULF", "RIOT"]
    host = window_returns(quotes, hosts, 20, offset)
    if stale_or(hosts, host is None):
        add("F", "Texas-pipeline hosts versus others", "stale",
            "Line: equal-weight CIFR, HUT, and IREN lag equal-weight WULF and RIOT by more than 5pp.",
            "Yahoo Finance. Relative return, not a price difference.")
    else:
        texas = sum(host["ret"][name] for name in ("CIFR", "HUT", "IREN")) / 3
        other = (host["ret"]["WULF"] + host["ret"]["RIOT"]) / 2
        lag = other - texas
        add("F", "Texas-pipeline hosts versus others", "lit" if lag > 0.05 else "unlit",
            f"WULF and RIOT minus CIFR, HUT, and IREN {fmt_pp(lag)}. Line: others ahead by more than 5pp. "
            f"Window {fmt_day(host['start'])} to {fmt_day(host['end'])}.",
            "Equal-weight 20-session returns. Texas-pipeline names are CIFR, HUT, IREN. The comparison names are WULF and RIOT.")
    return checks


def cpi_rows(bundle: dict, offset: int) -> list[dict]:
    rows = shifted(bundle["cpi"], offset)
    out = []
    for older, newer in zip(rows, rows[1:]):
        if older[1] == 0:
            continue
        raw = (newer[1] / older[1] - 1) * Decimal(100)
        out.append({
            "month": newer[0],
            "raw": raw,
            "published": round_tenth(raw),
        })
    return out


def month_value(rows, months_back: int, offset: int):
    use = shifted(rows, offset)
    if not use:
        return None
    year, month = _add_month(use[-1][0].year, use[-1][0].month, -months_back)
    for day, value in use:
        if day.year == year and day.month == month:
            return value
    return None


def build_legs(bundle: dict, offset: int, apply_missing: bool) -> list[dict]:
    now = bundle["now"]
    quotes = bundle["quotes"]
    status = bundle["status"]
    legs = []

    def price(ticker: str):
        series = quotes.get(ticker)
        if not series:
            return None
        bars = shifted(series["bars"], offset)
        if not bars:
            return None
        return series, bars[-1], bars

    # Inflation
    cpi = cpi_rows(bundle, offset)
    core = cpi[-1] if cpi else None
    prior = cpi[-2] if len(cpi) > 1 else None
    cpi_old = core is None or (apply_missing and monthly_stale(core["month"], now, "cpi"))
    dgs = shifted(bundle["dgs2"], offset)
    dgs_old = len(dgs) < 21 or (apply_missing and fred_stale(bundle["dgs2"], now))
    rates_bp = None
    rates_up = False
    if len(dgs) >= 21:
        rates_bp = dgs[-1][1] - dgs[-21][1]
        rates_up = rates_bp > 0
    twice = bool(core and prior and core["published"] >= Decimal("0.3") and prior["published"] >= Decimal("0.3"))
    core_det = bool(core and core["published"] >= Decimal("0.3") and not cpi_old)
    wti = price("CL=F")
    brent = price("BZ=F")
    oil_old = True
    brent_px = wti_px = None
    if brent:
        brent_px = brent[1]["close"]
        oil_old = apply_missing and series_stale(brent[2], now)
    if wti:
        wti_px = wti[1]["close"]
        oil_old = oil_old and (apply_missing and series_stale(wti[2], now))
    if brent or wti:
        oil_old = False
        if apply_missing:
            oil_old = True
            if brent and not series_stale(brent[2], now):
                oil_old = False
            if wti and not series_stale(wti[2], now):
                oil_old = False
    oil_det = False
    oil_status = ""
    if brent_px is not None and brent_px > 100 or wti_px is not None and wti_px > 100:
        oil_det = True
        oil_status = "red"
    elif (brent_px is not None and brent_px > 95) or (wti_px is not None and wti_px > 95):
        oil_det = True
        oil_status = "yellow"
    if oil_old:
        oil_det = False
        oil_status = "stale"

    core_status = "yellow" if core_det else ""
    if core and twice and rates_up and not cpi_old:
        core_status = "red"
    if cpi_old:
        core_status = "stale"
        core_det = False

    if core:
        core_value = f"{core['published']:.1f}%"
        core_tip = (
            f"FRED CPILFESL, seasonally adjusted index. Published month-on-month change is the index ratio "
            f"rounded half up to one decimal, the CPI release convention. Unrounded {core['raw']:.3f}%. "
            f"Month {fmt_day(core['month'])}."
        )
        if prior:
            core_change = f"prior {prior['published']:.1f}%"
            core_tip += f" Prior month unrounded {prior['raw']:.3f}%."
        else:
            core_change = DASH
    else:
        core_value, core_change, core_tip = DASH, DASH, "FRED CPILFESL was not loaded."
    if cpi_old and core:
        core_tip += " The print is stale: a newer CPI release is out, or the file is behind that release."

    if len(dgs) >= 2 and not dgs_old:
        dgs_value = f"{dgs[-1][1]:.2f}%"
        week = dgs[-1][1] - dgs[-6][1] if len(dgs) >= 6 else None
        dgs_change = fmt_bp(rates_bp) + " / 20d" if rates_bp is not None else DASH
        if week is not None:
            dgs_change = fmt_bp(week) + " 1w · " + dgs_change
        dgs_tip = (
            f"FRED DGS2. Observation {fmt_day(dgs[-1][0])}. "
            + (f"20-observation change {fmt_bp(rates_bp)}. " if rates_bp is not None else "")
            + "Dec meeting odds were not loaded."
        )
    else:
        dgs_value, dgs_change = DASH, DASH
        dgs_tip = "FRED DGS2 was not loaded or is old." + failure_note(status, "fred DGS2")

    def oil_bit(label, ticker, px, bar):
        if px is None or bar is None:
            return tip(DASH, f"{label} was not loaded." + failure_note(status, ticker))
        kind = ""
        if not oil_old:
            if px > 100:
                kind = "st-red"
            elif px > 95:
                kind = "st-yellow"
        elif oil_old:
            kind = "stale"
        text = tip(f"{label} {px:,.2f}", f"Yahoo Finance {ticker}. {session_phrase(bar)}.", kind)
        return text

    brent_bar = brent[1] if brent else None
    wti_bar = wti[1] if wti else None
    oil_value = " ".join([
        oil_bit("Brent", "BZ=F", brent_px, brent_bar),
        oil_bit("WTI", "CL=F", wti_px, wti_bar),
    ])
    oil_change_parts = []
    if brent and len(brent[2]) >= 6:
        oil_change_parts.append("Brent " + fmt_pct(brent[2][-1]["close"] / brent[2][-6]["close"] - 1) + " 1w")
    if wti and len(wti[2]) >= 6:
        oil_change_parts.append("WTI " + fmt_pct(wti[2][-1]["close"] / wti[2][-6]["close"] - 1) + " 1w")
    oil_change = " · ".join(oil_change_parts) if oil_change_parts else DASH

    inflation_flags = [("core", core_det), ("oil", oil_det)]
    inflation_missing = bool(cpi_old or oil_old)
    if core and twice and not rates_up and rates_bp is not None:
        rates_clause = f"Two published 0.3% prints, and the 2-year yield is {fmt_bp(rates_bp)} over 20 observations, so the rates-up half is not met."
    elif core and core["published"] >= Decimal("0.3") and not twice:
        rates_clause = "The latest published print is at least 0.3%. The red line needs two months, plus higher 2-year yields."
    elif core and twice and rates_up:
        rates_clause = "Two published prints are at least 0.3% and the 2-year yield is up. That is the core red line."
    else:
        rates_clause = "The latest published core print is below 0.3%."
    oil_clause = "Neither benchmark is above $95."
    if oil_status == "red":
        oil_clause = "A benchmark is above the $100 red line."
    elif oil_status == "yellow":
        names = []
        if brent_px is not None and brent_px > 95:
            names.append("Brent")
        if wti_px is not None and wti_px > 95:
            names.append("WTI")
        oil_clause = " and ".join(names) + " is above the $95 yellow line and short of $100." if names else oil_clause

    core_meter = ""
    if core and not cpi_old:
        core_meter = meter(float(core["raw"]), 0, 0.6, "yellow and the level inside the red line: 0.3%", 0.3, 0.3, core_status)
    oil_meter = ""
    if brent_px is not None:
        oil_meter = meter(brent_px, 70, 120, "Brent yellow $95, red $100", 95, 100, oil_status if brent_px > 95 else "")
    if wti_px is not None:
        wti_state = "red" if wti_px > 100 else "yellow" if wti_px > 95 else ""
        oil_meter += meter(wti_px, 70, 120, "WTI yellow $95, red $100", 95, 100, wti_state)

    legs.append({
        "name": "Inflation",
        "light": leg_light(inflation_flags, inflation_missing and not (core_det or oil_det)),
        "because": ", ".join(part for part, flag in (("core CPI", core_det), ("oil", oil_det)) if flag) or "no line crossed",
        "yellow": "Proposal: one core CPI print at or above 0.3% month on month, or oil above $95.",
        "red": "Core CPI at or above 0.3% for two consecutive months while the 2-year yield is up over 20 trading days, or oil above $100. " + rates_clause + " " + oil_clause,
        "indicators": [
            {
                "name": "Core CPI",
                "value": tip(core_value, core_tip, "stale" if cpi_old else ("st-yellow" if core_status == "yellow" else "st-red" if core_status == "red" else "")),
                "change": core_change,
                "spark": spark([float(item["raw"]) for item in cpi[-24:]]),
                "meter": core_meter,
                "deteriorating": core_det,
            },
            {
                "name": "2-year and Dec odds",
                "value": tip(dgs_value, dgs_tip, "stale" if dgs_old else "") + " Dec odds " + tip(DASH, "CME FedWatch did not return a parseable Dec meeting probability. Nothing is filled in." + failure_note(status, "cme")),
                "change": dgs_change,
                "spark": spark([row[1] for row in dgs[-30:]]),
                "meter": "",
                "deteriorating": False,
            },
            {
                "name": "Oil",
                "value": oil_value,
                "change": oil_change,
                "spark": spark([bar["close"] for bar in (brent[2] if brent else [])[-30:]]),
                "meter": oil_meter,
                "deteriorating": oil_det,
            },
        ],
    })

    # Growth
    pay = shifted(bundle["pay"], offset)
    unrate = shifted(bundle["unrate"], offset)
    claims = shifted(bundle["claims"], offset)
    pay_old = len(pay) < 2 or (apply_missing and monthly_stale(pay[-1][0], now, "jobs"))
    un_old = len(unrate) < 4 or (apply_missing and monthly_stale(unrate[-1][0], now, "jobs"))
    claims_old = len(claims) < 4 or (apply_missing and fred_stale(bundle["claims"], now, weekly=True))
    pay_change = pay[-1][1] - pay[-2][1] if len(pay) >= 2 else None
    pay_det = bool(pay_change is not None and pay_change < 50 and not pay_old)
    claims_avg = sum(row[1] for row in claims[-4:]) / 4 if len(claims) >= 4 else None
    prev_avg = sum(row[1] for row in claims[-5:-1]) / 4 if len(claims) >= 5 else None
    claims_det = bool(claims_avg is not None and claims_avg > 210_000 and not claims_old)
    un_change = None
    if unrate and not un_old:
        back = month_value(bundle["unrate"], 3, offset)
        if back is not None:
            un_change = unrate[-1][1] - back
    un_det = bool(un_change is not None and un_change >= 0.3 and not un_old)
    if pay_change is None:
        pay_value, pay_tip = DASH, "FRED PAYEMS was not loaded."
    else:
        pay_value = f"{pay_change:+,.0f}k"
        pay_tip = (
            f"FRED PAYEMS level change, thousands of persons. {fmt_day(pay[-2][0])} {pay[-2][1]:,.0f} to "
            f"{fmt_day(pay[-1][0])} {pay[-1][1]:,.0f}. Proposal yellow is below +50k. Red level is below zero."
        )
    claims_value = DASH if claims_avg is None else f"{claims_avg / 1000:.1f}k"
    claims_tip = "FRED ICSA, 4-week average of weekly initial claims."
    if claims:
        claims_tip += f" Latest week {fmt_day(claims[-1][0])} {claims[-1][1]:,.0f}."
    if claims_old:
        claims_tip += " Weekly prints go stale after 8 days."
    un_value = DASH if not unrate or un_old else f"{unrate[-1][1]:.1f}%"
    un_tip = "FRED UNRATE."
    if unrate:
        un_tip += f" Month {fmt_day(unrate[-1][0])}."
    if un_change is not None:
        un_tip += f" Change versus three months earlier {un_change:+.1f}pp."
    pay_status = "red" if pay_change is not None and pay_change < 0 and not pay_old else ("yellow" if pay_det else "")
    claims_status = "red" if claims_avg is not None and claims_avg > 227_000 and not claims_old else ("yellow" if claims_det else "")
    growth_missing = pay_old or claims_old
    legs.append({
        "name": "Growth",
        "light": leg_light([("payrolls", pay_det), ("claims", claims_det), ("unrate", un_det)], growth_missing and not (pay_det or claims_det or un_det)),
        "because": ", ".join(part for part, flag in (("payrolls", pay_det), ("claims", claims_det), ("unemployment", un_det)) if flag) or "no line crossed",
        "yellow": "Proposal: payrolls monthly change below +50k, the 4-week claims average above 210k, or unemployment up 0.3pp over three months.",
        "red": "The 4-week average of initial claims above 227k AND a negative payrolls print.",
        "indicators": [
            {
                "name": "Payrolls",
                "value": tip(pay_value, pay_tip, "stale" if pay_old else ("st-red" if pay_status == "red" else "st-yellow" if pay_status == "yellow" else "")),
                "change": "m/m" if pay_change is not None else DASH,
                "spark": spark([pay[index][1] - pay[index - 1][1] for index in range(1, len(pay))][-24:]),
                "meter": meter(pay_change, -100, 300, "yellow +50k, red 0", 50, 0, pay_status) if pay_change is not None and not pay_old else "",
                "deteriorating": pay_det,
            },
            {
                "name": "Unemployment",
                "value": tip(un_value, un_tip, "stale" if un_old else ("st-yellow" if un_det else "")),
                "change": DASH if un_change is None else f"{un_change:+.1f}pp / 3m",
                "spark": spark([row[1] for row in unrate[-24:]]),
                "meter": meter(un_change, -0.6, 0.8, "proposal yellow +0.3pp over 3 months", 0.3, None, "yellow" if un_det else "") if un_change is not None else "",
                "deteriorating": un_det,
            },
            {
                "name": "Claims, 4-week",
                "value": tip(claims_value, claims_tip, "stale" if claims_old else ("st-red" if claims_status == "red" else "st-yellow" if claims_status == "yellow" else "")),
                "change": DASH if prev_avg is None or claims_avg is None else fmt_k_delta(claims_avg - prev_avg) + " 1w",
                "spark": spark([row[1] for row in claims[-20:]]),
                "meter": meter(claims_avg, 150_000, 260_000, "yellow 210k, red 227k", 210_000, 227_000, claims_status) if claims_avg is not None and not claims_old else "",
                "deteriorating": claims_det,
            },
        ],
    })

    # AI rules
    manual = bundle["manual"]
    asof = datetime.fromisoformat(manual["asof_sgt"])
    rules_old = apply_missing and manual_stale(asof, now)
    bans = manual.get("signed_state_bans")
    pause = bool(manual.get("grid_pause_confirmed"))
    rules_det_ban = bool(bans is not None and bans >= 1 and not rules_old)
    rules_det_pause = bool(pause and not rules_old)
    rules_tip = f"Manual entry {fmt_dt(asof)}. Source: {manual.get('source', '')}"
    texas = manual.get("texas_status", "")
    tceq = manual.get("tceq_note", "")
    legs.append({
        "name": "AI rules",
        "light": "stale" if rules_old else leg_light([("bans", rules_det_ban), ("grid", rules_det_pause)], False),
        "because": ", ".join(part for part, flag in (("signed ban", rules_det_ban), ("grid pause", rules_det_pause)) if flag) or "no line crossed",
        "yellow": "Proposal: a major-state ban has passed one chamber, or the ERCOT verification report recommends a pause.",
        "red": "A signed ban in a major state, or a confirmed grid pause. " + texas + " " + tceq,
        "indicators": [
            {
                "name": "Signed state bans",
                "value": tip(DASH if bans is None else str(bans), rules_tip, "stale" if rules_old else ("st-red" if rules_det_ban else "")),
                "change": "manual",
                "spark": "",
                "meter": meter(bans or 0, 0, 2, "red line: 1 signed major-state ban", None, 1, "red" if rules_det_ban else "") if bans is not None and not rules_old else "",
                "deteriorating": rules_det_ban,
            },
            {
                "name": "Texas grid",
                "value": tip("Confirmed pause" if pause else "Unconfirmed", rules_tip + " " + texas + " " + tceq, "stale" if rules_old else ("st-red" if rules_det_pause else "")),
                "change": "decision 17 Dec",
                "spark": "",
                "meter": "",
                "deteriorating": rules_det_pause,
            },
        ],
    })

    # AI money — required prints are not loaded.
    money_missing_tip = "No live print is loaded. A remembered spread or yield is not filled in."
    legs.append({
        "name": "AI money",
        "light": "missing",
        "because": "prints not loaded",
        "yellow": "Auction price at 90% to 95% of par is the yellow band. A CRWV funding flag without a second channel stays on this leg.",
        "red": "The data-center loan auction below 90% of par, or pulled, PLUS a CRWV funding red flag. Bids are 19 Nov 2026. CDS and the 2031/2032 unsecured yield are not loaded.",
        "indicators": [
            {"name": "CRWV CDS and unsecured yield", "value": tip(DASH, money_missing_tip), "change": DASH, "spark": "", "meter": "", "deteriorating": False},
            {"name": "SoftBank and Oracle CDS", "value": tip(DASH, money_missing_tip), "change": DASH, "spark": "", "meter": "", "deteriorating": False},
            {"name": "Loan auction", "value": tip(DASH, "Bids 19 Nov 2026. Green at or above 95% of par, yellow 90% to 95%, red below 90% or pulled. No price is loaded."), "change": DASH, "spark": "", "meter": "", "deteriorating": False},
        ],
    })

    # AI demand
    nvda = price("NVDA")
    nvda_value, nvda_change, nvda_spark, nvda_tip = DASH, DASH, "", "Yahoo Finance NVDA was not loaded."
    if nvda:
        bar = nvda[1]
        bars = nvda[2]
        nvda_value = fmt_px(bar["close"], "NVDA")
        nvda_tip = f"Yahoo Finance NVDA. {session_phrase(bar)}. Shown as context. The demand red line is rents and a 2027 capex cut, not the share price."
        if len(bars) >= 6:
            nvda_change = fmt_pct(bars[-1]["close"] / bars[-6]["close"] - 1) + " 1w"
        nvda_spark = spark([item["close"] for item in bars[-30:]])
        if apply_missing and series_stale(bars, now):
            nvda_tip += " The price is stale."
    legs.append({
        "name": "AI demand",
        "light": "missing",
        "because": "rent prints not loaded",
        "yellow": "Proposal: H100 or B200 one-month rent down 10% or more.",
        "red": "Rents down 20% in a month PLUS a 2027 capex cut that cites demand. Neither rent nor the capex guide is loaded. NVDA is context only.",
        "indicators": [
            {"name": "H100 rent, 1 month", "value": tip(DASH, "No public H100 rent series was loaded."), "change": DASH, "spark": "", "meter": "", "deteriorating": False},
            {"name": "B200 rent, 1 month", "value": tip(DASH, "No public B200 rent series was loaded."), "change": DASH, "spark": "", "meter": "", "deteriorating": False},
            {"name": "NVDA", "value": tip(nvda_value, nvda_tip), "change": nvda_change, "spark": nvda_spark, "meter": "", "deteriorating": False},
        ],
    })

    # Spillover
    hy = shifted(bundle["hy"], offset)
    ig = shifted(bundle["ig"], offset)
    sofr = shifted(bundle["sofr"], offset)
    srf = shifted(bundle["srf"], offset)
    hy_old = len(hy) < 2 or (apply_missing and fred_stale(bundle["hy"], now))
    ig_old = len(ig) < 2 or (apply_missing and fred_stale(bundle["ig"], now))
    sofr_old = len(sofr) < 2 or (apply_missing and fred_stale(bundle["sofr"], now))
    srf_old = len(srf) < 1 or (apply_missing and fred_stale(bundle["srf"], now))
    hy_det = bool(hy and hy[-1][1] > 4.0 and not hy_old)
    hy_status = "red" if hy and hy[-1][1] > 4.5 and not hy_old else ("yellow" if hy_det else "")
    hy_value = DASH if not hy else f"{hy[-1][1]:.2f}%"
    hy_change = DASH
    if len(hy) >= 6:
        hy_change = fmt_bp(hy[-1][1] - hy[-6][1]) + " 1w"
    hy_tip = "FRED BAMLH0A0HYM2, percent."
    if hy:
        hy_tip += f" Observation {fmt_day(hy[-1][0])}. Proposal yellow is above 4.0%. Red level is above 4.5%."
    ig_value = DASH if not ig else f"{ig[-1][1]:.2f}%"
    ig_change = fmt_bp(ig[-1][1] - ig[-6][1]) + " 1w" if len(ig) >= 6 else DASH
    ig_tip = "FRED BAMLC0A0CM, percent. No separate yellow or red line in the 8 Nov brief."
    if ig:
        ig_tip += f" Observation {fmt_day(ig[-1][0])}."
    sofr_value = DASH if not sofr else f"{sofr[-1][1]:.2f}%"
    sofr_tip = "FRED SOFR, percent. Official range bounds were not loaded, so the range comparison is empty."
    if sofr:
        sofr_tip += f" Observation {fmt_day(sofr[-1][0])}."
    srf_value = DASH if not srf else f"{srf[-1][1]:.2f}bn"
    srf_tip = "FRED RPONTSYD, billions of dollars. Standing repo usage. No numeric red line is set."
    if srf:
        srf_tip += f" Observation {fmt_day(srf[-1][0])}."
    spill_missing = hy_old
    legs.append({
        "name": "Spillover",
        "light": leg_light([("hy", hy_det)], spill_missing and not hy_det),
        "because": "HY OAS" if hy_det else "no line crossed",
        "yellow": "Proposal: HY OAS above 4.0%. IG, SOFR, and SRF are shown beside it. SOFR versus its official range is empty until the bounds are loaded.",
        "red": "HY OAS above 4.5% AND SOFR above the official range. AI-name CDS counts on the money leg unless HY, IG, SOFR, or SRF also move. "
        + (f"HY OAS is {hy[-1][1]:.2f}%, so the 4.5% half is not met. " if hy else "")
        + "The SOFR range comparison is empty.",
        "indicators": [
            {
                "name": "HY OAS",
                "value": tip(hy_value, hy_tip, "stale" if hy_old else ("st-red" if hy_status == "red" else "st-yellow" if hy_status == "yellow" else "")),
                "change": hy_change,
                "spark": spark([row[1] for row in hy[-30:]]),
                "meter": meter(hy[-1][1], 2.5, 5.5, "yellow 4.0%, red 4.5%", 4.0, 4.5, hy_status) if hy and not hy_old else "",
                "deteriorating": hy_det,
            },
            {
                "name": "IG OAS",
                "value": tip(ig_value, ig_tip, "stale" if ig_old else ""),
                "change": ig_change,
                "spark": spark([row[1] for row in ig[-30:]]),
                "meter": "",
                "deteriorating": False,
            },
            {
                "name": "SOFR and SRF",
                "value": tip("SOFR " + sofr_value, sofr_tip, "stale" if sofr_old else "") + " range " + tip(DASH, "Official SOFR range bounds were not loaded.") + " SRF " + tip(srf_value, srf_tip, "stale" if srf_old else ""),
                "change": DASH,
                "spark": spark([row[1] for row in sofr[-30:]]),
                "meter": "",
                "deteriorating": False,
            },
        ],
    })

    # Crypto
    btc = price("BTC-USD")
    funding = shifted(bundle["funding"], offset)
    usde = shifted(bundle["usde"], offset)
    btc_old = True
    btc_value, btc_change, btc_spark, btc_tip = DASH, DASH, "", "Yahoo Finance BTC-USD was not loaded."
    if btc:
        bar, bars = btc[1], btc[2]
        btc_old = apply_missing and series_stale(bars, now, crypto=True)
        btc_value = fmt_px(bar["close"], "BTC-USD")
        btc_tip = f"Yahoo Finance BTC-USD. {fmt_dt(datetime.fromtimestamp(bar['ts'], SGT))}."
        if len(bars) >= 8:
            btc_change = fmt_pct(bars[-1]["close"] / bars[-8]["close"] - 1) + " 7d"
        btc_spark = spark([item["close"] for item in bars[-30:]])
    fund_old = True
    fund_value, fund_change = DASH, DASH
    fund_tip = "Binance BTCUSDT perpetual funding was not loaded." + failure_note(status, "binance")
    if funding:
        last = funding[-1]
        fund_old = apply_missing and funding_is_stale(last["ts"], now)
        fund_value = f"{last['rate'] * 100:.4f}% / 8h"
        fund_tip = (
            f"Binance BTCUSDT perpetual funding, per 8 hours. {fmt_dt(datetime.fromtimestamp(last['ts'], SGT))}."
            + failure_note(status, "binance")
        )
        week_cut = last["ts"] - 7 * 86400
        prior = min(funding, key=lambda item: abs(item["ts"] - week_cut))
        fund_change = f"{(last['rate'] - prior['rate']) * 100:+.4f}pp / ~7d"
    usde_old = True
    usde_value, usde_change, usde_spark = DASH, DASH, ""
    usde_tip = "DefiLlama USDe was not loaded." + failure_note(status, "usde")
    if usde:
        last = usde[-1]
        usde_old = apply_missing and (now.astimezone(SGT).date() - datetime.fromtimestamp(last["ts"], SGT).date()).days > 1
        usde_value = fmt_usd(last["value"])
        usde_tip = f"DefiLlama USDe circulating supply. {fmt_dt(datetime.fromtimestamp(last['ts'], SGT))}."
        target = last["ts"] - 30 * 86400
        prior = min(usde, key=lambda item: abs(item["ts"] - target))
        if prior["value"]:
            usde_change = fmt_pct(last["value"] / prior["value"] - 1) + " ~30d"
        usde_spark = spark([item["value"] for item in usde[-60:]])
    mstr = price("MSTR")
    strc = price("STRC")
    mstr_value = tip(DASH, "The coin count was not loaded, so the MSTR multiple is not computed.")
    strc_value = tip(DASH, "Yahoo Finance STRC was not loaded.")
    if strc:
        px = strc[1]["close"]
        versus = px / 100 - 1
        strc_value = tip(
            f"{px:,.2f} ({fmt_pct(versus)} vs $100 par)",
            f"Yahoo Finance STRC. {session_phrase(strc[1])}. Par is the $100 face. No accrued-dividend adjustment.",
        )
    crypto_missing = btc_old or fund_old or usde_old
    legs.append({
        "name": "Crypto",
        "light": "stale" if crypto_missing else "green",
        "because": "no numeric red line in the brief",
        "yellow": "No numeric yellow line is set in the 8 Nov brief. Prints are shown and not scored.",
        "red": "No numeric red line is set in the 8 Nov brief for BTC, funding, USDe, the MSTR multiple, or STRC versus par.",
        "indicators": [
            {"name": "BTC and funding", "value": tip(btc_value, btc_tip, "stale" if btc_old else "") + " funding " + tip(fund_value, fund_tip, "stale" if fund_old else ""), "change": " ".join(part for part in (btc_change, fund_change) if part != DASH) or DASH, "spark": btc_spark, "meter": "", "deteriorating": False},
            {"name": "USDe", "value": tip(usde_value, usde_tip, "stale" if usde_old else ""), "change": usde_change, "spark": usde_spark, "meter": "", "deteriorating": False},
            {"name": "MSTR mNAV and STRC", "value": "mNAV " + mstr_value + " STRC " + strc_value, "change": mstr_change(mstr), "spark": spark([bar["close"] for bar in mstr[2][-30:]]) if mstr else "", "meter": "", "deteriorating": False},
        ],
    })
    return legs


def mstr_change(mstr) -> str:
    if not mstr or len(mstr[2]) < 6:
        return DASH
    return "MSTR " + fmt_pct(mstr[2][-1]["close"] / mstr[2][-6]["close"] - 1) + " 1w"


def fmt_k_delta(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value / 1000:.1f}k"


def fmt_usd(value: float) -> str:
    if abs(value) >= 1e12:
        return f"${value / 1e12:.2f}tn"
    if abs(value) >= 1e9:
        return f"${value / 1e9:.2f}bn"
    if abs(value) >= 1e6:
        return f"${value / 1e6:.1f}m"
    return f"${value:,.0f}"


def session_phrase(bar: dict) -> str:
    stamp = fmt_dt(datetime.fromtimestamp(bar["ts"], SGT))
    return f"Session {fmt_day(bar['session'])}, print {stamp}"


def closest_candidates(bundle: dict) -> list[dict]:
    candidates = []
    quotes = bundle["quotes"]
    for ticker, label in (("BZ=F", "Brent"), ("CL=F", "WTI")):
        series = quotes.get(ticker)
        if not series or series_stale(series["bars"], bundle["now"]):
            continue
        px = series["bars"][-1]["close"]
        gap = 100 - px
        candidates.append({
            "name": label,
            "leg": "Inflation",
            "frac": gap / 100,
            "phrase": (
                f"{label} is ${abs(gap):.2f} {'through' if gap < 0 else 'under'} the $100 red line "
                f"(last ${px:,.2f}). The yellow line is $95."
            ),
        })
    hy = bundle["hy"]
    if hy and not fred_stale(hy, bundle["now"]):
        gap = 4.5 - hy[-1][1]
        candidates.append({
            "name": "HY OAS",
            "leg": "Spillover",
            "frac": gap / 4.5,
            "phrase": (
                f"HY OAS is {abs(gap):.2f} percentage points {'through' if gap < 0 else 'under'} the 4.5% red line "
                f"(last {hy[-1][1]:.2f}%). The red line also needs SOFR above its official range, and those bounds are not loaded."
            ),
        })
    claims = bundle["claims"]
    pay = bundle["pay"]
    if len(claims) >= 4 and len(pay) >= 2 and not fred_stale(claims, bundle["now"], weekly=True) and not monthly_stale(pay[-1][0], bundle["now"], "jobs"):
        avg = sum(row[1] for row in claims[-4:]) / 4
        pay_change = pay[-1][1] - pay[-2][1]
        claims_frac = (227_000 - avg) / 227_000
        pay_frac = pay_change / 100
        binding = max(claims_frac, pay_frac)
        candidates.append({
            "name": "Claims and payrolls",
            "leg": "Growth",
            "frac": binding,
            "phrase": (
                f"The growth red line needs claims above 227k and negative payrolls. "
                f"The 4-week average is {avg / 1000:.1f}k and payrolls are {pay_change:+,.0f}k. "
                f"Distance uses the further of those two gaps. Payrolls are scaled by 100k because the red threshold is zero."
            ),
        })
    cpi = cpi_rows(bundle, 0)
    dgs = bundle["dgs2"]
    if len(cpi) >= 2 and len(dgs) >= 21 and not monthly_stale(cpi[-1]["month"], bundle["now"], "cpi"):
        twice = cpi[-1]["published"] >= Decimal("0.3") and cpi[-2]["published"] >= Decimal("0.3")
        rates_up = dgs[-1][1] - dgs[-21][1] > 0
        if twice and rates_up:
            gap = float(Decimal("0.3") - cpi[-1]["published"])
            candidates.append({
                "name": "Core CPI",
                "leg": "Inflation",
                "frac": gap / 0.3,
                "phrase": "Core CPI is through the two-month 0.3% red line and the 2-year yield is up.",
            })
    return candidates


PLACE = {
    "CL=F": "the inflation leg",
    "BZ=F": "the inflation leg",
    "DGS2": "the inflation leg",
    "BAMLH0A0HYM2": "the spillover leg",
    "BAMLC0A0CM": "the spillover leg",
    "SOFR": "the spillover leg",
    "RPONTSYD": "the spillover leg",
    "CRWV": "the AI money leg and the neocloud pair",
    "NBIS": "the neocloud control",
    "NVDA": "AI demand, as context only",
    "SMH": "the supplier side of the D check",
    "XLP": "the D check",
    "XLE": "the C check",
    "TLT": "the E check",
    "SPY": "the market-implied checks",
    "QQQ": "the C check",
    "IWM": "the A check",
    "EQIX": "the F check",
    "DLR": "the F check",
    "VST": "the F avoid list",
    "CIFR": "box A and the Texas-host side of the F check",
    "HUT": "the Texas-host side of the F check",
    "IREN": "box A and the Texas-host side of the F check",
    "WULF": "the F check",
    "RIOT": "the F check",
    "BTC-USD": "the crypto leg",
    "MSTR": "the crypto leg",
    "STRC": "the crypto leg",
    "USDE": "the crypto leg",
    "FUNDING": "the crypto leg",
}


def level_side_oil(value: float) -> str:
    if value > 100:
        return "through the $100 red line"
    if value > 95:
        return "through the $95 yellow line"
    return "short of the $95 yellow line"


def build_moves(bundle: dict) -> list[dict]:
    moves = []
    for ticker, series in bundle["quotes"].items():
        bars = series["bars"]
        if len(bars) < 2 or bars[-2]["close"] == 0:
            continue
        frac = bars[-1]["close"] / bars[-2]["close"] - 1
        extra = "No red line on this page, so this print does not change the leg count by itself."
        if ticker in ("CL=F", "BZ=F"):
            extra = (
                f"It was {level_side_oil(bars[-2]['close'])} and is {level_side_oil(bars[-1]['close'])}."
            )
        name = {"^NDX": "NDX", "BTC-USD": "BTC", "CL=F": "WTI", "BZ=F": "Brent"}.get(ticker, ticker)
        moves.append({
            "score": abs(frac) * 100,
            "name": name,
            "text": f"{name} {fmt_pct(frac)} → {PLACE.get(ticker, 'the watchlist')}. {extra}",
            "when": fmt_dt(datetime.fromtimestamp(bars[-1]["ts"], SGT)),
            "source": "Yahoo Finance",
            "old": fmt_px(bars[-2]["close"], ticker),
            "new": fmt_px(bars[-1]["close"], ticker),
        })
    fred_moves = [
        ("DGS2", bundle["dgs2"], "2-year yield", "percent"),
        ("BAMLH0A0HYM2", bundle["hy"], "HY OAS", "percent"),
        ("BAMLC0A0CM", bundle["ig"], "IG OAS", "percent"),
        ("SOFR", bundle["sofr"], "SOFR", "percent"),
        ("RPONTSYD", bundle["srf"], "SRF usage", "billions"),
    ]
    for key, rows, label, unit in fred_moves:
        if len(rows) < 2:
            continue
        change = rows[-1][1] - rows[-2][1]
        if unit == "percent":
            shown = fmt_bp(change)
            score = abs(change) * 10
        else:
            shown = f"{change:+.2f}bn"
            score = abs(change)
        moves.append({
            "score": score,
            "name": label,
            "text": f"{label} {shown} → {PLACE.get(key, 'the tape')}. No standalone leg change from this one-session move.",
            "when": fmt_day(rows[-1][0]),
            "source": "FRED " + key,
            "old": f"{rows[-2][1]:.2f}",
            "new": f"{rows[-1][1]:.2f}",
        })
    if len(bundle["funding"]) >= 2:
        last, prev = bundle["funding"][-1], bundle["funding"][-2]
        change = (last["rate"] - prev["rate"]) * 100
        moves.append({
            "score": abs(change) * 100,
            "name": "BTC funding",
            "text": f"BTC funding {change:+.4f}pp per 8h → the crypto leg. No numeric red line is set, so this does not change the leg count.",
            "when": fmt_dt(datetime.fromtimestamp(last["ts"], SGT)),
            "source": "Binance BTCUSDT funding",
            "old": f"{prev['rate'] * 100:.4f}%",
            "new": f"{last['rate'] * 100:.4f}%",
        })
    if len(bundle["usde"]) >= 2:
        last, prev = bundle["usde"][-1], bundle["usde"][-2]
        if prev["value"]:
            frac = last["value"] / prev["value"] - 1
            moves.append({
                "score": abs(frac) * 100,
                "name": "USDe",
                "text": f"USDe supply {fmt_pct(frac)} → the crypto leg. No numeric red line is set, so this does not change the leg count.",
                "when": fmt_dt(datetime.fromtimestamp(last["ts"], SGT)),
                "source": "DefiLlama",
                "old": fmt_usd(prev["value"]),
                "new": fmt_usd(last["value"]),
            })
    moves.sort(key=lambda item: (-item["score"], item["name"]))
    return moves[:3]


def flags_only(bundle: dict, offset: int) -> list[tuple[str, str]]:
    """Threshold lights for a prior print. Missing money and demand stay missing."""
    legs = build_legs(bundle, offset, apply_missing=True)
    return [(leg["name"], leg["light"]) for leg in legs]


def reason_for(action: str, legs: list[dict], det: list[str], grey: list[str]) -> str:
    detail = {leg["name"]: leg["because"] for leg in legs}
    if action == "CUT":
        bits = [f"{name} ({detail.get(name, '')})" for name in det]
        return "CUT. Deteriorating legs: " + "; ".join(bits) + "."
    if det:
        name = det[0]
        extra = ""
        if grey:
            extra = " Missing or stale: " + ", ".join(grey) + ". That also blocks ADD."
        return f"HOLD. Only {name} is deteriorating ({detail.get(name, '')}). A second leg would be CUT.{extra}"
    if grey:
        return "HOLD. No leg is through a line, but " + ", ".join(grey) + " cannot count as green, so this is not ADD."
    return "ADD. No leg is deteriorating, and the required inputs are fresh enough."


def watch_groups() -> list[tuple[str, list, str]]:
    return [
        ("A", [("SPCX", ""), ("^NDX", ""), ("SMH", ""), ("BTC-USD", ""), ("MSTR", ""), ("IREN", ""), ("CIFR", "")], ""),
        ("B", [("MSFT", ""), ("GOOGL", ""), ("AMZN", ""), ("SPY", ""), ("XLE", "")], "Pair below is the NBIS/CRWV ratio."),
        ("C", [("XLE", ""), ("STRC", "Short watch")], ""),
        ("D", [("XLP", ""), ("STRC", ""), ("CRWV", ""), ("APLD", ""), ("CORZ", "")], "No individual short tag is set on this list."),
        ("E", [("TLT", ""), ("CASH", "")], ""),
        ("F", [("MSFT", ""), ("AMZN", ""), ("GOOGL", ""), ("CAT", "F only"), ("GEV", "F only"), ("EQIX", ""), ("DLR", ""), ("WULF", ""), ("RIOT", ""), ("VST", "Avoid"), ("CIFR", "Avoid"), ("HUT", "Avoid")], ""),
    ]


def chip(ticker: str, tag: str, quotes: dict) -> str:
    if ticker == "CASH":
        return '<div class="chip"><div class="chip-k">Cash</div><div class="na">\u2014</div><p class="muted">Not a ticker. No price.</p></div>'
    series = quotes.get(ticker)
    label = {"^NDX": "NDX", "BTC-USD": "BTC"}.get(ticker, ticker)
    tag_html = f'<span class="tag">{esc(tag)}</span>' if tag else ""
    if not series or len(series["bars"]) < 2:
        return f'<div class="chip"><div class="chip-k">{esc(label)} {tag_html}</div><div class="na">\u2014</div></div>'
    bars = series["bars"]
    last = bars[-1]
    one = last["close"] / bars[-2]["close"] - 1
    five = last["close"] / bars[-6]["close"] - 1 if len(bars) >= 6 else None
    five_txt = fmt_pct(five) + " 5d" if five is not None else DASH
    return (
        f'<div class="chip"><div class="chip-k">{esc(label)} {tag_html}</div>'
        f'<div class="chip-px">{tip(fmt_px(last["close"], ticker), "Yahoo Finance " + label + ". " + session_phrase(last))}</div>'
        f'<div class="muted">{esc(fmt_pct(one) + " 1d · " + five_txt)}</div>'
        f'{spark([bar["close"] for bar in bars[-30:]])}</div>'
    )


def ratio_chip(quotes: dict) -> str:
    if "NBIS" not in quotes or "CRWV" not in quotes:
        return '<div class="chip wide"><div class="chip-k">NBIS/CRWV</div><div class="na">\u2014</div><p class="muted">Ratio, not a price difference. One name is not loaded.</p></div>'
    left = {bar["session"]: bar for bar in quotes["NBIS"]["bars"]}
    right = {bar["session"]: bar for bar in quotes["CRWV"]["bars"]}
    dates = sorted(set(left) & set(right))
    vals = [left[day]["close"] / right[day]["close"] for day in dates if right[day]["close"]]
    if len(vals) < 2:
        return '<div class="chip wide"><div class="chip-k">NBIS/CRWV</div><div class="na">\u2014</div></div>'
    one = vals[-1] / vals[-2] - 1
    five = vals[-1] / vals[-6] - 1 if len(vals) >= 6 else None
    five_txt = fmt_pct(five) + " 5d" if five is not None else DASH
    detail = (
        f"NBIS close divided by CRWV close. Last shared session {fmt_day(dates[-1])}. "
        "This is a ratio, not a price difference. Sparkline uses up to 60 sessions."
    )
    return (
        f'<div class="chip wide"><div class="chip-k">NBIS/CRWV</div>'
        f'<div class="chip-px">{tip(f"{vals[-1]:.2f}", detail)}</div>'
        f'<div class="muted">{esc(fmt_pct(one) + " 1d · " + five_txt)}</div>'
        f'{spark(vals[-60:])}</div>'
    )


def neocloud(quotes: dict, now: datetime) -> str:
    def block(ticker: str) -> str:
        series = quotes.get(ticker)
        if not series:
            return f"<h3>{esc(ticker)}</h3><p class='na'>\u2014</p>"
        bar = series["bars"][-1]
        high = series.get("high52")
        from_high = DASH if not high else f"{(bar['close'] / high - 1) * 100:.1f}% from the 52-week high"
        high_tip = "Yahoo Finance fiftyTwoWeekHigh in the chart metadata. " + session_phrase(bar)
        return (
            f"<h3>{esc(ticker)} {tip(fmt_px(bar['close'], ticker), 'Yahoo Finance. ' + session_phrase(bar))}</h3>"
            f"<p>{tip(from_high, high_tip) if high else tip(DASH, '52-week high was not in the chart metadata.')}</p>"
        )

    report = datetime(2026, 11, 11, 6, 0, tzinfo=SGT)
    if now < report:
        intro = "Before the report (11 Nov 2026, about 06:00 SGT). Criteria only. Results stay empty."
    else:
        intro = "The 11 Nov 2026, 06:00 SGT report time has passed. No results were entered, so every result stays empty."
    rows = [
        ("New financing rate", "Unsecured, about 15% in the 8 Nov brief. Not a live yield.", "New unsecured at or above 15%, or secured only", "At or below 12%, or prepay / partner funding"),
        ("Q4 interest guide", "Q3 guide $860–940M", "Above $1.0bn, and operating income not keeping up", "Interest growing slower than operating income"),
        ("Adj. operating income", "Q3 guide $200–260M", "Below $200M", "Above $260M"),
        ("Capex guide", "Raised at Q2", "Cut because of funding. A cut that cites power or permits is F, not money.", "Held or raised, and funding is named"),
        ("Credit reaction, 48h", "No live CDS baseline is loaded.", "+100bp", "−100bp"),
    ]
    body = []
    for metric, base, red, green in rows:
        body.append(
            "<tr>"
            f"<td>{esc(metric)}</td><td>{esc(base)}</td><td>{esc(red)}</td><td>{esc(green)}</td>"
            f"<td class='na'>{DASH}</td></tr>"
        )
    return f"""
    <div class="neo-grid">
      <div>
        <p class="kicker">Neoclouds</p>
        <div class="pair">{block("CRWV")}{block("NBIS")}</div>
        <p>CRWV unsecured yield {tip(DASH, "No public 2031 or 2032 unsecured yield was loaded.")}. CRWV CDS {tip(DASH, "No public CDS print was loaded.")}.</p>
        {ratio_chip(quotes)}
      </div>
      <div>
        <p class="kicker">CRWV Q3 scorecard</p>
        <p>{esc(intro)}</p>
        <table>
          <thead><tr><th>Metric</th><th>Baseline</th><th>Red</th><th>Green</th><th>Result</th></tr></thead>
          <tbody>{''.join(body)}</tbody>
        </table>
        <p>Demand, recorded separately: revenue versus the guide $3.45–3.60bn and consensus about $3.54bn. Backlog versus about $129bn. Result {tip(DASH, "Not entered. The report has not been scored on this page.")}.</p>
        <p>NBIS reports 12 Nov 2026, about 21:00 SGT, and is the control. If NBIS falls on good numbers too, the market is pricing the whole neocloud model. If NBIS rebounds and CRWV does not, the stress is CRWV's balance sheet.</p>
      </div>
    </div>
    """


def catalysts(now: datetime) -> str:
    items = [
        ("10 Nov 2026, 15:30 SGT", "SoftBank Q2", "AI money", "If the print is a funding red flag beside CRWV, that points at D-money.", datetime(2026, 11, 10, 15, 30, tzinfo=SGT)),
        ("10 Nov 2026, 21:30 SGT", "October CPI", "Inflation", "If core month-on-month is at or above 0.3%, the inflation channel is on its yellow line. A second hot print with the 2-year yield up points at C.", datetime(2026, 11, 10, 21, 30, tzinfo=SGT)),
        ("11 Nov 2026, about 06:00 SGT", "CoreWeave Q3", "AI money", "A red scorecard on funding points at D-money. A cut that cites power or permits points at F.", datetime(2026, 11, 11, 6, 0, tzinfo=SGT)),
        ("12 Nov 2026, about 21:00 SGT", "Nebius Q3", "Neocloud control", "If NBIS falls on good numbers too, the market is pricing the whole neocloud model. If NBIS rebounds and CRWV does not, the stress is CRWV's balance sheet.", datetime(2026, 11, 12, 21, 0, tzinfo=SGT)),
        ("18 Nov 2026, about 05:20 SGT", "Nvidia Q3", "AI demand", "If 2027 capex is cut and the cut cites demand, with rents down 20% in a month, that is the demand red line.", datetime(2026, 11, 18, 5, 20, tzinfo=SGT)),
        ("19 Nov 2026", "Data-center loan auction bids", "AI money", "Below 90% of par, or a pulled auction, plus a CRWV funding red flag, is the money red line.", None),
        ("25 Nov 2026, 21:30 SGT", "October PCE", "Inflation", "A hot core print with the 2-year yield up points at C.", datetime(2026, 11, 25, 21, 30, tzinfo=SGT)),
        ("about 29 Nov 2026, UV", "OPEC+", "Inflation", "If oil settles above $100, that is the oil red line.", None),
        ("4 Dec 2026, 21:30 SGT", "November jobs", "Growth", "Negative payrolls and a 4-week claims average above 227k are the growth red line.", datetime(2026, 12, 4, 21, 30, tzinfo=SGT)),
        ("about 8 Dec 2026, UV", "SPCX lockup", "Box A watchlist", "Unconfirmed. A lockup is a supply event for an A watchlist name. It is not, by itself, a box change.", None),
        ("10 Dec 2026, about 03:00 SGT", "FOMC and the ERCOT verification report", "Inflation and AI rules", "A hawkish shift with hot inflation points at C. The ERCOT report is the rules input for 10 Dec.", datetime(2026, 12, 10, 3, 0, tzinfo=SGT)),
        ("17 Dec 2026, UV", "Texas grid decision", "AI rules", "Unconfirmed. A confirmed grid pause is the rules red line and points at a blocked buildout, F.", None),
        ("22 Dec 2026", "PJM auction", "AI rules", "A capacity result that blocks the buildout points at F.", None),
    ]
    cards = []
    for when, event, leg, implication, moment in items:
        if moment is not None and now >= moment:
            result = "Time has passed. Result not entered."
        else:
            result = "Result: " + DASH
        cards.append(
            f'<article class="card"><p class="kicker">{esc(when)}</p><h3>{esc(event)}</h3>'
            f'<p>{esc(leg)}</p><p>{esc(implication)}</p><p class="muted">{esc(result)}</p></article>'
        )
    return "".join(cards)


def render_leg(leg: dict) -> str:
    light = leg["light"]
    label = {"green": "Green", "yellow": "Yellow", "red": "Red", "stale": "Stale", "missing": "Missing"}.get(light, light)
    sub = {
        "green": "No line crossed",
        "yellow": "One indicator through a line",
        "red": "Two indicators through a line",
        "stale": "Print is old",
        "missing": "Required print not loaded",
    }.get(light, "")
    inds = []
    for item in leg["indicators"]:
        inds.append(
            "<div class='ind'>"
            f"<div class='ind-k'>{esc(item['name'])}</div>"
            f"<div class='ind-v'>{item['value']}</div>"
            f"<div class='muted'>{esc(item['change'])}</div>"
            f"{item['spark']}{item['meter']}</div>"
        )
    return (
        f"<article class='leg'>"
        f"<div class='lamp {esc(light)}'>{esc(label)}</div> <span class='muted'>{esc(sub)}</span>"
        f"<h3>{esc(leg['name'])}</h3>"
        f"<div class='inds'>{''.join(inds)}</div>"
        f"<p><span class='k'>Yellow line. </span>{esc(leg['yellow'])}</p>"
        f"<p><span class='k'>Red line. </span>{esc(leg['red'])}</p>"
        f"</article>"
    )


def render_map(judgment: dict) -> str:
    probs = judgment["probabilities"]
    current = judgment["current_box"]

    def prob(key: str) -> str:
        value = probs.get(key)
        if value is None:
            return DASH
        return f"{value:g}%"

    def cell(area: str, code: str, title: str, probability: str, place: str, extra: str = "") -> str:
        current_cls = " current" if code == current or (code == "D" and current in ("D", "D_money", "D_demand")) else ""
        mark = "<span class='here'>Current</span>" if current_cls else ""
        return (
            f"<div class='cell{current_cls}' style='grid-area:{area}'>"
            f"<div class='place'>{esc(place)}</div>"
            f"<strong>{esc(code)}</strong> {mark}"
            f"<div>{esc(title)}</div><div class='prob'>{esc(probability)}</div>"
            f"<div class='muted'>{esc(extra)}</div></div>"
        )

    return f"""
    <div class="map">
      <div class="mh" style="grid-area:corner"></div>
      <div class="mh" style="grid-area:healthy">Healthy</div>
      <div class="mh" style="grid-area:blocked">Blocked</div>
      <div class="mh" style="grid-area:retr">Retrenching</div>
      <div class="rh" style="grid-area:cooling">Cooling</div>
      <div class="rh" style="grid-area:sticky">Sticky</div>
      <div class="rh" style="grid-area:squeeze">Squeeze</div>
      <div class="rh" style="grid-area:breakr">Break</div>
      {cell("A", "A", "Cooling expansion", prob("A"), "Cooling · Healthy")}
      {cell("B", "B", "Sticky but viable", prob("B"), "Sticky · Healthy")}
      {cell("C", "C", "Inflation squeeze", prob("C"), "Squeeze · Healthy")}
      {cell("F", "F", "Blocked buildout", prob("F"), "Cooling or sticky · Blocked", "The well-funded self-build continues. The rest wait.")}
      {cell("D", "D", "AI retrenchment", "money " + prob("D_money"), "Retrenching, except in a break", "demand " + prob("D_demand"))}
      <div class="cell" style="grid-area:hole"><div class="place">Squeeze · Blocked</div><div class="muted">No named box for squeeze plus blocked.</div></div>
      {cell("E", "E", "Broad break", prob("E"), "Break · any AI state", "Break takes the whole row.")}
    </div>
    <p class="muted">Rows are the macro state. Columns are the AI state. There is no separate B checklist. If no other box has a lit check, the market-implied box is B. A tie keeps every tied box and does not pick a winner.</p>
    """


def render_pills(checks: list[dict]) -> str:
    items = []
    for check in checks:
        items.append(
            f"<div class='pill {esc(check['state'])}'>"
            f"<span class='pill-k'>{esc(check['box'])} · {esc(check['state'])}</span> "
            f"<span class='pill-t'>{esc(check['name'])}</span>"
            f"<div>{tip(check['detail'], check['source'])}</div></div>"
        )
    return "".join(items)


def page(view: dict) -> str:
    judgment = view["judgment"]
    current = judgment["current_box"]
    implied = view["implied"]
    action = view["action"]
    banner = ""
    if view["disagree"]:
        banner = f"<p class='banner'>Market disagrees: {esc(implied_label(implied))}</p>"
    last = judgment.get("last_box")
    if not last:
        arrow = "No prior box."
    elif last == current:
        arrow = "Unchanged versus the last published box."
    else:
        arrow = f"From {BOX_TITLE.get(last, last)} to {BOX_TITLE.get(current, current)}."
    prob = judgment["probabilities"].get(current)
    prob_txt = DASH if prob is None else f"{prob:g}%"
    changes = "".join(f"<li>{esc(item['text'])}</li>" for item in view["moves"])
    log_rows = []
    for row in view["changelog"]:
        log_rows.append(
            f"<tr><td>{esc(fmt_dt(datetime.fromisoformat(row['date_sgt'])))}</td>"
            f"<td>{esc(row['what'])}</td><td>{esc(row['old'])} → {esc(row['new'])}</td>"
            f"<td>{esc(row['source'])}</td></tr>"
        )
    for item in view["moves"]:
        log_rows.append(
            f"<tr><td>{esc(item['when'])}</td><td>{esc(item['text'])}</td>"
            f"<td>{esc(item['old'])} → {esc(item['new'])}</td><td>{esc(item['source'])}</td></tr>"
        )
    chips = []
    for code, names, note in watch_groups():
        body = "".join(chip(ticker, tag, view["quotes"]) for ticker, tag in names)
        extra = ratio_chip(view["quotes"]) if code == "B" else ""
        note_html = f"<p class='muted'>{esc(note)}</p>" if note else ""
        chips.append(f"<section><h3>{esc(code)} · {esc(BOX_TITLE.get(code, ''))}</h3>{note_html}<div class='chips'>{body}{extra}</div></section>")
    missing = ", ".join(view["missing"])
    blob = json.dumps(view["summary"], ensure_ascii=False).replace("<", "\\u003c")
    body = f"""
    <header class="mast">
      <div>
        <p class="kicker">Vortex Regime Monitor</p>
        <p class="muted">Public market data. Built {esc(view['built'])}.</p>
      </div>
      <button id="theme-toggle" type="button">Use light mode</button>
    </header>
    <section class="card span-12">
      <p class="kicker">So what today</p>
      <div class="sowhat">
        <div>
          <p class="eyebrow">Current box</p>
          <p class="letter">{esc(current)}</p>
          <p>{esc(BOX_TITLE.get(current, current))} · {tip(prob_txt, judgment.get('note', ''))}</p>
          <p class="muted">{esc(arrow)} Judgment {esc(fmt_dt(datetime.fromisoformat(judgment['asof_sgt'])))}.</p>
        </div>
        <div>
          <p class="eyebrow">Market-implied</p>
          <p class="letter{'' if len(implied_label(implied)) <= 2 else ' long'}">{esc(implied_label(implied))}</p>
          <p>{esc(check_tally(view['checks']))}. Stale checks do not count. B is the residual when nothing else is lit.</p>
          {banner}
        </div>
      </div>
      <p class="action {esc(action.lower())}">{esc(action)}</p>
      <p>{esc(view['reason'])}</p>
      <p class="muted">ADD, HOLD, and CUT are research labels, not instructions. One deteriorating leg is HOLD. Two are CUT. The same news counts once.</p>
      <p><span class="k">Closest to a red line. </span>{esc(view['closest'])}</p>
      <p class="k">What changed since the prior print</p>
      <ol>{changes}</ol>
      <p>{esc(view['change_line'])}</p>
      <p class="muted">{esc(view['implied_line'])}</p>
    </section>
    <section class="card span-5">
      <p class="kicker">Regime map</p>
      {render_map(judgment)}
    </section>
    <section class="card span-7">
      <p class="kicker">Seven legs</p>
      <p>One deteriorating indicator turns that leg yellow. Two independent indicators turn it red. The same news counts once. The badge above counts legs, not every indicator. Friday's session stays current through the weekend. Stale inputs are grey and cannot count as green.</p>
      {''.join(render_leg(leg) for leg in view['legs'])}
    </section>
    <section class="card span-12">
      <p class="kicker">Market-implied checks</p>
      <div class="pills">{render_pills(view['checks'])}</div>
    </section>
    <section class="card span-12">
      {neocloud(view['quotes'], view['now'])}
    </section>
    <section class="card span-12">
      <p class="kicker">Catalysts</p>
      <p class="muted">The next 14 days run from 9 Nov through 22 Nov. Later dates from the same brief are listed too. UV means the date is unconfirmed.</p>
      <div class="cards">{catalysts(view['now'])}</div>
    </section>
    <section class="card span-12">
      <p class="kicker">Watchlist</p>
      {''.join(chips)}
    </section>
    <section class="card span-12">
      <p class="kicker">Change log</p>
      <table>
        <thead><tr><th>When, SGT</th><th>What moved</th><th>Old → new</th><th>Source</th></tr></thead>
        <tbody>{''.join(log_rows)}</tbody>
      </table>
      <p class="muted">Not loaded, so shown as {DASH}: {esc(missing)}.</p>
      <p class="muted">Sources: Yahoo Finance, FRED, Binance BTCUSDT funding, DefiLlama USDe. Probabilities are Jess's judgment of 8 Nov 2026 and are not rewritten by the refresh.</p>
    </section>
    <script type="application/json" id="vortex-data">{blob}</script>
    """
    return HTML_HEAD + body + HTML_FOOT


HTML_HEAD = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vortex Regime Monitor</title>
<script>
try {
  var saved = localStorage.getItem("vortex-theme");
  if (saved === "light" || saved === "dark") document.documentElement.setAttribute("data-theme", saved);
  else if (window.matchMedia("(prefers-color-scheme: light)").matches) document.documentElement.setAttribute("data-theme", "light");
} catch (e) {}
</script>
<style>
:root {
  color-scheme: dark;
  --bg: #121418;
  --card: #1a1d22;
  --ink: #f3f0e8;
  --muted: #b1ab9f;
  --line: #343a42;
  --good: #1f9d62;
  --warn: #c8922a;
  --bad: #d15b52;
  --stale: #9aa0a8;
}
[data-theme="light"] {
  color-scheme: light;
  --bg: #f4f1ea;
  --card: #fffdf8;
  --ink: #1c1915;
  --muted: #5f594e;
  --line: #e3ddd2;
  --good: #0e7a45;
  --warn: #8a5b00;
  --bad: #a33b34;
  --stale: #6d7278;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px;
  line-height: 1.45;
  font-variant-numeric: tabular-nums;
}
.wrap { max-width: 1140px; margin: 0 auto; padding: 20px 18px 56px; }
.grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 14px; }
.span-12 { grid-column: span 12; }
.span-5 { grid-column: span 5; }
.span-7 { grid-column: span 7; }
.mast, .sowhat, .pair, .neo-grid { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }
.mast { grid-column: 1 / -1; align-items: flex-end; margin-bottom: 2px; }
.card, .cell, .pill, .chip, .leg {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 14px;
}
.card { padding: 16px 16px 14px; }
.kicker, .eyebrow, .k {
  margin: 0 0 6px;
  color: var(--muted);
  font-size: 12px;
  letter-spacing: .12em;
  text-transform: uppercase;
}
h3 { margin: 0 0 6px; font-size: 16px; font-weight: 650; }
p { margin: 0 0 8px; }
ol { margin: 0 0 8px; padding-left: 18px; }
li { margin: 0 0 6px; }
.letter { font-family: Georgia, "Iowan Old Style", serif; font-size: 48px; line-height: .9; margin: 0 0 4px; }
.letter.long { font-size: 28px; line-height: 1.15; }
.muted, .scale { color: var(--muted); }
.na, .stale, .lamp.missing, .lamp.stale { color: var(--stale); }
.st-yellow, .lamp.yellow, .action.hold, .banner { color: var(--warn); }
.st-red, .lamp.red, .action.cut { color: var(--bad); }
.lamp.green, .action.add { color: var(--good); }
.action { font-size: 28px; font-weight: 700; margin: 8px 0 4px; }
.banner { font-weight: 700; }
button {
  background: transparent;
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 8px 12px;
  font: inherit;
  cursor: pointer;
}
.map {
  display: grid;
  grid-template-columns: 92px repeat(3, minmax(0, 1fr));
  grid-template-areas:
    "corner healthy blocked retr"
    "cooling A F D"
    "sticky B F D"
    "squeeze C hole D"
    "breakr E E E";
  gap: 6px;
}
.mh, .rh, .cell, .cell div { overflow-wrap: break-word; hyphens: auto; }
p, h3, li, td, th, .kicker { overflow-wrap: break-word; }
.mh, .rh { color: var(--muted); font-size: 12px; letter-spacing: .06em; text-transform: uppercase; align-self: end; }
.cell { padding: 8px; min-width: 0; }
.cell.current { border-color: var(--ink); }
.here { font-size: 12px; border: 1px solid var(--ink); border-radius: 999px; padding: 0 6px; }
.prob { font-weight: 650; }
.leg { padding: 10px; margin: 8px 0; }
.lamp { display: inline-block; font-weight: 700; border: 1px solid currentColor; border-radius: 999px; padding: 1px 8px; margin-bottom: 4px; }
.inds { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 6px 0; }
.ind { min-width: 0; }
.ind-k { color: var(--muted); font-size: 12px; letter-spacing: .06em; text-transform: uppercase; }
.spark { display: block; color: var(--muted); margin-top: 4px; overflow: visible; }
.place { display: none; color: var(--muted); font-size: 12px; letter-spacing: .04em; text-transform: uppercase; }
.meter { margin-top: 4px; }
.track { position: relative; height: 8px; background: var(--line); border-radius: 99px; margin: 8px 0 4px; }
.mark, .dot { position: absolute; top: -3px; }
.mark { width: 2px; height: 14px; }
.mark.y { background: var(--warn); }
.mark.r { background: var(--bad); }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--ink); transform: translateX(-5px); }
.dot.warn { background: var(--warn); }
.dot.bad { background: var(--bad); }
.dot.grey { background: var(--stale); }
.pills, .cards, .chips { display: flex; flex-wrap: wrap; gap: 8px; }
.pill, .chip, .card article, .cards .card { padding: 10px; }
.pill, .chip { flex: 1 1 220px; }
.cards .card, .cards article { flex: 1 1 240px; }
.chip-px { font-size: 18px; font-weight: 650; }
.tag { border: 1px solid var(--line); border-radius: 999px; padding: 0 6px; font-size: 12px; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { text-align: left; vertical-align: top; padding: 6px 8px 6px 0; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
.tip { position: relative; }
.tip:hover::after, .tip:focus::after {
  content: attr(data-tip);
  position: absolute;
  z-index: 40;
  left: 0;
  top: calc(100% + 6px);
  width: 280px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--ink);
  color: var(--bg);
  font-size: 13px;
  line-height: 1.4;
  font-weight: 450;
  white-space: normal;
}
.neo-grid { display: grid; grid-template-columns: 1fr 1.3fr; gap: 16px; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 860px) {
  .span-5, .span-7, .neo-grid, .inds, .pair { grid-template-columns: 1fr; }
  .span-5, .span-7 { grid-column: span 12; }
  .mast, .sowhat { display: block; }
  .map { display: flex; flex-direction: column; }
  .mh, .rh { display: none; }
  .place { display: block; }
}
</style>
</head>
<body>
<div class="wrap">
<div class="grid">
"""

HTML_FOOT = """
</div>
</div>
<script>
(function () {
  var key = "vortex-theme";
  var root = document.documentElement;
  var button = document.getElementById("theme-toggle");
  function label(theme) {
    button.textContent = theme === "dark" ? "Use light mode" : "Use dark mode";
  }
  label(root.getAttribute("data-theme") || "dark");
  button.addEventListener("click", function () {
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem(key, next); } catch (e) {}
    label(next);
  });
})();
</script>
</body>
</html>
"""


def load_bundle(now: datetime) -> dict:
    quotes = {}
    for ticker in TICKERS:
        path = DATA / yahoo_name(ticker)
        if path.exists():
            loaded = load_yahoo(path)
            if loaded:
                quotes[ticker] = loaded
    status = load_json(DATA / "fetch_status.json") if (DATA / "fetch_status.json").exists() else {"failed": []}
    manual = load_json(DATA / "manual.json")
    judgment = load_json(DATA / "judgment.json")
    for key in ("A", "B", "C", "D_money", "D_demand", "F", "E"):
        if key not in judgment["probabilities"]:
            raise SystemExit(f"judgment probabilities missing {key}")
    if judgment.get("current_box") not in BOX_TITLE:
        raise SystemExit("judgment current_box is not a known box")
    changelog = load_json(DATA / "changelog.json")
    return {
        "now": now,
        "quotes": quotes,
        "status": status,
        "manual": manual,
        "judgment": judgment,
        "changelog": changelog,
        "dgs2": load_fred(DATA / "f_DGS2.csv") if (DATA / "f_DGS2.csv").exists() else [],
        "hy": load_fred(DATA / "f_BAMLH0A0HYM2.csv") if (DATA / "f_BAMLH0A0HYM2.csv").exists() else [],
        "ig": load_fred(DATA / "f_BAMLC0A0CM.csv") if (DATA / "f_BAMLC0A0CM.csv").exists() else [],
        "sofr": load_fred(DATA / "f_SOFR.csv") if (DATA / "f_SOFR.csv").exists() else [],
        "srf": load_fred(DATA / "f_RPONTSYD.csv") if (DATA / "f_RPONTSYD.csv").exists() else [],
        "claims": load_fred(DATA / "f_ICSA.csv") if (DATA / "f_ICSA.csv").exists() else [],
        "pay": load_fred(DATA / "f_PAYEMS.csv") if (DATA / "f_PAYEMS.csv").exists() else [],
        "unrate": load_fred(DATA / "f_UNRATE.csv") if (DATA / "f_UNRATE.csv").exists() else [],
        "cpi": load_fred_decimal(DATA / "f_CPILFESL.csv") if (DATA / "f_CPILFESL.csv").exists() else [],
        "funding": load_funding(DATA / "btcusdt_funding.json") if (DATA / "btcusdt_funding.json").exists() else [],
        "usde": load_usde(DATA / "usde.json") if (DATA / "usde.json").exists() else [],
    }


def privacy_scan(html: str) -> None:
    banned = [
        "beta.json", "0.6509", "184679", "variational", "dry powder", "liquidation",
        "fables", "drawdown", "rrpontsyd", "fund.json", "p&l", "p/l", "allocation",
        "text-overflow", "ellipsis", "nowrap",
    ]
    lowered = html.lower()
    for token in banned:
        if token in lowered:
            raise SystemExit("removed a forbidden or clipping string: " + token)
    if "overflow: hidden" in lowered or "overflow:hidden" in lowered:
        raise SystemExit("overflow hidden clips text")
    import re
    if re.search(r"(?<!m)NAV", html):
        raise SystemExit("stripped a NAV string that is not the MSTR multiple")
    if re.search(r"\bbeta\b", html, re.I):
        raise SystemExit("stripped a beta string")
    if "fetch(" in html:
        raise SystemExit("the page must not fetch at runtime")


def write_snapshots(bundle: dict, view: dict) -> None:
    latest = {"asof_sgt": view["built"], "description": "Latest print in each stored public series.", "series": {}}
    prev = {"asof_sgt": view["built"], "description": "Prior print in each stored public series.", "series": {}}
    for ticker, series in bundle["quotes"].items():
        bars = series["bars"]
        latest["series"][ticker] = {"value": bars[-1]["close"], "session": bars[-1]["session"].isoformat()}
        if len(bars) >= 2:
            prev["series"][ticker] = {"value": bars[-2]["close"], "session": bars[-2]["session"].isoformat()}
    for key, rows in (("DGS2", bundle["dgs2"]), ("BAMLH0A0HYM2", bundle["hy"]), ("BAMLC0A0CM", bundle["ig"]), ("SOFR", bundle["sofr"]), ("RPONTSYD", bundle["srf"])):
        if rows:
            latest["series"][key] = {"value": rows[-1][1], "session": rows[-1][0].isoformat()}
        if len(rows) >= 2:
            prev["series"][key] = {"value": rows[-2][1], "session": rows[-2][0].isoformat()}
    for name, payload in (("snapshot_latest.json", latest), ("snapshot_prev.json", prev)):
        path = DATA / name
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)


def main() -> int:
    self_check()
    if not (DATA / "judgment.json").exists():
        raise SystemExit("data/judgment.json is missing")
    now = datetime.now(SGT).replace(microsecond=0)
    bundle = load_bundle(now)
    checks = build_checks(bundle, 0, True)
    implied = implied_box([(item["box"], item["state"]) for item in checks])
    legs = build_legs(bundle, 0, True)
    lights = [(leg["name"], leg["light"]) for leg in legs]
    action, det, grey = action_of(lights)
    prev_lights = flags_only(bundle, 1)
    prev_action = action_of(prev_lights)[0]
    prev_checks = build_checks(bundle, 1, False)
    prev_implied = implied_box([(item["box"], item["state"]) for item in prev_checks])
    chosen = pick_closest(closest_candidates(bundle))
    if chosen:
        closest = f"{chosen['phrase']} Leg: {chosen['leg']}."
    else:
        closest = "No numeric red line could be measured from the loaded series."
    moves = build_moves(bundle)
    if prev_action == action:
        change_line = f"No. The prior daily prints also mapped to {action}."
    else:
        change_line = f"Yes. The prior daily prints mapped to {prev_action}. The latest prints map to {action}."
    implied_line = (
        f"Market-implied box on the prior window: {implied_label(prev_implied)}. "
        f"Latest: {implied_label(implied)}."
    )
    reason = reason_for(action, legs, det, grey)
    missing = [
        "Dec hike odds",
        "CRWV CDS",
        "CRWV unsecured yield",
        "SoftBank CDS",
        "Oracle CDS",
        "data-center loan auction price",
        "H100 rent",
        "B200 rent",
        "2027 capex guides",
        "MSTR multiple",
        "official SOFR range bounds",
    ]
    summary = {
        "built_sgt": fmt_dt(now),
        "current_box": bundle["judgment"]["current_box"],
        "probabilities": bundle["judgment"]["probabilities"],
        "market_implied": implied_label(implied),
        "disagrees": disagrees(bundle["judgment"]["current_box"], implied),
        "action": action,
        "reason": reason,
        "closest": closest,
        "changes": [item["text"] for item in moves],
        "change_line": change_line,
        "implied_line": implied_line,
        "leg_lights": lights,
        "missing": missing,
    }
    view = {
        "now": now,
        "built": fmt_dt(now),
        "judgment": bundle["judgment"],
        "quotes": bundle["quotes"],
        "changelog": bundle["changelog"],
        "checks": checks,
        "legs": legs,
        "implied": implied,
        "disagree": summary["disagrees"],
        "action": action,
        "reason": reason,
        "closest": closest,
        "moves": moves,
        "change_line": change_line,
        "implied_line": implied_line,
        "missing": missing,
        "summary": summary,
    }
    html = page(view)
    privacy_scan(html)
    if "SO WHAT".lower() not in html.lower() and "So what today" not in html:
        raise SystemExit("top strip missing")
    if "localStorage.getItem(\"vortex-theme\")" not in html and "vortex-theme" not in html:
        raise SystemExit("theme key missing")
    tmp = OUT.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(OUT)
    write_snapshots(bundle, view)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
