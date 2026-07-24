"""Phase 3: popularity discount (lift/PMI) unit tests."""

from __future__ import annotations

import pytest

from ken.ranker.channels import base_rate_discount, lift_enabled


def test_lift_disabled_by_default(monkeypatch):
    monkeypatch.delenv("KEN_RANKER_LIFT", raising=False)
    assert lift_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "on", "YES"])
def test_lift_enabled_truthy(monkeypatch, val):
    monkeypatch.setenv("KEN_RANKER_LIFT", val)
    assert lift_enabled() is True


def test_discount_neutral_for_young_projects():
    # Below the session floor we have no base-rate estimate → no discount.
    assert base_rate_discount(3, {"a.py": 3}, "a.py") == 1.0


def test_ubiquitous_file_discounted_more_than_rare():
    n = 100
    df = {"ubiquitous.py": 95, "rare.py": 2}
    ubi = base_rate_discount(n, df, "ubiquitous.py")
    rare = base_rate_discount(n, df, "rare.py")
    assert ubi < rare
    assert rare > 0.85          # rare file barely discounted
    assert ubi < 0.3            # near-universal file heavily discounted
    assert 0.0 < ubi <= 1.0


def test_unseen_file_gets_full_credit():
    # A file with no snapshot history has the lowest possible base rate.
    n = 50
    assert base_rate_discount(n, {}, "never_seen.py") == pytest.approx(
        1.0 / (1.0 + 4.0 * (1.0 / 52.0))
    )
