# 20. Brinson-Fachler on local returns, with currency and costs apart and funds looked through

- **Status:** Accepted
- **Date:** 2026-09-25

## Context

The account holds stocks and a bond in five currencies, plus two index funds, and is
measured against a multi-currency policy benchmark. A single-currency Brinson
attribution run on dollar returns mixes two decisions: which German stock to own, and
whether to own euros. It also has nowhere to put costs, and it treats an index fund
as a segment the benchmark does not have.

Brinson-Hood-Beebower measures allocation against zero, so it rewards overweighting
any segment that rose, even one that rose less than the market.

## Decision

- **Brinson-Fachler**: allocation is `(wp - wb)(Rb_s - Rb)`, selection
  `wb(Rp_s - Rb_s)`, and interaction the remainder of the segment's active
  contribution. So the three add up exactly, by construction.
- The three effects are computed on **local** returns. The **currency** effect is
  computed per currency as the portfolio's currency contribution less the
  benchmark's, on the same closing-local-value convention as the value bridge
  (ADR 0017).
- **Costs** are the portfolio's own effect.
- Segments where the portfolio held nothing at the start of the day have no `Rp_s`.
  Their effect is allocation, plus selection for anything earned by a position opened
  that day.
- **Index funds are looked through** to the benchmark's constituents in their scope
  (a region, or the whole index), in the constituents' weights of the day.
- Attribution is computed by sector and by region.

## Consequences

- Each day the effects sum to the day's active return with a residual around 1e-17.
- Stock pickers are judged on stock picking. The yen underweight appears as a currency
  effect (-86 bp) rather than hidden in "Japan allocation".
- Look-through depends on the benchmark's composition, so a fund that tracks its part
  of the benchmark shows almost no selection, which is the truth.
- Interaction is reported rather than folded into selection. Some firms fold it; the
  choice is visible in the output and can be changed in one place.
