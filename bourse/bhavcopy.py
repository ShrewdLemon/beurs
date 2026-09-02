"""NSE bhavcopy: the exchange's own end-of-day file, normalised.

Two things make this more than a URL.

TWO ARCHIVE LAYOUTS, AND YOU NEED BOTH. The legacy path stops working around
mid-2024 and the current path does not reach back to 2023. A loader that knows
only one silently loses roughly two of three and a half years -- with 404s, not
errors.

    legacy   /content/historical/EQUITIES/{YYYY}/{MON}/cm{DDMONYYYY}bhav.csv.zip
    current  /content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip

The column names differ too, so both are normalised to one schema.

SERIES 'EQ' IS NOT ENOUGH. Filter `SERIES in ('EQ','BE')`. PATANJALI traded in
BE and is invisible to an EQ-only filter.

Why bother when a price API is one line? Because the bhavcopy is the only source
that distinguishes "did not trade" from "traded flat", carries ISIN (the one
identifier stable across renames), and is not adjusted -- so it is the reference
you check an adjusted series against. See `bhavkit.audit`.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd

LEGACY = ("https://nsearchives.nseindia.com/content/historical/EQUITIES/"
          "{year}/{mon}/cm{ddmonyyyy}bhav.csv.zip")
CURRENT = ("https://nsearchives.nseindia.com/content/cm/"
           "BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip")

HEADERS = {
    "Referer": "https://www.nseindia.com/",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
}

EQUITY_SERIES = ("EQ", "BE")

COLUMNS = ["date", "symbol", "series", "isin", "open", "high", "low", "close",
           "prev_close", "volume", "turnover", "trades"]

_CURRENT_COLS = {
    "TckrSymb": "symbol", "SctySrs": "series", "OpnPric": "open",
    "HghPric": "high", "LwPric": "low", "ClsPric": "close",
    "PrvsClsgPric": "prev_close", "TtlTradgVol": "volume",
    "TtlTrfVal": "turnover", "TtlNbOfTxsExctd": "trades", "ISIN": "isin",
}
_LEGACY_COLS = {
    "SYMBOL": "symbol", "SERIES": "series", "OPEN": "open", "HIGH": "high",
    "LOW": "low", "CLOSE": "close", "PREVCLOSE": "prev_close",
    "TOTTRDQTY": "volume", "TOTTRDVAL": "turnover", "TOTALTRADES": "trades",
    "ISIN": "isin",
}


class Unavailable(Exception):
    """Neither archive layout served this date.

    Raised, never returned as an empty frame. A session you could not load is a
    hole in every window that spans it, and a loader that reports it as "no rows"
    is indistinguishable from one reporting a genuine market holiday.
    """


def _get(url: str):
    try:
        from curl_cffi import requests as http
        return http.get(url, impersonate="chrome", headers=HEADERS, timeout=60)
    except ImportError:                                   # pragma: no cover
        import requests
        return requests.get(url, headers=HEADERS, timeout=60)


def _read_zip(content: bytes) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(content))
    df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
    df.columns = [c.strip() for c in df.columns]
    return df


def _normalise(df: pd.DataFrame, mapping: dict, day: date,
               series: tuple[str, ...]) -> pd.DataFrame:
    out = df.rename(columns=mapping)
    out = out[[c for c in COLUMNS if c in out.columns]].copy()
    out["date"] = day
    for c in ("symbol", "series", "isin"):
        if c in out:
            out[c] = out[c].astype(str).str.strip()
    out = out[out["series"].isin(series)]
    return out.reindex(columns=COLUMNS).reset_index(drop=True)


def bhavcopy(day, *, series: tuple[str, ...] = EQUITY_SERIES,
             cache_dir: str | Path | None = None) -> pd.DataFrame:
    """One session's end-of-day file, from whichever archive layout serves it.

    >>> df = bhavcopy("2024-01-20")        # a Saturday NSE actually traded
    >>> len(df)
    2098
    """
    d = day if isinstance(day, date) and not isinstance(day, datetime) else (
        day.date() if isinstance(day, datetime) else date.fromisoformat(str(day)[:10]))

    cache = Path(cache_dir) if cache_dir else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        hit = cache / f"{d:%Y%m%d}.parquet"
        if hit.exists():
            return pd.read_parquet(hit)

    attempts = (
        (LEGACY.format(year=d.year, mon=d.strftime("%b").upper(),
                       ddmonyyyy=d.strftime("%d%b%Y").upper()), _LEGACY_COLS),
        (CURRENT.format(yyyymmdd=d.strftime("%Y%m%d")), _CURRENT_COLS),
    )
    errors = []
    for url, mapping in attempts:
        try:
            r = _get(url)
            if r.status_code == 200 and len(r.content) > 1000:
                out = _normalise(_read_zip(r.content), mapping, d, series)
                if len(out):
                    if cache:
                        out.to_parquet(cache / f"{d:%Y%m%d}.parquet")
                    return out
                errors.append("parsed 0 equity rows")
            else:
                errors.append(f"HTTP {r.status_code} ({len(r.content)}B)")
        except Exception as e:                            # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")
    raise Unavailable(f"{d}: " + "; ".join(errors))


def security_master(day, **kw) -> pd.DataFrame:
    """Every symbol and ISIN listed on a session.

    The point-in-time identity map. Resolving a historical symbol through
    today's index constituent file cannot work -- that file lists only names
    still in the index, so a company that was renamed AND dropped, which is
    exactly the survivorship population, comes back unresolved.
    """
    df = bhavcopy(day, **kw)
    return df[["symbol", "series", "isin", "close"]].drop_duplicates()


def returns(frames: dict, symbol: str) -> pd.Series:
    """Close-to-close returns for one symbol across a dict of {date: frame}.

    No forward fill, ever. A session the stock did not trade is absent, not
    flat -- the gap between "did not trade" and "traded flat" is why this
    package exists.

    NOTE these are RAW exchange closes and are NOT adjusted for corporate
    actions. `prev_close` in the bhavcopy is the previous traded close and is
    NOT ex-adjusted either: RELIANCE's 1:2 reads -49.76% and BAJFINANCE's
    split-plus-bonus reads -89.95%. Use `bhavkit.audit.suspected_actions` to
    find them.
    """
    rows = []
    for d, df in sorted(frames.items()):
        hit = df[df["symbol"] == symbol]
        if len(hit):
            rows.append((pd.Timestamp(d), float(hit.iloc[0]["close"])))
    if not rows:
        return pd.Series(dtype="float64")
    s = pd.Series({d: c for d, c in rows}).sort_index()
    return s.pct_change()
