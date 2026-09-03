# 13 measured traps in Indian market data

All thirteen were hit, measured and fixed while building a real study. Four of
them are automated by [`beurs.audit`](README.md); the rest are documented here
because they are just as costly and not yet checkable in code.

Every one of these was hit, measured, and fixed while building a pre-registered
event study over 1,628 Indian earnings calls. Every one **fails silently** — no
exception, no warning, just a number that is wrong in a way you cannot see
downstream.

They are listed worst-first: the ones that produce confidently wrong numbers
come before the ones that merely lose data.

If you are doing quantitative research on Indian equities, you will hit most of
these. Each entry says what it looks like, what it costs, and how to check.

---

## 1. yfinance fabricates a −33% day

**What happens.** For some names the split factor is applied to only *part* of
the history, and the boundary is a one-day crash that never happened.

| name | date | yfinance says | NSE says |
|---|---|---|---|
| `TRENT.NS` | 2026-01-01 | **−33.05%** | +0.43% |
| `CONCOR.NS` | 2025-01-01 | **−20.88%** | −1.10% |

Both fall on 1 January of the split year. The factor is applied from that date
backwards and no further. Reproducible across fresh processes and different
download ranges, so it is not a cache artifact. That is **2 of the 10 in-window
split events**.

**What it costs.** A fabricated −33% sitting inside an estimation window
destroys the beta fitted on it and every abnormal return measured against it.
It will not look like a data error; it will look like a stock with strange risk.

**How to check.** For each name, compute `implied_factor = NSE_raw_close /
yf_adjusted_close` at several anchor dates. A consistent back-adjustment is
**non-increasing** through time and steps only on declared action dates. Any
name whose implied factor *rises* going forward has a fabricated jump.

**Careful:** a rising factor is not by itself impossible — a share consolidation
(reverse split) produces one legitimately. Corroborate every rise against the
exchange's own close before condemning it.

---

## 2. A real 3.3-billion-share session, rendered stale for 196 of 197 names

**What happens.** 2025-03-18 was a full NSE trading session — 3,043 bhavcopy
rows, 3.32 billion shares, RELIANCE traded 15.7 million shares. yfinance returns
a **carried-forward flat row** (Volume 0, Open = High = Low = Close) for 196 of
197 NIFTY 200 names.

Measured against the true close: mean absolute error **2.02%**, median 1.78%,
max 7.62% (PAYTM). 151 of 197 names off by more than 1%.

**What it costs.** It looks exactly like a holiday, so the usual "drop flat
zero-volume rows" filter *deletes a real market-wide move*. Reindexing onto the
index date set is worse — it keeps the fabricated 0% return for all 197.

**How to check.** Compare your session set against NSE's own dated archive, not
against another price series.

---

## 3. Non-trading days are forward-filled, and it inflates every t-statistic

**What happens.** yfinance returns a row for every weekday whether or not the
stock traded. Ground truth from 123 consecutive bhavcopies:

| name | real sessions | yfinance rows | fabricated |
|---|---|---|---|
| `UNIVAFOODS` | 40 | 123 | **83** |
| `MASKINVEST` | 84 | 123 | 39 |
| `ABMINTLLTD` | 106 | 123 | 17 |

**What it costs.** For UNIVAFOODS that is 92 zero-return days instead of 6.
Daily log-return sigma comes out **0.0249 against a true 0.0462** — volatility
understated by 46%. Volatility is the denominator of your test statistic, so
this **inflates every t-stat** computed on it. The bias points toward finding
significance that is not there.

It also reports the **wrong close on genuinely traded days**: on 2023-05-22 NSE
recorded a UNIVAFOODS trade at 6.25 while yfinance shows a flat 6.35.

**Fix.** Filter on `Volume == 0 AND O == H == L == C` and treat those dates as
*missing*, not as 0% returns. Below large-cap, reconcile every stock-day against
the bhavcopy — it is the only source that distinguishes "did not trade" from
"traded flat".

---

## 4. Every trading calendar you can install is wrong

For 2023-01-01 to 2026-06-30, ground truth is **864 sessions** (probed from
NSE's own dated index archive, cross-checked against bhavcopy row counts):

| source | sessions | defect |
|---|---|---|
| **NSE archive** | **864** | ground truth |
| `^NSEI` dates | 859 | misses 5 real sessions |
| `exchange_calendars` XBOM | 858 | misses 6; never invents |
| `pandas_market_calendars` NSE | 859 | misses 8 **and invents 3** — 11 wrong |

The five `^NSEI` misses are **weekend special sessions**: 2023-11-12 (Sun,
Muhurat), 2024-01-20, 2024-03-02, 2024-05-18 (Saturdays), 2026-02-01 (Sun,
Budget). An event landing on one has no price at all.

**The trap inside the trap.** Validating a calendar by comparing *weekday holiday
lists* matches 15/15 for 2023 and 16/16 for 2024 and **proves nothing** — every
known defect is a Saturday or Sunday. Diff the full session set, weekends
included.

There is also no `XNSE` in `exchange_calendars`; only `XBOM`.

---

## 5. Splits reissue the ISIN, so 12 live companies look delisted

**What happens.** Identity moves two independent ways:

- **Symbol changes, ISIN constant** (6 names): `ZOMATO→ETERNAL`,
  `TATAMOTORS→TMPV`, `LTIM→LTM`, `ADANITRANS→ADANIENSOL`,
  `MCDOWELL-N→UNITDSPR`, `L&TFH→LTF`
- **ISIN changes, symbol constant** (12 names): a split or bonus reissues the
  ISIN — `BAJFINANCE`, `KOTAKBANK`, `NESTLEIND`, `DRREDDY`, `HAL`, `CANBK`,
  `COFORGE`, `NAUKRI`, `PERSISTENT`, `SHRIRAMFIN`, `ADANIPOWER`, `VBL`

**What it costs.** Following the ISIN alone marks **all 12 as DELISTED**,
because the old ISIN's last print is indistinguishable from a terminal event.
Confirmed by mutation: disabling the symbol→ISIN direction turns 12 live, liquid
names into delistings.

`VBL` is the compound case: it reissued **twice**, and the ISIN written in a
2023 constituent snapshot is the *middle* one, which was not live on the date
the snapshot describes.

**Fix.** Walk the `(symbol, ISIN)` chain in **both** directions, alternating,
until it closes. Bound the walk — exchanges recycle tickers.

---

## 6. Resolving identity through today's index file loses exactly the names you need

Today's constituent CSV contains only names *still in the index*. A company that
was **renamed AND dropped** — which is precisely the survivorship population —
comes back unresolved.

Use the **bhavcopy security master** (~2,700 EQ/BE rows, carries ISIN). It
resolves every rename above, and correctly reports only genuinely delisted names
as gone.

**Related:** `GUJGASLTD` is alive, liquid, and trading under an unchanged
symbol — and yfinance returns **26 rows total**. A live listed name can silently
return nothing, with no corporate-action signal to flag it. Assert row counts
against your session calendar for every name.

---

## 7. BSE's `AttachLive` is a staging path that 404s into your corpus

**What happens.** The attachment URL every example uses,
`bseindia.com/xml-data/corpfiling/AttachLive/<name>`, is short-lived. It 404s on
anything more than a few weeks old — 4 of 5 files tested, including two earnings
transcripts — and the 404 arrives as **an 8,406-byte `text/html` error page**.

`AttachHis` served 100% of the same files.

But `AttachHis` fails too, differently: it returned a **13,272-byte Angular app
shell with HTTP 200** for a recent HDFCBANK transcript that `AttachLive` served
correctly. There is no clean age rule — a five-month-old filing came off
`AttachHis` fine while a four-month-old one did not.

**What it costs.** A loader that writes response bytes without checking fills
your corpus with HTML stubs named `.pdf`. They look like successful downloads.

**Fix.** Try both bases, and validate **every** download against `%PDF` magic
**and** the row's `Fld_Attachsize`, which matches served Content-Length exactly.

---

## 8. BSE returns HTTP 200 with a 2-byte body instead of an error

**What happens.** A market-wide announcements query (`strScrip=""`) over a
**multi-day** range returns HTTP 200 with a body of `{}` — no `Table`, no
`Table1`. Not an error, not an empty result. Reproducible for 2-day, 7-day and
31-day windows.

Single-day market-wide works. Single-scrip works over arbitrarily wide ranges
(a 20-year query returned ROWCNT 4,054 in one call).

**Fix.** Treat a **missing `Table1` key as a retryable failure**, never as zero
announcements. And assert `len(set(NEWSIDs)) == ROWCNT` before accepting a
window.

---

## 9. Paginating a live window silently drops rows

**What happens.** Offset pagination over a DESC-sorted feed that is still
receiving inserts loses rows at the page seam. Measured on a same-day query:
`ROWCNT` moved **260 → 267 in 210 seconds**, and 7 NEWSIDs that were on page 1
had been pushed off it.

**Fix.** Never paginate a window whose end is *today*. Backfill strictly-before-
today, or sweep repeatedly until two consecutive passes give the same NEWSID set
*and* the same ROWCNT.

---

## 10. `CATEGORYNAME` has three spellings of the same thing

`"Corp. Action"`, `" Corp Action"` (leading space), and `"Corp Action"`.
`str.strip()` alone still leaves two buckets.

`AGENDA_ID` and `SUBCATNAME` are **nullable**. `PDFFLAG` is **mutable** — it
flips as a filing ages, which also proves feed rows are *not* immutable after
publication. Do not key on it.

**Fix.** Normalise punctuation- and case-insensitively. Guard every int/string
op on the nullable fields. Record an ingest timestamp per row.

---

## 11. NSE's bhavcopy path changes mid-2024

Two archive layouts, and you need both:

```
# pre-mid-2024
nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MON}/cm{DDMONYYYY}bhav.csv.zip
# 2024 onward
nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip
```

The legacy path 404s from mid-2024; the new path 404s for 2023. Column names
differ too (`TckrSymb`/`SctySrs`/`ClsPric` vs `SYMBOL`/`SERIES`/`CLOSE`).

**Also:** filter `SERIES in ('EQ','BE')`, not just `'EQ'`. `PATANJALI` traded in
BE and is invisible to an EQ-only filter.

---

## 12. The 429 is TLS fingerprinting, not rate limiting

Yahoo returns 429 on the **very first request**, every time, to plain `curl` and
to `python-requests` — including with a browser User-Agent. `curl_cffi` with
Chrome impersonation gets 200 every time. 198 sequential downloads, zero 429s.

NSE fingerprints too: `python-requests` is frequently rejected with 403 where
`curl` succeeds.

**Fix.** Use `curl_cffi` with impersonation (yfinance ≥1.6 already does). Do not
add backoff for a problem that is not rate limiting.

NSE's index archive *does* rate-limit for real: a 12-worker sweep gets ~360 files
then 403s every subsequent date, **including ones it served minutes earlier**.
Throttle and retry.

---

## 13. Most "transcripts" are not transcripts

Of 2,304 PDFs fetched from filings whose metadata says *earnings call
transcript*, only **75.1% are transcripts**. The rest are one-page covering
letters pointing at an audio file (564) and scans with no text layer (9).

Metadata cannot tell them apart, and filing style varies by issuer:

- Some file under `SUBCATNAME="Earnings Call Transcript"` (`AGENDA_ID=157`)
- HDFCBANK and SBIN use `AGENDA_ID=80` "Analyst / Investor Meet"
- ICICIBANK used `AGENDA_ID=1` "General"
- KOTAKBANK's carry `HEADLINE="Intimation attached"` — text-invisible
- At least one issuer filed an **audio recording** under the transcript
  subcategory

**What it costs.** Taking candidates at face value inflated the event count from
1,619 to 2,147 — a third of the sample would have been documents returning all
nulls while still occupying a row in every regression.

**Coverage is also ragged *within* filers.** One large-cap bank filed results in
four consecutive quarters and a transcript in only three. Do not assume a
balanced panel.

**Fix.** Treat metadata as a high-recall **candidate generator** and confirm from
the PDF text — operator turns, Q&A structure, participant list, length. And
distinguish "we could not read it" (no text layer) from "it is not a transcript";
only the second is a fact about the issuer.

---

## Verifying any of this

Every claim above is checked by code in this repository:

| trap | automated by |
|---|---|
| 1 fabricated jumps | `beurs.audit(..., exchange_close=...)` |
| 2 stale sessions | `beurs.audit` |
| 3 phantom rows | `beurs.audit` |
| 4 wrong calendars | `beurs.sessions`, `beurs.audit_calendar` |
| 11 bhavcopy paths | `beurs.bhavcopy` |
| 5, 6, 7, 8, 9, 10, 12, 13 | documented here; see [alpha](https://github.com/ShrewdLemon/alpha) for working code |

```bash
pip install beurs[all]
python -m pytest tests/ -q
```

---

## Why this list exists

It is a by-product of [alpha](https://github.com/ShrewdLemon/alpha) — a pre-registered study testing whether
LLM-extracted earnings-call signals predict abnormal returns on Indian equities.

The study found **nothing**: 0 of 24 pre-registered cells survived the gate. But
getting to a trustworthy zero meant fixing every trap above first, because each
one produces a *plausible non-zero* if you leave it in.

That is the real argument for writing them down. A pipeline with these bugs does
not fail loudly — it hands you a result.
