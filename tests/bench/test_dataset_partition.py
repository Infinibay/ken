import copy
import hashlib

import pytest

from tests.bench.test_retrieval import case


def test_partition_rejects_repository_or_behavior_leakage():
    from ken.bench.protocol import validate_partitions
    dev = case()
    reserve = copy.deepcopy(case(1))
    reserve["repo_commit"] = "b" * 40
    with pytest.raises(ValueError, match="repository"):
        validate_partitions([dev], [reserve])
    reserve["repo_id"] = "unrelated"
    reserve["behavior_group"] = dev["behavior_group"]
    with pytest.raises(ValueError, match="behavior"):
        validate_partitions([dev], [reserve])


def test_acceptance_cannot_certify_tiny_or_duplicate_dataset():
    from ken.bench.protocol import acceptance_failures
    assert any("300" in f for f in acceptance_failures([case()]))
    cases = [case(i) for i in range(300)]
    assert any("negative" in f for f in acceptance_failures(cases))
    assert any("duplicate query" in f for f in acceptance_failures(cases))


def test_frozen_artifact_mismatch_is_rejected_before_execution(tmp_path):
    from ken.bench.protocol import verify_files
    path = tmp_path / "engine.py"
    path.write_text("original")
    hashes = {"engine.py": hashlib.sha256(path.read_bytes()).hexdigest()}
    verify_files(tmp_path, hashes)
    path.write_text("changed")
    with pytest.raises(ValueError, match="mismatch"):
        verify_files(tmp_path, hashes)


def test_reserve_attempt_cannot_be_silently_reused(tmp_path):
    from ken.bench.protocol import claim_reserve
    registry = tmp_path / "attempts.db"
    claim_reserve(registry, dataset_sha256="a" * 64, engine_sha256="b" * 64,
                  profile_sha256="c" * 64)
    with pytest.raises(ValueError, match="consumed"):
        claim_reserve(registry, dataset_sha256="a" * 64, engine_sha256="d" * 64,
                      profile_sha256="c" * 64)
