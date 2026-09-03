# bourse

[![tests](https://github.com/ShrewdLemon/bourse/actions/workflows/ci.yml/badge.svg)](https://github.com/ShrewdLemon/bourse/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://github.com/ShrewdLemon/bourse)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![venues](https://img.shields.io/badge/venues-54-orange)](#54-venues-each-carrying-its-provenance)

**Market data that does not lie to you.**

Your price API does not raise an exception when it is wrong. It returns a frame,
and the frame looks fine. bourse finds the failures, fixes what can be fixed,
and tells you what cannot.

```bash
pip install git+https://github.com/ShrewdLemon/bourse
```

---

## Three things, on 54 exchanges

```python
import bourse

bourse.audit(df,  "TRENT.NS")     # what is wrong with this series
bourse.repair(df, "TRENT.NS")     # hand me back one I can use
bourse.screen(universe)           # which of these silently return nothing
```

The venue is read off the ticker suffix — `.NS` is India, `.HK` is Hong Kong, a
bare symbol is the US calendar — so you rarely have to say.

---

## 1. Your universe is smaller than you think

```python
>>> print(bourse.screen(["SIRI","LCID","PLUG","NKLA","AMC","GME","MULN","BBBYQ",
...                      "WE","CVNA","SNDL","FFIE","ATER","GNUS","RIDE"]).summary())
```
```
15 tickers [US] 2023-01-01..2026-06-30: ok=8 empty=7 short=0 error=0

  empty  -- returned NOTHING, no exception raised
           NKLA MULN BBBYQ WE FFIE GNUS RIDE

  7/15 names (47%) would vanish from a universe built by looping this list.
  Survivors outperform by construction. Any backtest over the remainder is
  biased upward.
```

**Seven of fifteen returned an empty frame and did not raise.** Every one went
bankrupt, was delisted, or was renamed. The obvious loop — iterate the universe,
download, concat — drops them on the floor, and nothing anywhere says so.

This is survivorship bias, and it is not a historical-database problem you can
read about and move on from. It happens live, today, to anyone assembling a
universe from a ticker list.

`short` is the nastier sibling: data comes back, just not enough of it. The frame
is non-empty, so every length check and every `try/except` passes.

---

## 2. A fifth of the Israeli trading year is missing

```console
$ bourse audit TEVA.TA -v
```
```
TEVA.TA [TASE]: missing_sessions=51 dropped_weekday=51 stale_sessions=3

  dropped_weekday [51]
    98% of the missing sessions fall on Sunday. This is not scattered data
    loss -- the source is serving a Monday-Friday week to a venue that does
    not keep one, and every Sunday session is gone. Nothing raises, and a
    holiday-count check cannot see it.
```

Tel Aviv trades **Sunday to Thursday**. So does Tadawul. A Mon–Fri assumption is
wrong in both directions there: it deletes every Sunday and invents every Friday.

Saudi Aramco shows the other half of the same problem — three rows on days the
exchange was shut, all inside Eid windows, where the moon-sighting date cannot be
published far in advance:

```
2222.SR [TADAWUL]: unexpected_sessions=3 phantom_rows=1 stale_sessions=9
```

---

## 3. Get the fixed series back, not just a complaint

A linter gets tried once. A formatter gets kept.

```python
>>> out = bourse.repair(df, "TEVA.TA")
>>> print(out.log.summary())
TEVA.TA [TASE]: nulled_stale=3 inserted_missing=51
>>> out.frame        # ready to use
>>> out.usable_rows
191
```

What it does, and what it refuses to do:

| finding | repair |
|---|---|
| `phantom_rows` | **dropped** — a flat row on a day the venue was shut is an absence, not a 0% return |
| `stale_sessions` | **nulled, never deleted or filled** — the session was real; deleting shortens your window, filling invents a return |
| `missing_sessions` | **reindexed onto the real calendar** — the gap becomes a visible NaN instead of an invisible absence |
| `fabricated_jumps` | **re-adjusted from raw exchange closes**, or nulled if they don't cover the break |

**Nothing is ever forward-filled, and nothing changes silently.** Every edit is in
`out.log`. A tool that quietly rewrites your prices is a worse problem than the
one it fixes.

Re-adjustment scales the post-break segment by a constant, which changes exactly
one return — the invented one — and leaves every other return in the series
bit-for-bit untouched.

---

## It does not cry wolf

Live, one call each, venue inferred from the ticker:

```
AAPL       US       clean (251 rows / 251 sessions)      BMW.DE   XETRA  clean
JPM        US       clean                                MC.PA    EPA    clean
7203.T     TSE      clean                                SHOP.TO  TSX    clean
005930.KS  KRX      clean                                NESN.SW  SIX    clean
BHP.AX     ASX      clean                                D05.SI   SGX    clean
SHEL.L     LSE      clean                                BBCA.JK  IDX    clean
000001.SZ  SZSE     clean

0700.HK    HKEX     stale_sessions=1
600519.SS  SSE      stale_sessions=1
2330.TW    TWSE     missing_sessions=1
NPN.JO     JSE      missing_sessions=1
RELIANCE.NS NSE     missing_sessions=3
TEVA.TA    TASE     missing_sessions=51 dropped_weekday=51 stale_sessions=3
2222.SR    TADAWUL  unexpected_sessions=3 phantom_rows=1 stale_sessions=9
```

**US and European large-cap data is genuinely clean.** If that is all you trade,
the value here is the *check* — run it in CI and forget it. Asia and the Gulf are
where it earns its keep.

And `RELIANCE.NS` shows **no** `fabricated_jumps` despite a 2:1 split in the
window, because that split *is* correctly adjusted. The check separates a real
corporate action from an invented price change; it does not just flag big moves.

---

## The five checks

| finding | what it means |
|---|---|
| `fabricated_jumps` | The adjusted series contains a price change that never happened. **TRENT reads −33.05%** where the exchange moved +0.43%: a split factor applied to part of the history. |
| `dropped_weekday` | The source is serving a Mon–Fri week to a venue that does not keep one. |
| `stale_sessions` | A real session where the API repeats the previous close. **2025-03-18 was a 3.32-billion-share NSE session**, rendered stale for 196 of 197 names, median error 1.78%. |
| `unexpected_sessions` | Full-volume rows on days the venue did not trade. |
| `phantom_rows` | Zero-volume flat rows on non-sessions. Each is a spurious 0% return. |

**Why phantoms matter more than they look.** They understate volatility, and
volatility is the denominator of your test statistic. On one measured name sigma
came out 0.0249 against a true 0.0462 — **46% too low**. That *inflates* every
t-statistic built on it, so the bias points toward finding significance that
isn't there.

---

## From the command line

```console
$ bourse screen universe.txt          # or: cat tickers | bourse screen -
$ bourse audit TRENT.NS -v
$ bourse audit RELIANCE.NS TCS.NS INFY.NS      # table, worst first
$ bourse repair TRENT.NS -o clean.csv
$ bourse venues                       # 54 exchanges and their provenance
$ bourse sessions 2024-01-01 2024-12-31 -e NYSE -n
252
```

Exit codes are the interface: **0 clean, 1 could not run, 2 findings.** Drops
straight into CI as a data-quality gate.

```yaml
- run: bourse screen universe.txt && bourse audit RELIANCE.NS TCS.NS
```

---

## 54 venues, each carrying its provenance

```console
$ bourse venues
NSE    National Stock Exchange of India  India       INR  .NS  verified
US     US equities (NYSE / Nasdaq)       United ...  USD  -    sourced
HKEX   Hong Kong Exchanges               Hong Kong   HKD  .HK  sourced
TADAWUL Saudi Exchange                   Saudi ...   SAR  .SR  sourced
...
54 venues: 1 verified, 53 sourced.
```

- **verified** — probed against the exchange's own published record, session by
  session, by this project.
- **sourced** — from [`exchange_calendars`](https://github.com/gerrymanoim/exchange_calendars),
  which is well maintained and correct for those venues. Not re-checked here.

**Exactly one venue is verified, and saying so is the point.** A package claiming
54 verified calendars would be claiming 54 audits it had not done.

### Why NSE had to be shipped

`exchange_calendars` has no `XNSE` at all, and its `XBOM` is wrong for Indian
equities. Over 2023-01-01 to 2026-06-30, where the truth is **864 sessions**:

| source | sessions | defect |
|---|---|---|
| **bourse** | **864** | probed from NSE's own archive |
| `exchange_calendars` XBOM | 858 | misses 6; never invents |
| `pandas_market_calendars` NSE | 859 | misses 8 **and invents 3** |
| yfinance `^NSEI` dates | 859 | misses 5 |

The misses are weekend sessions NSE genuinely traded: 2023-11-12 (Sunday,
Muhurat), 2024-01-20, 2024-03-02, 2024-05-18 (Saturdays), 2026-02-01 (Sunday,
Budget).

**The check most people run cannot see this.** Comparing weekday *holiday lists*
matches 15/15 for 2023 and 16/16 for 2024 against a calendar missing every
weekend session. Diff the full session set instead:

```python
idx = yf.download("^NSEI", start="2023-01-01", end="2026-07-01").index
bourse.audit_calendar(idx, exchange="NSE")["missing"]
# [date(2023,11,12), date(2024,1,20), date(2024,3,2), date(2024,5,18), date(2026,2,1)]
```

---

## Works with what you already use

bourse does not fetch your prices — it **checks them**.

| you use | bourse adds |
|---|---|
| [`yfinance`](https://github.com/ranaroussi/yfinance) | finds the fabricated jumps, dropped weekdays, stale sessions and phantom rows in its output |
| [`exchange_calendars`](https://github.com/gerrymanoim/exchange_calendars) | used directly for 53 venues; bourse fills the NSE gap it does not cover |
| [`jugaad-data`](https://github.com/jugaad-py/jugaad-data), [`nsepython`](https://github.com/aeron7/nsepython) | a verified NSE calendar to check their coverage against |
| any backtester | a pre-flight check, so you find out before the backtest rather than after |

Pass any OHLCV frame with a `DatetimeIndex`. There is no ingestion step, no
database, no config file.

---

## API

```python
import bourse

# Audit
bourse.audit(df, "0700.HK")                       # venue inferred
bourse.audit(df, "TRENT", exchange="NSE")         # or named
bourse.audit(df, "TRENT", exchange="NSE",
             exchange_close=raw_closes)           # enables fabricated_jumps
bourse.audit_many({"A": df1, "B": df2})           # worst-first DataFrame
report.explain()                                  # what each finding means

# Repair
out = bourse.repair(df, "TRENT.NS")
out.frame, out.log, out.usable_rows, out.report_before

# Screen a universe
s = bourse.screen(tickers)
s.ok, s.empty, s.short, s.errors, s.biased, s.survivor_rate, s.to_frame()

# Calendars
bourse.infer("600519.SS")                         # 'SSE'
bourse.sessions("2024-01-01", "2024-12-31", "NYSE")
bourse.is_session("2024-01-20", "NSE")            # True -- a Saturday NSE traded
bourse.offset("2026-01-23", 5, "NSE")             # date(2026, 2, 1)
bourse.audit_calendar(some_index, exchange="SSE")
bourse.status()

# India: the exchange's own end-of-day file
bourse.bhavcopy("2024-01-20")
bourse.security_master("2023-04-03")
```

`offset("2026-01-23", 5, "NSE")` returning a **Sunday** is not a bug: Republic
Day falls in the window and NSE traded that Sunday. Sessions, not calendar days.

`fabricated_jumps` needs raw exchange closes — it is the only way to tell an
invented −33% from a real one. The other four checks run without it.

---

## Where this came from

Every check exists because the failure it catches produced a *plausible wrong
number* in a real study: a pre-registered event study over 1,628 Indian earnings
calls.

That study found nothing — **0 of 24 pre-registered hypotheses survived.** Getting
to a *trustworthy* zero meant fixing every one of these first, because each
produces a plausible non-zero if you leave it in.

That is the argument for the package. A pipeline carrying these bugs does not
fail loudly. It hands you a result.

**[TRAPS.md](TRAPS.md)** documents 13 measured failure modes, worst-first —
including several this package does not yet automate.

---

## Scope, honestly

- NSE ships verified for **2022-01-03 to 2026-06-30**. Outside that, `sessions()`
  raises rather than guessing. Other venues inherit `exchange_calendars`' range.
- Venue inference is a convenience and it can be wrong: a bare Indian symbol
  looks exactly like a US one. No test reliably separates "bad data" from "right
  data, wrong calendar", so rather than pretend otherwise, any report built on a
  guessed venue says so in its own output.
- `screen` and the CLI's fetching need `pip install 'bourse[fetch]'`; the 53
  sourced calendars need `bourse[global]`.
- NSE and Yahoo both fingerprint TLS — plain `requests` gets 403/429 on the first
  call whatever User-Agent you send. That is not rate limiting and backoff will
  not fix it. Hence `curl_cffi`.
- The bhavcopy is the **raw, unadjusted** exchange record. `prev_close` is not
  ex-adjusted either: RELIANCE's 1:2 reads −49.76%. A feature for auditing, a
  trap if you difference it naively.

## Contributing

The most valuable contribution is **a measured trap**: what the source says vs
what the exchange says, with dates and numbers, plus a snippet that reproduces
it. See [CONTRIBUTING.md](CONTRIBUTING.md).

Adding a venue is one entry in `EXCHANGES` for a `sourced` calendar. Shipping a
`verified` one requires showing the diff against the sourced calendar it
replaces.

MIT. See [DISCLAIMER.md](DISCLAIMER.md) — educational software, not investment
advice, not affiliated with any exchange. Security policy: [SECURITY.md](SECURITY.md).
