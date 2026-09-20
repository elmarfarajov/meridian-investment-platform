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
