# 1. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-09-19

## Context

Meridian will be built over several weeks, in modules that depend on each other. The
decisions taken early - how money is represented, where the schema lives, how the domain
reaches the database - are the ones that are expensive to reverse later, and they are
exactly the ones that are invisible in the finished code. Anyone reading the repository
afterwards, including its author in three months, needs to know not only what was chosen
but what the alternatives were and why they lost.

## Decision

Architecture decisions are recorded as short numbered documents in `docs/adr`, in the
format Michael Nygard proposed: context, decision, consequences. A record is written at
the moment the decision is taken, in the same pull request as the code that implements
it. Records are immutable: a decision that is later reversed gets a new record that
supersedes the old one, and the old one stays.

## Consequences

- Pull requests carry the reasoning, not only the diff.
- A reversal is visible as a reversal rather than as a silent rewrite.
- There is a small ongoing cost: one document per significant decision.
