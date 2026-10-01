# 53. Currency regimes and lifecycles are reference data, and statistics stand aside under management

- **Status:** Accepted
- **Date:** 2026-10-02

## Context

Under a currency board the central bank, not the market, decides where a rate sits,
and an outlier test asks the wrong question there. A currency that joined the euro has
no fixings to miss. A suspended fixing that resumes nine years later does not have a
one-day return.

Without being told any of this, the FX rules mistook policy for faults. They flagged
25 years of the lev as stale, the euro adoptions as 13 runs of missing days, and the
krona's resumption as a 57% one-day move.

## Decision

- `refdata.currency_regimes` records, for the currencies the ECB fixes:
  - **regimes** - currency board, ERM II, unilateral peg, crawling peg, floor - with
    their central rates, bands, dates and sources;
  - **endings** - the nine euro adoptions with their conversion rates, the two
    redenominations, and the two suspensions with the resumption where there was one.
- The quality context takes the periods with nothing to expect. Missing-days ignores
  them, and no return is taken across one.
- Statistics (robust outlier, spike reversal, the staleness gate) stand aside on days
  under a managed regime, and for 60 fixings after one ends. `PegBand` checks the band
  instead, and floors are checked one-sided with 1% slack.

## Consequences

- The reference data is tested against the real data:
  - every euro joiner's last ECB fixing equals its conversion rate;
  - every managed rate stays within its band, plus rounding.
- With resolution, lifecycle and regime known, 1,282 findings fall to 135.
- The register is maintained by hand. A production system would source regimes from
  the IMF's AREAER classification and central bank notices. Getting one wrong is
  visible: the band test fails.
