# 40. Cost is measured as implementation shortfall; the client report is assembled from the modules' own objects

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

Two decisions close the loop from decision to client.

**Which cost.** Brokers are usually judged against VWAP. But VWAP can be beaten by an
order that pushes the price up all day and trades into it. The client pays the
difference between the decision and the result.

**Which report.** A client report is often assembled by re-keying numbers from each
system into a document. That is exactly how a report comes to show a return that
disagrees with the valuation, or a cost that disagrees with the trades.

## Decision

- **Transaction cost is implementation shortfall** against the decision price (the
  previous close). It is decomposed into delay, spread, temporary and permanent
  impact, timing, opportunity and fees, and every order checks that the components
  add up. The costs the desk controls (spread, impact, fees) are reported apart from
  the market's own move. VWAP slippage is reported as secondary.
- **The client report is built from the platform's own objects**:
  - the valuation (Day 3);
  - the returns and the factsheet (Day 4);
  - the risk model and its report (Day 5);
  - the mandate and its report (Day 6);
  - the rebalance proposal (Day 7);
  - the allocations and their shortfall (Day 8).
  Nine A3 pages go into one PDF through Matplotlib's PDF backend, with document
  metadata and no creation date, so that the same data gives the same file.

## Consequences

- The rebalance cost the demonstration account −7.9 bp: +9.8 bp the desk controls and
  −17.7 bp the market gave. The report says so in those terms rather than claiming the
  saving.
- A number cannot differ between the summary page and the page it summarises, because
  both come from the same object.
- A dedicated PDF library (ReportLab, WeasyPrint) would add typographic control. The
  cost is a second rendering stack beside the one every chart already uses.
