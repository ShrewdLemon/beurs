"""Tests for the global venue table and ticker inference.

Inference is a convenience that can be WRONG -- a bare Indian symbol looks
exactly like a US one -- so the guard against a silently mismatched calendar is
tested here alongside the happy path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import beurs
from beurs.calendars import UnknownExchange


def test_every_major_market_has_a_venue():
    codes = set(beurs.EXCHANGES)
    for c in ("US", "NYSE", "NASDAQ", "NSE", "BSE", "SSE", "SZSE", "HKEX",
              "TSE", "KRX", "TWSE", "LSE", "XETRA", "EPA", "ASX", "TSX",
              "B3", "JSE", "TADAWUL", "SGX"):
        assert c in codes, c
    assert len(codes) >= 50


def test_suffix_inference_covers_the_common_ones():
    cases = {"RELIANCE.NS": "NSE", "TCS.BO": "BSE", "0700.HK": "HKEX",
             "600519.SS": "SSE", "000001.SZ": "SZSE", "7203.T": "TSE",
             "005930.KS": "KRX", "2330.TW": "TWSE", "BHP.AX": "ASX",
             "SHEL.L": "LSE", "BMW.DE": "XETRA", "MC.PA": "EPA",
             "VALE.SA": "B3", "SHOP.TO": "TSX", "NESN.SW": "SIX",
             "2222.SR": "TADAWUL", "AAPL": "US", "BRK-B": "US"}
    for ticker, want in cases.items():
        assert beurs.infer(ticker) == want, ticker


def test_a_longer_suffix_wins_over_a_shorter_one():
    """.TWO must not be matched as .TW."""
    assert beurs.infer("6488.TWO") == "TWSE"
    assert beurs.infer("2330.TW") == "TWSE"


def test_an_unrecognised_suffix_returns_none_rather_than_guessing():
    assert beurs.infer("FOO.ZZZ") is None
    with pytest.raises(UnknownExchange):
        beurs.audit(pd.DataFrame(), "FOO.ZZZ")


def test_us_venues_share_one_session_calendar():
    """NYSE and Nasdaq observe identical holidays, which is why a bare ticker
    can resolve to either without losing information."""
    a = beurs.sessions("2024-01-01", "2024-12-31", exchange="NYSE")
    b = beurs.sessions("2024-01-01", "2024-12-31", exchange="NASDAQ")
    c = beurs.sessions("2024-01-01", "2024-12-31", exchange="US")
    assert a == b == c
    assert len(a) == 252


def test_shenzhen_shares_the_mainland_calendar():
    a = beurs.sessions("2024-01-01", "2024-12-31", exchange="SSE")
    b = beurs.sessions("2024-01-01", "2024-12-31", exchange="SZSE")
    assert a == b


def test_sunday_trading_venues_are_not_forced_into_a_western_week():
    """Tadawul and TASE trade Sunday-Thursday. A Mon-Fri assumption is wrong in
    both directions here -- it invents Fridays and drops Sundays."""
    for code in ("TADAWUL", "TASE"):
        days = beurs.sessions("2024-01-01", "2024-03-31", exchange=code)
        assert any(d.weekday() == 6 for d in days), f"{code} should trade Sundays"
        assert not any(d.weekday() == 4 for d in days), f"{code} should not trade Fridays"


def test_the_inferred_venue_is_recorded_on_the_report():
    days = beurs.sessions("2024-02-01", "2024-04-30", exchange="US")
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0,
                       "Volume": 1}, index=idx)
    rep = beurs.audit(df, "AAPL")
    assert rep.exchange == "US" and rep.inferred and rep.clean


def test_findings_on_a_guessed_venue_carry_the_guess_with_them():
    """A bare Indian symbol looks exactly like a US one, and no test reliably
    separates "bad data" from "right data, wrong calendar". So rather than
    accuse, a report built on a GUESSED venue carries the guess in its own
    output, where the reader will see it next to the findings."""
    days = beurs.sessions("2024-02-01", "2024-04-30", exchange="NSE")
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0,
                       "Volume": 1}, index=idx)

    rep = beurs.audit(df, "TRENT")            # inferred as US -- wrong
    assert rep.wrong_venue_suspected
    assert "venue inferred as US" in rep.summary()

    named = beurs.audit(df, "TRENT", exchange="NSE")
    assert not named.wrong_venue_suspected and named.clean


def test_a_named_venue_is_never_second_guessed():
    """The warning is for guesses. If the caller named the venue, that is their
    call and the tool does not argue with it."""
    days = beurs.sessions("2024-02-01", "2024-04-30", exchange="NSE")
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0,
                       "Volume": 1}, index=idx)
    rep = beurs.audit(df, "TRENT", exchange="US")
    assert not rep.inferred and not rep.wrong_venue_suspected


def test_status_is_fast_and_lists_every_venue():
    text = beurs.status()
    assert "verified" in text and "sourced" in text
    for c in ("NSE", "HKEX", "B3", "TADAWUL"):
        assert c in text
    assert str(len(beurs.EXCHANGES)) in text


def test_a_source_serving_a_monday_friday_week_to_a_sunday_market_is_caught():
    """The TEVA.TA case. Tel Aviv trades Sunday-Thursday; the source serves a
    Mon-Fri week, so every Sunday session is silently gone -- a fifth of the
    trading year. No holiday-count check can see this."""
    days = beurs.sessions("2024-01-01", "2024-12-31", exchange="TASE")
    kept = [d for d in days if d.weekday() != 6]        # drop every Sunday
    assert len(days) - len(kept) > 40

    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in kept])
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0,
                       "Volume": 1}, index=idx)

    rep = beurs.audit(df, "TEVA.TA", exchange="TASE")
    dropped = rep["dropped_weekday"]
    assert dropped is not None
    assert "Sunday" in dropped.detail
    assert all(d.weekday() == 6 for d in dropped.dates)


def test_ordinary_scattered_holidays_do_not_trip_the_weekday_check():
    """Real data loss is scattered. The check must not fire on it."""
    days = beurs.sessions("2024-01-01", "2024-12-31", exchange="US")
    kept = [d for i, d in enumerate(days) if i % 17]    # sparse, all weekdays
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in kept])
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0,
                       "Volume": 1}, index=idx)

    rep = beurs.audit(df, "TEST", exchange="US")
    assert rep["missing_sessions"] is not None
    assert rep["dropped_weekday"] is None


def test_a_handful_of_misses_is_never_a_dropped_weekday():
    """Three misses that happen to share a weekday is a coincidence, not a
    pattern, so the check has a floor."""
    days = beurs.sessions("2024-01-01", "2024-12-31", exchange="US")
    mondays = [d for d in days if d.weekday() == 0][:3]
    kept = [d for d in days if d not in mondays]
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in kept])
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0,
                       "Volume": 1}, index=idx)
    assert beurs.audit(df, "TEST", exchange="US")["dropped_weekday"] is None
