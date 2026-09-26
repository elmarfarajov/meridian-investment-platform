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
