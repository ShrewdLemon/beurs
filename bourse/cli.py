"""Command line: audit a ticker without writing any Python.

    bourse audit TRENT.NS --exchange NSE
    bourse audit AAPL MSFT JPM --exchange NASDAQ
    bourse sessions 2024-01-01 2024-12-31 --exchange NYSE
    bourse status

The audit is the reason to have a CLI at all: "is my data lying to me" is a
question people ask once, about a ticker, before deciding whether to trust a
source. Making them write a script to find out loses most of them.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__, calendars as cals
from .audit import audit, audit_many


def _download(tickers: list[str], start: str, end: str):
    try:
        import yfinance as yf
    except ImportError:
        sys.exit("this command needs yfinance:  pip install yfinance")
    out = {}
    for t in tickers:
        df = yf.download(t, start=start, end=end, auto_adjust=True,
                         progress=False, threads=False)
        if df is None or df.empty:
            print(f"  {t}: NO DATA RETURNED -- a live listed name can silently "
                  f"return nothing; that is itself a finding", file=sys.stderr)
            continue
        out[t] = df
    return out


def cmd_audit(a) -> int:
    frames = _download(a.tickers, a.start, a.end)
    if not frames:
        return 1
    if len(frames) == 1:
        sym, df = next(iter(frames.items()))
        rep = audit(df, sym, exchange=a.exchange)
        print(rep.explain() if a.verbose else rep.summary())
        return 0 if rep.clean else 2
    table = audit_many(frames, exchange=a.exchange)
    print(table.to_string(index=False))
    return 0 if bool(table["clean"].all()) else 2


def cmd_sessions(a) -> int:
    s = cals.sessions(a.start, a.end, exchange=a.exchange)
    if a.count:
        print(len(s))
    else:
        for d in s:
            print(d)
    return 0


def cmd_status(a) -> int:
    print(cals.status())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="bourse",
        description="Audit market data against the exchange that produced it.")
    p.add_argument("--version", action="version", version=f"bourse {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="check one or more tickers for silent failures")
    a.add_argument("tickers", nargs="+")
    a.add_argument("-e", "--exchange", default=cals.DEFAULT,
                   help=f"venue the ticker trades on (default {cals.DEFAULT})")
    a.add_argument("-s", "--start", default="2023-01-01")
    a.add_argument("-t", "--end", default="2026-06-30")
    a.add_argument("-v", "--verbose", action="store_true",
                   help="explain every finding rather than summarising")
    a.set_defaults(fn=cmd_audit)

    c = sub.add_parser("sessions", help="list verified trading sessions")
    c.add_argument("start")
    c.add_argument("end")
    c.add_argument("-e", "--exchange", default=cals.DEFAULT)
    c.add_argument("-n", "--count", action="store_true", help="print the count only")
    c.set_defaults(fn=cmd_sessions)

    s = sub.add_parser("status", help="show every venue and its calendar provenance")
    s.set_defaults(fn=cmd_status)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (cals.UnknownExchange, cals.OutOfRange) as e:
        sys.exit(str(e))


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
