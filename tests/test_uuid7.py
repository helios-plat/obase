import time
import uuid

from obase import uuid7


def test_uuid7_format():
    u = uuid7()
    assert len(u) == 36
    # Should be valid UUID
    parsed = uuid.UUID(u)
    assert parsed.version == 7


def test_uuid7_chronological():
    u1 = uuid7()
    time.sleep(0.002)
    u2 = uuid7()
    assert u1 < u2


def test_uuid7_uniqueness():
    uuids = {uuid7() for _ in range(10000)}
    assert len(uuids) == 10000


def test_uuid7_timestamp():
    # Verify timestamp is roughly correct
    now_ms = int(time.time() * 1000)
    u = uuid7()
    u_bytes = uuid.UUID(u).bytes
    timestamp_ms = int.from_bytes(u_bytes[:6], "big")
    assert abs(timestamp_ms - now_ms) < 1000


def test_uuid7_multiple_in_same_ms():
    # Even in same ms, they should be unique (due to randomness)
    uuids = {uuid7() for _ in range(100)}
    assert len(uuids) == 100
