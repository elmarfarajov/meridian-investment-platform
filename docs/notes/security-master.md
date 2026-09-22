# The security master: identifiers that move, and vendors that disagree

Reference data errors are silent. A wrong price is visible the moment someone looks
at a valuation; a wrong identifier books a trade against the wrong company and looks
perfectly normal until somebody reconciles. This note covers the two defences
Meridian implements: identifiers resolved *by date*, and golden records built field
by field with their lineage kept.

**Implementation:** [`refdata/`](../../src/meridian/refdata) ·
**Decisions:** [ADR 0012](../adr/0012-identifiers-have-validity-intervals.md)

---

## 1. An identifier is not a name

Identifiers move. Three ways, all of them ordinary:

- **A ticker changes.** Facebook traded as `FB` until 9 June 2022 and as `META`
  after. Any file older than that date uses the old symbol.
- **A ticker is reused.** A company delists and its symbol is later reassigned to an
  unrelated company. A dateless lookup on an old trade file resolves to the new
  owner, and nothing raises.
- **An ISIN changes.** A company redomiciles or restructures, and the country prefix
  changes with it, while the ticker stays the same.

So every mapping carries a half-open validity interval `[valid_from, valid_to)` and
every lookup carries a date:

```python
reference.resolve("ticker", "FB", date(2021, 6, 1))    # -> US-META
reference.resolve("ticker", "FB", date(2023, 1, 4))    # -> None
```

![An identifier is not a name](../images/identifier-timeline.png)

Two ambiguities are refused outright when a mapping is added, because either makes an
answer impossible rather than merely wrong: one identifier pointing at two
instruments over overlapping dates, and one instrument holding two ISINs at once.
Check-digit schemes are validated on entry, so a mistyped ISIN never enters the map
at all.

---

## 2. Three vendors describe the same security three ways

Every data vendor has its own version of a security's attributes. One has the coupon
as `4.125`, another as `4.12500`; one files a defence contractor under "Aerospace &
Defense", another under "Industrials"; one has a London stock priced in GBP and
another in GBX. A *golden record* is built from them in four steps.

1. **Validate.** A value that fails its check digit cannot win, whatever its source's
   rank. An ISIN with a bad check digit is not a disagreement to be arbitrated; it is
   a broken value.
2. **Normalise.** Numbers are compared numerically, dates as dates, codes
   upper-cased, sector names mapped to one taxonomy. `4.125` and `4.12500` are the
   same value and should not be reported as a conflict.
3. **Choose by survivorship rules.** A ranking per field, not per vendor: the
   exchange for listing data, the data vendor for classification, the evaluated
   service for bond terms.
4. **Keep the disagreements.** Where sources genuinely differ, the loser is recorded
   alongside the winner.

![One security, three vendors](../images/golden-record.png)

Step 4 is the one that is usually skipped, and it is the one that earns its keep: a
disagreement between two reputable vendors about a price-sensitive field is often the
first sign that one of them has missed a corporate action. The GBP/GBX conflict in
the chart is the same pence-and-pounds trap the quality rules watch for in prices — a
security master that silently picked one would push a 100× error into every
valuation of that position.

---

## 3. Lineage, because "the system says so" is not an answer

Every field of a golden record names the source it came from. When a coupon is
questioned six months later, the answer is "vendor B, loaded on the 14th, and the
evaluated service disagreed by a day on the issue date" — not a shrug. That is what
makes the security master reviewable rather than merely authoritative.
