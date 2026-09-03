"""Tests for the CLI. No network: only the commands that do not fetch.

The exit codes are the contract that matters -- this tool is meant to sit in a
CI job, where 0 vs 2 is the whole interface.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bourse.cli import CLEAN, FAILED, _read_tickers, main


def test_venues_lists_every_exchange(capsys):
    assert main(["venues"]) == CLEAN
    out = capsys.readouterr().out
    for code in ("NSE", "US", "HKEX", "B3", "TADAWUL", "JSE"):
        assert code in out
    assert "verified" in out and "sourced" in out


def test_status_is_an_alias_for_venues(capsys):
    assert main(["status"]) == CLEAN
    assert "verified" in capsys.readouterr().out


def test_sessions_counts(capsys):
    assert main(["sessions", "2023-01-01", "2026-06-30", "-n"]) == CLEAN
    assert capsys.readouterr().out.strip() == "864"


def test_sessions_on_another_venue(capsys):
    assert main(["sessions", "2024-01-01", "2024-12-31", "-e", "NYSE", "-n"]) == CLEAN
    assert capsys.readouterr().out.strip() == "252"


def test_an_unknown_venue_fails_cleanly_rather_than_raising(capsys):
    assert main(["sessions", "2024-01-01", "2024-12-31", "-e", "ATLANTIS"]) == FAILED
    assert "unknown exchange" in capsys.readouterr().err


def test_a_date_outside_the_verified_range_fails_cleanly(capsys):
    assert main(["sessions", "2001-01-01", "2001-12-31", "-e", "NSE"]) == FAILED
    assert "outside" in capsys.readouterr().err


def test_tickers_can_come_from_a_file(tmp_path):
    f = tmp_path / "universe.txt"
    f.write_text("AAPL\nMSFT  # a comment\n\nJPM\n")
    assert _read_tickers([str(f)]) == ["AAPL", "MSFT", "JPM"]


def test_tickers_can_be_mixed_inline_and_from_a_file(tmp_path):
    f = tmp_path / "u.txt"
    f.write_text("AAPL\n")
    assert _read_tickers([str(f), "TSLA"]) == ["AAPL", "TSLA"]


def test_a_ticker_that_is_not_a_path_is_kept_as_a_ticker():
    assert _read_tickers(["RELIANCE.NS", "0700.HK"]) == ["RELIANCE.NS", "0700.HK"]


def test_screen_with_no_tickers_fails_rather_than_reporting_clean(capsys, tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("\n\n")
    assert main(["screen", str(f)]) == FAILED


@pytest.mark.parametrize("argv", [["audit"], ["repair"], []])
def test_missing_arguments_exit_nonzero(argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code != 0
