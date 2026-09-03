"""Trading calendars for 50 venues, each carrying its provenance.

Every calendar here says WHERE IT CAME FROM, because that is the difference
between a number you can rely on and one you inherited.

    VERIFIED   probed against the exchange's own published record, session by
               session, by this project. Currently: NSE.
    SOURCED    from `exchange_calendars`, which is well maintained and correct
               for these venues. Not independently re-checked here.

Only one venue is shipped verified, and saying so is the point. A package that
claimed fifty verified calendars would be claiming fifty audits it had not done.

WHY NSE IS THE ONE. `exchange_calendars` has no XNSE at all, and its XBOM -- the
closest thing -- is wrong for the Indian equity session set. Measured over
2023-01-01..2026-06-30, where the truth is 864 sessions:

    NSE archive (shipped here)   864   ground truth
    exchange_calendars XBOM      858   misses 6; never invents
    pandas_market_calendars NSE  859   misses 8 AND invents 3
    yfinance ^NSEI dates         859   misses 5

The misses are weekend special sessions NSE genuinely traded. For every other
venue `exchange_calendars` is good, and rebuilding it would add risk rather than
remove it -- so this package does not.

THE CHECK MOST PEOPLE RUN CANNOT SEE THE DEFECT. Comparing weekday HOLIDAY LISTS
matches 15/15 for 2023 and 16/16 for 2024 against a calendar missing every
weekend session. Diff the full session set: `beurs.audit_calendar`.

TICKER INFERENCE. `exchange="auto"` reads the venue off the symbol suffix, so
`0700.HK` is audited against Hong Kong and `RELIANCE.NS` against India without
anyone having to say so. A bare symbol resolves to `US`, the shared NYSE/Nasdaq
session calendar -- shared because the two venues observe identical holidays, so
no information is lost by not distinguishing them.
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
    country: str = ""
    currency: str = ""
    suffixes: tuple[str, ...] = ()  # Yahoo-style ticker suffixes
    note: str = ""


def _x(code, name, ec, country, ccy, suffixes=(), note="", prov=SOURCED):
    return Exchange(code, name, prov, ec, country, ccy, tuple(suffixes), note)


# Ordered roughly by region so `beurs status` reads like an atlas.
EXCHANGES: dict[str, Exchange] = {e.code: e for e in [
    # ---- Asia-Pacific -----------------------------------------------------
    Exchange("NSE", "National Stock Exchange of India", VERIFIED, None,
             "India", "INR", (".NS",),
             "Shipped verified. exchange_calendars has no XNSE, and XBOM misses "
             "6 sessions over 2023-2026 -- all weekend specials."),
    _x("BSE", "BSE Ltd", "XBOM", "India", "INR", (".BO",),
       "Prefer NSE. XBOM was measured missing 6 Indian sessions over 2023-2026."),
    _x("SSE", "Shanghai Stock Exchange", "XSHG", "China", "CNY", (".SS",),
       "Mainland sessions move with State Council holiday notices published "
       "annually, and include make-up weekend workdays. Check the year you care "
       "about before trusting any source for China."),
    _x("SZSE", "Shenzhen Stock Exchange", "XSHG", "China", "CNY", (".SZ",),
       "Shenzhen observes the same mainland holiday schedule as Shanghai, so it "
       "shares XSHG here. If the two ever diverge this mapping is wrong."),
    _x("HKEX", "Hong Kong Exchanges", "XHKG", "Hong Kong", "HKD", (".HK",)),
    _x("TSE", "Tokyo Stock Exchange", "XTKS", "Japan", "JPY", (".T",)),
    _x("KRX", "Korea Exchange", "XKRX", "South Korea", "KRW", (".KS", ".KQ"),
       "KOSPI (.KS) and KOSDAQ (.KQ) share one session calendar."),
    _x("TWSE", "Taiwan Stock Exchange", "XTAI", "Taiwan", "TWD", (".TW", ".TWO")),
    _x("ASX", "Australian Securities Exchange", "XASX", "Australia", "AUD", (".AX",)),
    _x("NZX", "New Zealand Exchange", "XNZE", "New Zealand", "NZD", (".NZ",)),
    _x("SGX", "Singapore Exchange", "XSES", "Singapore", "SGD", (".SI",)),
    _x("IDX", "Indonesia Stock Exchange", "XIDX", "Indonesia", "IDR", (".JK",)),
    _x("MYX", "Bursa Malaysia", "XKLS", "Malaysia", "MYR", (".KL",)),
    _x("SET", "Stock Exchange of Thailand", "XBKK", "Thailand", "THB", (".BK",)),
    _x("PSE", "Philippine Stock Exchange", "XPHS", "Philippines", "PHP", (".PS",)),
    _x("PSX", "Pakistan Stock Exchange", "XKAR", "Pakistan", "PKR", (".KA",)),

    # ---- Americas ---------------------------------------------------------
    _x("US", "US equities (NYSE / Nasdaq shared calendar)", "XNYS",
       "United States", "USD", (),
       "NYSE and Nasdaq observe identical holidays, so one calendar serves both. "
       "This is what a bare ticker infers to."),
    _x("NYSE", "New York Stock Exchange", "XNYS", "United States", "USD", ()),
    _x("NASDAQ", "Nasdaq", "XNAS", "United States", "USD", ()),
    _x("CBOE", "Cboe BZX", "BATS", "United States", "USD", ()),
    _x("TSX", "Toronto Stock Exchange", "XTSE", "Canada", "CAD", (".TO",)),
    _x("TSXV", "TSX Venture Exchange", "XTSX", "Canada", "CAD", (".V",)),
    _x("B3", "B3 Brasil Bolsa Balcao", "BVMF", "Brazil", "BRL", (".SA",)),
    _x("BMV", "Bolsa Mexicana de Valores", "XMEX", "Mexico", "MXN", (".MX",)),
    _x("BCBA", "Bolsa de Comercio de Buenos Aires", "XBUE", "Argentina", "ARS", (".BA",)),
    _x("BCS", "Bolsa de Santiago", "XSGO", "Chile", "CLP", (".SN",)),
    _x("BVL", "Bolsa de Valores de Lima", "XLIM", "Peru", "PEN", (".LM",)),
    _x("BVC", "Bolsa de Valores de Colombia", "XBOG", "Colombia", "COP", ()),

    # ---- Europe -----------------------------------------------------------
    _x("LSE", "London Stock Exchange", "XLON", "United Kingdom", "GBP", (".L",)),
    _x("XETRA", "Deutsche Boerse Xetra", "XETR", "Germany", "EUR", (".DE",)),
    _x("FWB", "Frankfurt Stock Exchange", "XFRA", "Germany", "EUR", (".F",)),
    _x("EPA", "Euronext Paris", "XPAR", "France", "EUR", (".PA",)),
    _x("AMS", "Euronext Amsterdam", "XAMS", "Netherlands", "EUR", (".AS",)),
    _x("EBR", "Euronext Brussels", "XBRU", "Belgium", "EUR", (".BR",)),
    _x("ELI", "Euronext Lisbon", "XLIS", "Portugal", "EUR", (".LS",)),
    _x("ISE", "Euronext Dublin", "XDUB", "Ireland", "EUR", (".IR",)),
    _x("BME", "Bolsa de Madrid", "XMAD", "Spain", "EUR", (".MC",)),
    _x("BIT", "Borsa Italiana", "XMIL", "Italy", "EUR", (".MI",)),
    _x("SIX", "SIX Swiss Exchange", "XSWX", "Switzerland", "CHF", (".SW",)),
    _x("OMXS", "Nasdaq Stockholm", "XSTO", "Sweden", "SEK", (".ST",)),
    _x("OSE", "Oslo Bors", "XOSL", "Norway", "NOK", (".OL",)),
    _x("OMXC", "Nasdaq Copenhagen", "XCSE", "Denmark", "DKK", (".CO",)),
    _x("OMXH", "Nasdaq Helsinki", "XHEL", "Finland", "EUR", (".HE",)),
    _x("OMXI", "Nasdaq Iceland", "XICE", "Iceland", "ISK", (".IC",)),
    _x("WSE", "Warsaw Stock Exchange", "XWAR", "Poland", "PLN", (".WA",)),
    _x("PSE_CZ", "Prague Stock Exchange", "XPRA", "Czechia", "CZK", (".PR",)),
    _x("BSE_HU", "Budapest Stock Exchange", "XBUD", "Hungary", "HUF", (".BD",)),
    _x("WBAG", "Wiener Boerse", "XWBO", "Austria", "EUR", (".VI",)),
    _x("ATHEX", "Athens Stock Exchange", "ASEX", "Greece", "EUR", (".AT",)),
    _x("MOEX", "Moscow Exchange", "XMOS", "Russia", "RUB", (".ME",),
       "Sanctions-era data for Russian equities is unreliable from every "
       "Western source. Treat anything you get here as unverified."),

    # ---- Middle East & Africa ---------------------------------------------
    _x("TADAWUL", "Saudi Exchange", "XSAU", "Saudi Arabia", "SAR", (".SR",),
       "Trades Sunday-Thursday. A Mon-Fri assumption is wrong here in both "
       "directions -- it invents Fridays and drops Sundays."),
    _x("TASE", "Tel Aviv Stock Exchange", "XTAE", "Israel", "ILS", (".TA",),
       "Trades Sunday-Thursday."),
    _x("BIST", "Borsa Istanbul", "XIST", "Turkey", "TRY", (".IS",)),
    _x("JSE", "Johannesburg Stock Exchange", "XJSE", "South Africa", "ZAR", (".JO",)),
]}

DEFAULT = "NSE"
AUTO = "auto"

# Longest suffix first, so ".TWO" is matched before ".TW".
_BY_SUFFIX: dict[str, str] = {}
for _e in EXCHANGES.values():
    for _s in _e.suffixes:
        _BY_SUFFIX.setdefault(_s.upper(), _e.code)
_SUFFIXES = sorted(_BY_SUFFIX, key=len, reverse=True)


def _as_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def exchanges() -> list[Exchange]:
    """Every venue this package can answer for, with provenance."""
    return list(EXCHANGES.values())


def infer(ticker: str) -> str | None:
    """Guess the venue from a Yahoo-style ticker suffix.

    >>> infer("RELIANCE.NS"), infer("0700.HK"), infer("AAPL")
    ('NSE', 'HKEX', 'US')

    A bare symbol returns 'US' -- the shared NYSE/Nasdaq calendar -- because
    that is what an unsuffixed ticker means in every major data source. Returns
    None only for a suffix this package does not recognise, which is a case the
    caller must decide about rather than have decided for it.
    """
    t = str(ticker).strip().upper()
    if not t:
        return None
    for s in _SUFFIXES:
        if t.endswith(s):
            return _BY_SUFFIX[s]
    return None if "." in t else "US"


def resolve(code: str, ticker: str | None = None) -> Exchange:
    """Look up an exchange. `code='auto'` infers it from `ticker`."""
    key = str(code).strip()
    if key.lower() == AUTO:
        guess = infer(ticker) if ticker else None
        if guess is None:
            raise UnknownExchange(
                f"could not infer an exchange from ticker {ticker!r}. Pass "
                f"exchange= explicitly. Known: {', '.join(sorted(EXCHANGES))}")
        key = guess
    key = key.upper()
    if key not in EXCHANGES:
        raise UnknownExchange(
            f"unknown exchange {code!r}. Known: {', '.join(sorted(EXCHANGES))}. "
            "Add one to EXCHANGES rather than passing a calendar in blind -- an "
            "audit against the wrong session set is worse than none.")
    return EXCHANGES[key]


@lru_cache(maxsize=8)
def _verified(code: str) -> tuple[date, ...]:
    p = DATA / f"{code.lower()}_sessions.json"
    if not p.exists():
        raise UnknownExchange(f"no shipped calendar for {code}")
    return tuple(date.fromisoformat(s) for s in json.loads(p.read_text()))


@lru_cache(maxsize=64)
def _calendar(ec_name: str):
    """Build (and keep) an exchange_calendars calendar.

    Construction costs 50-200ms per venue, so this cache is the difference
    between a fast tool and a slow one when auditing many names.
    """
    try:
        import exchange_calendars as xc
    except ImportError as e:                              # pragma: no cover
        raise UnknownExchange(
            "this exchange's calendar comes from `exchange_calendars`, which is "
            "not installed. pip install 'beurs[global]'") from e
    return xc.get_calendar(ec_name)


@lru_cache(maxsize=256)
def _sourced(ec_name: str, lo: date, hi: date) -> tuple[date, ...]:
    s = _calendar(ec_name).sessions_in_range(str(lo), str(hi))
    return tuple(x.date() for x in s)


@lru_cache(maxsize=64)
def coverage(exchange: str = DEFAULT) -> tuple[date, date]:
    """First and last session this package will answer for."""
    ex = resolve(exchange)
    if ex.provenance == VERIFIED:
        s = _verified(ex.code)
        return s[0], s[-1]
    cal = _calendar(ex.ec_name)
    return cal.first_session.date(), cal.last_session.date()


def sessions(start=None, end=None, exchange: str = DEFAULT) -> list[date]:
    """Trading sessions in [start, end], inclusive.

    >>> len(sessions("2023-01-01", "2026-06-30", exchange="NSE"))
    864
    """
    ex = resolve(exchange)
    first, last = coverage(ex.code)
    lo = _as_date(start) if start else first
    hi = _as_date(end) if end else last
    for d in (lo, hi):
        if not (first <= d <= last):
            raise OutOfRange(
                f"{d} is outside {ex.code}'s known range [{first} .. {last}]")
    if ex.provenance == VERIFIED:
        return [d for d in _verified(ex.code) if lo <= d <= hi]
    return list(_sourced(ex.ec_name, lo, hi))


@lru_cache(maxsize=128)
def _session_set(exchange: str, lo: date, hi: date) -> frozenset:
    return frozenset(sessions(lo, hi, exchange=exchange))


def is_session(d, exchange: str = DEFAULT) -> bool:
    """Did this venue trade on this date?

    >>> is_session("2024-01-20", exchange="NSE")   # a Saturday NSE traded
    True
    """
    d = _as_date(d)
    ex = resolve(exchange)
    first, last = coverage(ex.code)
    if not (first <= d <= last):
        raise OutOfRange(f"{d} is outside [{first} .. {last}]")
    return d in _session_set(ex.code, first, last)


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
    ex = resolve(exchange)
    if not cand:
        return {"exchange": ex.code, "n_reference": 0, "n_candidate": 0,
                "missing": [], "invented": [], "agrees": False}
    first, last = coverage(ex.code)
    lo, hi = max(min(cand), first), min(max(cand), last)
    truth = set(sessions(lo, hi, exchange=ex.code))
    cand = {d for d in cand if lo <= d <= hi}
    missing, invented = sorted(truth - cand), sorted(cand - truth)
    return {"exchange": ex.code, "provenance": ex.provenance,
            "n_reference": len(truth), "n_candidate": len(cand),
            "missing": missing, "invented": invented,
            "agrees": not missing and not invented}


def status(full: bool = False) -> str:
    """Provenance table for every venue. Print this before trusting anything.

    `full=True` also resolves each calendar's date range, which builds every
    sourced calendar and takes a few seconds. The default is instant.
    """
    rows = [f"{'code':10} {'venue':38} {'country':16} {'ccy':4} {'suffix':7} prov",
            "-" * 92]
    for ex in exchanges():
        suf = ex.suffixes[0] if ex.suffixes else "-"
        line = (f"{ex.code:10} {ex.name[:38]:38} {ex.country[:16]:16} "
                f"{ex.currency:4} {suf:7} {ex.provenance}")
        if full:
            try:
                lo, hi = coverage(ex.code)
                line += f"  {lo} .. {hi}"
            except Exception:                             # noqa: BLE001
                line += "  unavailable (pip install 'beurs[global]')"
        rows.append(line)
    n_v = sum(e.provenance == VERIFIED for e in exchanges())
    rows += ["",
             f"{len(EXCHANGES)} venues: {n_v} verified, {len(EXCHANGES) - n_v} sourced.",
             "verified = probed against the exchange's own record by this project",
             "sourced  = from exchange_calendars, not independently re-checked",
             "",
             "Pass exchange='auto' and the suffix column is used to pick the venue."]
    return "\n".join(rows)
