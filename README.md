# bourse

**Market data that does not lie to you.**

Audit any price series against the exchange that produced it. Four failure modes
that never raise an exception, on any venue.

```bash
pip install bourse          # calendar + audit
pip install bourse[all]     # + global calendars and fetching
```

---

## 30 seconds

```python
import yfinance as yf, bourse

df = yf.download("TRENT.NS", start="2023-01-01", end="2026-07-01", auto_adjust=True)
print(bourse.audit(df, "TRENT", exchange="NSE").summary())
```

```
TRENT [NSE]: missing_sessions=5 phantom_rows=4 stale_sessions=1 fabricated_jumps=1
```

Four distinct things wrong with a series most people use as-is. None of them
throws.

| finding | what it means |
|---|---|
| `fabricated_jumps` | **−33.05% on 2026-01-01.** The exchange moved +0.43%. A split factor was applied to part of the history only. |
| `stale_sessions` | 2025-03-18 was a real 3.32-billion-share session. The series repeats the previous close. |
| `phantom_rows` | Zero-volume flat rows on days the market was shut. Each is a spurious 0% return. |
| `missing_sessions` | Real sessions absent — on NSE, the weekend specials no calendar package carries. |

---

## It does not cry wolf

Run the same audit across venues and it discriminates:

```
AAPL      [NASDAQ]  clean (502 rows / 502 sessions)
MSFT      [NASDAQ]  clean
JPM       [NYSE]    clean
600519.SS [SSE]     stale_sessions=1
0700.HK   [HKEX]    missing_sessions=2  stale_sessions=2
TRENT     [NSE]     missing_sessions=5  phantom_rows=4  stale_sessions=1  fabricated_jumps=1
RELIANCE  [NSE]     missing_sessions=5  phantom_rows=4  stale_sessions=1
```

**US large-cap data is genuinely clean.** If you work on US equities the value
here is the *check*, not a promise of finding bugs — run it in CI and forget it.
Asian venues are where it earns its keep.

And note `RELIANCE` has **no** `fabricated_jumps` despite a 2:1 split in the
window, because that split *is* correctly adjusted. The check separates a real
corporate action from an invented price change; it does not just flag large
moves.

---

## Calendars carry their provenance

```python
>>> print(bourse.status())
exchange  provenance  range
NSE       verified    2022-01-03 .. 2026-06-30
NYSE      sourced     2006-09-05 .. 2027-09-02
NASDAQ    sourced     2006-09-05 .. 2027-09-02
SSE       sourced     2006-09-04 .. 2026-12-31
HKEX      sourced     2006-09-04 .. 2027-09-02
LSE, TSE, BSE ...
```

- **verified** — probed against the exchange's own published record, session by
  session, by this project.
- **sourced** — from [`exchange_calendars`](https://github.com/gerrymanoim/exchange_calendars),
  which is well maintained and correct for those venues. Not re-checked here.

**Only NSE is shipped verified, and only because it had to be.**
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

For NYSE, Shanghai and Hong Kong, `exchange_calendars` is good and rebuilding it
would add risk rather than remove it — so this package doesn't.

### The check most people run cannot see the defect

Comparing **weekday holiday lists** matches 15/15 for 2023 and 16/16 for 2024
against a calendar missing every weekend session. Diff the full session set:

```python
idx = yf.download("^NSEI", start="2023-01-01", end="2026-07-01").index
bourse.audit_calendar(idx, exchange="NSE")["missing"]
# [date(2023,11,12), date(2024,1,20), date(2024,3,2), date(2024,5,18), date(2026,2,1)]
```

---

## API

```python
import bourse

# Audit — any venue
bourse.audit(df, "AAPL", exchange="NASDAQ")           # Report
bourse.audit(df, "TRENT", exchange="NSE",
             exchange_close=raw_closes)               # enables fabricated_jumps
bourse.audit_many({"A": df1, "B": df2}, exchange="NYSE")   # worst-first DataFrame
report.explain()                                      # what each finding means

# Calendars
bourse.sessions("2024-01-01", "2024-12-31", "NYSE")
bourse.is_session("2024-01-20", "NSE")                # True — a Saturday NSE traded
bourse.offset("2026-01-23", 5, "NSE")                 # date(2026, 2, 1)
bourse.count("2023-01-01", "2026-06-30", "NSE")       # 864
bourse.audit_calendar(some_index, exchange="SSE")
bourse.status()

# India: the exchange's own end-of-day file
bourse.bhavcopy("2024-01-20")                         # both archive layouts
bourse.security_master("2023-04-03")                  # symbol / series / ISIN
```

`offset("2026-01-23", 5, "NSE")` returning a **Sunday** is not a bug: Republic
Day falls in the window and NSE traded that Sunday. Sessions, not calendar days.

`fabricated_jumps` needs raw exchange closes to compare against — it is the only
way to tell an invented −33% from a real one. The other three checks run without
it.

---

## Where this came from

Every check exists because the failure it catches produced a *plausible wrong
number* in a real study — a pre-registered event study over 1,628 Indian
earnings calls ([alpha](https://github.com/ShrewdLemon/alpha)).

That study found nothing: **0 of 24 pre-registered hypotheses survived.** Getting
to a *trustworthy* zero meant fixing every one of these first, because each
produces a plausible non-zero if you leave it in.

That is the argument for the package. A pipeline carrying these bugs does not
fail loudly. It hands you a result.

**[TRAPS.md](TRAPS.md)** documents 13 measured failure modes, worst-first —
including several this package does not yet automate: BSE returning HTTP 200
with a 2-byte body instead of an error, an attachment path that 404s HTML into
your corpus, and ISIN reissues that make 12 live companies look delisted.

---

## Scope, honestly

- NSE ships verified for **2022-01-03 to 2026-06-30**. Outside that, `sessions()`
  raises rather than guessing. Other venues inherit `exchange_calendars`' range.
- Global calendars need `bourse[global]`; fetching needs `bourse[fetch]`.
- NSE and Yahoo both fingerprint TLS — plain `requests` gets 403/429 on the
  first call whatever User-Agent you send. That is not rate limiting and backoff
  will not fix it. Hence `curl_cffi`.
- The bhavcopy is the **raw, unadjusted** exchange record. `prev_close` is not
  ex-adjusted either: RELIANCE's 1:2 reads −49.76%. That is a feature for
  auditing and a trap if you difference it naively.

MIT. Issues and PRs welcome — especially measured traps on other venues.
