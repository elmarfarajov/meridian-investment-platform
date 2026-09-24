# 16. Tax basis is kept apart from book cost, on the lot

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

Three facts about a lot matter for tax and are not its economic cost:

- **When the holding period started.** Shares transferred in keep the donor's
  acquisition date; wash sale replacement shares add the holding period of the shares
  sold.
- **What it cost in the base currency.** A euro holding in a dollar account was bought
  at a rate; its dollar gain on sale depends on that rate as much as on the price.
- **Whether a disallowed loss has been added to it.** Under the wash sale rule (IRC
  1091) a loss on a sale followed by a repurchase within 30 days is not lost but moved
  into the replacement shares' basis.

If these are folded into `cost_per_unit`, the book cost stops being what was paid, the
ledger no longer ties to the lots, and a later report cannot say how much of a
lot's basis is cash and how much is tax adjustment.

## Decision

- `TaxLot` gains `holding_period_start`, `open_fx_rate` and `wash_sale_adjustment`
  (per unit, in base currency). `cost_per_unit` remains the economic cost, commission
  included.
- `tax_basis = quantity x (cost_per_unit x open_fx_rate + wash_sale_adjustment)`.
  Holding period and long-term status are measured from `holding_start`.
- Splitting, rescaling and every corporate action carry the three attributes: a split
  divides the per-unit adjustment, a spin-off divides it with the basis, a stock
  merger moves it into the acquirer's lots.
- Wash sales are applied with full knowledge of acquisitions 30 days either side.
  Replacement capacity is tracked per purchase, each share replaces at most one sold
  share, and a match against a purchase not yet booked is deferred until it is.
  Losses are measured in the tax currency.

## Consequences

- The general ledger never sees a wash sale; the lot does. Book and tax gains are both
  available on every realised lot, with the Form 8949 code and adjustment.
- The same attributes let a realised or unrealised gain be split exactly into price and
  currency (ADR 0017).
- Drawing the demonstration's wash sale showed a replacement lot tacked 598 days,
  longer than the sold shares had been held: one sale closing two lots had applied its
  second match to shares the first had already adjusted. Replacement lots are now
  remembered, and each piece is tacked once with its own sold shares' period.
