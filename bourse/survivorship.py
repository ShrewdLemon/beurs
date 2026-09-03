"""Which of these tickers silently returns nothing?

THE BUG THIS CATCHES. A price API asked for a delisted, renamed or acquired
ticker does not raise. It returns an empty frame. Callers written the obvious
way -- loop the universe, download, concat -- drop those names on the floor and
never learn they existed.

The survivors are what remains, and survivors outperform by construction. This
is survivorship bias, and it is not a historical-database problem you can read
about and dismiss: it happens LIVE, today, to anyone building a universe from a
ticker list.

MEASURED. Fifteen US small and micro caps, all real listings within the window:

    returned data   SIRI LCID PLUG AMC GME CVNA SNDL ATER      8/15
    returned NOTHING NKLA BBBYQ WE FFIE RIDE GNUS MULN         7/15

Every one of the seven went bankrupt, was delisted, or was renamed. Not one
raised an exception. A backtest over that universe silently becomes a backtest
over the eight that lived -- and then reports a healthy return.

WHAT `screen` DOES. Asks for each ticker, and sorts the answers into four
buckets that mean different things:

    ok          a full-length series came back
    empty       the API returned nothing at all -- the silent case
    short       data came back, but far less than the window asked for, which
                is what an IPO, a delisting mid-window, or a halt looks like
    error       the request itself failed; a network problem, not a finding

`empty` and `short` are the ones that bias a universe. `short` is separated out
because it is the more insidious of the two: the name IS there, the frame is
non-empty, and every naive length check passes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

OK, EMPTY, SHORT, ERROR = "ok", "empty", "short", "error"


@dataclass
class Row:
    ticker: str
    status: str
    n_rows: int = 0
    first: object = None
    last: object = None
    detail: str = ""


@dataclass
class Screen:
    start: str
    end: str
    exchange: str
    rows: list[Row] = field(default_factory=list)

    def _of(self, status: str) -> list[Row]:
        return [r for r in self.rows if r.status == status]

    @property
    def ok(self) -> list[str]:
        return [r.ticker for r in self._of(OK)]

    @property
    def empty(self) -> list[str]:
        return [r.ticker for r in self._of(EMPTY)]

    @property
    def short(self) -> list[str]:
        return [r.ticker for r in self._of(SHORT)]

    @property
    def errors(self) -> list[str]:
        return [r.ticker for r in self._of(ERROR)]

    @property
    def biased(self) -> bool:
        """True if building a universe from this list would drop names silently."""
        return bool(self.empty or self.short)

    @property
    def survivor_rate(self) -> float:
        n = len(self.rows)
        return len(self.ok) / n if n else 0.0

    def to_frame(self):
        import pandas as pd
        return pd.DataFrame([r.__dict__ for r in self.rows])

    def summary(self) -> str:
        n = len(self.rows)
        if not n:
            return "no tickers screened"
        head = (f"{n} tickers [{self.exchange}] {self.start}..{self.end}: "
                f"ok={len(self.ok)} empty={len(self.empty)} "
                f"short={len(self.short)} error={len(self.errors)}")
        if not self.biased and not self.errors:
            return head + "\nno silent drops -- this universe is safe to build from"
        lines = [head, ""]
        if self.empty:
            lines += ["  empty  -- returned NOTHING, no exception raised",
                      "           " + " ".join(self.empty), ""]
        if self.short:
            lines += ["  short  -- returned far less than the window asked for",
                      "           " + " ".join(f"{r.ticker}({r.n_rows})"
                                               for r in self._of(SHORT)), ""]
        if self.errors:
            lines += ["  error  -- request failed; retry before treating as a finding",
                      "           " + " ".join(self.errors), ""]
        drop = len(self.empty) + len(self.short)
        if drop:
            lines.append(f"  {drop}/{n} names ({drop / n:.0%}) would vanish from a "
                         f"universe built by looping this list.")
            lines.append("  Survivors outperform by construction. Any backtest "
                         "over the remainder is biased upward.")
        else:
            lines.append("  No silent drops. The errors above are requests that "
                         "failed, not names that disappeared -- retry them "
                         "before drawing any conclusion.")
        return "\n".join(lines)


def screen(tickers, *, start: str = "2023-01-01", end: str = "2026-06-30",
           exchange: str = "auto", min_fraction: float = 0.5,
           workers: int = 8, download=None) -> Screen:
    """Ask for every ticker and report which ones silently return nothing.

    >>> bourse.screen(["AAPL", "NKLA", "BBBYQ"]).summary()

    `min_fraction` is the share of the window's expected sessions below which a
    result counts as `short` rather than `ok`.

    `workers` fetches in parallel. This is entirely network-bound -- the
    classification costs under a millisecond a name -- so concurrency is the
    only thing that makes a 500-name universe practical. Set `workers=1` for a
    source that rate-limits, or to keep the order of requests deterministic.

    `download` is injectable, so this is testable without a network and usable
    with any source, not just yfinance.
    """
    from concurrent.futures import ThreadPoolExecutor

    from . import calendars as cals

    tickers = [str(t).strip() for t in tickers if str(t).strip()]
    if download is None:
        download = _yf_download

    # One list is normally one venue, so resolve it from the first ticker that
    # yields a guess rather than demanding the caller name it.
    code = exchange
    if str(exchange).lower() == cals.AUTO:
        code = next((g for t in tickers if (g := cals.infer(t))), "US")
    code = cals.resolve(code).code

    expected = _expected_sessions(start, end, code)
    out = Screen(start=str(start), end=str(end), exchange=code)

    def one(t: str) -> Row:
        try:
            df = download(t, start, end)
        except Exception as e:                             # noqa: BLE001
            return Row(t, ERROR, detail=f"{type(e).__name__}: {e}")
        if df is None or not len(df):
            return Row(t, EMPTY, 0, detail=(
                "returned an empty frame and did not raise. Delisted, renamed, "
                "acquired, or never listed under this symbol."))
        n = len(df)
        try:
            first, last = df.index[0].date(), df.index[-1].date()
        except Exception:                                  # noqa: BLE001
            first = last = None
        if expected and n < expected * min_fraction:
            return Row(t, SHORT, n, first, last, detail=(
                f"{n} rows where the window holds about {expected}. Listed late, "
                f"delisted early, or halted mid-window -- the frame is non-empty, "
                f"so a length check will not catch it."))
        return Row(t, OK, n, first, last)

    if workers > 1 and len(tickers) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            out.rows = list(pool.map(one, tickers))        # input order preserved
    else:
        out.rows = [one(t) for t in tickers]
    return out


def _expected_sessions(start, end, exchange) -> int:
    from . import calendars as cals
    try:
        lo, hi = cals.coverage(exchange)
        a, b = cals._as_date(start), cals._as_date(end)
        return cals.count(max(a, lo), min(b, hi), exchange=exchange)
    except Exception:                                      # noqa: BLE001
        return 0


def _yf_download(ticker: str, start, end):
    try:
        import yfinance as yf
    except ImportError as e:                               # pragma: no cover
        raise RuntimeError("screen() needs yfinance: pip install bourse[fetch]") from e
    return yf.download(ticker, start=start, end=end, auto_adjust=True,
                       progress=False, threads=False)
