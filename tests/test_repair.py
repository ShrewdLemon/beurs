"""Tests for `repair`: the frame you get back must be usable AND honest.

The invariants worth pinning are not "it changed something". They are:

  * a phantom is DROPPED but a stale session is NULLED, because the first is an
    absence and the second is a real session -- confusing them is the single
    most expensive mistake in this area;
  * nothing is ever forward-filled, so no repair invents a return;
  * every change appears in the log, so a caller can always reconstruct what
    was done to their data.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bourse

WEEKEND_SESSIONS = [date(2024, 1, 20), date(2024, 3, 2), date(2024, 5, 18)]


def _frame(dates, close=100.0, volume=1000, flat=()):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    df = pd.DataFrame({"Open": close, "High": close, "Low": close,
                       "Close": close, "Volume": volume}, index=idx)
    for d in flat:
        ts = pd.Timestamp(d)
        if ts in df.index:
            df.loc[ts, ["Open", "High", "Low", "Close", "Volume"]] = [close] * 4 + [0]
    return df


def test_a_clean_frame_is_returned_unchanged():
    days = bourse.sessions("2024-02-01", "2024-04-30")
    out = bourse.repair(_frame(days), "TEST", exchange="NSE")
    assert out.log.n_changed == 0
    assert "nothing to repair" in out.log.summary()
    assert len(out.frame) == len(days)
    assert out.frame["Close"].notna().all()


def test_phantom_rows_are_dropped_not_nulled():
    """A row on a day the venue was shut is an absence, not a 0% return."""
    days = bourse.sessions("2024-02-01", "2024-04-30")
    holiday = date(2024, 3, 8)                      # NSE closed, Mahashivratri
    assert holiday not in days
    df = _frame(sorted(days + [holiday]), flat=[holiday])

    out = bourse.repair(df, "TEST", exchange="NSE")
    assert out.log.dropped_phantoms == (holiday,)
    assert pd.Timestamp(holiday) not in out.frame.index


def test_stale_sessions_are_nulled_not_dropped():
    """The session was real. Deleting the row would silently shorten a window;
    filling it would invent a return. NaN is the only honest answer."""
    days = bourse.sessions("2024-02-01", "2024-04-30")
    stale = days[10]
    out = bourse.repair(_frame(days, flat=[stale]), "TEST", exchange="NSE")

    assert out.log.nulled_stale == (stale,)
    assert pd.Timestamp(stale) in out.frame.index          # row kept
    assert pd.isna(out.frame.loc[pd.Timestamp(stale), "Close"])


def test_missing_sessions_become_visible_holes():
    """Absent rows are invisible; NaN rows are not. That is the whole point."""
    days = [d for d in bourse.sessions("2024-01-02", "2024-06-28")
            if d not in WEEKEND_SESSIONS]
    out = bourse.repair(_frame(days), "TEST", exchange="NSE")

    assert set(out.log.inserted_missing) == set(WEEKEND_SESSIONS)
    for d in WEEKEND_SESSIONS:
        assert pd.Timestamp(d) in out.frame.index
        assert pd.isna(out.frame.loc[pd.Timestamp(d), "Close"])


def test_repair_never_forward_fills():
    """No repair may invent a price. Every hole stays a hole."""
    days = bourse.sessions("2024-02-01", "2024-04-30")
    out = bourse.repair(_frame(days, flat=[days[10], days[11]]), "TEST",
                        exchange="NSE")
    holes = out.frame["Close"].isna().sum()
    assert holes == 2
    assert out.usable_rows == len(out.frame) - holes


def test_a_fabricated_jump_is_rebuilt_from_raw_closes():
    """The exchange record is the only ground truth, so re-adjustment uses it --
    and the invented step is gone from the returned series."""
    days = bourse.sessions("2024-02-01", "2024-04-30")
    close = pd.Series(100.0, index=pd.DatetimeIndex([pd.Timestamp(d) for d in days]))
    # The adjusted series steps DOWN mid-window while the exchange price does
    # not move: implied factor raw/adj RISES going forward, which is the
    # signature of a split factor applied to part of the history only.
    close.iloc[20:] = 50.0
    df = _frame(days)
    df["Close"] = close
    raw = pd.Series(100.0, index=close.index)    # exchange never moved

    assert bourse.audit(df, "TEST", exchange="NSE",
                        exchange_close=raw)["fabricated_jumps"] is not None

    out = bourse.repair(df, "TEST", exchange="NSE", exchange_close=raw)
    assert out.log.readjusted, "the break should have been rebuilt, not nulled"
    assert not out.log.nulled_fabricated

    # The invented step is gone: the repaired series no longer moves where the
    # exchange did not.
    step = out.frame["Close"].pct_change().abs().max()
    assert step < 0.15, f"an invented {step:.0%} step survived the repair"


def test_a_break_outside_the_raw_closes_is_nulled_not_guessed():
    """Ground truth that does not cover the break is not ground truth. The dates
    become NaN and the log says so."""
    days = bourse.sessions("2024-02-01", "2024-04-30")
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    close = pd.Series(100.0, index=idx)
    close.iloc[20:] = 50.0
    df = _frame(days)
    df["Close"] = close
    raw = pd.Series(100.0, index=idx[18:])       # starts only just before

    out = bourse.repair(df, "TEST", exchange="NSE", exchange_close=raw)
    if out.log.nulled_fabricated:
        assert any("nulled rather than" in n for n in out.log.notes)
        for d in out.log.nulled_fabricated:
            assert pd.isna(out.frame.loc[pd.Timestamp(d), "Close"])


def test_the_report_before_repair_is_kept():
    """A caller must be able to see what was wrong, not just what changed."""
    days = bourse.sessions("2024-02-01", "2024-04-30")
    out = bourse.repair(_frame(days, flat=[days[10]]), "TEST", exchange="NSE")
    assert not out.report_before.clean
    assert out.report_before["stale_sessions"] is not None


def test_a_multiindex_frame_is_handled_and_the_flattening_is_logged():
    """yfinance returns (field, ticker) columns even for one ticker."""
    days = bourse.sessions("2024-02-01", "2024-04-30")
    df = _frame(days)
    df.columns = pd.MultiIndex.from_product([df.columns, ["TEST"]])
    out = bourse.repair(df, "TEST", exchange="NSE")
    assert "Close" in out.frame.columns
    assert any("MultiIndex" in n for n in out.log.notes)


def test_repair_many_skips_what_it_cannot_repair():
    days = bourse.sessions("2024-02-01", "2024-04-30")
    out = bourse.repair_many({"GOOD": _frame(days),
                              "BAD": pd.DataFrame({"px": [1, 2]})},
                             exchange="NSE")
    assert "GOOD" in out and "BAD" not in out
