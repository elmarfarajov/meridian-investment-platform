"""Passwords, tokens, the role matrix, and the audit chain, without the web layer."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import jwt
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meridian.api.security import (
    PERMISSIONS,
    ROLES,
    Principal,
    hash_password,
    issue_token,
    permission_matrix,
    read_token,
    roles_from,
    verify_password,
)
from meridian.core import ValidationError
from meridian.core.audit_chain import GENESIS, AuditRecord, chain, verify

SECRET = "a-test-secret-that-is-long-enough-for-hs256"


def entry(path: str = "/v1/portfolios", status: int = 200) -> AuditRecord:
    return AuditRecord(
        0, datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc), "r", "analyst", "GET", path, status, 1.5, None, None, ""
    )


def test_passwords_are_salted_and_verified_in_constant_time():
    first, second = hash_password("correct horse", iterations=1000), hash_password("correct horse", iterations=1000)
    assert first != second  # a fresh salt each time
    assert first.startswith("pbkdf2_sha256$1000$")
    assert verify_password("correct horse", first) and not verify_password("wrong horse", first)
    assert not verify_password("anything", "md5$garbage")
    with pytest.raises(ValidationError):
        hash_password("short")


def test_tokens_round_trip_and_reject_tampering():
    principal = Principal("aliyeva", frozenset({"client"}), frozenset({"PF-GLOBAL-EQ"}))
    token, seconds = issue_token(principal, SECRET, 30)
    assert seconds == 1800
    assert read_token(token, SECRET) == principal
    header, payload, signature = token.split(".")
    with pytest.raises(jwt.InvalidTokenError):
        read_token(f"{header}.{payload}.{signature[:-2]}xx", SECRET)
    with pytest.raises(jwt.InvalidTokenError):
        read_token(token, "another-secret-that-is-long-enough-too")


def test_the_role_matrix_separates_duties():
    assert "orders:approve" not in ROLES["trader"] and "orders:approve" not in ROLES["portfolio_manager"]
    assert "orders:create" not in ROLES["compliance_officer"]
    assert ROLES["administrator"] == frozenset({"users:manage", "audit:read"})
    assert all(ROLES[role] <= set(PERMISSIONS) for role in ROLES)
    matrix = permission_matrix()
    assert len(matrix) == len(ROLES) and all(len(row) == len(PERMISSIONS) for _, row in matrix)
    with pytest.raises(ValidationError):
        roles_from("analyst, wizard")
    staff = Principal("pm", frozenset({"portfolio_manager"}))
    assert staff.sees("anything") and staff.can("rebalance:propose") and not staff.can("audit:read")


def test_a_chain_verifies_and_every_kind_of_tampering_is_found():
    records = chain([entry(f"/v1/{number}") for number in range(6)])
    assert records[0].previous_hash == GENESIS
    assert verify(records).valid and verify(records).records == 6
    edited = [*records[:2], replace(records[2], status=500), *records[3:]]
    assert verify(edited).first_broken == 3 and "hash" in (verify(edited).reason or "")
    deleted = records[:2] + records[3:]
    assert verify(deleted).first_broken == 4 and "jumps" in (verify(deleted).reason or "")
    resealed = [*records[:2], replace(records[2], status=500).sealed(), *records[3:]]
    assert verify(resealed).first_broken == 4  # re-hashing one record breaks the next link


@settings(max_examples=40, deadline=None)
@given(st.integers(min_value=0, max_value=9), st.sampled_from(["status", "path", "username", "latency_ms"]))
def test_any_single_field_edit_anywhere_breaks_the_chain(position, name):
    records = chain([entry(f"/v1/{number}") for number in range(10)])
    value = {"status": 599, "path": "/forged", "username": "intruder", "latency_ms": 99.0}[name]
    tampered = list(records)
    tampered[position] = replace(records[position], **{name: value})
    check = verify(tampered)
    assert not check.valid and check.first_broken == position + 1


def test_the_hash_survives_a_database_round_trip_of_the_timestamp():
    aware = entry().sealed()
    naive = replace(aware, recorded_at=aware.recorded_at.replace(tzinfo=None))
    assert naive.computed_hash() == aware.record_hash
