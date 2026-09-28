# 38. Algorithms are schedules; IS follows Almgren-Chriss with impact matched to the square-root law; a wheel routes by size

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

A desk needs a small set of algorithms that span the standard benchmarks (time,
volume, participation, arrival price, close), and a rule for which to use. The
arrival-price algorithm needs an optimal trajectory. The textbook one (Almgren–Chriss)
assumes linear temporary impact, while the simulator, like the evidence, uses the
square-root law.

## Decision

- Each algorithm is a **schedule**: the cumulative share of the order planned by the
  end of each minute.
  - TWAP is even;
  - VWAP follows the expected volume curve;
  - Close trades in the last ten minutes;
  - POV follows realised volume;
  - IS is the Almgren–Chriss trajectory.
- One engine works any schedule into child orders, one per 15-minute slice. It catches
  up with the plan minute by minute, capped at 25% of the minute's volume and by any
  limit price.
- For IS, the linear `η` is set so that linear and square-root impact agree at the
  order's own average rate. The trajectory is then optimal for the simulator to first
  order. **Urgency** is expressed as `κT`, which is dimensionless and comparable
  across stocks, and converted to a risk aversion.
- A size-based **algorithm wheel** routes the day's blocks:
  - VWAP under 2% of ADV;
  - IS from 2% to 10%;
  - POV at 15% above 10%.

## Consequences

- Re-running the day's blocks with every algorithm shows:
  - VWAP, TWAP and IS at about 10.5 bp of controllable cost;
  - POV and Close at about 21–22 bp, because they concentrate their trading;
  - Close also leaving the most undone.
- The largest blocks expire with shares left. That is correct for one day, and the
  opportunity cost is charged; a real desk would carry them over.
