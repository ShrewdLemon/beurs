# Security

## Reporting

Open an issue at https://github.com/ShrewdLemon/bourse/issues. For anything you
believe should not be public first, mark the issue title `[security]` and leave
out the details until we have a private channel.

## Threat model

bourse is a library that reads data you already have, plus one optional network
fetch from NSE's public archive. It has no server, no credentials, no telemetry,
and no persistent state beyond an optional parquet cache you name yourself.

What that leaves:

**The exchange archive is a third party.** Its response is not trusted. The
bhavcopy fetch enforces a 64 MB ceiling on the wire and 256 MB unpacked, checks
declared member sizes *before* expanding anything, and raises `Untrusted` rather
than parsing an HTML error page as a data file. Nothing from an archive is ever
written to disk under a name the archive chose, so archive path traversal does
not apply. These are pinned by tests in `tests/test_security.py`, including a
traversal test that exists to fail loudly if anyone ever refactors to
`extractall()`.

**Optional dependencies.** `yfinance`, `curl_cffi` and `exchange_calendars` are
not required to import bourse. The audit, repair and calendar paths run on
pandas alone.

**No dynamic execution.** No `eval`, `exec`, `pickle`, `subprocess`, or
`yaml.load` anywhere in the package.

**File writes.** Only to paths you pass (`repair -o`, `cache_dir`). bourse does
not choose locations on your behalf.

## What bourse does not protect you from

It checks data quality, not authenticity. If your source is compromised and
returns internally consistent fabricated prices, no check here will notice —
`fabricated_jumps` compares your series against raw exchange closes *you*
supply, so it is only as trustworthy as that reference.
