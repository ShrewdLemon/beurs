"""Tests for bourse. No network.

The calendar assertions are the load-bearing ones: they pin the exact sessions
every other package gets wrong, so a regression in the shipped data is a red
test rather than a quietly different answer.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bourse
from bourse.calendars import OutOfRange, UnknownExchange

# NSE traded on these, and no installable calendar package has them all.
WEEKEND_SESSIONS = [date(2023, 11, 12), date(2024, 1, 20), date(2024, 3, 2),
                    date(2024, 5, 18), date(2025, 2, 1), date(2026, 2, 1)]


# ------------------------------------------------------------------ calendar

def test_session_count_matches_the_exchange():
    assert bourse.count("2023-01-01", "2026-06-30") == 864


def test_the_weekend_sessions_everyone_else_misses_are_present():
    for d in WEEKEND_SESSIONS:
        assert bourse.is_session(d), d
        assert d.weekday() >= 5, f"{d} should be a weekend"


def test_known_holidays_are_not_sessions():
    for d in ("2024-01-26", "2024-08-15", "2023-10-02", "2025-12-25"):
        assert not bourse.is_session(d)


def test_offset_counts_sessions_not_calendar_days():
    """From Friday 23 Jan 2026: Republic Day is Monday, and NSE traded Sunday
    1 February. Five sessions later is 2026-02-01."""
    assert bourse.offset("2026-01-23", 5) == date(2026, 2, 1)
    assert bourse.offset("2026-02-01", -5) == date(2026, 1, 23)


def test_next_and_previous_skip_holidays():
    assert bourse.next_session("2024-01-26") == date(2024, 1, 29)
    assert bourse.previous_session("2024-01-26") == date(2024, 1, 25)
    assert bourse.next_session("2024-01-25", strictly=False) == date(2024, 1, 25)


def test_dates_outside_the_verified_range_raise_rather_than_guess():
    """Returning a plausible answer for an unverified date is how a wrong
    calendar spreads -- the caller cannot tell what was checked."""
    with pytest.raises(OutOfRange):
        bourse.is_session("2019-06-03")
    with pytest.raises(OutOfRange):
        bourse.sessions("2019-01-01", "2019-12-31")


def test_offset_off_the_end_raises():
    last = bourse.coverage()[1]
    with pytest.raises(OutOfRange):
        bourse.offset(last, 5)


def test_offset_from_a_non_session_raises():
    with pytest.raises(OutOfRange):
        bourse.offset("2024-01-26", 1)


def test_calendar_audit_finds_missing_and_invented():
    truth = bourse.sessions("2024-01-01", "2024-06-30")
    short = [d for d in truth if d not in WEEKEND_SESSIONS]
    rep = bourse.audit_calendar(short, exchange="NSE")
    assert set(rep["missing"]) == {d for d in WEEKEND_SESSIONS
                                   if date(2024, 1, 1) <= d <= date(2024, 6, 30)}
    assert rep["invented"] == [] and not rep["agrees"]
    assert bourse.audit_calendar(truth, exchange="NSE")["agrees"]


def test_holiday_comparison_cannot_see_the_defect():
    """The reason audit_calendar exists. A calendar missing every weekend
    session still produces an identical weekday-holiday list."""
    truth = bourse.sessions("2024-01-01", "2024-12-31")
    broken = [d for d in truth if d not in WEEKEND_SESSIONS]
    have_t, have_b = set(truth), set(broken)
    weekday_holidays = lambda have: {  # noqa: E731
        d for d in pd.date_range("2024-01-01", "2024-12-31")
        if d.weekday() < 5 and d.date() not in have}
    assert weekday_holidays(have_t) == weekday_holidays(have_b)   # identical!
    assert bourse.audit_calendar(broken, exchange="NSE")["missing"]               # but caught


# --------------------------------------------------------------------- audit

def _frame(dates, close=100.0, volume=1000, flat=()):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    df = pd.DataFrame({"Open": close, "High": close, "Low": close,
                       "Close": close, "Volume": volume}, index=idx)
    for d in flat:
        ts = pd.Timestamp(d)
        if ts in df.index:
            df.loc[ts, ["Open", "High", "Low", "Close", "Volume"]] = [close] * 4 + [0]
    return df


def test_a_clean_series_is_clean():
    days = bourse.sessions("2024-02-01", "2024-04-30")
    rep = bourse.audit(_frame(days), "TEST")
    assert rep.clean and rep.n_rows == len(days)


def test_missing_weekend_sessions_are_reported():
    days = [d for d in bourse.sessions("2024-01-02", "2024-06-28")
            if d not in WEEKEND_SESSIONS]
    rep = bourse.audit(_frame(days), "TEST")
    assert len(rep["missing_sessions"]) == 3      # 20 Jan, 2 Mar, 18 May


def test_phantom_rows_on_non_sessions_are_reported():
    days = bourse.sessions("2024-02-01", "2024-04-30")
    with_holiday = days + [date(2024, 3, 8)]      # a non-session
    rep = bourse.audit(_frame(with_holiday, flat=[date(2024, 3, 8)]), "TEST")
    f = rep["phantom_rows"]
    assert f and date(2024, 3, 8) in f.dates


def test_a_flat_row_on_a_REAL_session_is_stale_not_phantom():
    """The distinction that matters. Deleting a stale row throws away a real
    market-wide move; keeping a phantom invents a 0% return."""
    days = bourse.sessions("2024-02-01", "2024-04-30")
    rep = bourse.audit(_frame(days, flat=[days[10]]), "TEST")
    assert rep["stale_sessions"] and days[10] in rep["stale_sessions"].dates
    assert rep["phantom_rows"] is None


def test_a_fabricated_jump_is_caught_and_a_real_split_is_not():
    """A rising adjustment factor is not by itself impossible -- a share
    consolidation makes one legitimately. The exchange price is what separates
    them, so the check is two-sided."""
    days = bourse.sessions("2024-02-01", "2024-04-30")
    n = len(days)
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    k = 20

    # Fabricated: the adjusted series jumps, the exchange did not move.
    adj = pd.Series([100.0] * k + [50.0] * (n - k), index=idx)
    raw_flat = pd.Series([100.0] * n, index=idx)
    df = pd.DataFrame({"Open": adj, "High": adj, "Low": adj, "Close": adj,
                       "Volume": 1000}, index=idx)
    assert bourse.audit(df, "FAKE", exchange_close=raw_flat)["fabricated_jumps"]

    # Real: the exchange printed the same move, so the factor rise is explained.
    raw_moved = pd.Series([100.0] * k + [50.0] * (n - k), index=idx)
    adj_ok = pd.Series([50.0] * n, index=idx)
    df2 = pd.DataFrame({"Open": adj_ok, "High": adj_ok, "Low": adj_ok,
                        "Close": adj_ok, "Volume": 1000}, index=idx)
    assert bourse.audit(df2, "REAL", exchange_close=raw_moved)["fabricated_jumps"] is None


def test_multiindex_columns_are_handled():
    """yfinance returns a (field, ticker) MultiIndex even for one ticker, which
    is a common source of silent breakage in callers' code."""
    days = bourse.sessions("2024-02-01", "2024-03-28")
    df = _frame(days)
    df.columns = pd.MultiIndex.from_product([df.columns, ["TEST.NS"]])
    assert bourse.audit(df, "TEST").n_rows == len(days)


def test_audit_many_returns_a_row_per_symbol():
    days = bourse.sessions("2024-02-01", "2024-03-28")
    out = bourse.audit_many({"A": _frame(days), "B": _frame(days)})
    assert len(out) == 2 and set(out["symbol"]) == {"A", "B"}
    assert out["clean"].all()


def test_a_frame_with_no_close_column_names_the_problem():
    with pytest.raises(KeyError, match="no Close column"):
        bourse.audit(pd.DataFrame({"px": [1, 2]}), "TEST")


# ------------------------------------------------------------------- global

def test_other_venues_resolve_and_disagree_with_nse():
    """The package is not India-only. These come from exchange_calendars and are
    labelled `sourced` rather than `verified` -- the provenance is the point."""
    pytest.importorskip("exchange_calendars")
    assert bourse.count("2024-01-01", "2024-12-31", "NYSE") == 252
    assert bourse.count("2024-01-01", "2024-12-31", "SSE") == 242
    assert bourse.count("2024-01-01", "2024-12-31", "NSE") != 252


def test_provenance_is_stated_not_implied():
    by = {e.code: e for e in bourse.exchanges()}
    assert by["NSE"].provenance == "verified"
    assert by["NYSE"].provenance == "sourced"
    assert "verified" in bourse.status() and "sourced" in bourse.status()


def test_an_unknown_exchange_is_named_not_defaulted():
    with pytest.raises(UnknownExchange, match="unknown exchange"):
        bourse.sessions("2024-01-01", "2024-12-31", "MOON")


def test_audit_works_on_a_us_venue():
    pytest.importorskip("exchange_calendars")
    days = bourse.sessions("2024-02-01", "2024-04-30", "NYSE")
    rep = bourse.audit(_frame(days), "TEST", exchange="NYSE")
    assert rep.clean and rep.exchange == "NYSE"


def test_the_same_frame_is_wrong_on_the_wrong_calendar():
    """An NSE series audited against NYSE reports differences, which is why the
    exchange is a required part of the question rather than a default."""
    pytest.importorskip("exchange_calendars")
    days = bourse.sessions("2024-02-01", "2024-04-30", "NSE")
    assert not bourse.audit(_frame(days), "TEST", exchange="NYSE").clean


def test_explain_names_every_finding():
    days = [d for d in bourse.sessions("2024-01-02", "2024-06-28")
            if d not in WEEKEND_SESSIONS]
    text = bourse.audit(_frame(days), "TEST").explain()
    assert "missing_sessions" in text and "weekend" in text.lower()
