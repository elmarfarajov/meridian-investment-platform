# 22. The benchmark is a synthetic index generated in the same market as the book

- **Status:** Accepted
- **Date:** 2026-09-25

## Context

Brinson attribution needs the benchmark's constituents, weights, sectors, regions and
currencies every day. Real index data is licensed, cannot be committed to a public
repository, and would make the documentation impossible to reproduce. A benchmark that
is only a return series cannot be attributed. A benchmark of independent random stocks
would not move with the book, so every active return would be noise.

## Decision

- Build **Meridian World Equity**: a cap-weighted, total-return index of 36 stocks. Six
  are the book's own stocks; thirty are companions with plainly synthetic identifiers
  (`BM-US-FIN-1`) that do not claim to be real companies.
- Generate the companions with `SyntheticMarket.companion`, which replays the market's
  own market-factor and sector-factor draws and uses a separate random stream only for
  idiosyncratic noise. Existing instruments' prices are unchanged.
- The account's benchmark is a **policy blend**: 80% the index, 15% the Treasury bond
  the account can hold (total return), 5% cash, rebalanced monthly.
- The interfaces take constituents and total-return series, so a licensed index can
  replace the synthetic one without touching the attribution.

## Consequences

- The whole platform stays reproducible from one seed. Documentation numbers are
  assertions in the tests.
- The book and the benchmark behave realistically together: correlation 0.87, beta
  0.85, tracking error 5.7%.
- The synthetic index is not a claim about any real market. The documentation says so
  wherever it appears.
