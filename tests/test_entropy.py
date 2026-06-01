"""Unit tests for client/trackers/entropy.py."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from client.trackers.entropy import (
    entropy_metrics,
    shannon_entropy,
    total_bits,
    value_length,
)


def test_empty_value_is_zero():
    assert shannon_entropy("") == 0.0
    assert total_bits("") == 0.0
    assert value_length("") == 0


def test_uniform_characters_have_zero_entropy():
    # All identical chars -> no per-char uncertainty.
    assert shannon_entropy("aaaaaaaa") == 0.0
    # ...but total_bits is also 0 because entropy is 0.
    assert total_bits("aaaaaaaa") == 0.0


def test_functional_value_is_low_entropy():
    # Short functional values score low on total information content.
    assert total_bits("en") < 10
    assert total_bits("en_US") < 20


def test_random_uid_is_high_entropy():
    uid = "a7x9f228j991pqzm2c4b8"
    assert shannon_entropy(uid) > 3.0
    assert total_bits(uid) > 36.0


def test_functional_vs_uid_ordering():
    # A real UID must out-score a functional value on total bits.
    assert total_bits("a7x9f228j991pqzm2") > total_bits("en_US")


def test_entropy_metrics_bundle_shape():
    m = entropy_metrics("GA1.2.1234567890.1715776200")
    assert set(m) == {"entropy", "total_bits", "value_length"}
    assert m["value_length"] == len("GA1.2.1234567890.1715776200")
    # total_bits == entropy * length (within rounding).
    assert abs(m["total_bits"] - m["entropy"] * m["value_length"]) < 0.01
