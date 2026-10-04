# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] - 2026-10-05

Day 5 revisited: risk against independent references and a century of daily returns. A
second reading found six faults; the Basel Committee's table, `arch`, pandas,
scikit-learn, PyPortfolioOpt and 97 years of daily VaR backtests check what is left.

### Added

- **Reconciliation against references** (`devtools/risk_reference.py`), 41 checks:
  - the Basel Committee's 1996 traffic-light table, to the printed digit;
  - `garch_filter` against `arch`'s conditional volatilities and forecast, to 0;
  - `EwmaState` against pandas;
  - Ledoit-Wolf against scikit-learn and PyPortfolioOpt. PyPortfolioOpt feeds Ledoit
    and Wolf's `covCor.m` the T - 1 sample; given the T sample the original uses, it
    agrees exactly.
- **A century of daily US returns** (`marketdata/french.py`): the 12 industry
  portfolios and the factors, daily from 1 July 1926.
- **Daily VaR forecasters for a single series** (`risk/backtest.py`): normal with
  RiskMetrics volatility, historical and filtered historical simulation, and GARCH-t.
- **`services/century_risk.py`:**
  - VaR backtested since 1929, with Basel's zone year by year;
  - bias statistics by decade;
  - QLIKE losses (`risk.validation.qlike`);
  - minimum-variance trials on the twelve industries.
- **Eight charts** (one hundred and eighty in the gallery), a methodology note, and
  ADRs 0064 to 0067.

### Fixed

- **Monte Carlo VaR** drew one Student-t for the whole book's specific risk; each
  holding now draws its own. The account's Monte Carlo VaR is 1.92%, not 1.99%.
- **The Basel traffic light** was a 250-day lookup. The zones are now the Committee's
  binomial rule for any window, and the callers pass the window they scored.
- **`minimum_variance_weights`** promised a pseudo-inverse for a singular matrix and
  raised an error instead.
- **`RollingForecaster`** ignored its own half-lives in the description and in the
  z-scores.
- **Cornish-Fisher** answered outside the domain where its expansion is monotone; it
  now refuses.
- **`standardise_against`** skipped the re-centring and rescaling after winsorising.
  An off-universe stock now gets the exposure of a universe stock with the same
  descriptor, and the account's volatility forecast is 12.24%, not 12.22%.

### Changed

- **GARCH is filtered by one function**, `garch_filter`, in every forecaster.
- PyPortfolioOpt is a development dependency.

## [1.4.0] - 2026-10-05

Day 4 revisited: performance against independent references and a century of real
returns. A second reading found six faults; empyrical, Microsoft's XIRR examples and
Kenneth French's data library check what is left.

### Added

- **Reconciliation against empyrical and scipy** (`devtools/performance_reference.py`).
  Fifteen measures on the demonstration account (daily) and the equal-weighted US
  market (monthly since 1926):
  - 22 of 30 agree to 1e-10;
  - 8 differ by a convention, and each is recombined from Meridian's blocks to land on
    empyrical's figure to 1e-10.
- **Four linking methods** (`performance/linking.py`): Cariño, Menchero, GRAP and
  Frongello. Each is exact; the method is chosen per attribution and recorded on the
  result.
- **A century of US equity returns** (`marketdata/french.py`, `devtools/fetch_french.py`):
  - Kenneth French's 12 industry portfolios, with firm counts and sizes;
  - the Fama-French factors, monthly from July 1926.
  `services/century_review.py` uses them to:
  - rebuild the market from its industries (11 bp a month from the published market);
  - attribute equal weight against cap weight by decade and over the century;
  - measure drawdowns and Sharpe ratios since 1926.
- **`xnpv`**, and `brinson_fachler_day` for data that arrives already segmented.
- **Eight charts** (one hundred and seventy-two in the gallery), a methodology note,
  and ADRs 0060 to 0063.

### Fixed

- **The trailing year** started on `min(day, 28)` of the month a year back, three days
  early at a month end. It now starts on the same date a year earlier, and a month end
  on a month end.
- **Short-period Sharpe and Sortino ratios** set an unannualised return against an
  annual risk-free rate. Ratios now always use the annual rate; the presented return
  still follows GIPS.
- **Relative measures** were annualised over the union of both series' spans. They now
  cover the shared period.
- **XIRR** counted years of 365.25 days. It now counts actual/365, as Excel does, and
  Microsoft's published examples are reproduced.
- **Capture ratios** divided compounded totals. They are now Morningstar's ratio of
  returns annualised over the up or down periods, as empyrical computes it.
- **Modified Dietz** weighted a flow on the opening date above one. Flows outside the
  period are refused.

### Changed

- **Return series carry an origin and a frequency.** The demonstration series start
  from their first valuation, the Friday rather than the Sunday before, and monthly
  series annualise with twelve periods.
- empyrical-reloaded (with pytz) is a development dependency.

## [1.3.0] - 2026-10-04

Day 3 revisited: the book of record held to the tax authorities' own worked examples,
and to properties that must hold for any history of trades. Between them they found
three gaps in UK matching, two engine bugs and one arithmetic slip in HMRC's manual.

### Added

- **The published examples** (`devtools/tax_reference.py`): 12 cases and 42 figures.
  - IRS Publication 550's wash-sale examples, which agree to the cent. They include
    replacements bought before the sale, and a loss that may not reduce gains on other
    blocks.
  - HMRC's CG51560, CG51590 and HS284 examples, which agree to the pound. They cover
    same day, bed and breakfast, the pool, two rights issues, a 1982 rebasing and the
    thirty-first day.
  - CG51590 Example 2 prints a pool cost of £4,236 where HMRC's own arithmetic gives
    £4,235. It is recorded in `KNOWN_ERRATA`, and the engine is not bent to match it.
- **Property tests of the book** (`tests/accounting/test_book_invariants.py`).
  Hypothesis writes histories in two currencies under three relief methods. Each must
  satisfy:
  - a zero trial balance;
  - the sub-ledger tied to the lots at historical cost;
  - quantities that reconcile;
  - every disallowed loss carried in a replacement basis.
- **`builders.rights_take_up`**: a purchase marked as rights taken up.
- **Six charts** (one hundred and sixty-four in the gallery), a methodology note, and
  ADRs 0056 to 0059.

### Fixed

- **Shares sold together replaced each other.** Under HIFO, the loss on the first lot
  a sale closed could be matched to shares of another lot the same sale closed. The
  disallowed loss then landed on no open lot and vanished from the tax basis.
- **An intraday round trip was refused.** Sales are booked before purchases within a
  day, so a sale of shares bought that day found nothing held. A sale of more than the
  day's opening holding is now booked after the day's purchases.
- **UK matching, against the statute:**
  - disposals (and acquisitions) on one day are one transaction, TCGA 1992 s105(1);
    two sales on a day used to be matched in turn;
  - rights taken up join the section 104 pool and are never matched under the 30-day
    rule (s127);
  - a disposal the pool cannot cover is matched with later acquisitions (HS284), not
    refused.

### Changed

- **The demonstration Treasury (`US-T-2032`) accrues actual/actual (ICMA)**, as US
  Treasuries do, not 30/360. Accrued interest on the test purchase is $1,588.40
  rather than $1,557.29. The largest Microsoft purchase the Day 6 hard limits allow
  returns to $85,976.

## [1.2.0] - 2026-10-02

Day 2 revisited: market data on real FX. The quality engine ran over 27 years of ECB
fixings and the Federal Reserve's noon rates. A second reading of the code found four
faults, and the real data found what the synthetic market could not.

### Added

- **27 years of real exchange rates** (`marketdata/fx_reference.py`):
  - the ECB's euro reference rates for 41 currencies since 1999;
  - the Federal Reserve's H.10 noon rates.
  Both are packaged, and rebuilt by `fetch_rates`.
- **Currency regimes and lifecycles** (`refdata/currency_regimes.py`):
  - currency boards, ERM II bands, unilateral and crawling pegs, and floors;
  - the nine euro adoptions with their conversion rates;
  - two redenominations and two suspensions.
  All are checked against the real data.
- **Regime-aware FX quality** (`quality/fx_regimes.py`):
  - `PegBand` checks a managed rate against its band;
  - statistics stand aside under management and for 60 fixings after;
  - a register of 31 documented market events explains the findings on their days.
- **The real-FX review** (`services/fx_review.py`, `meridian market fx-review`). It
  runs the rules stage by stage, 1,282 -> 560 -> 546 -> 135 findings, of which 82 are
  explained and 53 left for a person, including the ECB's krona frozen at 305 for 19
  days in October 2008. It also compares the ECB's fix with the Fed's: 18 bp apart at
  the median, 3h45 apart in UTC.
- **Fixing times in the golden copy.** A source fixed hours from the anchor is set
  aside with the reason, not counted as disagreeing, with daylight saving respected.
- **Quotation units** (`core.currency.QuoteUnit`): GBX, ZAc, ILA and USX.
- **Eleven charts** (one hundred and fifty-eight in the gallery), a methodology note,
  and ADRs 0051 to 0055.

### Fixed

- **The pence trap.** A sterling dividend on a share quoted in pence was set against
  the price unconverted, so a 1.02% payout read as 0.01%. Dividends are now restated
  in the price's unit, through a required exchange rate when the currencies differ.
- **Events on days without a print.** An ex-date the feed had no price for was never
  divided out, so a routine split scored as a bad tick. Every event between two
  observations now counts.
- **Gaps against the market.** A return spanning missing prints is set against the
  market's move over the whole span, and the market proxy uses one-session returns
  only.
- **The MAD scale** is 1/Phi^-1(3/4), as scipy uses, not 1.4826.

### Changed

- **The robust scale is floored at one tick of the quote**, measured locally.
  **Staleness** is the probability of repeating a tick given recent volatility, not a
  count. On the synthetic market nothing changes: every planted fault is still caught.

## [1.1.0] - 2026-10-01

Day 1 revisited: the rates engine, validated. It is reconciled against QuantLib and
tested on 36 years of the real US Treasury curve and the Federal Reserve's own fitted
curve. Every difference is either fixed or explained in writing.

### Added

- **Reconciliation against QuantLib** (`devtools/reference.py`, `meridian rates validate`).
  It runs 27 checks:
  - six calendars on every weekday 1990-2060;
  - eight day counts on 19,884 date pairs each;
  - bond analytics in ACT/ACT ICMA and 30/360 US;
  - a gilt through two ex-dividend periods;
  - a 20-swap SOFR curve.
  Every remaining break is listed with its reason and evidence, and a test holds the
  set to exactly those.
- **Curves from dated instruments** (`analytics/curve_building.py`):
  - deposits and SOFR OIS with spot lags, calendars, modified-following rolls,
    ACT/360 and payment lags;
  - the curve's repricing errors, the Jacobian of zero rates to quotes, and bucketed
    DV01 with hedge notionals.
  It matches QuantLib's `PiecewiseLogLinearDiscount` to 2.4e-13.
- **Monotone convex interpolation** (Hagan-West, `core/monotone_convex.py`), with the
  positivity collar and closed-form integrals. Property tests cover repricing,
  continuity, positivity and locality.
- **The equinoxes computed** (`core/astronomy.py`, Meeus chapter 27), to decide
  Japan's holidays where the references disagree.
- **36 years of real rates, packaged** (`marketdata/rates_history.py`):
  - the US Treasury daily par curve since 1990;
  - the Gurkaynak-Sack-Wright curve.
  Both are public domain, and `python -m meridian.devtools.fetch_rates` rebuilds them.
- **Nelson-Siegel and Svensson fitting** (`analytics/parametric.py`), to par yields,
  with a grid start and warm starts. The formula reproduces every published GSW yield
  to within 0.034 bp.
- **PCA of curve moves** (`analytics/curve_pca.py`), oriented to level, slope and
  curvature: 79.4, 12.7 and 4.1 per cent of the Treasury's daily moves since 1990.
- **UK gilts** (`FixedRateBond.gilt`): ACT/ACT ICMA, paid the next business day, seven
  business days ex-dividend, negative accrued interest. They match QuantLib's
  `exCouponPeriod` to 1e-13.
- `meridian rates treasury DATE`: the real curve on any day since 1990, bootstrapped
  and fitted.
- **Fifteen charts** (one hundred and forty-seven in the gallery), a methodology note,
  and ADRs 0046 to 0050.

### Fixed

- **Calendars that did not know their history.** v1.0.0 disagreed with QuantLib on
  309 weekdays; 72 remain, all explained. Now fixed:
  - rules applied before they existed (NYSE's Martin Luther King Jr. Day before 1998,
    TARGET's Easter and Labour Day before 2000, Japan before the Happy Monday reforms,
    Marine Day and Mountain Day before they began);
  - Japan's substitute-holiday rule before 2007, and its citizens' holidays;
  - special closures no rule predicts (9/11, Hurricane Sandy, five presidential days
    of mourning, the moved bank holidays and jubilees, the royal funeral and
    coronation, the enthronements);
  - SIFMA's Good Friday early closes and Saturday Veterans Day;
  - Xetra trading on Whit Monday.
- **30/360 US** had no end-of-February rules; it now follows SIFMA. The ISDA
  convention is kept as `30/360 Bond Basis`.
- **Bonds on 30/360** are priced with DSC/E counted on 30/360 days, the street
  convention, not calendar days. The largest Microsoft purchase the Day 6 hard limits
  allow moves from $85,976 to $85,978.
- **The par bootstrap** repeats its pass for non-local interpolators. Monotone cubic
  curves had been left up to 0.86 bp off their quotes.
- **Par yields between coupon dates** include the accrued interest of the short first
  period. Without it, sampled par curves were a sawtooth.

### Changed

- Calendars separate the **scheduled** view (the rules) from the **actual** one
  (scheduled, less special openings, plus special closures). The synthetic market and
  the demonstration desk step through the scheduled view, so a closure recorded after
  the fact no longer reshuffles every simulated price. Quotes are published only on
  actual sessions; a closed day's move is priced at the next open.
- Each vendor has its own random stream per instrument, so one series' missing day
  cannot shift another's noise. The pricing run now records 16,735 observations, 207
  findings, 5,606 golden prices and 140 challenges (from 16,758, 211, 5,613 and 143),
  and every planted fault is still caught.
- QuantLib joins the development dependencies.

### Known

- The demonstration Treasury (`US-T-2032`) carries a 30/360 day count; Treasuries
  accrue ACT/ACT. Changing it changes the whole demonstration book, so it is left for
  the Day 3 revisit.

## [1.0.0] - 2026-09-30

Day 9: the platform. One web service over the eight modules, with the controls a
regulated firm needs, and the whole stack runnable with one command. Release 1.0.0.

### Added

- **The API** (`api/`): FastAPI with 21 endpoints under `/v1`:
  - portfolios with valuation, performance, attribution, risk, compliance and tax lots;
  - pre-trade checks and rebalance proposals;
  - orders with four-eyes decisions;
  - trading costs, the client report as a PDF, and the audit log.
  Every response is a Pydantic model, errors are RFC 9457 problem details, and the
  OpenAPI 3.1 document records each endpoint's permission as `x-permission`. The API
  serves the modules through a data facade and computes nothing of its own.
- **Access control** (`api/security.py`):
  - PBKDF2-HMAC-SHA256 passwords at 600,000 iterations;
  - HS256 JWTs with issuer and expiry;
  - six roles as bundles of twelve permissions, and client entitlements answered as
    absent;
  - separation of duties, and a token-bucket rate limit with `Retry-After`;
  - refusal to start in production with the development key.
- **A tamper-evident audit log** (`core/audit_chain.py`): every request chained by
  SHA-256, verified at `/v1/audit/verify` and by the readiness probe, appended
  optimistically across worker processes.
- **Idempotent writes** by `Idempotency-Key`, and **four-eyes orders**: checked against
  the Day 6 mandate, approved by a second person above $250,000 or when an override is
  needed, never by their author.
- **Observability**: Prometheus metrics (requests, latency histograms, refusals, audit
  records and failures) and a provisioned Grafana dashboard.
- **Deployment**:
  - a multi-stage, non-root, health-checked image, with dependencies in their own
    cached layer;
  - Docker Compose with PostgreSQL 16, a migration job, the API, Prometheus and
    Grafana;
  - a CI job that builds the stack and smoke-tests it.
- **Persistence**: `platform_users`, `audit_log`, `idempotency_keys` and
  `order_requests`, in migration 0009.
- **`meridian platform`**: `serve`, `users`, `add-user`, `verify-audit`, `openapi`.
- **The project measured** (`devtools/`):
  - growth at every release tag;
  - the package graph, with a test that every import points down the layers;
  - a working day driven over HTTP against the real modules.
- **Fifteen charts** (one hundred and thirty-two in the gallery), a methodology note and
  ADRs 0041 to 0045.

### Changed

- The workload simulator lives in `devtools`, not `services`, and the hash chain lives in
  `core`. The layering test found two imports pointing up; both were moved rather than
  excused.

## [0.9.0] - 2026-09-29

Day 8: execution and reporting. The Day 7 rebalance traded: block orders across three
accounts worked by algorithms through a simulated market, allocated back at one price,
and its cost decomposed exactly - then everything the platform knows about the
account assembled into a nine-page client report.

### Added

- **Orders** (`execution/orders.py`): a FIX `OrdStatus` state machine with a checked
  transition table, an audit trail of every event, parent and child orders, and
  invariants re-checked after every event (no overfill, no fill through the limit,
  average price recomputed from the fills).
- **The market** (`execution/market.py`): 390 one-minute bars per stock from its Day 2
  profile:
  - U-shaped volume;
  - U-shaped intraday variance and an overnight gap;
  - half-spread, square-root temporary impact and linear permanent impact.
  The price path without our trades is kept beside the one with them.
- **Algorithms** (`execution/algorithms.py`): TWAP, VWAP, POV, IS and Close as
  schedules, worked into 15-minute child orders under a 25% participation cap and
  optional limit. IS follows **Almgren-Chriss** (`execution/almgren_chriss.py`): the
  closed-form trajectory, its cost-risk frontier, and linear impact matched to the
  square-root law.
- **Allocation** (`execution/allocation.py`): account orders aggregated into blocks and
  allocated at one average price, pro rata by largest remainder, with a minimum and no
  account over its request.
- **Transaction cost analysis** (`execution/tca.py`): implementation shortfall against
  the decision price, split exactly into delay, spread, temporary and permanent impact,
  timing, opportunity and fees; VWAP and arrival slippage; a pre-trade estimate; impact
  calibration by regression, from measured impact and from what a desk observes.
- **The trading day** (`services/demo_execution.py`):
  - the Day 7 tickets for three accounts on the same model, 78 orders in 26 blocks;
  - an algorithm wheel;
  - every block re-run with every algorithm on the same day;
  - a 400-order desk history for calibration.
- **The client report** (`reporting/client_pack.py`): nine A3 pages in one PDF.
  - New pages: cover, summary, holdings and tax, trading and costs, methodology.
  - The Day 4 to Day 7 one-page reports, drawn from the same objects.
- **Persistence**: `execution_orders`, `execution_events`, `execution_fills`,
  `order_allocations` and `transaction_costs`, in migration 0008. The run writes
  nothing unless:
  - every order's invariants hold;
  - every fill is within the day's prices;
  - every block is allocated in full;
  - every shortfall adds up.
- **`meridian trade`**: `blotter`, `order`, `costs`, `algos`, `calibrate`,
  `allocations`, `run` and `stored`. **`meridian report client`** writes the PDF.
- **Fourteen charts** (one hundred and seventeen in the gallery), a methodology note and
  ADRs 0036 to 0040.

## [0.8.0] - 2026-09-28

Day 7: tax-aware optimisation. Rebalancing that chooses which lots to sell, harvests
losses the wash-sale rule allows, meets the mandate, and knows what each dollar of tax
buys in tracking error - with the frontier to prove it and a multi-year simulation to
say what it is worth.

### Added

- **The rebalance** (`optimisation/rebalance.py`), a conic programme in cvxpy solved by
  Clarabel:
  - weights bought per asset and **sold per tax lot**;
  - tracking error in the Day 5 model's factor form (a second-order cone);
  - tax linear per lot at the lot's own rate, a loss as a saving;
  - commission, half-spread and square-root market impact as a 3-D power cone;
  - the cash band, and optional tracking-error and tax budgets.
  Solver fallback: Clarabel, then Clarabel given longer, then SCS.
- **The mandate compiled into constraints** (`optimisation/constraints.py`): weights
  with look-through, the heaviest group, exclusions (applied by removing the
  variables), tracking error, volatility, and active share. Soft rules are penalised,
  and every limit is met 5 bp inside.
- **Non-convex rules in rounds**:
  - wash sales by repair (a stock whose loss lots are sold is barred from purchase);
  - an active-share floor by the convex-concave procedure, started twice with the
    better kept.
  Every round is recorded.
- **Lot relief**: specific identification (lowest tax per unit first), FIFO, LIFO and
  highest cost first, and the same trades relieved every way.
- **Orders** (`optimisation/rounding.py`): a mixed-integer programme in HiGHS that
  rounds the continuous trades to whole lots (100-share board lots in Tokyo) and
  minimum tickets, keeping the cash band. Sales are allocated to lots.
- **The frontier** (`optimisation/frontier.py`): tracking error against tax as the lower
  envelope of an epsilon-constraint sweep and a price-of-risk sweep, with the dominated
  local optima kept.
- **Tax alpha** (`optimisation/backtest.py`): four managers through the same markets,
  simulated from the Day 5 model on a 100-stock index reconstituted quarterly:
  - the US ledger: netting, the $3,000 offset, carryforward, and wash-sale deferral
    into the replacement's basis;
  - the client's outside gains, which harvested losses offset;
  - tax alpha on liquidation value and as held.
- **The demonstration** (`services/demo_optimisation.py`):
  - the book's 31 open lots and 30 benchmark stocks to buy;
  - the Day 6 mandate;
  - a proposal checked by the Day 6 compliance engine as one basket;
  - three managers compared.
- **Persistence**: `rebalance_proposals`, `proposed_orders`, `proposed_lot_sales`,
  `rebalance_frontier` and `tax_alpha_results`, in migration 0007. The run writes
  nothing unless:
  - value is conserved;
  - no stock is both sold at a loss and bought;
  - the orders are tradable;
  - the compliance engine does not block the proposal;
  - the frontier is monotone.
- **`meridian rebalance`**: `propose`, `lots`, `frontier`, `compare`, `backtest`, `run`
  and `stored`.
- **Fourteen charts** (one hundred and three in the gallery), a methodology note and ADRs
  0031 to 0035. `cvxpy` joins the dependencies.

### Changed

- The Day 6 pre-trade metric model re-computes active share for a proposed portfolio
  instead of carrying the morning's value.

### Fixed (found while building it)

- cvxpy's default rewriting of `x^1.5` stalled the interior-point solver on small
  trades. Impact is now an explicit power cone.
- Pinning a barred purchase to zero with an equality left the problem without an
  interior. Such variables are now removed instead.
- A float remnant of a sold lot, carrying a deferred wash-sale loss, reached a basis of
  hundreds of thousands per unit. Near-complete sales now relieve the whole lot.
- The first tax-alpha simulation valued harvested losses at the full short-term rate.
  It harvested three times as much and lost after-tax return. A loss is now valued at
  the short-term rate less the long-term rate it will be recaptured at.

## [0.7.0] - 2026-09-26

Day 6: compliance. The account's investment restrictions written in a small language,
checked before every order and after every close, with a register of every breach and
what caused it.

### Added

- **The mandate language.** A Lark LALR(1) grammar (`compliance/grammar.lark`) for
  investment restrictions: weights with filters, the heaviest group, concentration sums
  above a threshold, counts, "no holdings", and risk metrics; `and`/`or` filters with
  comparisons and memberships; five bound shapes; hard and soft severities; warning
  levels. Exact decimal limits, ratings compared by credit quality, errors with line
  and column. A printer that is the parser's inverse, verified by a Hypothesis property
  test over generated rules.
- **Mandates**: the account's eighteen restrictions and the UCITS diversification
  rules, shipped as `.mandate` files.
- **The rule engine** with value, status, utilisation, headroom and contributors for
  every rule, and look-through of index funds to their constituents as a clause of
  each rule.
- **Pre-trade checks**: blocked, override required, warning or allowed from the
  portfolio the order would leave; trades that reduce a breach always allowed; the
  largest permissible order by bisection; baskets checked as a whole; tracking error
  and volatility re-forecast by the Day 5 model.
- **Post-trade checks and the breach register**: active or passive by what traded since
  the previous check, deadlines (same day, or thirty days for passive breaches),
  overdue, resolved by trading or by the market, graded by severity and peak.
- **The history replayed**: the Day 3 book's 43 orders through the pre-trade check, one
  at a time and as daily baskets.
- **Liquidity** from Day 2 volumes (days to liquidate at 20% of the 20-day average).
- **Persistence**: `compliance_rules` (text and SHA-256), `compliance_results`,
  `compliance_breaches`, `pretrade_checks`, migration 0006. The run first proves each
  stored text parses back to its rule, every breach opened on a day of breach, and no
  hard breach is overdue.
- **`meridian compliance`**: `rules`, `parse`, `check`, `pretrade`, `breaches`,
  `replay`, `ucits`, `report`, `run` and `stored`.
- **Twelve charts** (eighty-nine in the gallery), two methodology notes and ADRs 0027
  to 0030. `lark` joins the dependencies.

### Fixed

- Cash payables are carried as negative amounts; an early snapshot subtracted them,
  and weights on two settlement days added up to 2.9. The snapshot now uses the ledger's
  own `total_base` and refuses weights that do not add up to one.

## [0.6.0] - 2026-09-26

Day 5: risk. A fundamental factor model estimated on a universe whose true risk is
known, applied to the demonstration account, and validated - on ten years of the
universe and on every morning's forecast for the account.

### Added

- **The estimation universe.** Five hundred synthetic stocks over ten years with GARCH
  Student-t factors and residuals, crisis regimes whose factor totals are fixed (the 2020
  crash, the 2022 bear market, a momentum crash), and every true factor return,
  exposure and conditional variance recorded. Over the demonstration window it replays
  the Day 2 market through `SyntheticMarket.factor_draws`.
- **The factor model.** Twenty-one factors - world, eleven industries, beta, size,
  value, momentum, quality, four currencies. Descriptors (Vasicek-shrunk historical
  beta, log size, log book-to-price, 12-1 momentum, return on equity) standardised to
  cap-weighted mean zero and unit spread; a daily square-root-cap WLS regression with
  cap-weighted industries constrained to sum to zero.
- **Covariance.** Sample, EWMA with separate volatility and correlation half-lives
  (42 and 200 days), Ledoit-Wolf towards the identity (matched to scikit-learn) and
  towards constant correlation, Marchenko-Pastur bounds and density, the riskless
  portfolio of a singular sample, Woodbury minimum variance. GARCH(1,1) via `arch`.
- **The model and its decomposition.** `V = X F X' + D`; Euler contributions to
  volatility and tracking error by factor, group and holding; marginal risk.
- **Coverage.** The account's stocks and the benchmark's on the universe's scale; index
  funds looked through with their basis as its own risk; the bond by time-series beta;
  cash by currency.
- **VaR and ES** parametric, Cornish-Fisher, historical and factor Monte Carlo with
  multivariate Student-t; **stress tests** from historical replays and hypothetical
  factor shocks.
- **Validation.** A forward-only rolling forecaster; bias statistics with their band,
  MRAD and a truth yardstick; Kupiec, Christoffersen and the Basel traffic light; the
  minimum-variance experiment across estimators.
- **Persistence**: `risk_factor_returns`, `risk_forecasts`, `risk_exposures` and
  migration 0005. The risk run checks its controls before writing; the backtest and
  factor volatilities are recounted in SQL on SQLite and PostgreSQL.
- **`meridian risk`**: `model`, `portfolio`, `contributions`, `var`, `stress`,
  `backtest`, `validate`, `report`, `run` and `stored`.
- **Sixteen charts** (seventy-seven in the gallery), three methodology notes and ADRs
  0023 to 0026. `scipy` and `arch` join the dependencies, `scikit-learn` the
  development tools.

### Found by the backtest

- Index funds deviate from their look-through by about 12% a year; without a basis
  line the tracking error was under-forecast (bias 1.18).
- The universe's beta factor was at first only loosely tied to the world factor, so
  the Day 2 stocks' market betas (0.57 to 1.20) could not flow through the model.
- Bayesian shrinkage of specific risk widened the spread of the stocks' own biases
  fourfold on the universe and pulled the account's tracking error a fifth too low;
  it is off by default.
- A drift cannot make a crash: with volatility four times normal, the first "2020
  crash" window ended up. Regimes now fix their factors' totals.

## [0.5.0] - 2026-09-25

Day 4: performance and attribution. What the return was, measured three ways; a
benchmark that can be taken apart; and an attribution that explains the active return
to the last basis point, with currency and costs kept apart and the days linked.

### Added

- **Returns.** Daily time-weighted returns chained from the value bridge's own
  investment result, with flows at the start of the day; money-weighted returns by
  XIRR on actual days; Modified Dietz; factsheet periods (MTD, QTD, YTD, one year,
  since inception), annualised only beyond a year; monthly and yearly tables.
- **Holding contributions.** Every day taken apart into one exposure per holding
  (opening value, local result with dividends and coupons from the ledger, currency
  result) and one per currency for cash, with costs apart. Largest daily residual on
  the demonstration: 9e-11 dollars. Linked by Cariño, the contributions sum to the
  time-weighted return.
- **The benchmark.** `SyntheticMarket.companion` generates new instruments in the same
  market, replaying its market and sector factors without changing any existing
  price. Meridian World Equity: a cap-weighted, total-return index of 36 stocks with
  drifting weights and returns split into local and currency. A policy benchmark of
  80% equity, 15% the Treasury bond (total return from dirty prices and coupons) and
  5% cash, rebalanced monthly.
- **Brinson-Fachler attribution** by sector and by region: allocation against the
  benchmark's total return, selection, interaction as the exact remainder; currency
  per currency and costs as their own effects; index funds looked through to the
  benchmark's constituents. Daily residual around 1e-17.
- **Cariño linking** of daily effects over any period, with the unlinked gap
  reported; linked monthly attribution.
- **Risk statistics**: volatility, downside deviation, Sharpe, Sortino, tracking error,
  information ratio, beta, Jensen's alpha, correlation, up and down capture, hit rate,
  historical VaR and expected shortfall, skewness and kurtosis, drawdown episodes with
  recovery dates, and rolling 63-day windows.
- **Persistence**: `performance_returns` (one row per day) and `attribution_effects`
  (linked effects per period, dimension and segment), migration 0004. The
  performance run refuses to write a period whose residual exceeds 1e-10.
- **`meridian perf`**: `run`, `returns`, `attribution`, `risk`, `contributions`,
  `factsheet` and `stored`.
- **Fifteen charts** (sixty-one in the gallery), three methodology notes and ADRs 0019
  to 0022.

### Changed

- The data model diagram now includes the two performance tables.

## [0.4.0] - 2026-09-24

Day 3: portfolio accounting. A double-entry book of record at cost, tax lots that know
their holding period and their wash sales, the same disposals under two tax codes, a
value bridge with no residual, and a reconciliation that is measured rather than
asserted.

### Added

- **The general ledger.** A chart of accounts numbered by class, journal entries with
  one sign convention (debit positive), postings in local and base currency, entries
  that must balance in base and in each local currency, and a ledger answering
  balances, activity and the trial balance by date - also computed in SQL and held
  equal to it account by account on SQLite and PostgreSQL.
- **The trade blotter.** Bookings, amendments and cancellations as versions with their
  knowledge time; the book as known at any moment is a replay. Settlement fails with
  contractual and actual dates.
- **Settlement cycles by market and date**, including the US move to T+1 on 28 May
  2024 and the announced European move in 2027, counted on the joint calendar of the
  exchange and the settlement currency.
- **The accounting engine**: purchases and sales against payables and receivables,
  currency results on settlement and conversion, commission capitalised, dividends
  with withholding split into reclaimable and lost, bond accrued interest bought and
  recovered, transfers in kind with carried cost and acquisition date, and splits,
  stock dividends, spin-offs and mergers from the corporate action feed.
- **Tax lots with tax attributes** - holding period start, opening FX rate, wash sale
  adjustment - kept apart from book cost; realised lots with the gain split exactly
  into price and currency.
- **The US wash sale rule** with its 30-day look-ahead, replacement capacity per
  purchase and deferred matches; Schedule D netting with the $3,000 limit and
  carryforward; Form 8949 rows; lot choice under four methods with a minimum-tax
  order proved optimal by a property test.
- **UK share matching**: same-day, 30-day and section 104 pool, in sterling, with tax
  years, the exempt amount and the October 2024 rate change.
- **Daily valuation** in local and base currency with a staleness limit, and a
  **value bridge** whose residual is zero on every day of the demonstration and of
  random books generated by a property test.
- **Custodian reconciliation** on settled terms, with breaks classified into eight
  causes, a break register that ages them, and a synthetic custodian that plants
  breaks to measure it: recall 100%, precision 100%, and nothing raised on clean
  statements.
- **The demonstration book**: two and a half years of a four-currency account,
  including a transfer in kind, two tax-loss harvests (one a wash sale), a failed
  settlement and a trade corrected at month-end.
- **Persistence**: six tables and migration 0003; the accounting run checks its
  controls before writing anything.
- **`meridian book`**: `run`, `positions`, `lots`, `cash`, `gains`, `lot-choice`,
  `nav`, `bridge`, `trial-balance`, `journal`, `reconcile` and `wash-sales`.
- **Sixteen charts** (forty-six in the gallery), five methodology notes and ADRs 0014
  to 0018.

### Changed

- `TaxLot` gains `holding_period_start`, `open_fx_rate` and `wash_sale_adjustment`;
  corporate action entitlements carry them through splits, spin-offs and mergers.

### Fixed

- A wash sale replacement matched to two sold lots was tacked twice. Drawing the
  Bayer wash sale showed a holding period 598 days longer than the replacement's own;
  each replacement share is now used once and tacked with its own sold shares' period.
- A split's per-share cost was rounded to 1e-10 by the entitlement rules, leaving the
  lots 7e-8 dollars away from the ledger. Found by the control that ties the
  sub-ledger to the lots; the engine now rescales exactly.

## [0.3.0] - 2026-09-22

Day 2: market data. Prices with a memory of what was known and when, quality rules
that are measured rather than asserted, corporate actions applied to both the history
and the book, and one published price built from several disagreeing sources.

### Added

- **Bitemporal market data.** Every observation carries its value date and the
  moment the platform learned it; corrections are new records, never edits, so the
  series as known at any past moment can be rebuilt and the look-ahead in a restated
  history can be measured. The same "as known at" query is implemented in memory and
  in SQL and tested case for case against each other.
- **A synthetic market** with the stylised facts a quality rule has to survive:
  Student-t innovations, GARCH(1,1) volatility clustering, market and sector factors,
  one exchange calendar per instrument, and splits and dividends that move the quoted
  price. Its economic value is kept as ground truth for the adjustment code.
- **A fault injector** that damages clean data in the nine ways real feeds fail and
  records exactly where, so the rules can be scored.
- **Thirteen quality rules** across the five DAMA dimensions, with robust (median and
  MAD) statistics on event-adjusted returns net of a leave-one-out market proxy, an
  engine that scores each series and decides what may be published, and detection
  measured at 100% recall and 97% precision over 126 planted faults.
- **Corporate actions**: dividends, splits, stock dividends, spin-offs, rights, cash
  and stock mergers and symbol changes - with CRSP-style back-adjustment as a derived
  view, and entitlement rules that conserve cost basis, tack holding periods, pay
  cash in lieu of fractional shares and tax merger boot under IRC 356/358.
- **A golden copy** built by ranked consensus with price challenges recorded, and
  **FX history** with as-of lookup, cross rates and staleness limits.
- **A security master**: identifiers mapped to instruments over validity intervals
  and resolved by date, and golden records built field by field with lineage,
  conflicts and check-digit validation.
- **The end-of-day pricing run** - collect, record, validate, reconcile, publish -
  with five new tables, migration 0002, and batch upserts.
- **`meridian market`**: `rules`, `quality`, `price --persist`, `history --known-at`,
  `actions`, `adjust` and `xref --on`.
- **Thirteen charts** (thirty in the gallery), four methodology notes and ADRs 0009
  to 0013.

### Changed

- `PriceRepository` and `FxRateRepository` gained batch upserts, and observations are
  written with one insert rather than one merge per row: the demonstration load fell
  from 24 s to 2.8 s.
- The market proxy used by the outlier rules is exposed as `attach_market_proxy`.
- The demonstration book gains one clearly labelled synthetic instrument, so the
  history contains a 4-for-1 split to adjust for.

### Fixed

- A stale source can no longer outvote the source that moved. Two vendors resending
  yesterday's close agreed with each other, formed the median and excluded the one
  vendor with the right price; the worst golden-copy error fell from 254 bp to 13 bp
  once unchanged values were set aside on days when other sources moved.
- The synthetic market's GARCH parameters now satisfy the fourth-moment condition.
  With Student-t(4) innovations it failed, and a two-year sample came out 56% more
  volatile than specified.

## [0.2.0] - 2026-09-20

Day 1, continued: the financial mathematics the rest of the platform will be built on,
and the charts that argue for it.

### Added

- **Analytics layer.** Safeguarded Newton root finding with a bisection fallback;
  yield curves bootstrapped from par yields with the round trip asserted at every
  tenor; bond pricing, accrued interest, yield to maturity, Macaulay and modified
  duration, convexity, DV01, z-spread and key rate durations.
- **Payment schedules.** Rolled backwards from maturity, with the sticky end-of-month
  rule, four stub conventions, payment lags, and adjusted or unadjusted accrual.
- **Five more calendars** - the US bond market, Xetra, SIX, Tokyo and the weekend
  base - with holiday names, and `JointCalendar` for cross-border settlement.
- **Four more day-count conventions**: ACT/ACT ICMA, BUS/252, 30E/360 ISDA and
  ACT/365.25, including the context each one needs.
- **Compounding conventions** with exact conversion between them, and three
  interpolation methods including Fritsch-Carlson monotone cubic.
- **LEI validation** by ISO 7064 MOD 97-10, identifier scheme detection, and
  expected-check-digit reporting for near misses.
- **Eleven more charts**, an entity-relationship diagram generated from the live
  SQLAlchemy metadata, and one gallery definition behind the docs, the CLI and the
  tests.
- **`meridian rates` and `meridian charts`** command groups; `calendar matrix`,
  `calendar ladder` and named holidays.
- **Two methodology notes** - fixed income mathematics and calendar conventions -
  and ADRs 0006 to 0008.

### Changed

- Chart title blocks scale with the figure, so a tall multi-panel page and a single
  wide chart look the same.
- Repository queries return `Sequence` rather than `list`: a query result is a
  snapshot, not a collection to mutate.

## [0.1.0] - 2026-09-19

The foundation: the vocabulary every later module is written in.

### Added

- **Core value objects.** `Money` on `Decimal` with banker's rounding, currency tagging
  and a remainder-conserving `allocate`; 22 currencies with correct minor units; FX rates
  with inversion and pivot cross rates.
- **Security identifiers.** ISIN, CUSIP, SEDOL and FIGI with their real check-digit
  algorithms, CUSIP-to-ISIN conversion, and tests against published identifiers.
- **Trading calendars.** NYSE, LSE and TARGET generated from statutory rules, business-day
  conventions, T+n settlement arithmetic, and ACT/360, ACT/365F, 30/360 and ACT/ACT ISDA
  day counts.
- **Domain model.** Instruments (equity, fund, bond, cash), clients, households, accounts,
  portfolios with an investment policy, transactions with fixed sign conventions, and
  positions as tax lots with FIFO, LIFO, HIFO, average-cost and specific identification.
- **Persistence.** Typed SQLAlchemy 2.0 schema with fixed-scale `NUMERIC` columns,
  explicit domain-to-row mappers, repositories returning domain objects, a unit of work,
  and Alembic migrations with a drift check.
- **Visualisation.** A house chart style, and the exchange trading calendar chart showing
  the weekdays on which markets disagree.
- **CLI.** `meridian info`, `db init|seed|status`, `calendar list|holidays|settle|chart`
  and `security validate|to-isin`, with structured logging.
- **Demonstration book.** Twelve instruments across four currencies, a taxable account and
  a pension, and eight trades spanning short and long holding periods.
- **Project infrastructure.** CI running lint, format, types, the suite on Python 3.10 to
  3.12, and integration tests against PostgreSQL 16; architecture decision records
  0001-0005.

[1.5.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v1.5.0
[1.4.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v1.4.0
[1.3.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v1.3.0
[1.2.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v1.2.0
[1.1.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v1.1.0
[1.0.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v1.0.0
[0.9.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.9.0
[0.8.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.8.0
[0.7.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.7.0
[0.6.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.6.0
[0.5.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.5.0
[0.4.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.4.0
[0.3.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.3.0
[0.2.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.2.0
[0.1.0]: https://github.com/elmarfarajov/meridian-investment-platform/releases/tag/v0.1.0
