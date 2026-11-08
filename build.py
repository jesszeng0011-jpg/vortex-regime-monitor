#!/usr/bin/env python3
"""Build the one-page December monitor from public series and hand entries."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
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
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25), date(2027, 1, 1), date(2027, 1, 18),
}

PHRASE_DEPLOY = "beta toward 1.0"
PHRASE_STOP = "beta to ~0.25"
PHRASE_BASE = "deploy as B (beta 0.5–0.75)"
FOOTER = "Base case: deploy as B (beta 0.5–0.75) in tranches after each catalyst."

PRICES = [
    ("SPY", "B lead"),
    ("MSFT", "B lead"),
    ("GOOGL", "B lead"),
    ("AMZN", "B lead"),
    ("NVDA", "B/D cut first"),
    ("CRWV", "B/D cut first"),
    ("XLP", "D hedge"),
    ("GLD", "D hedge"),
    ("XLE", "C hedge"),
]


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


def add_month(year: int, month: int, step: int = 1) -> tuple[int, int]:
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
    if kind == "cpi" and (year, month) == (2026, 10):
        return datetime(2026, 11, 10, 21, 30, tzinfo=SGT)
    if kind == "cpi" and (year, month) == (2026, 11):
        return datetime(2026, 12, 10, 21, 30, tzinfo=SGT)
    if kind == "jobs" and (year, month) == (2026, 11):
        return datetime(2026, 12, 4, 21, 30, tzinfo=SGT)
    ny, nm = add_month(year, month, 1)
    if kind == "jobs":
        day = first_friday(ny, nm)
        return datetime(day.year, day.month, day.day, 21, 30, tzinfo=SGT)
    return datetime(ny, nm, 12, 21, 30, tzinfo=SGT)


def latest_released_month(now: datetime, kind: str) -> date:
    year, month = now.astimezone(SGT).year, now.astimezone(SGT).month
    for _ in range(36):
        if release_dt(kind, year, month) <= now:
            return date(year, month, 1)
        year, month = add_month(year, month, -1)
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


def daily_stale(session: date, now: datetime) -> bool:
    return trading_lag(session, latest_completed_session(now)) > 1


def fmt_dt(moment: datetime) -> str:
    moment = moment.astimezone(SGT)
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{moment.day} {months[moment.month - 1]} {moment.year}, {moment.hour:02d}:{moment.minute:02d} SGT"


def fmt_day(day: date) -> str:
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{day.day} {months[day.month - 1]} {day.year}"


def fmt_px(value: float) -> str:
    return f"{value:,.2f}"


def fmt_pct(frac: float) -> str:
    pct = frac * 100
    digits = 1 if abs(pct) >= 0.15 else 2
    return f"{pct:+.{digits}f}%"


def fmt_bp(change_pp: float) -> str:
    bp = change_pp * 100
    if abs(bp) >= 9.5:
        return f"{bp:+.0f}bp"
    return f"{bp:+.1f}bp"


def yahoo_name(ticker: str) -> str:
    return "y_" + ticker.replace("^", "%5E").replace("=", "%3D") + ".json"


def tip(text: str, detail: str, kind: str = "") -> str:
    classes = "tip"
    if text == DASH:
        classes += " na"
    elif kind:
        classes += " " + kind
    clean = " ".join(str(detail).split())
    return f'<span class="{classes}" tabindex="0" data-tip="{esc(clean)}">{esc(text)}</span>'


def spark(values: list[float], width: int = 72, height: int = 16) -> str:
    vals = [value for value in values if value is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    last = len(vals) - 1
    points = []
    for index, value in enumerate(vals):
        x = 1 + index * (width - 2) / last
        y = height - 1 - (value - lo) / span * (height - 2)
        points.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" aria-hidden="true">'
        f'<polyline fill="none" stroke="currentColor" stroke-width="1.2" points="{" ".join(points)}"/></svg>'
    )


def load_json(path: Path):
    return json.loads(path.read_text())


def load_fred(path: Path) -> list[tuple[date, float]]:
    rows = []
    for line in path.read_text().splitlines()[1:]:
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
    dedup = {}
    for stamp, value in zip(result.get("timestamp") or [], series):
        if stamp is None or value is None:
            continue
        session = datetime.fromtimestamp(int(stamp), NY).date()
        dedup[session] = {"session": session, "close": float(value), "ts": int(stamp)}
    bars = [dedup[key] for key in sorted(dedup)]
    if not bars:
        return None
    return {"high52": meta.get("fiftyTwoWeekHigh"), "bars": bars}


def load_bundle(now: datetime) -> dict:
    quotes = {}
    for ticker in [row[0] for row in PRICES] + ["NBIS", "SMH", "CL=F", "BZ=F"]:
        path = DATA / yahoo_name(ticker)
        if path.exists():
            loaded = load_yahoo(path)
            if loaded:
                quotes[ticker] = loaded
    judgment = load_json(DATA / "judgment.json")
    for key in ("A", "B", "C", "D_money", "D_demand", "F", "E"):
        if key not in judgment["probabilities"]:
            raise SystemExit(f"judgment is missing {key}")
    if judgment.get("current_box") != "B":
        raise SystemExit("judgment current box is not B")
    return {
        "now": now,
        "quotes": quotes,
        "judgment": judgment,
        "manual": load_json(DATA / "manual.json"),
        "catalysts": load_json(DATA / "catalysts.json"),
        "status": load_json(DATA / "fetch_status.json") if (DATA / "fetch_status.json").exists() else {"failed": []},
        "dgs2": load_fred(DATA / "f_DGS2.csv") if (DATA / "f_DGS2.csv").exists() else [],
        "hy": load_fred(DATA / "f_BAMLH0A0HYM2.csv") if (DATA / "f_BAMLH0A0HYM2.csv").exists() else [],
        "sofr": load_fred(DATA / "f_SOFR.csv") if (DATA / "f_SOFR.csv").exists() else [],
        "claims": load_fred(DATA / "f_ICSA.csv") if (DATA / "f_ICSA.csv").exists() else [],
        "pay": load_fred(DATA / "f_PAYEMS.csv") if (DATA / "f_PAYEMS.csv").exists() else [],
        "cpi": load_fred_decimal(DATA / "f_CPILFESL.csv") if (DATA / "f_CPILFESL.csv").exists() else [],
        "silicon": load_json(DATA / "silicon_index.json") if (DATA / "silicon_index.json").exists() else None,
    }


def session_phrase(bar: dict) -> str:
    return f"Session {fmt_day(bar['session'])}, print {fmt_dt(datetime.fromtimestamp(bar['ts'], SGT))}."


def ret(bars: list[dict], sessions: int) -> float | None:
    if len(bars) <= sessions or not bars[-(sessions + 1)]["close"]:
        return None
    return bars[-1]["close"] / bars[-(sessions + 1)]["close"] - 1


def cpi_prints(rows) -> list[dict]:
    out = []
    for older, newer in zip(rows, rows[1:]):
        if not older[1]:
            continue
        raw = (newer[1] / older[1] - 1) * Decimal(100)
        out.append({"month": newer[0], "raw": raw, "published": round_tenth(raw)})
    return out


def rent_change(rows: list[dict], days: int) -> tuple[float | None, int | None]:
    if len(rows) < 2:
        return None, None
    last = date.fromisoformat(rows[-1]["date"])
    target = last - timedelta(days=days)
    prior = min(rows[:-1], key=lambda row: abs((date.fromisoformat(row["date"]) - target).days))
    span = (last - date.fromisoformat(prior["date"])).days
    if not prior["value"]:
        return None, span
    return rows[-1]["value"] / prior["value"] - 1, span


def failure_note(status: dict, needle: str) -> str:
    for item in status.get("failed") or []:
        if needle in str(item.get("id", "")):
            return " Latest refresh failed: " + " ".join(str(item.get("error", "")).split())[:140]
    return ""


def money_is_red(auction_state: str, funding_flag: bool) -> bool:
    return auction_state == "red" and funding_flag


def header_action(money_red: bool, hy_red: bool) -> str:
    if money_red or hy_red:
        return "CUT"
    return "HOLD"


def visible_catalyst(event: dict, now: datetime) -> bool:
    when = datetime.fromisoformat(event["when_sgt"])
    return now - timedelta(days=2) <= when <= now + timedelta(days=14)


def scorecard_open(event: dict, now: datetime) -> bool:
    """Open only on the report's SGT day, through two days after the report time."""
    if not event.get("scorecard"):
        return False
    when = datetime.fromisoformat(event["when_sgt"])
    start = when.astimezone(SGT).replace(hour=0, minute=0, second=0, microsecond=0)
    return start <= now <= when + timedelta(days=2)


def self_check() -> None:
    now = datetime(2026, 11, 8, 22, 49, tzinfo=SGT)
    assert latest_completed_session(now) == date(2026, 11, 6)
    assert trading_lag(date(2026, 11, 5), date(2026, 11, 6)) == 1
    assert weekly_stale(date(2026, 10, 31), now) is False
    assert latest_released_month(now, "cpi") == date(2026, 9, 1)
    assert latest_released_month(now, "jobs") == date(2026, 10, 1)
    aug = (Decimal("337.765") / Decimal("336.789") - 1) * 100
    sep = (Decimal("338.896") / Decimal("337.765") - 1) * 100
    assert round_tenth(aug) == Decimal("0.3")
    assert round_tenth(sep) == Decimal("0.3")
    assert header_action(False, False) == "HOLD"
    assert header_action(True, False) == "CUT"
    assert header_action(False, True) == "CUT"
    assert money_is_red("red", True) is True
    assert money_is_red("pending", True) is False
    assert money_is_red("yellow", True) is False
    sample = [
        {"when_sgt": "2026-11-10T15:30:00+08:00", "id": "a"},
        {"when_sgt": "2026-11-25T21:30:00+08:00", "id": "b"},
        {"when_sgt": "2026-12-17T09:00:00+08:00", "id": "c"},
    ]
    shown = [row["id"] for row in sample if visible_catalyst(row, now)]
    assert shown == ["a"]
    page = f"Deploy fully ({PHRASE_DEPLOY}). Stop ({PHRASE_STOP}). {FOOTER} Book beta 0.65"
    privacy_scan(page)
    softbank = {"scorecard": True, "when_sgt": "2026-11-10T15:30:00+08:00"}
    assert scorecard_open(softbank, now) is False
    assert scorecard_open(softbank, datetime(2026, 11, 10, 8, 0, tzinfo=SGT)) is True
    assert scorecard_open(softbank, datetime(2026, 11, 12, 16, 0, tzinfo=SGT)) is False
    try:
        privacy_scan(page + " extra " + "".join(chr(code) for code in (98, 101, 116, 97)))
    except SystemExit:
        pass
    else:
        raise SystemExit("privacy scan missed a stray phrase")
    try:
        privacy_scan(page + " " + "".join(chr(code) for code in (48, 46, 54, 53, 48, 57)))
    except SystemExit:
        pass
    else:
        raise SystemExit("privacy scan missed an unrounded figure")


def _needles() -> list[str]:
    def word(text: str) -> str:
        return text

    encoded = [
        [48, 46, 54, 53, 48, 57],
        [102, 117, 110, 100, 46, 106, 115, 111, 110],
        [98, 101, 116, 97, 46, 106, 115, 111, 110],
        [108, 105, 113, 117, 105, 100, 97, 116, 105, 111, 110],
        [100, 114, 121, 32, 112, 111, 119, 100, 101, 114],
        [86, 97, 114, 105, 97, 116, 105, 111, 110, 97, 108],
        [70, 97, 98, 108, 101, 115],
        [100, 114, 97, 119, 100, 111, 119, 110],
        [97, 108, 108, 111, 99, 97, 116, 105, 111, 110],
        [82, 82, 80, 79, 78, 84, 83, 89, 68],
    ]
    needles = ["".join(chr(code) for code in row) for row in encoded]
    needles.extend([
        "".join(chr(code) for code in row)
        for row in ([80, 38, 76], [80, 47, 76], [65, 85, 77], [78, 65, 86])
    ])
    return [word(item) for item in needles]


def privacy_scan(html: str, layout: bool = False) -> None:
    cleaned = html
    for phrase in (PHRASE_DEPLOY, PHRASE_STOP, PHRASE_BASE, "Book beta"):
        cleaned = cleaned.replace(phrase, "")
    lowered = cleaned.lower()
    token = "".join(chr(code) for code in (98, 101, 116, 97))
    if re.search(r"(?<![\w])" + token + r"(?![\w])", lowered):
        raise SystemExit("privacy scan found a phrase outside the December memo lines")
    for needle in _needles():
        if needle.lower() in lowered:
            raise SystemExit("privacy scan failed")
    if layout:
        clip = ["".join(chr(c) for c in row) for row in (
            [116, 101, 120, 116, 45, 111, 118, 101, 114, 102, 108, 111, 119],
            [101, 108, 108, 105, 112, 115, 105, 115],
            [110, 111, 119, 114, 97, 112],
            [111, 118, 101, 114, 102, 108, 111, 119, 58, 104, 105, 100, 100, 101, 110],
            [111, 118, 101, 114, 102, 108, 111, 119, 58, 32, 104, 105, 100, 100, 101, 110],
        )]
        if any(token in lowered for token in clip):
            raise SystemExit("layout clips text")
    if "".join(chr(code) for code in (102, 101, 116, 99, 104, 40)) in html:
        raise SystemExit("the page must not fetch")


def build_view(bundle: dict) -> dict:
    now = bundle["now"]
    quotes = bundle["quotes"]
    status = bundle["status"]
    manual = bundle["manual"]

    prints = cpi_prints(bundle["cpi"])
    core = prints[-1] if prints else None
    prior = prints[-2] if len(prints) > 1 else None
    cpi_old = core is None or monthly_stale(core["month"], now, "cpi")
    dgs = bundle["dgs2"]
    dgs_old = len(dgs) < 21 or daily_stale(dgs[-1][0], now)
    rates_bp = (dgs[-1][1] - dgs[-21][1]) if len(dgs) >= 21 else None
    rates_up = bool(rates_bp is not None and rates_bp > 0)
    twice = bool(core and prior and core["published"] >= Decimal("0.3") and prior["published"] >= Decimal("0.3"))
    core_hot = bool(core and core["published"] >= Decimal("0.3") and not cpi_old)

    def px(ticker: str):
        series = quotes.get(ticker)
        if not series:
            return None
        return series["bars"]

    brent, wti = px("BZ=F"), px("CL=F")
    brent_px = brent[-1]["close"] if brent else None
    wti_px = wti[-1]["close"] if wti else None
    oil_old = True
    if brent and not daily_stale(brent[-1]["session"], now):
        oil_old = False
    if wti and not daily_stale(wti[-1]["session"], now):
        oil_old = False
    if brent is None and wti is None:
        oil_old = True
    oil_red = ((brent_px is not None and brent_px > 100) or (wti_px is not None and wti_px > 100)) and not oil_old
    oil_yellow = ((brent_px is not None and brent_px > 95) or (wti_px is not None and wti_px > 95)) and not oil_old
    full_core_red = bool(twice and rates_up and not cpi_old and not dgs_old)
    if (full_core_red or oil_red) and not (cpi_old and oil_old):
        inflation = "red"
    elif (core_hot or oil_yellow) and not (cpi_old and oil_old):
        inflation = "yellow"
    elif cpi_old or oil_old or dgs_old:
        inflation = "missing"
    else:
        inflation = "green"

    claims = bundle["claims"]
    claims_old = len(claims) < 4 or weekly_stale(claims[-1][0], now)
    claims_avg = sum(row[1] for row in claims[-4:]) / 4 if len(claims) >= 4 else None
    prev_claims = sum(row[1] for row in claims[-5:-1]) / 4 if len(claims) >= 5 else None
    pay = bundle["pay"]
    pay_old = len(pay) < 2 or monthly_stale(pay[-1][0], now, "jobs")
    pay_change = pay[-1][1] - pay[-2][1] if len(pay) >= 2 else None
    growth_red = bool(claims_avg is not None and claims_avg > 227_000 and pay_change is not None and pay_change < 0 and not claims_old and not pay_old)
    if growth_red:
        growth = "red"
    elif claims_old or pay_old:
        growth = "missing"
    else:
        growth = "green"

    texas = manual["texas"]
    texas_asof = datetime.fromisoformat(texas["asof_sgt"])
    texas_old = manual_stale(texas_asof, now)
    rules_red = bool((texas.get("signed_ban") or texas.get("grid_pause_confirmed")) and not texas_old)
    rules = "red" if rules_red else ("missing" if texas_old else "green")

    yield_m = manual["crwv_yield"]
    cds_m = manual["crwv_cds"]
    yield_old = manual_stale(datetime.fromisoformat(yield_m["asof_sgt"]), now)
    cds_old = manual_stale(datetime.fromisoformat(cds_m["asof_sgt"]), now)
    funding_flag = yield_m.get("label", "").startswith(">") and not yield_old
    auction_state = "pending"
    money_red = money_is_red(auction_state, funding_flag)
    if money_red:
        money = "red"
    elif funding_flag:
        money = "yellow"
    elif yield_old and cds_old:
        money = "missing"
    else:
        money = "green"

    silicon = bundle["silicon"]
    rent_manual = False
    h100_rows = b200_rows = None
    if silicon and silicon.get("series", {}).get("h100", {}).get("rows") and silicon.get("series", {}).get("b200", {}).get("rows"):
        h100_rows = silicon["series"]["h100"]["rows"]
        b200_rows = silicon["series"]["b200"]["rows"]
    else:
        rent_manual = True
    h100_1m = b200_1m = None
    h100_span = b200_span = None
    h100_1w = b200_1w = None
    rents_old = True
    if h100_rows and b200_rows:
        h100_day = date.fromisoformat(h100_rows[-1]["date"])
        b200_day = date.fromisoformat(b200_rows[-1]["date"])
        rents_old = (now.astimezone(SGT).date() - max(h100_day, b200_day)).days > 1
        h100_1m, h100_span = rent_change(h100_rows, 30)
        b200_1m, b200_span = rent_change(b200_rows, 30)
        h100_1w, _ = rent_change(h100_rows, 7)
        b200_1w, _ = rent_change(b200_rows, 7)
    rent_drop_10 = bool((h100_1m is not None and h100_1m <= -0.10) or (b200_1m is not None and b200_1m <= -0.10))
    rent_drop_20 = bool((h100_1m is not None and h100_1m <= -0.20) or (b200_1m is not None and b200_1m <= -0.20))
    capex_cut = False
    if rents_old or h100_1m is None or b200_1m is None:
        demand = "missing"
    elif rent_drop_20 and capex_cut:
        demand = "red"
    elif rent_drop_10:
        demand = "yellow"
    else:
        demand = "green"

    hy = bundle["hy"]
    sofr = bundle["sofr"]
    hy_old = len(hy) < 2 or daily_stale(hy[-1][0], now)
    sofr_old = len(sofr) < 1 or daily_stale(sofr[-1][0], now)
    hy_red_level = bool(hy and hy[-1][1] > 4.5 and not hy_old)
    hy_yellow = bool(hy and hy[-1][1] > 4.0 and not hy_old)
    sofr_above = False
    hy_red = hy_red_level and sofr_above
    if hy_red:
        spill = "red"
    elif hy_yellow:
        spill = "yellow"
    elif hy_old:
        spill = "missing"
    else:
        spill = "green"

    legs = {
        "inflation": inflation,
        "growth": growth,
        "rules": rules,
        "money": money,
        "demand": demand,
        "spill": spill,
    }
    action = header_action(legs["money"] == "red", hy_red)

    hy_gap = (4.5 - hy[-1][1]) if hy and not hy_old else None
    closest = "Closest to CUT: HY OAS is not loaded."
    if hy_gap is not None:
        closest = f"Closest to CUT: HY OAS, {abs(hy_gap) * 100:.0f}bp {'through' if hy_gap < 0 else 'under'} 4.5%."
    if legs["money"] == "red" or hy_red:
        closest = "A stop item is already on."

    if inflation == "yellow":
        why = "Inflation is yellow"
    elif inflation == "red":
        why = "Inflation is red"
    elif inflation == "green":
        why = "Inflation is green"
    else:
        why = "Inflation is missing"
    if action == "CUT":
        why = "A stop item has triggered"
    else:
        why = why + "; the stop list is clear"
    reason = f"{why}. {closest}"

    events = []
    for row in bundle["catalysts"]:
        when = datetime.fromisoformat(row["when_sgt"])
        events.append({**row, "when": when})
    events.sort(key=lambda row: row["when"])
    upcoming = [row for row in events if row["when"] > now]
    nxt = upcoming[0] if upcoming else None
    shown = [row for row in events if visible_catalyst(row, now)]

    return {
        "now": now,
        "legs": legs,
        "action": action,
        "reason": reason,
        "closest": closest,
        "core": core,
        "prior": prior,
        "cpi_old": cpi_old,
        "rates_bp": rates_bp,
        "rates_up": rates_up,
        "twice": twice,
        "dgs": dgs,
        "dgs_old": dgs_old,
        "brent": brent,
        "wti": wti,
        "brent_px": brent_px,
        "wti_px": wti_px,
        "oil_old": oil_old,
        "claims": claims,
        "claims_avg": claims_avg,
        "prev_claims": prev_claims,
        "claims_old": claims_old,
        "pay": pay,
        "pay_change": pay_change,
        "pay_old": pay_old,
        "texas": texas,
        "texas_old": texas_old,
        "yield_m": yield_m,
        "cds_m": cds_m,
        "yield_old": yield_old,
        "cds_old": cds_old,
        "h100_rows": h100_rows,
        "b200_rows": b200_rows,
        "rent_manual": rent_manual,
        "rents_old": rents_old,
        "h100_1m": h100_1m,
        "b200_1m": b200_1m,
        "h100_1w": h100_1w,
        "b200_1w": b200_1w,
        "h100_span": h100_span,
        "b200_span": b200_span,
        "hy": hy,
        "sofr": sofr,
        "hy_old": hy_old,
        "sofr_old": sofr_old,
        "hy_gap": hy_gap,
        "quotes": quotes,
        "status": status,
        "silicon": silicon,
        "nxt": nxt,
        "shown": shown,
        "events": events,
        "deploy_met": 0,
        "stop_hit": int(legs["money"] == "red") + int(hy_red),
        "hy_red": hy_red,
        "book_beta": manual.get("book_beta"),
    }


def countdown(target: datetime, now: datetime) -> str:
    seconds = int((target - now).total_seconds())
    if seconds <= 0:
        return "now"
    days, rem = divmod(seconds, 86400)
    hours = rem // 3600
    if days:
        return f"in {days}d {hours}h"
    return f"in {hours}h"


def move_class(value: float | None) -> str:
    if value is None or value == 0:
        return ""
    return "up" if value > 0 else "down"


def tile(name: str, light: str, key_html: str, change_html: str, body: str, to_red: str, key_class: str = "key") -> str:
    label = {"green": "Green", "yellow": "Yellow", "red": "Red", "missing": "Missing"}.get(light, light)
    change = f'<span class="chg">{change_html}</span>' if change_html else ""
    return (
        f'<article class="tile {esc(light)}">'
        f'<div class="top"><span class="name">{esc(name)}</span><span class="lamp {esc(light)}">{esc(label)}</span></div>'
        f'<div class="keyline"><span class="{esc(key_class)}">{key_html}</span>{change}</div>'
        f'<div class="rest">{body}</div>'
        f'<p class="to">to red: {to_red}</p>'
        f"</article>"
    )


def inflation_tile(view: dict) -> str:
    core, prior = view["core"], view["prior"]
    if core:
        kind = "st-yellow" if view["legs"]["inflation"] == "yellow" else ("st-red" if view["legs"]["inflation"] == "red" else "")
        if view["cpi_old"]:
            kind = "na"
        core_html = tip(
            f"{core['published']:.1f}%",
            f"FRED CPILFESL. Published month-on-month change, half up to one decimal. "
            f"Unrounded {core['raw']:.3f}%. Month {fmt_day(core['month'])}."
            + (f" Prior published {prior['published']:.1f}%." if prior else ""),
            kind,
        )
    else:
        core_html = tip(DASH, "FRED CPILFESL was not loaded.")
    if view["rates_bp"] is not None and not view["dgs_old"]:
        dgs = view["dgs"]
        rate_html = tip(
            fmt_bp(view["rates_bp"]) + "/20d",
            f"FRED DGS2, from {dgs[-21][1]:.2f}% on {fmt_day(dgs[-21][0])} to {dgs[-1][1]:.2f}% on {fmt_day(dgs[-1][0])}. Not a bill or 10-year yield.",
        )
    else:
        rate_html = tip(DASH, "FRED DGS2 was not loaded or is old." + failure_note(view["status"], "fred DGS2"))
    def oil_html(label, ticker, bars, value):
        if not bars or value is None:
            return tip(DASH, f"{label} was not loaded." + failure_note(view["status"], ticker))
        kind = ""
        if not view["oil_old"]:
            if value > 100:
                kind = "st-red"
            elif value > 95:
                kind = "st-yellow"
        week = ret(bars, 5)
        week_txt = "" if week is None else " " + fmt_pct(week) + " 1w"
        return tip(f"{label} {value:,.2f}", f"Yahoo Finance {ticker}. {session_phrase(bars[-1])}", kind) + esc(week_txt)
    missing = []
    if view["twice"] and not view["rates_up"]:
        missing.append("two 0.3% prints are in, and the 2-year yield is not up")
    elif view["core"] and view["core"]["published"] >= Decimal("0.3"):
        missing.append("needs a second core print at or above 0.3% with the 2-year yield up")
    else:
        missing.append("core is under 0.3%")
    missing.append("oil is under $100")
    return tile(
        "Inflation",
        view["legs"]["inflation"],
        core_html,
        "",
        "2Y " + rate_html + "<br>" + oil_html("Brent", "BZ=F", view["brent"], view["brent_px"]) + " · " + oil_html("WTI", "CL=F", view["wti"], view["wti_px"]),
        esc("; ".join(missing)) + ".",
    )


def growth_tile(view: dict) -> str:
    if view["claims_avg"] is None:
        claims_html = tip(DASH, "FRED ICSA was not loaded.")
        week = ""
    else:
        kind = "na" if view["claims_old"] else ""
        claims = view["claims"]
        claims_html = tip(
            f"{view['claims_avg'] / 1000:.1f}k",
            f"FRED ICSA, 4-week average. Latest week {fmt_day(claims[-1][0])} {claims[-1][1]:,.0f}.",
            kind,
        )
        if view["prev_claims"] is not None:
            week = " 1w " + tip(f"{(view['claims_avg'] - view['prev_claims']) / 1000:+.1f}k", "Change in the 4-week average versus the prior week.")
        else:
            week = ""
    if view["pay_change"] is None:
        pay_html = tip(DASH, "FRED PAYEMS was not loaded.")
    else:
        pay = view["pay"]
        pay_html = tip(
            f"{view['pay_change']:+,.0f}k",
            f"FRED PAYEMS monthly change, thousands of persons. {fmt_day(pay[-2][0])} to {fmt_day(pay[-1][0])}.",
            "na" if view["pay_old"] else "",
        )
    delta = None
    if view["claims_avg"] is not None and view["prev_claims"] is not None:
        delta = view["claims_avg"] - view["prev_claims"]
    change = week if delta is None else tip(f"{delta / 1000:+.1f}k", "Change in the 4-week average versus the prior week.", move_class(delta))
    return tile(
        "Growth",
        view["legs"]["growth"],
        claims_html,
        change,
        "Payrolls " + pay_html,
        "claims above 227k and payrolls below zero.",
    )


def rules_tile(view: dict) -> str:
    texas = view["texas"]
    kind = "na" if view["texas_old"] else ""
    line = tip(texas["line"], f"Manual {fmt_dt(datetime.fromisoformat(texas['asof_sgt']))}. {texas['source']}", kind)
    return tile(
        "AI rules",
        view["legs"]["rules"],
        line,
        "",
        "",
        "a signed ban in a major state, or a confirmed grid pause.",
        key_class="key sentence",
    )


def ratio_bits(view: dict) -> tuple[str, str]:
    quotes = view["quotes"]
    if "NBIS" not in quotes or "CRWV" not in quotes:
        return tip(DASH, "NBIS or CRWV was not loaded."), ""
    left = {bar["session"]: bar["close"] for bar in quotes["NBIS"]["bars"]}
    right = {bar["session"]: bar["close"] for bar in quotes["CRWV"]["bars"]}
    dates = [day for day in sorted(set(left) & set(right)) if right[day]]
    vals = [left[day] / right[day] for day in dates]
    if len(vals) < 2:
        return tip(DASH, "The shared NBIS and CRWV history is too short."), ""
    one = vals[-1] / vals[-2] - 1
    week = vals[-1] / vals[-6] - 1 if len(vals) >= 6 else None
    detail = (
        f"NBIS close divided by CRWV close on {fmt_day(dates[-1])}. "
        f"1d {fmt_pct(one)}" + (f", 5 sessions {fmt_pct(week)}." if week is not None else ".")
        + " A ratio, not a price difference. " + session_phrase(quotes["CRWV"]["bars"][-1])
    )
    number = tip(f"{vals[-1]:.2f}", detail)
    week_html = "" if week is None else tip(fmt_pct(week), "Five-session change in the NBIS/CRWV ratio.", move_class(week))
    return number + ((" " + week_html) if week_html else "") + spark(vals[-30:]), ""


def money_tile(view: dict) -> str:
    y = view["yield_m"]
    c = view["cds_m"]
    y_html = tip(y["label"], f"Manual {fmt_dt(datetime.fromisoformat(y['asof_sgt']))}. {y['source']}", "na" if view["yield_old"] else "st-yellow")
    c_html = tip(c["label"], f"Manual {fmt_dt(datetime.fromisoformat(c['asof_sgt']))}. {c['source']}", "na" if view["cds_old"] else "")
    ratio, _week = ratio_bits(view)
    return tile(
        "AI money",
        view["legs"]["money"],
        y_html,
        "",
        "CDS " + c_html + "<br>NBIS/CRWV " + ratio,
        "auction below 90% of par, or pulled, and a CRWV funding flag. Bids 19 Nov; no auction print yet.",
    )


def demand_tile(view: dict) -> str:
    if view["h100_rows"] and view["b200_rows"] and not view["rent_manual"]:
        h100 = view["h100_rows"][-1]
        b200 = view["b200_rows"][-1]
        h_tip = (
            f"Silicon Data H100 index, public page, {h100['date']}. "
            f"1-month change uses a {view['h100_span']}-day span in that table."
            + failure_note(view["status"], "silicon")
        )
        b_tip = (
            f"Silicon Data B200 index, public page, {b200['date']}. "
            f"1-month change uses a {view['b200_span']}-day span in that table."
        )
        kind = "na" if view["rents_old"] else ""
        h_html = tip(f"${h100['value']:.2f}", h_tip, kind)
        b_html = tip(f"${b200['value']:.2f}", b_tip, kind)
        def chg(value, label):
            if value is None:
                return tip(DASH, label + " change was not in the table.")
            return tip(fmt_pct(value), label)
        one_m = "1m " + chg(view["h100_1m"], "H100") + " / " + chg(view["b200_1m"], "B200")
        one_w = "1w " + chg(view["h100_1w"], "H100") + " / " + chg(view["b200_1w"], "B200")
        mark = ""
    else:
        manual = view["manual"]["silicon_data"] if False else None
        # manual fallback is read from the file in the bundle via the tile caller's view; use the stored manual through a direct read below
        h_html = tip(DASH, "Silicon Data index was not parsed." + failure_note(view["status"], "silicon"))
        b_html = h_html
        one_m = "1m " + tip(DASH, "No 1-month change without a history.")
        one_w = ""
        mark = ""
    # Prefer live rows. Manual path is filled here when rows are missing.
    if not view["h100_rows"]:
        manual = json_manual_rents()
        h_html = tip(f"${manual['h100_usd']:.2f}", f"Manual {manual['asof_sgt']}. {manual['source']}", "na")
        b_html = tip(f"${manual['b200_usd']:.2f}", f"Manual {manual['asof_sgt']}. {manual['source']}", "na")
        one_m = "1m " + tip(DASH, "The manual note has no 1-month history.")
        one_w = ""
        mark = " manual"
    h100_week = view["h100_1w"] if not view["rent_manual"] else None
    change = ""
    if h100_week is not None:
        change = tip(fmt_pct(h100_week), "H100 index, about seven days.", move_class(h100_week))
    return tile(
        "AI demand",
        view["legs"]["demand"],
        h_html,
        change,
        f"B200 {b_html}{mark}" + ((" · " + one_m) if one_m else ""),
        "a 20% monthly drop and a 2027 capex cut that cites demand. Yellow is a 10% monthly drop.",
    )


def json_manual_rents() -> dict:
    return load_json(DATA / "manual.json")["silicon_data"]


def spill_tile(view: dict) -> str:
    hy = view["hy"]
    if hy and not view["hy_old"]:
        week = fmt_bp(hy[-1][1] - hy[-6][1]) + " 1w" if len(hy) >= 6 else ""
        hy_html = tip(f"{hy[-1][1]:.2f}%", f"FRED BAMLH0A0HYM2. Observation {fmt_day(hy[-1][0])}.", "")
        week_html = "" if not week else " " + tip(week, f"Change versus {fmt_day(hy[-6][0])}.")
    else:
        hy_html = tip(DASH, "FRED HY OAS was not loaded or is old.")
        week_html = ""
    if view["sofr"] and not view["sofr_old"]:
        sofr = view["sofr"]
        sofr_html = tip(f"{sofr[-1][1]:.2f}%", f"FRED SOFR. Observation {fmt_day(sofr[-1][0])}.")
    else:
        sofr_html = tip(DASH, "FRED SOFR was not loaded or is old.")
    range_html = tip(DASH, "Official SOFR range bounds were not loaded. The above-range half is not treated as met.")
    hy_delta = None
    if view["hy"] and len(view["hy"]) >= 6 and not view["hy_old"]:
        hy_delta = view["hy"][-1][1] - view["hy"][-6][1]
    change = week_html
    if hy_delta is not None:
        change = tip(fmt_bp(hy_delta), f"Change versus {fmt_day(view['hy'][-6][0])}.", move_class(hy_delta))
    return tile(
        "Spillover",
        view["legs"]["spill"],
        hy_html,
        change,
        "SOFR " + sofr_html + " · range " + range_html,
        "HY above 4.5% and SOFR above its official range. Yellow is HY above 4.0%.",
    )


def checklist(view: dict) -> str:
    deploy = [
        ("Oct core at or below 0.2%", "10 Nov", "pending"),
        ("Fed signals an end, or flat 2027 dots", "10 Dec", "pending"),
        ("Payrolls above zero", "4 Dec", "pending"),
        ("CRWV yield falling and auction at or above 95% of par", "19 Nov", "pending"),
        ("Nvidia orders intact", "18 Nov", "pending"),
    ]
    stop = [
        ("AI money leg red", "clear" if view["legs"]["money"] != "red" else "triggered", "hit" if view["legs"]["money"] == "red" else "clear"),
        ("HY OAS above 4.5%", "clear" if not view["hy_red"] else "triggered", "hit" if view["hy_red"] else "clear"),
    ]

    def icon(state: str) -> str:
        if state == "met":
            return '<span class="mark good">✓</span>'
        if state in ("hit", "failed"):
            return '<span class="mark bad">✗</span>'
        if state == "clear":
            return '<span class="mark wait">○</span>'
        return '<span class="mark wait">○</span>'

    def rows(items) -> str:
        out = []
        for text, when, state in items:
            out.append(
                f'<li class="crow">{icon(state)}<span class="clabel">{esc(text)}</span>'
                f'<span class="cwhen">{esc(when)}</span></li>'
            )
        return "".join(out)

    met = sum(1 for _, _, state in deploy if state == "met")
    hit = sum(1 for _, _, state in stop if state == "hit")
    def bar(done: int, total: int) -> str:
        width = 0 if total == 0 else round(100 * done / total)
        return f'<div class="prog"><i style="width:{width}%"></i></div>'
    return (
        f'<div class="box"><h2>Deploy fully ({esc(PHRASE_DEPLOY)})</h2>'
        f'<p class="count">{met}/5 met</p>{bar(met, 5)}<ul>{rows(deploy)}</ul></div>'
        f'<div class="box"><h2>Stop ({esc(PHRASE_STOP)})</h2>'
        f'<p class="count">{hit}/2 triggered</p>{bar(hit, 2)}<ul>{rows(stop)}</ul></div>'
        f'<p class="foot">{esc(FOOTER)}</p>'
    )


def reaction_text(hit: str, event: dict, view: dict) -> str:
    now = view["now"]
    if now < event["when"]:
        return ""
    if hit == "CRWV yield":
        return "CRWV yield " + DASH
    if hit == "2Y":
        return "2Y " + DASH
    series = view["quotes"].get(hit)
    if not series:
        return f"{hit} {DASH}"
    # 1-day reaction: the session that contains the event, versus the prior session.
    when_ny = event["when"].astimezone(NY)
    session = when_ny.date()
    if not is_trading_day(session) or when_ny.hour >= 16:
        session = session + timedelta(days=1)
        while not is_trading_day(session):
            session += timedelta(days=1)
    bars = {bar["session"]: bar for bar in series["bars"]}
    if session not in bars:
        return f"{hit} {DASH}"
    prev = prev_trading_day(session)
    if prev not in bars or not bars[prev]["close"]:
        return f"{hit} {DASH}"
    change = bars[session]["close"] / bars[prev]["close"] - 1
    return f"{hit} {fmt_pct(change)}"


def leg_chip(name: str) -> str:
    low = name.lower()
    kind = "rules"
    if "money" in low:
        kind = "money"
    elif "demand" in low:
        kind = "demand"
    elif "inf" in low:
        kind = "inflation"
    elif "growth" in low:
        kind = "growth"
    return f'<span class="chip leg {kind}">{esc(name)}</span>'


def split_when(label: str) -> tuple[str, str]:
    parts = label.split(" ", 2)
    if len(parts) >= 3:
        return parts[0] + " " + parts[1], parts[2]
    return label, ""


def catalyst_block(view: dict) -> str:
    chunks = []
    for event in view["shown"]:
        if view["now"] >= event["when"]:
            bits = [reaction_text(hit, event, view) for hit in event["hits"]]
            result = ", ".join(bit for bit in bits if bit) or DASH
            result_html = esc(result)
        else:
            result_html = '<span class="na">pending</span>'
        chips = "".join(f'<span class="chip">{esc(hit)}</span>' for hit in event["hits"]) or f'<span class="chip">{DASH}</span>'
        day, clock = split_when(event["label"])
        ready = ""
        cards = ""
        if event.get("scorecard"):
            if scorecard_open(event, view["now"]):
                cards = scorecard_html(event)
            else:
                ready = '<span class="ready">Scorecard ready · 3 questions</span>'
        chunks.append(
            f'<article class="ev"><div class="twhen"><b>{esc(day)}</b><span>{esc(clock)}</span></div>'
            f'<div class="emain"><div class="etop"><b>{esc(event["event"])}</b>{leg_chip(event["leg"])}{chips}{ready}</div>{cards}</div>'
            f'<div class="eresult">{result_html}</div></article>'
        )
    return "".join(chunks)


def scorecard_html(event: dict) -> str:
    op_note = "Pending. Green only if the operating-income dollar gain is larger."
    if event["id"] == "crwv-q3":
        op_body = (
            esc(op_note + " Pre-report guide midpoints, not Q3 actuals: op. income +$102M vs interest +$260M, ")
            + '<span class="lamp red">gap widening</span>.'
        )
    else:
        op_body = esc(op_note)
    cards = [
        ("Interest vs guide", esc("Pending. Red if above the company guide."), "pending"),
        ("Op. income $ vs interest $", op_body, "pending"),
        ("Next 12 months", esc("Pending. Debt due vs cash and undrawn. 2027 plan: prepay, new debt, equity."), "pending"),
    ]
    # Rate, capex, and the 48-hour CDS rule stay with the scorecard once it opens.
    extra = esc("New rate ≥15% red, ≤12% green. Capex cut for funding is red; for power or permits it is F. CDS 48h: +100bp red, −100bp green. Pending.")
    body = "".join(
        f'<article class="qcard"><p class="qlabel">{esc(title)}</p><p class="qstate na">{state}</p><p>{text}</p></article>'
        for title, text, state in cards
    )
    return f'<div class="qcards">{body}</div><p class="ready">{extra}</p>'


def price_cells(ticker: str, view: dict) -> str:
    since = tip(DASH, "No catalyst in the list has occurred yet, so there is no post-event move.")
    series = view["quotes"].get(ticker)
    if not series:
        blank = f"<td class='num na'>{DASH}</td>"
        return f"<tr><td>{esc(ticker)}</td>{blank * 3}<td></td><td class='num'>{since}</td></tr>"
    bars = series["bars"]
    last = bars[-1]
    one = ret(bars, 1)
    five = ret(bars, 5)
    price = tip(fmt_px(last["close"]), f"Yahoo Finance {ticker}. {session_phrase(last)}")
    one_html = tip(fmt_pct(one), "Prior session to the latest session.", move_class(one)) if one is not None else tip(DASH, "No prior session.")
    five_html = tip(fmt_pct(five), "Five sessions back to the latest session.", move_class(five)) if five is not None else tip(DASH, "Not enough sessions.")
    line = spark([bar["close"] for bar in bars[-20:]], 72, 14)
    return f"<tr><td>{esc(ticker)}</td><td class='num'>{price}</td><td class='num'>{one_html}</td><td class='num'>{five_html}</td><td>{line}</td><td class='num'>{since}</td></tr>"


def price_table(view: dict) -> str:
    groups = [
        ("B lead", ["SPY", "MSFT", "GOOGL", "AMZN"]),
        ("Cut first", ["NVDA", "CRWV"]),
        ("Hedges", ["XLP", "GLD", "XLE"]),
    ]
    body = []
    for title, tickers in groups:
        body.append(f'<tr class="group"><th colspan="6">{esc(title)}</th></tr>')
        for ticker in tickers:
            body.append(price_cells(ticker, view))
    body.append('<tr class="group"><th colspan="6">Money-leg pair</th></tr>')
    body.append(ratio_row(view))
    return (
        "<table class='prices'><thead><tr><th>Ticker</th><th class='num'>Price</th><th class='num'>1d</th>"
        "<th class='num'>5d</th><th>20d</th><th class='num'>Since last catalyst</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def ratio_row(view: dict) -> str:
    quotes = view["quotes"]
    since = tip(DASH, "No catalyst in the list has occurred yet.")
    empty = f"<tr><td>NBIS/CRWV</td><td class='num na'>{DASH}</td><td class='num na'>{DASH}</td><td class='num na'>{DASH}</td><td></td><td class='num'>{since}</td></tr>"
    if "NBIS" not in quotes or "CRWV" not in quotes:
        return empty
    left = {bar["session"]: bar["close"] for bar in quotes["NBIS"]["bars"]}
    right = {bar["session"]: bar["close"] for bar in quotes["CRWV"]["bars"]}
    dates = [day for day in sorted(set(left) & set(right)) if right[day]]
    vals = [left[day] / right[day] for day in dates]
    if len(vals) < 6:
        return empty
    one = vals[-1] / vals[-2] - 1
    five = vals[-1] / vals[-6] - 1
    detail = f"NBIS divided by CRWV on {fmt_day(dates[-1])}. A ratio, not a price difference."
    return (
        f"<tr><td>NBIS/CRWV</td><td class='num'>{tip(f'{vals[-1]:.2f}', detail)}</td>"
        f"<td class='num'>{tip(fmt_pct(one), 'One-session change in the ratio.', move_class(one))}</td>"
        f"<td class='num'>{tip(fmt_pct(five), 'Five-session change in the ratio.', move_class(five))}</td>"
        f"<td>{spark(vals[-20:], 72, 14)}</td><td class='num'>{since}</td></tr>"
    )


def changes_block(prior: dict | None, current: dict) -> str:
    if not prior or not prior.get("series"):
        return f"<p>No stored snapshot to compare. {DASH}</p>"
    rows = []
    for key, new in current["series"].items():
        old = prior["series"].get(key)
        if not old or not isinstance(old.get("value"), (int, float)) or not isinstance(new.get("value"), (int, float)):
            continue
        if old["value"] == 0:
            continue
        frac = abs(new["value"] / old["value"] - 1) if abs(old["value"]) > 1 else abs(new["value"] - old["value"])
        delta = new["value"] - old["value"]
        if abs(delta) < 0.005 and frac < 0.0005:
            continue
        rows.append((frac, key, old, new))
    rows.sort(key=lambda item: item[0], reverse=True)
    if not rows:
        when = prior.get("asof_sgt", "the stored snapshot")
        return f"<p>{esc(when)} · no tracked print moved · same → same</p>"
    lines = []
    for _, key, old, new in rows[:3]:
        lines.append(
            f"<p>{esc(current['asof_sgt'])} · {esc(key)} · {old['value']:.2f} → {new['value']:.2f}</p>"
        )
    return "".join(lines)


BOX_NAME = {
    "A": "Cooling expansion",
    "B": "Sticky but viable",
    "C": "Inflation squeeze",
    "D": "AI retrenchment",
    "D_money": "AI retrenchment, money",
    "E": "Broad break",
    "F": "Blocked buildout",
}
BANDS = {"B": (0.5, 0.75)}
SEGMENTS = [
    ("B", "B", "b"),
    ("D_money", "D-money", "d"),
    ("F", "F", "f"),
    ("C", "C", "c"),
    ("A", "A", "a"),
    ("E", "E", "e"),
]


def prob_line(judgment: dict) -> str:
    probs = judgment["probabilities"]
    prior = judgment.get("prior_probabilities") or {}
    note = judgment.get("note", "")
    parts = []
    for key, label, kind in SEGMENTS:
        value = probs.get(key)
        if value is None:
            continue
        arrow = ""
        if isinstance(prior, dict) and key in prior and isinstance(prior[key], (int, float)) and prior[key] != value:
            arrow = " ↑" if value > prior[key] else " ↓"
        parts.append(f'<span class="seg {kind}" style="flex:{value}">{esc(label)} {value:g}{arrow}</span>')
    return f'<div class="pbar" title="{esc(note)}">{"".join(parts)}</div>'


def beta_tile(view: dict, judgment: dict) -> str:
    raw = view.get("book_beta") or {}
    value = raw.get("value")
    if not isinstance(value, (int, float)):
        return (
            '<article class="htile"><p class="k">Book beta</p>'
            f'<p class="key na">{DASH}</p></article>'
        )
    shown = f"{value:.2f}"
    detail = f"Manual {fmt_dt(datetime.fromisoformat(raw['asof_sgt']))}. {raw.get('source', '')}"
    number = tip(shown, detail, "")
    box = judgment.get("current_box")
    band = BANDS.get(box)
    if not band:
        gauge = '<p class="muted">no band for this box</p>'
    else:
        lo, hi = band
        inside = lo <= value <= hi
        pos = 0 if hi == lo else max(0, min(100, (value - lo) / (hi - lo) * 100))
        state = "in" if inside else "out"
        gauge = (
            f'<div class="gauge {state}"><i style="left:{pos:.1f}%"></i></div>'
            f'<p class="muted">{esc(box)} band {lo:.1f}–{hi:.2f}</p>'
        )
    return (
        '<article class="htile"><p class="k">Book beta</p>'
        f'<p class="key">{number} <span class="manual">manual</span></p>{gauge}</article>'
    )


def page(view: dict, judgment: dict, changes_html: str) -> str:
    nxt = view["nxt"]
    box = judgment.get("current_box", "B")
    weight = judgment["probabilities"].get(box)
    weight_txt = DASH if weight is None else f"{weight:g}%"
    if nxt:
        count = countdown(nxt["when"], view["now"])
        catalyst = (
            f'<p class="ename">{esc(nxt["event"])}</p>'
            f'<p class="muted">{esc(nxt["label"])}</p>'
            f'<p class="countline" id="count" data-target="{esc(nxt["when"].isoformat())}">{esc(count)}</p>'
        )
    else:
        catalyst = f'<p class="ename">{DASH}</p>'
    body = f"""
    <section class="heroes">
      <article class="htile">
        <p class="k">Box</p>
        <p class="boxletter">{esc(box)}</p>
        <p>{esc(BOX_NAME.get(box, box))} · {esc(weight_txt)}</p>
      </article>
      <article class="htile">
        <p class="k">Action</p>
        <p class="badge {esc(view["action"].lower())}">{esc(view["action"])}</p>
        <p>{esc(view["reason"])}</p>
      </article>
      {beta_tile(view, judgment)}
      <article class="htile">
        <div class="top"><p class="k">Next catalyst</p><button id="theme-toggle" type="button">Theme</button></div>
        {catalyst}
      </article>
    </section>
    {prob_line(judgment)}
    <p class="note">HOLD and CUT are research labels, not instructions.</p>
    <h2>Legs</h2>
    <section class="legs">
      {inflation_tile(view)}
      {growth_tile(view)}
      {rules_tile(view)}
      {money_tile(view)}
      {demand_tile(view)}
      {spill_tile(view)}
    </section>
    <h2>December checklist</h2>
    <section class="checks">{checklist(view)}</section>
    <h2>Next 14 days</h2>
    <section class="timeline">{catalyst_block(view)}</section>
    <h2>Prices we act on</h2>
    {price_table(view)}
    <h2>Last 3 changes</h2>
    <section class="changes">{changes_html}</section>
    """
    return HTML_HEAD + body + HTML_FOOT


HTML_HEAD = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vortex Regime Monitor</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
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
  --bg: #0f1115;
  --card: #16181d;
  --ink: #f2f0ea;
  --muted: #a1a6ad;
  --line: #2c3138;
  --good: #1f8a4c;
  --warn: #c98a00;
  --bad: #c0392b;
  --stale: #9aa0a6;
  --shadow: 0 1px 2px rgba(0, 0, 0, .35);
}
[data-theme="light"] {
  color-scheme: light;
  --bg: #f5f3ee;
  --card: #ffffff;
  --ink: #1b1d21;
  --muted: #6b7078;
  --line: #e6e3dc;
  --good: #1f8a4c;
  --warn: #c98a00;
  --bad: #c0392b;
  --stale: #9aa0a6;
  --shadow: 0 1px 2px rgba(27, 29, 33, .06);
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  background: var(--bg);
  color: var(--ink);
  font-family: Inter, "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
  font-size: 15px;
  line-height: 1.25;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
}
.page { max-width: 1280px; margin: 0 auto; padding: 8px 24px 4px; }
.tools { display: flex; justify-content: flex-end; }
h2 { margin: 6px 0 2px; font-size: 13px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
p { margin: 0; overflow-wrap: break-word; }
.note { color: var(--muted); font-size: 13px; margin: 4px 0 0; }
.heroes, .legs, .checks { display: grid; gap: 8px; }
.heroes { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.legs { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.checks { grid-template-columns: 1fr 1fr; }
.htile, .tile, .box, .ev, .qcard {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow);
}
.htile, .tile, .box { padding: 8px 10px; min-width: 0; }
.k, .name { font-size: 13px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.top { display: flex; justify-content: space-between; align-items: baseline; gap: 6px; }
.box h2 { margin: 0 0 4px; }
.boxletter { font-size: 40px; line-height: 1; font-weight: 700; margin: 4px 0; }
.key { font-size: 22px; line-height: 1.15; font-weight: 700; }
.key.sentence { font-size: 15px; font-weight: 600; }
.keyline { display: flex; align-items: baseline; gap: 8px; margin: 4px 0; }
.badge { font-size: 22px; font-weight: 700; margin: 4px 0; }
.manual { font-size: 13px; font-weight: 600; color: var(--muted); }
.muted, .ready, .cwhen, .twhen span { color: var(--muted); font-size: 13px; }
.lamp { font-weight: 700; }
.lamp.yellow, .badge.hold, .st-yellow, .gauge.out i { color: var(--warn); }
.lamp.red, .badge.cut, .st-red, .down, .mark.bad { color: var(--bad); }
.lamp.green, .badge.add, .st-green, .up, .mark.good { color: var(--good); }
.lamp.missing, .na, .mark.wait { color: var(--stale); }
.tile { display: flex; flex-direction: column; border-top-width: 4px; }
.tile.green { border-top-color: #1f8a4c; }
.tile.yellow { border-top-color: #c98a00; }
.tile.red { border-top-color: #c0392b; }
.tile.missing { border-top-color: #9aa0a6; }
.rest { font-size: 13px; margin-top: 4px; }
.to { margin-top: auto; padding-top: 4px; color: var(--muted); font-size: 13px; }
.gauge { position: relative; height: 8px; margin: 8px 0 4px; background: var(--line); border-radius: 99px; }
.gauge i { position: absolute; top: -3px; width: 4px; height: 14px; border-radius: 2px; background: var(--good); }
.gauge.out i { background: var(--warn); }
.pbar { display: flex; gap: 2px; width: 100%; margin-top: 8px; }
.seg { display: flex; align-items: center; justify-content: center; min-width: max-content; min-height: 26px; padding: 2px 4px; color: #fff; font-size: 12px; font-weight: 600; border-radius: 4px; }
.seg.b { background: #1f4d3a; flex-grow: 40; }
.seg.d { background: #8a5a12; }
.seg.f { background: #2f4a6e; }
.seg.c { background: #8a3a32; }
.seg.a { background: #3e4a57; }
.seg.e { background: #5a4568; }
.count { font-weight: 600; margin-bottom: 4px; }
.prog { height: 6px; background: var(--line); border-radius: 99px; margin: 0 0 4px; }
.prog i { display: block; height: 6px; background: var(--good); border-radius: 99px; }
ul { margin: 0; padding: 0; list-style: none; }
.crow { display: flex; gap: 8px; align-items: baseline; margin: 0 0 3px; }
.clabel { flex: 1; }
.mark { font-weight: 700; width: 1em; }
.foot { margin-top: 8px; }
.ev { display: grid; grid-template-columns: 108px minmax(0, 1fr) auto; gap: 8px; align-items: start; margin: 0; padding: 3px 0; background: transparent; border: 0; border-radius: 0; box-shadow: none; border-bottom: 1px solid var(--line); }
.twhen b { display: block; font-size: 15px; }
.etop { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chip { display: inline-block; padding: 1px 8px; border-radius: 999px; background: var(--bg); color: var(--muted); font-size: 12px; font-weight: 600; }
.chip.leg { color: #fff; }
.chip.money { background: #8a5a12; }
.chip.inflation { background: #8a3a32; }
.chip.demand { background: #2f4a6e; }
.chip.growth { background: #1f4d3a; }
.chip.rules { background: #3e4a57; }
.ready { margin-top: 4px; }
.qcards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 8px; }
.qcard { padding: 8px; }
.qlabel { font-size: 13px; font-weight: 600; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { text-align: left; vertical-align: middle; padding: 1px 6px 1px 0; border-bottom: 1px solid var(--line); overflow-wrap: break-word; font-weight: 400; }
th.num, td.num { text-align: right; }
tr.group th { padding-top: 6px; font-size: 13px; font-weight: 600; color: var(--muted); letter-spacing: .04em; text-transform: uppercase; border-bottom: 0; }
.spark { color: var(--muted); overflow: visible; vertical-align: middle; }
button { background: var(--card); color: var(--ink); border: 1px solid var(--line); border-radius: 999px; font: inherit; font-weight: 600; padding: 4px 10px; }
.tip { position: relative; }
.tip:hover::after, .tip:focus::after { content: attr(data-tip); position: absolute; z-index: 5; left: 0; top: calc(100% + 4px); width: 240px; padding: 6px 8px; border-radius: 8px; background: var(--ink); color: var(--bg); font-size: 13px; line-height: 1.35; font-weight: 400; white-space: normal; }
.ename { font-size: 22px; font-weight: 700; }
.countline { font-size: 15px; font-weight: 600; }
@media (max-width: 860px) {
  .heroes, .legs, .checks, .qcards, .ev { grid-template-columns: 1fr; }
  .page { padding: 8px 16px 16px; }
}
</style>
</head>
<body>
<div class="page">
"""

HTML_FOOT = """
</div>
<script>
(function () {
  var key = "vortex-theme";
  var root = document.documentElement;
  var button = document.getElementById("theme-toggle");
  function label(theme) { button.textContent = theme === "dark" ? "Use light mode" : "Use dark mode"; }
  label(root.getAttribute("data-theme") || "dark");
  button.addEventListener("click", function () {
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem(key, next); } catch (e) {}
    label(next);
  });
  var count = document.getElementById("count");
  if (!count) return;
  var target = new Date(count.getAttribute("data-target"));
  function tick() {
    var ms = target - new Date();
    if (ms <= 0) { count.textContent = "now"; return; }
    var hours = Math.floor(ms / 36e5);
    var days = Math.floor(hours / 24);
    hours = hours % 24;
    count.textContent = days ? ("in " + days + "d " + hours + "h") : ("in " + hours + "h");
  }
  tick();
  setInterval(tick, 60000);
})();
</script>
</body>
</html>
"""


def current_snapshot(view: dict, now: datetime) -> dict:
    series = {}
    for ticker, _role in PRICES:
        bars = view["quotes"].get(ticker, {}).get("bars")
        if bars:
            series[ticker] = {"value": bars[-1]["close"], "session": bars[-1]["session"].isoformat()}
    for ticker in ("SMH", "CL=F", "BZ=F"):
        bars = view["quotes"].get(ticker, {}).get("bars")
        if bars:
            series[ticker] = {"value": bars[-1]["close"], "session": bars[-1]["session"].isoformat()}
    if view["hy"]:
        series["HY"] = {"value": view["hy"][-1][1], "session": view["hy"][-1][0].isoformat()}
    if view["dgs"]:
        series["DGS2"] = {"value": view["dgs"][-1][1], "session": view["dgs"][-1][0].isoformat()}
    if view["h100_rows"]:
        series["H100"] = {"value": view["h100_rows"][-1]["value"], "session": view["h100_rows"][-1]["date"]}
    if view["b200_rows"]:
        series["B200"] = {"value": view["b200_rows"][-1]["value"], "session": view["b200_rows"][-1]["date"]}
    return {"asof_sgt": fmt_dt(now), "series": series}


def write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    self_check()
    now = datetime.now(SGT).replace(microsecond=0)
    bundle = load_bundle(now)
    view = build_view(bundle)
    prior_path = DATA / "snapshot_latest.json"
    prior = load_json(prior_path) if prior_path.exists() else None
    current = current_snapshot(view, now)
    changes = changes_block(prior, current)
    html = page(view, bundle["judgment"], changes)
    privacy_scan(html, layout=True)
    for source in (ROOT / "build.py", ROOT / "fetch_data.py", ROOT / "README.md"):
        privacy_scan(source.read_text())
    tmp = OUT.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(OUT)
    if prior:
        write_json(DATA / "snapshot_prev.json", prior)
    write_json(DATA / "snapshot_latest.json", current)
    summary = {
        "built_sgt": fmt_dt(now),
        "header": f"Box {bundle['judgment']['current_box']} · {bundle['judgment']['probabilities']['B']}% | {view['action']} | {view['reason']}",
        "next": None if not view["nxt"] else view["nxt"]["event"] + " " + view["nxt"]["label"] + " " + countdown(view["nxt"]["when"], now),
        "lights": view["legs"],
        "deploy": f"{view['deploy_met']}/5 met",
        "stop": f"{view['stop_hit']}/2 triggered",
        "core": None if not view["core"] else f"{view['core']['published']}",
        "rates_bp": view["rates_bp"],
        "brent": view["brent_px"],
        "wti": view["wti_px"],
        "claims_k": None if view["claims_avg"] is None else round(view["claims_avg"] / 1000, 1),
        "payrolls_k": view["pay_change"],
        "hy": None if not view["hy"] else view["hy"][-1][1],
        "h100_1m": view["h100_1m"],
        "b200_1m": view["b200_1m"],
        "rent_manual": view["rent_manual"],
        "shown": [row["id"] for row in view["shown"]],
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
