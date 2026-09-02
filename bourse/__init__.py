"""bourse -- market data that does not lie to you.

Audit any price series against the exchange that produced it.

    import yfinance as yf, bourse

    df = yf.download("TRENT.NS", start="2023-01-01", end="2026-07-01")
    print(bourse.audit(df, "TRENT", exchange="NSE").explain())

Works on any supported venue -- NSE, NYSE, NASDAQ, SSE, HKEX, LSE, TSE. The
failure modes are properties of price APIs, not of any one market.

Calendars carry their provenance: NSE is shipped VERIFIED against the exchange's
own record (exchange_calendars has no XNSE and its XBOM is wrong for Indian
equities); the rest are SOURCED from exchange_calendars, which is correct for
them. `bourse.status()` prints the table.

See TRAPS.md for the 13 measured failure modes this came from.
"""
from .audit import Finding, Report, audit, audit_many
from .bhavcopy import Unavailable, bhavcopy, returns, security_master
from .calendars import (DEFAULT, EXCHANGES, OutOfRange, UnknownExchange,
                        audit_calendar, count, coverage, exchanges, is_session,
                        next_session, offset, previous_session, sessions, status)

__version__ = "0.1.0"

__all__ = [
    "audit", "audit_many", "Report", "Finding",
    "sessions", "is_session", "next_session", "previous_session", "offset",
    "count", "coverage", "audit_calendar", "exchanges", "status",
    "bhavcopy", "security_master", "returns",
    "OutOfRange", "UnknownExchange", "Unavailable", "EXCHANGES", "DEFAULT",
]
