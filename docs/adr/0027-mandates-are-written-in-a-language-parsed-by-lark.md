# 27. Mandates are written in a small language, parsed by Lark, and stored as text

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Investment restrictions have to be:
- checked by a machine, on every order and every day;
- read by a compliance officer;
- signed off by a client;
- audited years later.

The options were:

- **Rules in code:** a Python function per restriction. Exact, but only a programmer
  can read or change it, and a code review is not a compliance sign-off.
- **Rules in configuration** (YAML or JSON with fixed keys). Readable, but every new
  kind of restriction needs a new key and new code, and nesting "sector A or (country B
  and weight above 1%)" in a configuration file is where configuration languages
  become programming languages by accident.
- **A small language:** a grammar for the restrictions mandates actually contain,
  parsed into typed rules.

## Decision

- A **mandate language** with six measures (weight, heaviest group, concentration sum,
  count, absence, risk metric), filters built from comparisons and memberships with
  `and`/`or`, five bound shapes, hard and soft severity, and warning levels.
- Parsed by **Lark** with an **LALR(1)** grammar kept in its own file
  (`grammar.lark`). Syntax errors report line, column and what was expected. Semantic
  checks (a warning before its limit, a non-empty range, groupable fields, unique
  identifiers) are part of parsing.
- Limits are **exact decimals**; comparisons at a limit use a 1e-12 tolerance.
- A **printer** that is the parser's inverse, verified by a Hypothesis property test on
  generated rules.
- Rules are **stored as text** with a SHA-256 hash. A new wording is a new version of
  the mandate, never an edit.

## Consequences

- The account's restrictions are an 18-rule file a non-programmer can read, and the
  UCITS diversification rules are four more lines in the same language.
- A result in the database can be traced to the exact words that produced it. The
  compliance run refuses to store a rule whose text would not parse back to itself.
- The language covers what these mandates need, not everything a mandate could say.
  Rules about the *process* of trading (best execution, approval chains) are out of
  scope, and a new measure means a grammar change, reviewed like any other code change.
