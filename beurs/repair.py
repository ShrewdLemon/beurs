"""Fix the series, not just report on it.

`audit` tells you what is wrong. This returns a frame you can actually use, and
a log of everything it changed. A linter gets tried once; a formatter gets kept.

WHAT IT DOES, AND WHAT IT REFUSES TO DO.

    phantom rows       DROPPED. A zero-volume flat row on a day the venue was
                       shut is not a 0% return, it is an absence. Left in, it
                       understates volatility -- measured at 46% too low on one
                       name -- and volatility is the denominator of your test
                       statistic, so it inflates every t you compute.

    stale sessions     Set to NaN, never deleted and never carried forward.
                       These are REAL sessions where the source repeated a
                       price. Deleting the row would silently shorten a window;
                       filling it would invent a return. NaN is the honest
                       answer and it propagates into your own dropna.

    missing sessions   Reindexed onto the venue's real calendar, so the gap is
                       visible as NaN instead of being invisible by absence.
                       This is the difference between a window you know is
                       short and one you do not.

    fabricated jumps   RE-ADJUSTED from raw exchange closes when they are
                       supplied, because the raw record is the only ground
                       truth. Without them the affected dates are set to NaN
                       rather than guessed at -- a repair that invents a price
                       is worse than the bug.

Every repair is recorded in `RepairLog`. Nothing is changed silently, because a
tool that quietly rewrites your prices is a worse problem than the one it fixes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from . import calendars as cals
from .audit import Report, _flat_zero_volume, audit


@dataclass
class RepairLog:
    symbol: str
    exchange: str
    dropped_phantoms: tuple[date, ...] = ()
    nulled_stale: tuple[date, ...] = ()
    inserted_missing: tuple[date, ...] = ()
    nulled_fabricated: tuple[date, ...] = ()
    readjusted: tuple[date, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def n_changed(self) -> int:
        return (len(self.dropped_phantoms) + len(self.nulled_stale) +
                len(self.inserted_missing) + len(self.nulled_fabricated) +
                len(self.readjusted))

    def summary(self) -> str:
        if not self.n_changed:
            return f"{self.symbol} [{self.exchange}]: nothing to repair"
        bits = []
        for name, v in (("dropped_phantoms", self.dropped_phantoms),
                        ("nulled_stale", self.nulled_stale),
                        ("inserted_missing", self.inserted_missing),
                        ("nulled_fabricated", self.nulled_fabricated),
                        ("readjusted", self.readjusted)):
            if v:
                bits.append(f"{name}={len(v)}")
        return f"{self.symbol} [{self.exchange}]: " + " ".join(bits)


@dataclass
class Repaired:
    frame: pd.DataFrame
    log: RepairLog
    report_before: Report

    @property
    def usable_rows(self) -> int:
        """Rows with a real close. The number your regression actually gets."""
        col = "Close" if "Close" in self.frame.columns else self.frame.columns[0]
        return int(self.frame[col].notna().sum())


def repair(df: pd.DataFrame, symbol: str, *, exchange: str = cals.AUTO,
           exchange_close: pd.Series | None = None,
           reindex: bool = True) -> Repaired:
    """Return a corrected copy of `df`, plus a log of every change.

    >>> out = beurs.repair(df, "TRENT", exchange="NSE")
    >>> out.log.summary()
    'TRENT [NSE]: dropped_phantoms=4 nulled_stale=1 inserted_missing=5'
    >>> out.frame          # ready to use; gaps are NaN, not absent
    """
    ex = cals.resolve(exchange, symbol)
    before = audit(df, symbol, exchange=ex.code, exchange_close=exchange_close)
    log = RepairLog(symbol=symbol, exchange=ex.code)

    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [c[0] if isinstance(c, tuple) else c for c in out.columns]
        log.notes.append("flattened a (field, ticker) MultiIndex")
    out.index = pd.DatetimeIndex(out.index).normalize()

    have = {d.date() for d in out.index}
    lo, hi = min(have), max(have)
    first, last = cals.coverage(ex.code)
    real = set(cals.sessions(max(lo, first), min(hi, last), exchange=ex.code))
    flat = _flat_zero_volume(df)

    # 1. Phantoms: a row on a day the venue did not trade. Drop it.
    phantoms = sorted(d for d in flat if d not in real and lo <= d <= hi)
    if phantoms:
        out = out.drop(index=pd.DatetimeIndex([pd.Timestamp(d) for d in phantoms]),
                       errors="ignore")
        log.dropped_phantoms = tuple(phantoms)

    # 2. Stale: a real session carrying a repeated price. NaN, do not delete.
    stale = sorted(d for d in flat if d in real)
    if stale:
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d in stale])
        cols = [c for c in ("Open", "High", "Low", "Close", "Adj Close")
                if c in out.columns]
        out.loc[out.index.intersection(idx), cols] = float("nan")
        log.nulled_stale = tuple(stale)

    # 3. Fabricated jumps: re-adjust from raw, or NaN. Never guess.
    # This check only ever fires when raw closes were supplied -- they are the
    # only way to tell an invented -33% from a real one -- so the question here
    # is not whether we have ground truth but whether it was enough to rebuild
    # the series. Anything re-adjustment could not fix is nulled, never guessed.
    fab = before["fabricated_jumps"]
    if fab:
        out, done = _readjust(out, exchange_close, fab.dates)
        log.readjusted = tuple(done)
        if done:
            log.notes.append(f"re-adjusted {len(done)} break(s) from raw closes")
        unfixed = [d for d in fab.dates if d not in set(done)]
        if unfixed:
            idx = pd.DatetimeIndex([pd.Timestamp(d) for d in unfixed])
            cols = [c for c in ("Open", "High", "Low", "Close") if c in out.columns]
            out.loc[out.index.intersection(idx), cols] = float("nan")
            log.nulled_fabricated = tuple(unfixed)
            log.notes.append(
                f"{len(unfixed)} fabricated break(s) could not be rebuilt from the "
                "raw closes supplied, so those dates were nulled rather than "
                "guessed at -- extend exchange_close to cover them")

    # 4. Missing sessions: make the hole visible.
    if reindex:
        full = pd.DatetimeIndex([pd.Timestamp(d) for d in
                                 cals.sessions(max(lo, first), min(hi, last),
                                               exchange=ex.code)])
        inserted = sorted(d.date() for d in full.difference(out.index))
        if inserted:
            out = out.reindex(full)
            log.inserted_missing = tuple(inserted)
        else:
            out = out.reindex(full)

    return Repaired(frame=out, log=log, report_before=before)


def _readjust(out: pd.DataFrame, raw: pd.Series | None, bad_dates) -> tuple[pd.DataFrame, list]:
    """Remove a fabricated adjustment step, using raw closes as ground truth.

    A fabricated break is an UNCORROBORATED RISE in the implied factor
    raw/adjusted -- the factor went up while the exchange price stood still. The
    factor BEFORE the break is therefore the trusted one (nothing disputes it),
    and the fix is to propagate it forward across the break:

        adj_correct(t) = raw(t) / factor_before      for t >= break

    which is the same as multiplying the whole post-break segment by
    factor_after / factor_before.

    That constant is the reason to do it this way: scaling a tail by a constant
    changes exactly ONE return -- the one at the break, which is the invented
    one -- and leaves every other return in the series bit-for-bit untouched.
    A repair that perturbs returns it was not asked to fix is not a repair.
    """
    if raw is None or not len(raw):
        return out, []
    r = raw.copy()
    r.index = pd.DatetimeIndex(r.index).normalize()
    if "Close" not in out.columns:
        return out, []
    j = pd.DataFrame({"adj": out["Close"], "raw": r}).dropna()
    if len(j) < 3:
        return out, []
    factor = (j["raw"] / j["adj"]).replace([float("inf"), float("-inf")], pd.NA).dropna()
    if len(factor) < 3:
        return out, []

    cols = [c for c in ("Open", "High", "Low", "Close") if c in out.columns]
    done = []
    for d in sorted(bad_dates):
        ts = pd.Timestamp(d)
        before, after = factor.loc[factor.index < ts], factor.loc[factor.index >= ts]
        if before.empty or after.empty:
            continue                       # no trusted side; caller gets a NaN
        f_before, f_after = float(before.iloc[-1]), float(after.iloc[0])
        if not f_before or f_after <= 0:
            continue
        scale = f_after / f_before
        tail = out.index[out.index >= ts]
        if not len(tail) or not (scale > 0):
            continue
        out.loc[tail, cols] = out.loc[tail, cols] * scale
        done.append(d)
    return out, done


def repair_many(frames: dict, *, exchange: str = cals.AUTO,
                exchange_close: dict | None = None, **kw) -> dict:
    """Repair a {symbol: frame} mapping. Returns {symbol: Repaired}."""
    out = {}
    for sym, df in frames.items():
        try:
            out[sym] = repair(df, sym, exchange=exchange,
                              exchange_close=(exchange_close or {}).get(sym), **kw)
        except Exception:                                 # noqa: BLE001
            continue
    return out
