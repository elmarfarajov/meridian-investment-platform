# 29. Breaches are active or passive, and age against a deadline

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

A limit found broken after the close can have two causes:
- a trade put the portfolio over the line;
- prices carried a compliant portfolio over it.

Regulators and clients treat the two differently. An active breach is a failure of
control and must be reversed at once. A passive breach is expected, and must be cured
in the investors' interest, not by a fire sale. A register that does not tell them apart
cannot say which breaches were somebody's fault.

## Decision

- A breach **opens** on the first day its rule is broken and **closes** on the first day
  it is not. Days on which the rule cannot be evaluated (a risk metric before the model
  has history) neither open nor close one.
- It is **active** if anything traded **since the previous check** is part of what broke
  the rule: a contributor to a weight, or the breaching group of a "max weight by" rule.
  A fund trade touches every constituent it contains. Otherwise it is **passive**.
- **Deadlines:** an active breach is due the day it opens. A passive one has 30
  calendar days, in the spirit of UCITS article 57. An open breach past its deadline is
  **overdue**.
- A breach ends **resolved by trading** (something traded touched it on the closing day)
  or **resolved by the market**. Its grade comes from severity and how far past the
  limit it went (peak utilisation above 110% is critical for a hard limit).
- The compliance run **refuses to store** the register while a hard breach is overdue:
  that is an escalation, not a data point.

## Consequences

- Replaying the book gives 37 breaches: 9 active and 28 passive. 23 were resolved by the
  market and 14 by trading. The median passive breach lasted 4.5 trading days, the
  median active one 31.
- A client deposit that lands as cash is correctly passive. The mandate's cash ceiling
  broke without a trade, and was cured by investing the cash.
- The classification is by what traded, not by intent. A trade that happens to touch a
  contributor on a day prices also moved makes the breach active. That is the
  conservative reading a compliance officer would choose.
