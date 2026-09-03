"""Tests for `screen`. No network: the downloader is injected.

The behaviour under test is the one that costs people real money -- an empty
frame coming back with no exception, and a short frame coming back looking
entirely healthy. Both are sorted into named buckets rather than dropped.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bourse


def _series(days):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0,
                         "Close": 1.0, "Volume": 1}, index=idx)


def _fake(mapping):
    """A downloader that answers from a dict, like a price API would."""
    def download(ticker, start, end):
        v = mapping.get(ticker)
        if isinstance(v, Exception):
            raise v
        return v
    return download


DAYS = None


def _days():
    global DAYS
    if DAYS is None:
        DAYS = bourse.sessions("2024-01-02", "2024-12-31", exchange="NSE")
    return DAYS


def test_an_empty_frame_is_a_finding_not_a_skip():
    """This is the whole point: the API did not raise, so a normal loop would
    have dropped the name without anyone noticing."""
    days = _days()
    out = bourse.screen(
        ["ALIVE", "DEAD"], start="2024-01-02", end="2024-12-31", exchange="NSE",
        download=_fake({"ALIVE": _series(days), "DEAD": pd.DataFrame()}))

    assert out.ok == ["ALIVE"]
    assert out.empty == ["DEAD"]
    assert out.biased
    assert out.survivor_rate == 0.5


def test_none_counts_as_empty_too():
    out = bourse.screen(["X"], start="2024-01-02", end="2024-12-31",
                        exchange="NSE", download=_fake({"X": None}))
    assert out.empty == ["X"]


def test_a_short_series_is_separated_from_a_full_one():
    """The insidious case: the frame is NOT empty, so every length check and
    every try/except passes, and the name still biases the universe."""
    days = _days()
    out = bourse.screen(
        ["FULL", "IPO"], start="2024-01-02", end="2024-12-31", exchange="NSE",
        download=_fake({"FULL": _series(days), "IPO": _series(days[-20:])}))

    assert out.ok == ["FULL"]
    assert out.short == ["IPO"]
    assert out.biased


def test_an_exception_is_an_error_not_a_delisting():
    """A network failure is not evidence about the listing. Keeping them apart
    stops a flaky connection being read as survivorship bias."""
    out = bourse.screen(["BOOM"], start="2024-01-02", end="2024-12-31",
                        exchange="NSE",
                        download=_fake({"BOOM": ConnectionError("timeout")}))
    assert out.errors == ["BOOM"]
    assert out.empty == [] and out.short == []
    assert "retry" in out.summary()


def test_a_universe_with_no_drops_says_so_plainly():
    days = _days()
    out = bourse.screen(["A", "B"], start="2024-01-02", end="2024-12-31",
                        exchange="NSE",
                        download=_fake({"A": _series(days), "B": _series(days)}))
    assert not out.biased
    assert out.survivor_rate == 1.0
    assert "safe to build from" in out.summary()


def test_the_summary_quantifies_the_bias():
    days = _days()
    out = bourse.screen(
        ["A", "B", "C", "D"], start="2024-01-02", end="2024-12-31",
        exchange="NSE",
        download=_fake({"A": _series(days), "B": pd.DataFrame(),
                        "C": pd.DataFrame(), "D": _series(days)}))
    text = out.summary()
    assert "2/4" in text and "50%" in text
    assert "B C" in text


def test_screen_returns_a_frame_for_further_work():
    days = _days()
    out = bourse.screen(["A", "B"], start="2024-01-02", end="2024-12-31",
                        exchange="NSE",
                        download=_fake({"A": _series(days), "B": pd.DataFrame()}))
    df = out.to_frame()
    assert list(df["ticker"]) == ["A", "B"]
    assert set(df["status"]) == {"ok", "empty"}


def test_the_venue_is_inferred_from_the_tickers():
    """A list is normally one market, so naming it should not be mandatory."""
    days = _days()
    out = bourse.screen(["RELIANCE.NS", "TCS.NS"], start="2024-01-02",
                        end="2024-12-31",
                        download=_fake({"RELIANCE.NS": _series(days),
                                        "TCS.NS": _series(days)}))
    assert out.exchange == "NSE"


def test_parallel_and_serial_screens_agree_and_keep_input_order():
    """Concurrency must not reorder results or change any classification."""
    days = _days()
    mapping = {"A": _series(days), "B": pd.DataFrame(),
               "C": _series(days[-20:]), "D": _series(days),
               "E": ConnectionError("x"), "F": pd.DataFrame()}
    order = list(mapping)
    kw = {"start": "2024-01-02", "end": "2024-12-31", "exchange": "NSE",
          "download": _fake(mapping)}

    par = bourse.screen(order, workers=4, **kw)
    ser = bourse.screen(order, workers=1, **kw)

    assert [r.ticker for r in par.rows] == order
    assert [r.ticker for r in ser.rows] == order
    assert [r.status for r in par.rows] == [r.status for r in ser.rows]
    assert par.empty == ser.empty == ["B", "F"]
    assert par.short == ser.short == ["C"]
