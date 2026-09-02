# Contributing

The most valuable contribution is **a measured trap**.

A trap is not "this data looks wrong". It is:

1. **What the source says** vs **what the exchange says**, with dates and numbers.
2. **How to reproduce it** — a snippet someone else can run.
3. **Why it is silent** — what a normal pipeline does with it, and why no
   exception is raised.

Traps that meet that bar go in `TRAPS.md`. If the check generalises, it goes in
`bourse/audit.py` with a test.

## Adding an exchange

Calendars carry provenance. Two ways in:

- **`sourced`** — add an entry to `EXCHANGES` in `bourse/calendars.py` pointing
  at an `exchange_calendars` name. Low effort, and honest: the package says the
  calendar was not independently checked.
- **`verified`** — ship a session list probed against the exchange's own
  published record, plus the script that produced it. Only do this where the
  sourced calendar is actually wrong, and show the diff.

Do not ship a `verified` calendar you have not verified. The provenance label is
the whole point of the package.

## Tests

`pytest tests/ -q`. No network in tests — capture a fixture instead. A test that
needs the internet will be flaky in CI and will be ignored, which is worse than
not having it.
