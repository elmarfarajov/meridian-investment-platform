"""A tamper-evident audit trail: every request, chained to the one before by a SHA-256 hash.

A regulator's first question about an audit log is whether it could have been
edited. A log in an ordinary table can be: a row updated, a row deleted, and
nothing shows. Here every record carries two hashes:

    record_hash = SHA-256(previous_hash ‖ canonical JSON of the record's fields)

so each record commits to everything before it. Changing any field of any
record changes its hash, which no longer matches the ``previous_hash`` stored
in the next record; deleting a record leaves a gap in the sequence and a
broken link; appending a forged record needs the hash of the true last one.
:func:`verify` walks the chain and reports the first record that fails.

This is the construction of certificate-transparency logs and of the
write-once audit trails that SEC Rule 17a-4 and MiFID II record-keeping expect,
without the external anchoring (publishing the head hash elsewhere) that
would also defeat an attacker who rewrites the whole table - that is noted as
the next step, not claimed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

GENESIS = "0" * 64


def utc_naive(moment: datetime) -> datetime:
    """A timestamp as UTC without its zone: what every database gives back, so the hash survives the round trip."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


@dataclass(frozen=True)
class AuditRecord:
    sequence: int
    recorded_at: datetime
    request_id: str
    username: str | None
    method: str
    path: str
    status: int
    latency_ms: float
    idempotency_key: str | None
    detail: str | None
    previous_hash: str
    record_hash: str = ""

    def payload(self) -> str:
        """The canonical text the hash covers: every field but the hash itself, in a fixed order."""
        fields = asdict(self)
        fields.pop("record_hash")
        fields["recorded_at"] = utc_naive(self.recorded_at).isoformat()
        fields["latency_ms"] = round(self.latency_ms, 3)
        return json.dumps(fields, sort_keys=True, separators=(",", ":"))

    def computed_hash(self) -> str:
        return hashlib.sha256((self.previous_hash + self.payload()).encode("utf-8")).hexdigest()

    def sealed(self) -> AuditRecord:
        from dataclasses import replace

        return replace(self, record_hash=self.computed_hash())


@dataclass(frozen=True)
class ChainCheck:
    records: int
    valid: bool
    first_broken: int | None = None
    reason: str | None = None


def verify(records: Iterable[AuditRecord]) -> ChainCheck:
    """Walk the chain from the first record: sequence unbroken, every link and every hash intact."""
    previous_hash = GENESIS
    expected = 1
    count = 0
    for record in records:
        count += 1
        if record.sequence != expected:
            return ChainCheck(count, False, record.sequence, f"sequence jumps from {expected - 1} to {record.sequence}")
        if record.previous_hash != previous_hash:
            return ChainCheck(count, False, record.sequence, "does not link to the record before it")
        if record.computed_hash() != record.record_hash:
            return ChainCheck(count, False, record.sequence, "its contents do not match its hash")
        previous_hash = record.record_hash
        expected += 1
    return ChainCheck(count, True)


def chain(entries: Sequence[AuditRecord]) -> list[AuditRecord]:
    """Seal a list of records into a chain, as the log does one at a time (for tests and demonstrations)."""
    output = []
    previous_hash = GENESIS
    for number, entry in enumerate(entries, start=1):
        from dataclasses import replace

        sealed = replace(entry, sequence=number, previous_hash=previous_hash).sealed()
        output.append(sealed)
        previous_hash = sealed.record_hash
    return output
