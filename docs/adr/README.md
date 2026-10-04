# Architecture decision records

Short records of the decisions that were expensive to reverse, written when they were
taken. The format is Michael Nygard's: context, decision, consequences. Records are
immutable - a reversal gets a new record that supersedes the old one.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-decimal-money-with-currency-tagging.md) | Money is a tagged `Decimal`, never a float | Accepted |
| [0003](0003-sqlite-locally-postgresql-in-ci.md) | SQLite for development, PostgreSQL in CI and production | Accepted |
| [0004](0004-rule-based-trading-calendars.md) | Trading calendars are generated from rules, not files | Accepted |
| [0005](0005-explicit-mapping-between-domain-and-database.md) | The domain model is mapped to rows explicitly | Accepted |
| [0006](0006-composable-settlement-calendars.md) | Settlement calendars are composed, not chosen | Accepted |
| [0007](0007-log-linear-interpolation-on-discount-factors.md) | Curves interpolate log-linearly on discount factors | Accepted |
| [0008](0008-decimal-in-the-ledger-float-in-the-analytics.md) | Decimal in the ledger, float in the analytics | Accepted |
| [0009](0009-bitemporal-market-data.md) | Market data is bitemporal and append-only | Accepted |
| [0010](0010-golden-copy-by-ranked-consensus.md) | The golden copy is the highest-ranked source within tolerance of the consensus | Accepted |
| [0011](0011-corporate-action-adjustment-is-a-view.md) | Corporate action adjustment is a view, never an overwrite | Accepted |
| [0012](0012-identifiers-have-validity-intervals.md) | Identifiers are mapped to instruments with validity intervals | Accepted |
| [0013](0013-quality-rules-are-measured-against-planted-faults.md) | Quality rules are measured against planted faults | Accepted |
| [0014](0014-a-double-entry-ledger-at-cost-is-the-book-of-record.md) | A double-entry ledger at cost is the book of record | Accepted |
| [0015](0015-the-book-is-a-replay-of-a-versioned-blotter.md) | The book is a replay of a versioned blotter; a correction is a replay | Accepted |
| [0016](0016-tax-basis-is-kept-apart-from-book-cost.md) | Tax basis is kept apart from book cost, on the lot | Accepted |
| [0017](0017-the-value-bridge-is-exact.md) | The value bridge is exact | Accepted |
| [0018](0018-reconciliation-is-on-the-custodians-terms-and-measured.md) | Reconciliation is on the custodian's terms, classified by cause, and measured | Accepted |
| [0019](0019-returns-are-chained-daily-from-the-value-bridge.md) | Returns are chained daily from the value bridge, with flows at the start of the day | Accepted |
| [0020](0020-brinson-fachler-on-local-returns-with-currency-and-costs-apart.md) | Brinson-Fachler on local returns, with currency and costs apart and funds looked through | Accepted |
| [0021](0021-attribution-is-linked-by-carino.md) | Multi-period attribution is linked by Cariño, and stored per period | Accepted |
| [0022](0022-a-synthetic-benchmark-from-the-same-market.md) | The benchmark is a synthetic index generated in the same market as the book | Accepted |
| [0023](0023-a-fundamental-factor-model-on-a-universe-with-known-truth.md) | A fundamental factor model, estimated on a universe whose true risk is known | Accepted |
| [0024](0024-ewma-factor-covariance-with-separate-half-lives.md) | The factor covariance is EWMA, with a shorter half-life for volatility than for correlation | Accepted |
| [0025](0025-specific-risk-by-ewma-and-fund-basis-as-its-own-risk.md) | Specific risk by EWMA without Bayesian shrinkage; a fund's basis is its own risk | Accepted |
| [0026](0026-a-risk-model-ships-with-its-validation.md) | A risk model ships with its validation, and a failed control writes nothing | Accepted |
| [0027](0027-mandates-are-written-in-a-language-parsed-by-lark.md) | Mandates are written in a small language, parsed by Lark, and stored as text | Accepted |
| [0028](0028-look-through-is-part-of-the-rule.md) | Look-through is part of the rule, not a global setting | Accepted |
| [0029](0029-breaches-are-active-or-passive-and-age-against-a-deadline.md) | Breaches are active or passive, and age against a deadline | Accepted |
| [0030](0030-pre-trade-checks-judge-the-portfolio-after-the-order-and-baskets-as-a-whole.md) | Pre-trade checks judge the portfolio after the order, and baskets as a whole | Accepted |
| [0031](0031-tax-aware-rebalancing-is-a-conic-programme.md) | Tax-aware rebalancing is a conic programme, solved by Clarabel through cvxpy | Accepted |
| [0032](0032-lots-are-decision-variables.md) | Lots are decision variables; fixed relief rules are applied after the solve | Accepted |
| [0033](0033-non-convex-rules-are-met-in-rounds.md) | Rules that are not convex are met in rounds: wash-sale repair and the convex-concave procedure | Accepted |
| [0034](0034-orders-are-rounded-by-a-mixed-integer-programme.md) | Orders are rounded to whole lots by a separate mixed-integer programme | Accepted |
| [0035](0035-tax-alpha-is-measured-on-liquidation-value-over-simulated-paths.md) | Tax alpha is measured on liquidation value, over simulated paths, against a tax-blind manager | Accepted |
| [0036](0036-orders-are-a-checked-state-machine-in-fix-states.md) | Orders are a checked state machine, in FIX states | Accepted |
| [0037](0037-execution-is-simulated-with-the-counterfactual-price-kept.md) | Execution is simulated minute by minute, with the price path without our trades kept | Accepted |
| [0038](0038-algorithms-are-schedules-and-is-follows-almgren-chriss.md) | Algorithms are schedules; IS follows Almgren-Chriss with impact matched to the square-root law | Accepted |
| [0039](0039-block-orders-are-allocated-at-one-price-pro-rata.md) | Block orders are allocated at one average price, pro rata, by a rule fixed before trading | Accepted |
| [0040](0040-the-client-report-is-assembled-from-the-modules-own-objects.md) | Cost is implementation shortfall; the client report is assembled from the modules' own objects | Accepted |
| [0041](0041-the-api-serves-the-modules-it-does-not-compute.md) | The API serves the modules; it does not compute | Accepted |
| [0042](0042-permissions-entitlements-and-separation-of-duties.md) | Access is permissions and entitlements, with separation of duties built into the matrix | Accepted |
| [0043](0043-the-audit-log-is-a-hash-chain.md) | The audit log is a hash chain, verified by the readiness probe | Accepted |
| [0044](0044-writes-are-idempotent-and-orders-need-four-eyes.md) | Writes are idempotent by key; orders are checked pre-trade and need four eyes above a threshold | Accepted |
| [0045](0045-one-command-deployment-with-its-own-observability.md) | One-command deployment, with its own observability, tested in CI | Accepted |
| [0046](0046-the-rates-engine-is-reconciled-against-quantlib.md) | The rates engine is reconciled against QuantLib, and every break is explained | Accepted |
| [0047](0047-curves-are-built-from-dated-instruments-with-monotone-convex-forwards.md) | Curves are built from dated instruments, with monotone convex forwards and an iterative bootstrap | Accepted |
| [0048](0048-calendars-carry-history-and-a-scheduled-view.md) | Calendars carry history, and a simulation steps through the scheduled view | Accepted |
| [0049](0049-real-rates-history-is-packaged-and-reproducible.md) | Real rates history is packaged, public domain, and rebuilt by a script | Accepted |
| [0050](0050-parametric-curves-are-fitted-to-par-yields-and-checked-against-the-fed.md) | Parametric curves are fitted to par yields and checked against the Federal Reserve's | Accepted |
| [0051](0051-prices-carry-a-quotation-unit.md) | Prices carry a quotation unit, and cash is restated in it before it meets a price | Accepted |
| [0052](0052-statistics-respect-the-resolution-of-the-data.md) | Quality statistics respect the resolution of the data | Accepted |
| [0053](0053-currency-regimes-and-lifecycles-are-reference-data.md) | Currency regimes and lifecycles are reference data, and statistics stand aside under management | Accepted |
| [0054](0054-findings-on-documented-events-are-explained-not-suppressed.md) | Findings on documented market events are explained, not suppressed | Accepted |
| [0055](0055-a-golden-copy-compares-sources-only-at-the-same-moment.md) | A golden copy compares sources only at the same moment | Accepted |
| [0056](0056-published-examples-are-the-acceptance-test-for-tax-rules.md) | The tax authorities' published examples are the acceptance test for tax rules | Accepted |
| [0057](0057-uk-matching-follows-s105-and-s127.md) | UK matching treats one day as one transaction, and rights as part of the holding | Accepted |
| [0058](0058-the-book-is-property-tested.md) | The book of record is property-tested | Accepted |
| [0059](0059-treasuries-accrue-actual-actual.md) | The demonstration Treasury accrues actual/actual (ICMA) | Accepted |
