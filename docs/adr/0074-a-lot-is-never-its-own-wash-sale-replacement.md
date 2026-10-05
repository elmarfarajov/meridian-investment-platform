# 74. A lot is never its own wash-sale replacement

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

The optimiser disallowed the loss on any lot of a security bought within the last 30
days, so a lot bought last week and sold today at a loss was always a wash sale. The
rule asks whether *substantially identical* stock was acquired within 30 days of the
sale. The shares sold are not acquired in that sense, so a lot cannot replace itself.

## Decision

`recently_bought` returns the recent lots by asset, and `has_replacement(lot, recent)`
asks whether any *other* lot was opened in the window. The backtest adds a disallowed
loss to the basis of another lot, never to the lot sold.

## Consequences

- Losses on young lots can be harvested when nothing else was bought.
- Purchases after the sale are still handled by the repair rounds and the 30-day ban
  on buying back.
