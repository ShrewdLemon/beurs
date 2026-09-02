"""Trading calendars, with their provenance attached.

Every calendar here says WHERE IT CAME FROM, because that is the difference
between a number you can rely on and one you inherited.

    VERIFIED   probed against the exchange's own published record, session by
               session, by this project. Currently: NSE.
    SOURCED    taken from `exchange_calendars`, which is well maintained and
               correct for these venues. Not independently re-checked here.

WHY NSE IS THE ONE WE SHIP OURSELVES. `exchange_calendars` has no XNSE at all,
and its XBOM -- the closest thing -- is wrong for the Indian equity session set.
Measured over 2023-01-01..2026-06-30, where the truth is 864 sessions:

    NSE archive (shipped here)   864   ground truth
    exchange_calendars XBOM      858   misses 6; never invents
    pandas_market_calendars NSE  859   misses 8 AND invents 3
    yfinance ^NSEI dates         859   misses 5

The misses are weekend special sessions NSE genuinely traded. For NYSE, NASDAQ,
Shanghai and Hong Kong, `exchange_calendars` is good and rebuilding it would add
risk rather than remove it -- so this package does not.

THE CHECK MOST PEOPLE RUN CANNOT SEE THE DEFECT. Comparing weekday HOLIDAY LISTS
matches 15/15 for 2023 and 16/16 for 2024 against a calendar missing every
weekend session. Diff the full session set: `bourse.audit_calendar`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"

VERIFIED = "verified"      # probed against the exchange by this project
SOURCED = "sourced"        # from exchange_calendars, not re-checked here


class OutOfRange(Exception):
    """A date outside a calendar's known range.

    Raised rather than guessed. Returning a plausible answer for an unchecked
    date is how a wrong calendar spreads: the caller cannot tell which sessions
    were verified and which were assumed.
    """


class UnknownExchange(Exception):
    """No calendar for this venue. Named, never silently defaulted."""


@dataclass(frozen=True)
class Exchange:
    code: str
    name: str
    provenance: str
    ec_name: str | None = None      # exchange_calendars identifier, if sourced
    note: str = ""


EXCHANGES: dict[str, Exchange] = {
    "NSE": Exchange("NSE", "National Stock Exchange of India", VERIFIED, None,
                    "Shipped verified. exchange_calendars has no XNSE, and XBOM "
                    "misses 6 sessions over this range."),
    "NYSE": Exchange("NYSE", "New York Stock Exchange", SOURCED, "XNYS"),
    "NASDAQ": Exchange("NASDAQ", "Nasdaq", SOURCED, "XNAS"),
    "SSE": Exchange("SSE", "Shanghai Stock Exchange", SOURCED, "XSHG",
                    "Mainland China sessions move with State Council holiday "
                    "notices published annually; check the year you care about."),
    "HKEX": Exchange("HKEX", "Hong Kong Exchanges", SOURCED, "XHKG"),
    "BSE": Exchange("BSE", "BSE Ltd (India)", SOURCED, "XBOM",
                    "Prefer NSE. XBOM was measured missing 6 Indian sessions "
                    "over 2023-2026."),
    "LSE": Exchange("LSE", "London Stock Exchange", SOURCED, "XLON"),
    "TSE": Exchange("TSE", "Tokyo Stock Exchange", SOURCED, "XTKS"),
}

DEFAULT = "NSE"


def _as_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def exchanges() -> list[Exchange]:
    """Every venue this package can answer for, with provenance."""
    return list(EXCHANGES.values())


def resolve(code: str) -> Exchange:
    key = str(code).upper().strip()
    if key not in EXCHANGES:
        raise UnknownExchange(
            f"unknown exchange {code!r}. Known: {sorted(EXCHANGES)}. "
            "Add one to EXCHANGES rather than passing a calendar in blind -- an "
            "audit against the wrong session set is worse than none.")
    return EXCHANGES[key]


@lru_cache(maxsize=8)
def _verified(code: str) -> tuple[date, ...]:
    p = DATA / f"{code.lower()}_sessions.json"
    if not p.exists():
        raise UnknownExchange(f"no shipped calendar for {code}")
    return tuple(date.fromisoformat(s) for s in json.loads(p.read_text()))


@lru_cache(maxsize=8)
def _sourced(ec_name: str, lo: date, hi: date) -> tuple[date, ...]:
    try:
        import exchange_calendars as xc
    except ImportError as e:                              # pragma: no cover
        raise UnknownExchange(
            "this exchange's calendar comes from `exchange_calendars`, which is "
            "not installed. pip install bourse[global]") from e
    cal = xc.get_calendar(ec_name)
    s = cal.sessions_in_range(str(lo), str(hi))
    return tuple(x.date() for x in s)


def coverage(exchange: str = DEFAULT) -> tuple[date, date]:
    """First and last session this package will answer for."""
    ex = resolve(exchange)
    if ex.provenance == VERIFIED:
        s = _verified(ex.code)
        return s[0], s[-1]
    import exchange_calendars as xc
    cal = xc.get_calendar(ex.ec_name)
    return cal.first_session.date(), cal.last_session.date()


def sessions(start=None, end=None, exchange: str = DEFAULT) -> list[date]:
    """Trading sessions in [start, end], inclusive.

    >>> len(sessions("2023-01-01", "2026-06-30", exchange="NSE"))
    864
    """
    ex = resolve(exchange)
    first, last = coverage(exchange)
    lo = _as_date(start) if start else first
    hi = _as_date(end) if end else last
    for d in (lo, hi):
        if not (first <= d <= last):
            raise OutOfRange(
                f"{d} is outside {ex.code}'s known range [{first} .. {last}]")
    if ex.provenance == VERIFIED:
        return [d for d in _verified(ex.code) if lo <= d <= hi]
    return list(_sourced(ex.ec_name, lo, hi))


@lru_cache(maxsize=32)
def _session_set(exchange: str, lo: date, hi: date) -> frozenset:
    return frozenset(sessions(lo, hi, exchange=exchange))


def is_session(d, exchange: str = DEFAULT) -> bool:
    """Did this venue trade on this date?

    >>> is_session("2024-01-20", exchange="NSE")   # a Saturday NSE traded
    True
    """
    d = _as_date(d)
    first, last = coverage(exchange)
    if not (first <= d <= last):
        raise OutOfRange(f"{d} is outside [{first} .. {last}]")
    return d in _session_set(exchange, first, last)


def next_session(d, exchange: str = DEFAULT, *, strictly: bool = True) -> date:
    d = _as_date(d)
    for s in sessions(exchange=exchange):
        if s > d or (not strictly and s == d):
            return s
    raise OutOfRange(f"no session after {d}")


def previous_session(d, exchange: str = DEFAULT, *, strictly: bool = True) -> date:
    d = _as_date(d)
    for s in reversed(sessions(exchange=exchange)):
        if s < d or (not strictly and s == d):
            return s
    raise OutOfRange(f"no session before {d}")


def offset(d, n: int, exchange: str = DEFAULT) -> date:
    """The session `n` trading days away. Counts SESSIONS, not calendar days.

    >>> offset("2026-01-23", 5, exchange="NSE")
    datetime.date(2026, 2, 1)

    That returns a Sunday, and it is right: Republic Day falls in the window and
    NSE traded that Sunday.
    """
    s = sessions(exchange=exchange)
    d = _as_date(d)
    try:
        i = s.index(d)
    except ValueError:
        raise OutOfRange(f"{d} is not a trading session on {exchange}") from None
    j = i + n
    if not (0 <= j < len(s)):
        raise OutOfRange(f"{d} {n:+d} sessions falls outside the known range")
    return s[j]


def count(start, end, exchange: str = DEFAULT) -> int:
    return len(sessions(start, end, exchange=exchange))


def audit_calendar(candidate, exchange: str = DEFAULT) -> dict:
    """Diff another calendar against this one, on the FULL session set.

    Use this rather than comparing holiday lists. A calendar missing every
    weekend session produces an identical weekday-holiday list, which is exactly
    how the NSE defects went unnoticed.
    """
    cand = {_as_date(x) for x in candidate}
    if not cand:
        return {"exchange": exchange, "n_reference": 0, "n_candidate": 0,
                "missing": [], "invented": [], "agrees": False}
    first, last = coverage(exchange)
    lo, hi = max(min(cand), first), min(max(cand), last)
    truth = set(sessions(lo, hi, exchange=exchange))
    cand = {d for d in cand if lo <= d <= hi}
    missing, invented = sorted(truth - cand), sorted(cand - truth)
    return {"exchange": exchange, "provenance": resolve(exchange).provenance,
            "n_reference": len(truth), "n_candidate": len(cand),
            "missing": missing, "invented": invented,
            "agrees": not missing and not invented}


def status() -> str:
    """Human-readable provenance table. Print this before trusting anything."""
    rows = ["exchange  provenance  range", "-" * 52]
    for ex in exchanges():
        try:
            lo, hi = coverage(ex.code)
            rng = f"{lo} .. {hi}"
        except Exception:                                 # noqa: BLE001
            rng = "unavailable (pip install bourse[global])"
        rows.append(f"{ex.code:9} {ex.provenance:11} {rng}")
    rows.append("")
    rows.append("verified = probed against the exchange's own record by this project")
    rows.append("sourced  = from exchange_calendars, not independently re-checked")
    return "\n".join(rows)
