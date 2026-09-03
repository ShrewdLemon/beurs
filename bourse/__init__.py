"""bourse -- market data that does not lie to you.

Audit any price series against the exchange that produced it.

    import yfinance as yf, bourse

    df = yf.download("TRENT.NS", start="2023-01-01", end="2026-07-01")
    print(bourse.audit(df, "TRENT", exchange="NSE").explain())

Fifty-four venues across every major market. `exchange` defaults to "auto",
which reads the venue off the ticker suffix. The failure modes are properties of
price APIs, not of any one market.

Three things it does:

    bourse.audit(df, "TRENT.NS")     what is wrong with this series
    bourse.repair(df, "TRENT.NS")    hand me back one I can use
    bourse.screen(universe)          which of these silently return nothing

Calendars carry their provenance: NSE is shipped VERIFIED against the exchange's
own record (exchange_calendars has no XNSE and its XBOM is wrong for Indian
equities); the rest are SOURCED from exchange_calendars, which is correct for
them. `bourse.status()` prints the table.

See TRAPS.md for the 13 measured failure modes this came from.
"""
from .audit import Finding, Report, audit, audit_many
from .bhavcopy import Unavailable, bhavcopy, returns, security_master
from .calendars import (
                        AUTO,
                        DEFAULT,
                        EXCHANGES,
                        Exchange,
                        OutOfRange,
                        UnknownExchange,
                        audit_calendar,
                        count,
                        coverage,
                        exchanges,
                        infer,
                        is_session,
                        next_session,
                        offset,
                        previous_session,
                        sessions,
                        status,
)
from .repair import Repaired, RepairLog, repair, repair_many
from .survivorship import Screen, screen

__version__ = "0.2.0"

__all__ = [
                        "AUTO",
                        "DEFAULT",
                        "EXCHANGES",
                        "Exchange",
                        "Finding",
                        "OutOfRange",
                        "RepairLog",
                        "Repaired",
                        "Report",
                        "Screen",
                        "Unavailable",
                        "UnknownExchange",
                        "audit",
                        "audit_calendar",
                        "audit_many",
                        "bhavcopy",
                        "count",
                        "coverage",
                        "exchanges",
                        "infer",
                        "is_session",
                        "next_session",
                        "offset",
                        "previous_session",
                        "repair",
                        "repair_many",
                        "returns",
                        "screen",
                        "security_master",
                        "sessions",
                        "status",
]
