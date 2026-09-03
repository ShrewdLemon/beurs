"""Check a price series for the failures that never raise.

Exchange-agnostic. Every check below is a failure mode of a price API against a
trading calendar, not of any one market -- the same bugs appear on US tickers.
What differs by venue is the calendar you check against, which is why `exchange`
is a parameter and why `bourse.calendars` states its provenance.

    fabricated_jumps   The adjusted series carries a price change that never
                       happened, because a split factor was applied to PART of
                       the history. Measured on NSE data: TRENT reads -33.05% on
                       2026-01-01 where the exchange moved +0.43%; CONCOR reads
                       -20.88% where the exchange moved -1.10%. That was 2 of 10
                       in-window split events.

    stale_sessions     A REAL session where the API repeats the previous close.
                       2025-03-18 was a full 3.32-billion-share NSE session
                       rendered stale for 196 of 197 names, median error 1.78%.

    phantom_rows       A row on a date the venue did not trade: zero volume,
                       Open == High == Low == Close. Each is a spurious 0%
                       return.

    missing_sessions   Sessions the venue traded that the series lacks.

    unexpected_sessions  Rows on dates the venue did NOT trade, carrying real
                       volume -- so not phantoms. Measured on Saudi Aramco:
                       3 such rows in 2024, all inside Eid windows, where the
                       moon-sighting date is hard to publish in advance.

    dropped_weekday    The missing sessions are not scattered -- they are one
                       weekday, gone. Measured on TEVA.TA: 50 of 51 missing 2024
                       sessions were SUNDAYS. Tel Aviv trades Sunday-Thursday,
                       and the source silently serves a Monday-Friday week,
                       deleting a fifth of the Israeli trading year. The same
                       shape appears on Gulf venues. This is invisible to any
                       check that counts holidays.

WHY PHANTOMS MATTER MORE THAN THEY LOOK. They understate volatility, and
volatility is the denominator of your test statistic. On one measured name sigma
came out 0.0249 against a true 0.0462 -- 46% too low. That INFLATES every
t-statistic built on it, so the bias points toward finding significance that is
not there.

The distinction between a phantom and a stale session is the one that costs
people data: deleting a stale row throws away a real market-wide move, while
keeping a phantom invents a flat day. They look identical in the frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from . import calendars as cals


@dataclass
class Finding:
    kind: str
    dates: tuple[date, ...]
    detail: str

    def __len__(self) -> int:
        return len(self.dates)


@dataclass
class Report:
    symbol: str
    exchange: str
    n_rows: int
    n_sessions_expected: int
    findings: list[Finding] = field(default_factory=list)
    inferred: bool = False        # venue was guessed from the ticker, not given

    @property
    def clean(self) -> bool:
        return not self.findings

    def __getitem__(self, kind: str) -> Finding | None:
        return next((f for f in self.findings if f.kind == kind), None)

    @property
    def wrong_venue_suspected(self) -> bool:
        """Could these findings just be the wrong calendar?

        Deliberately weak, and it says so. Two markets' session sets can agree
        to within a few percent over a short window -- India and the US differ
        by about 9% over a quarter -- so there is NO reliable test that separates
        "bad data" from "right data, wrong calendar" in the general case.

        Rather than pretend otherwise, this is true whenever the venue was
        GUESSED and anything was found. The remedy is one keyword, so a reminder
        costs the caller nothing and a false accusation would cost their trust.
        Never true for a venue the caller named: that is their call.
        """
        return self.inferred and not self.clean

    def _venue_warning(self) -> str:
        return (f"\n  (venue inferred as {self.exchange} from {self.symbol!r}; "
                f"if that is wrong so is everything above -- pass exchange=, "
                f"see bourse.status())")

    def summary(self) -> str:
        if self.clean:
            return (f"{self.symbol} [{self.exchange}]: clean "
                    f"({self.n_rows} rows / {self.n_sessions_expected} sessions)")
        parts = " ".join(f"{f.kind}={len(f)}" for f in self.findings)
        out = f"{self.symbol} [{self.exchange}]: {parts}"
        return out + self._venue_warning() if self.wrong_venue_suspected else out

    def explain(self) -> str:
        if self.clean:
            return self.summary()
        out = [self.summary(), ""]
        for f in self.findings:
            shown = ", ".join(str(d) for d in f.dates[:5])
            more = f" (+{len(f) - 5} more)" if len(f) > 5 else ""
            out += [f"  {f.kind} [{len(f)}]", f"    {f.detail}",
                    f"    {shown}{more}", ""]
        return "\n".join(out)


_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
         "Saturday", "Sunday")


def _dominant_weekday(missing, min_n: int = 8,
                      share: float = 0.8) -> tuple[int, float] | None:
    """Is one weekday responsible for nearly all the misses?

    A venue that trades Sunday-Thursday served through a Monday-Friday
    assumption loses every Sunday and nothing else, so the misses concentrate
    almost perfectly. Genuine data loss does not do that. The floor of 8 keeps
    a handful of ordinary holidays from tripping it by coincidence.
    """
    if len(missing) < min_n:
        return None
    counts: dict[int, int] = {}
    for d in missing:
        counts[d.weekday()] = counts.get(d.weekday(), 0) + 1
    day, n = max(counts.items(), key=lambda kv: kv[1])
    frac = n / len(missing)
    return (day, frac) if frac >= share else None


def _close(df: pd.DataFrame) -> pd.Series:
    """Pull a close series out of whatever shape the caller passed.

    yfinance returns a (field, ticker) MultiIndex even for a single ticker,
    which is a common source of silent breakage in callers' code.
    """
    d = df.copy()
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    for name in ("Close", "close", "Adj Close", "adj_close"):
        if name in d.columns:
            s = d[name]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            s.index = pd.DatetimeIndex(s.index).normalize()
            return s.astype(float)
    raise KeyError(f"no Close column in {list(d.columns)[:8]}")


def _flat_zero_volume(df: pd.DataFrame) -> set[date]:
    d = df.copy()
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    if not {"Open", "High", "Low", "Close", "Volume"} <= set(d.columns):
        return set()
    idx = pd.DatetimeIndex(d.index).normalize()
    flat = ((d["Volume"] == 0) & (d["Open"] == d["High"]) &
            (d["High"] == d["Low"]) & (d["Low"] == d["Close"]))
    return {x.date() for x in idx[flat.to_numpy()]}


def audit(df: pd.DataFrame, symbol: str, *, exchange: str = cals.AUTO,
          exchange_close: pd.Series | None = None,
          jump_threshold: float = 0.15) -> Report:
    """Check one price frame against a venue's trading calendar.

    `df` is a yfinance-shaped frame (Open/High/Low/Close/Volume, DatetimeIndex).

    `exchange` defaults to "auto", which reads the venue off the ticker suffix:
    ".NS" is India, ".HK" is Hong Kong, a bare symbol is the US calendar. Pass
    it explicitly when the symbol carries no suffix to go on.

    `exchange_close` is optional: RAW, UNADJUSTED exchange closes indexed by
    date. Supplying it enables the strongest check -- fabricated adjustment
    jumps -- because the exchange's own price is the only way to tell an
    invented -33% day from a real one.

    >>> import yfinance as yf, bourse
    >>> df = yf.download("AAPL", start="2023-01-01", end="2024-01-01")
    >>> bourse.audit(df, "AAPL", exchange="NASDAQ").summary()
    'AAPL [NASDAQ]: clean (250 rows / 250 sessions)'
    """
    ex = cals.resolve(exchange, symbol)
    close = _close(df)
    have = {d.date() for d in close.index}
    if not have:
        raise ValueError(f"{symbol}: empty price frame")
    first, last = cals.coverage(ex.code)
    lo, hi = max(min(have), first), min(max(have), last)
    expected = set(cals.sessions(lo, hi, exchange=ex.code))

    findings: list[Finding] = []

    missing = sorted(expected - have)
    if missing:
        findings.append(Finding(
            "missing_sessions", tuple(missing),
            f"Sessions {ex.code} traded that this series lacks. On NSE these are "
            f"typically weekend specials no price-API calendar carries; on "
            f"Sunday-Thursday venues they are usually a dropped weekday, which "
            f"is reported separately below when that is what it is."))
        wd = _dominant_weekday(missing)
        if wd is not None:
            day, share = wd
            findings.append(Finding(
                "dropped_weekday", tuple(missing),
                f"{share:.0%} of the missing sessions fall on {_DAYS[day]}. This "
                f"is not scattered data loss -- the source is serving a "
                f"Monday-Friday week to a venue that does not keep one, and every "
                f"{_DAYS[day]} session is gone. Nothing raises, and a holiday-count "
                f"check cannot see it."))

    flat = _flat_zero_volume(df)
    unexpected = sorted(d for d in have
                        if d not in expected and d not in flat and lo <= d <= hi)
    if unexpected:
        findings.append(Finding(
            "unexpected_sessions", tuple(unexpected),
            "Rows on dates this venue did not trade, carrying real volume -- so "
            "not phantom rows. Either the calendar is wrong for this series, or "
            "the series is not from this venue at all."))

    phantoms = sorted(d for d in flat if d not in expected and lo <= d <= hi)
    if phantoms:
        findings.append(Finding(
            "phantom_rows", tuple(phantoms),
            "Zero-volume flat rows on non-sessions. Drop them as MISSING, not as "
            "0% returns -- kept, they understate volatility and inflate every "
            "t-statistic built on it."))

    stale = sorted(d for d in flat if d in expected)
    if stale:
        findings.append(Finding(
            "stale_sessions", tuple(stale),
            "REAL sessions carrying a repeated close. The exchange traded; the "
            "series did not notice. Do NOT delete these -- repair them from the "
            "exchange record, or exclude the dates and say so."))

    if exchange_close is not None and len(exchange_close):
        findings += _adjustment_findings(close, exchange_close, jump_threshold)

    return Report(symbol=symbol, exchange=ex.code,
                  n_rows=len(close), n_sessions_expected=len(expected),
                  findings=findings,
                  inferred=str(exchange).lower() == cals.AUTO)


def _adjustment_findings(adjusted: pd.Series, raw: pd.Series,
                         threshold: float) -> list[Finding]:
    """Fabricated jumps, via the two-sided test that separates them from reality.

    For a consistent back-adjustment, implied_factor = raw / adjusted is
    NON-INCREASING through time and steps only on corporate-action dates. A
    factor that RISES going forward means the adjustment covers part of the
    history only.

    But a rise is not by itself impossible: a share consolidation (reverse
    split) produces one legitimately. So a rise is reported only when the
    exchange's OWN close did not move with it. Without that second side, every
    reverse split would be condemned as fabricated.
    """
    r = raw.copy()
    r.index = pd.DatetimeIndex(r.index).normalize()
    j = pd.DataFrame({"adj": adjusted, "raw": r}).dropna()
    if len(j) < 3:
        return []
    factor = (j["raw"] / j["adj"]).replace([float("inf"), float("-inf")], pd.NA).dropna()
    if len(factor) < 3:
        return []
    step, raw_move = factor.pct_change(), j["raw"].pct_change()

    bad = [ts.date() for ts, s in step.items()
           if s is not None and s > threshold
           and abs(raw_move.get(ts, 0.0) or 0.0) < 0.03]
    if not bad:
        return []
    return [Finding(
        "fabricated_jumps", tuple(sorted(bad)),
        "The implied adjustment factor rises but the exchange price did not "
        "move. The adjusted series contains a price change that never happened. "
        "Re-adjust from raw exchange closes, or drop the name.")]


def audit_many(frames: dict, *, exchange: str = cals.AUTO,
               exchange_close: dict | None = None, **kw) -> pd.DataFrame:
    """Audit a {symbol: frame} mapping. One row per symbol, sorted worst-first."""
    rows = []
    for sym, df in frames.items():
        try:
            rep = audit(df, sym, exchange=exchange,
                        exchange_close=(exchange_close or {}).get(sym), **kw)
        except Exception as e:                            # noqa: BLE001
            rows.append({"symbol": sym, "error": f"{type(e).__name__}: {e}"})
            continue
        row = {"symbol": sym, "rows": rep.n_rows,
               "sessions": rep.n_sessions_expected, "clean": rep.clean}
        for kind in ("fabricated_jumps", "stale_sessions", "phantom_rows",
                     "unexpected_sessions", "missing_sessions"):
            f = rep[kind]
            row[kind] = len(f) if f else 0
        rows.append(row)
    out = pd.DataFrame(rows)
    if "clean" in out.columns:
        cols = ["fabricated_jumps", "stale_sessions", "phantom_rows",
                "unexpected_sessions", "missing_sessions"]
        out["_severity"] = out[cols].fillna(0).sum(axis=1)
        out = out.sort_values("_severity", ascending=False).drop(columns="_severity")
    return out.reset_index(drop=True)
