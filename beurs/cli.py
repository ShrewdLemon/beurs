"""Command line: answer "is my data lying to me" without writing any Python.

    beurs audit  TRENT.NS                 what is wrong with this series
    beurs repair TRENT.NS -o clean.csv    hand me back one I can use
    beurs screen tickers.txt              which of these silently return nothing
    beurs venues                          54 exchanges and their provenance
    beurs sessions 2024-01-01 2024-12-31 -e NYSE

The venue is inferred from the ticker suffix, so `-e` is optional: `.NS` is
India, `.HK` is Hong Kong, a bare symbol is the US calendar.

EXIT CODES, because this is meant to sit in CI:
    0  clean
    1  could not run (no data, bad arguments)
    2  findings -- the data has a problem
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from . import calendars as cals
from .audit import audit, audit_many

CLEAN, FAILED, FINDINGS = 0, 1, 2


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _download(tickers: list[str], start: str, end: str) -> dict:
    try:
        import yfinance as yf
    except ImportError as e:
        _err("this command needs yfinance:  pip install 'beurs[fetch]'")
        raise SystemExit(FAILED) from e
    out = {}
    for t in tickers:
        try:
            df = yf.download(t, start=start, end=end, auto_adjust=True,
                             progress=False, threads=False)
        except Exception as e:                             # noqa: BLE001
            _err(f"  {t}: request failed -- {type(e).__name__}: {e}")
            continue
        if df is None or df.empty:
            _err(f"  {t}: NO DATA RETURNED, and no exception was raised. A "
                 f"delisted or renamed name looks exactly like this. Run "
                 f"`beurs screen` to check a whole universe for it.")
            continue
        out[t] = df
    return out


def _read_tickers(args: list[str]) -> list[str]:
    """Accept tickers inline, from a file, or on stdin.

    `beurs screen universe.txt` and `cat universe.txt | beurs screen -` both
    work, because a universe is normally already in a file somewhere.
    """
    out: list[str] = []
    for a in args:
        if a == "-":
            out += [x.strip() for x in sys.stdin.read().split()]
            continue
        try:
            with open(a, encoding="utf-8") as fh:
                out += [ln.split("#")[0].strip() for ln in fh]
            continue
        except (OSError, ValueError):
            out.append(a)
    return [t for t in out if t]


def cmd_audit(a) -> int:
    frames = _download(a.tickers, a.start, a.end)
    if not frames:
        return FAILED
    if len(frames) == 1:
        sym, df = next(iter(frames.items()))
        rep = audit(df, sym, exchange=a.exchange)
        print(rep.explain() if a.verbose else rep.summary())
        return CLEAN if rep.clean else FINDINGS
    table = audit_many(frames, exchange=a.exchange)
    print(table.to_string(index=False))
    return CLEAN if bool(table["clean"].all()) else FINDINGS


def cmd_repair(a) -> int:
    from .repair import repair

    frames = _download([a.ticker], a.start, a.end)
    if not frames:
        return FAILED
    sym, df = next(iter(frames.items()))
    out = repair(df, sym, exchange=a.exchange)
    print(out.log.summary(), file=sys.stderr)
    for n in out.log.notes:
        print(f"  note: {n}", file=sys.stderr)
    print(f"  {out.usable_rows} usable rows of {len(out.frame)}", file=sys.stderr)

    if a.output:
        if a.output.endswith(".parquet"):
            out.frame.to_parquet(a.output)
        else:
            out.frame.to_csv(a.output)
        print(f"  written to {a.output}", file=sys.stderr)
    else:
        out.frame.to_csv(sys.stdout)
    return CLEAN if out.log.n_changed == 0 else FINDINGS


def cmd_screen(a) -> int:
    from .survivorship import screen

    tickers = _read_tickers(a.tickers)
    if not tickers:
        _err("no tickers given")
        return FAILED
    out = screen(tickers, start=a.start, end=a.end, exchange=a.exchange,
                 workers=a.workers)
    print(out.summary())
    return FINDINGS if out.biased else CLEAN


def cmd_sessions(a) -> int:
    s = cals.sessions(a.start, a.end, exchange=a.exchange)
    if a.count:
        print(len(s))
    else:
        print("\n".join(str(d) for d in s))
    return CLEAN


def cmd_venues(a) -> int:
    print(cals.status(full=a.full))
    return CLEAN


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="beurs",
        description="Audit, repair and screen market data against the exchange "
                    "that produced it. 54 venues.",
        epilog="exit codes: 0 clean, 1 could not run, 2 findings")
    p.add_argument("--version", action="version", version=f"beurs {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def window(sp, exchange_default=cals.AUTO):
        sp.add_argument("-e", "--exchange", default=exchange_default,
                        help="venue; default infers it from the ticker suffix")
        sp.add_argument("-s", "--start", default="2023-01-01")
        sp.add_argument("-t", "--end", default="2026-06-30")

    a = sub.add_parser("audit", help="check tickers for silent failures")
    a.add_argument("tickers", nargs="+")
    window(a)
    a.add_argument("-v", "--verbose", action="store_true",
                   help="explain every finding rather than summarising")
    a.set_defaults(fn=cmd_audit)

    r = sub.add_parser("repair", help="write out a corrected series")
    r.add_argument("ticker")
    window(r)
    r.add_argument("-o", "--output", help="CSV or .parquet path; default stdout")
    r.set_defaults(fn=cmd_repair)

    sc = sub.add_parser("screen",
                        help="find tickers that silently return nothing")
    sc.add_argument("tickers", nargs="+",
                    help="tickers, a file of tickers, or - for stdin")
    window(sc)
    sc.add_argument("-j", "--workers", type=int, default=8,
                    help="parallel fetches; 1 if your source rate-limits")
    sc.set_defaults(fn=cmd_screen)

    c = sub.add_parser("sessions", help="list trading sessions")
    c.add_argument("start")
    c.add_argument("end")
    c.add_argument("-e", "--exchange", default=cals.DEFAULT)
    c.add_argument("-n", "--count", action="store_true", help="print the count only")
    c.set_defaults(fn=cmd_sessions)

    v = sub.add_parser("venues", help="every exchange and its calendar provenance")
    v.add_argument("--full", action="store_true",
                   help="also resolve each calendar's date range (slower)")
    v.set_defaults(fn=cmd_venues)

    sub.add_parser("status", help="alias for `venues`").set_defaults(
        fn=cmd_venues, full=False)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (cals.UnknownExchange, cals.OutOfRange) as e:
        _err(str(e))
        return FAILED
    except BrokenPipeError:                                # `| head`
        return CLEAN


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
