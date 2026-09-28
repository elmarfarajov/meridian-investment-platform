# 37. Execution is simulated minute by minute, with the price path without our trades kept

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

The platform has daily market data only. Execution happens inside the day, and its
cost depends on the shape of the day's volume and on what the order itself does to
the price. There were three options:
- a formula for cost (the square-root law) with no execution at all;
- a full limit-order-book simulation;
- a bar-level simulation with explicit impact.

A formula cannot compare algorithms or produce fills to allocate. A limit order book
needs data and calibration the platform does not have, and its impact emerges rather
than being a known parameter.

## Decision

- Each stock's day is **390 one-minute bars**:
  - U-shaped volume scaled to ADV;
  - a random walk whose variance follows the same U-shape and sums to the daily
    variance;
  - an overnight gap from the previous close.
- Our fills pay **half the spread** and a **square-root temporary impact**, and move
  the mid permanently by a **linear permanent impact**, for the rest of the day.
- The simulator keeps **two paths**: the mid-price without our trades, and with them.
  Transaction cost analysis uses both. Impact and timing, which no real desk can
  separate, are therefore measured exactly.
- The impact parameters are known (η = 0.35, γ = 0.25). A calibration from the desk's
  simulated history can be scored against them, as the Day 5 risk model was scored
  against a universe with known risk.

## Consequences

- Every block of the rebalance can be re-run with every algorithm on the identical
  day, which is the comparison a real desk cannot make.
- The calibration is instructive. Measured impact recovers η to within 1.5%. The costs
  a desk actually observes give an interval that includes zero after 400 orders, which
  quantifies why impact models are pooled across millions of orders.
- The market is simpler than a real one: one venue, no auctions, no transient impact.
  These are noted where the results depend on them.
