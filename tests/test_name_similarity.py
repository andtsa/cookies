"""Unit tests for client/trackers/name_similarity.py."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from client.trackers.name_similarity import cluster_names, normalize_name


def test_normalize_strips_ua_suffix():
    assert normalize_name("_gat_UA-12345-6") == "_gat"
    assert normalize_name("_gat_gtag_UA_12345_6") in ("_gat_gtag", "_gat")


def test_normalize_strips_trailing_digits_and_hex():
    assert normalize_name("ar_debug.12345") == "ar_debug"
    assert normalize_name("sessid_9f8e7d") == "sessid"


def test_normalize_keeps_plain_names():
    assert normalize_name("_ga") == "_ga"
    assert normalize_name("sessionid") == "sessionid"


def test_ga_variants_cluster_together():
    names = ["_ga", "_gat", "_gat_UA-12345-6", "_gat_UA-99999-1"]
    families = cluster_names(names)
    # All the _gat* variants should share one family label.
    gat_family = {families[n] for n in names if n.startswith("_gat")}
    assert len(gat_family) == 1


def test_unrelated_names_stay_separate():
    families = cluster_names(["_ga", "sessionid", "consent"])
    assert len({families["_ga"], families["sessionid"], families["consent"]}) == 3


def test_label_is_shortest_member():
    families = cluster_names(["_gat_UA-12345-6", "_gat", "_gat_UA-1-1"])
    # Shortest normalized-prefix member is "_gat".
    assert families["_gat_UA-12345-6"] == "_gat"


def test_disabling_edit_distance_uses_prefix_only():
    # With distance 0, only exact normalized-prefix matches group.
    families = cluster_names(["_gtag", "_gat"], max_edit_distance=0)
    assert families["_gtag"] != families["_gat"]
