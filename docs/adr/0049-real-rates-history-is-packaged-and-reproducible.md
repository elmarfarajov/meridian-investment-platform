# 49. Real rates history is packaged, public domain, and rebuilt by a script

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

Meridian's demonstration market is synthetic by design: the truth is known, so
every estimator can be checked against it. Rates are different. The history of the
US curve is public, and a curve fitter or a factor analysis that has never met it
has not been tested. Fetching the data at run time would make charts and tests
depend on the network, and let the documented numbers drift.

## Decision

- Two public-domain datasets ship in the package as gzip CSV under
  `meridian/marketdata/reference`:
  - **The US Treasury's daily par yield curve** since 1990: 9,194 days, 0.15 MB.
    Headings the Treasury renamed over the years ("1.5 Month") are normalised.
  - **The Gurkaynak-Sack-Wright curve** (FEDS 2006-28) since 1990: 9,171 days of
    parameters at full precision, plus zero yields to a millionth of a per cent,
    0.78 MB.
- `python -m meridian.devtools.fetch_rates` rebuilds both from their sources. The
  gzip timestamp is fixed, so an unchanged dataset produces an unchanged file.
- `marketdata.rates_history` reads them. A tenor appears on a day only if the
  Treasury published it that day; nothing is filled in.
- **SOFR swap quotes are illustrative** and labelled so wherever they appear.
  Cleared swap quotes are not free to publish. The illustration is the real
  Treasury curve of the day plus typical swap spreads.

## Consequences

- Charts and tests covering 36 years of real curves run offline and reproducibly.
- The data stops on the day it was fetched, 30 September 2026. Refreshing it is a
  deliberate commit, whose diff shows exactly what changed.
- The Fed publishes one day, Good Friday 2008, with parameters but no yields. A test
  pins that date, so a silent change in the source would be noticed.
