"""Original-only contracts; synthetic declarations cannot certify inference."""
from collections import Counter
from copy import deepcopy
import hashlib
import gzip
import json

import pytest

from tools.rust_migration.fastembed_catalog import build_catalogue, describe_catalogue
from tools.rust_migration.fastembed_reference import (
    dimension_corrections,
    fastembed_cases,
    native_request,
)


def test_raw_chunk_authenticates_before_bounded_decompression(tmp_path):
    from tools.rust_migration.fastembed_reference import read_chunk, write_chunk

    original = {"vectors_f32le_hex": "0000803f00000040", "stderr": "complete warning\n"}
    receipt = write_chunk(tmp_path, "model", original)
    assert read_chunk(tmp_path, receipt) == original
    path = tmp_path / receipt["path"]
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ValueError, match="compressed"):
        read_chunk(tmp_path, receipt)
    bomb = gzip.compress(b" " * (16 * 1024 * 1024 + 1), mtime=0)
    path.write_bytes(bomb)
    receipt.update(bytes=len(bomb), sha256=hashlib.sha256(bomb).hexdigest())
    with pytest.raises(ValueError, match="bound"):
        read_chunk(tmp_path, receipt)


def test_raw_chunk_rejects_resealed_false_raw_hash_and_trailing_stream(tmp_path):
    from tools.rust_migration.fastembed_reference import read_chunk, write_chunk

    receipt = write_chunk(tmp_path, "model", {"real": True})
    bad = dict(receipt, raw_sha256="0" * 64)
    with pytest.raises(ValueError, match="raw"):
        read_chunk(tmp_path, bad)
    path = tmp_path / receipt["path"]
    payload = path.read_bytes() + gzip.compress(json.dumps({"extra": True}).encode())
    path.write_bytes(payload)
    receipt.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    with pytest.raises(ValueError, match="trailing"):
        read_chunk(tmp_path, receipt)


def test_tokenizer_boundaries_include_special_token_overhead():
    from tokenizers import Tokenizer, models, pre_tokenizers, processors
    from tools.rust_migration.fastembed_reference import tokenizer_boundaries

    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "[CLS]": 1, "[SEP]": 2, "a": 3}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 1), ("[SEP]", 2)])
    tokenizer.enable_truncation(max_length=4)
    cases = tokenizer_boundaries(tokenizer, 4)
    unbounded = Tokenizer.from_str(tokenizer.to_str())
    unbounded.no_truncation()
    assert [len(unbounded.encode(case["text"]).ids) for case in cases] == [3, 4, 5]
    assert [len(tokenizer.encode(case["text"]).ids) for case in cases] == [3, 4, 4]


def declarations(descriptions):
    snapshots = {}
    digest = hashlib.sha256(b"abc").hexdigest()
    for row in descriptions:
        repo = row["sources"]["hf"]
        snapshot = snapshots.setdefault(repo, {"revision": "1" * 40, "artifacts": {}})
        for name in [row["model_file"], *row["additional_files"],
                     "tokenizer.json", "tokenizer_config.json", "config.json",
                     "special_tokens_map.json"]:
            snapshot["artifacts"][name] = {"bytes": 3, "sha256": digest}
    return snapshots


def test_catalog_captures_all_original_families_and_revisions():
    rows = describe_catalogue()
    assert len(rows) == len({r["model"].lower() for r in rows}) == 30
    assert Counter(r["implementation"] for r in rows) == {
        "OnnxTextEmbedding": 13, "CLIPOnnxEmbedding": 1,
        "PooledNormalizedEmbedding": 9, "PooledEmbedding": 6,
        "JinaEmbeddingV3": 1,
    }
    catalogue = build_catalogue(rows, declarations(rows))
    assert catalogue["format"] == "ken-fastembed-catalog/1"
    assert [r["name"] for r in catalogue["models"]] == [r["model"] for r in rows]
    for model in catalogue["models"]:
        assert model["format"] == "ken-fastembed-model/1"
        assert model["assets"]["revision"] == "1" * 40
        assert model["graph"] in model["assets"]["artifacts"]
        assert model["dimension"] > 0
    jina = next(r for r in catalogue["models"] if r["name"] == "jinaai/jina-embeddings-v3")
    assert (jina["pooling"], jina["task_id"]) == ("mean_l2", 1)


def test_catalog_rejects_missing_artifacts_or_mutable_revisions():
    rows = describe_catalogue()
    snapshots = declarations(rows)
    repo = rows[0]["sources"]["hf"]
    snapshots[repo]["revision"] = "main"
    with pytest.raises(ValueError):
        build_catalogue(rows, snapshots)
    snapshots = declarations(rows)
    del snapshots[repo]["artifacts"][rows[0]["model_file"]]
    with pytest.raises(ValueError):
        build_catalogue(rows, snapshots)


def test_shared_repository_keeps_both_model_graphs():
    from tools.rust_migration.fastembed_reference import catalogue_snapshots

    rows = describe_catalogue()
    catalogue = build_catalogue(rows, declarations(rows))
    snapshots = catalogue_snapshots(catalogue)
    assets = snapshots["nomic-ai/nomic-embed-text-v1.5"]["artifacts"]
    assert "onnx/model.onnx" in assets
    assert "onnx/model_quantized.onnx" in assets
    assert build_catalogue(rows, snapshots) == catalogue


def test_original_cases_have_no_native_expected_payload():
    names = [row["model"] for row in describe_catalogue()]
    cases = fastembed_cases(names)
    assert len(cases) == len({c["id"] for c in cases}) == 300
    for case in cases:
        request = native_request(case)
        assert set(request) == {"id", "operation", "side", "texts"}
        assert request["operation"] == "embed"
        assert request["side"] in {"query", "passage"}
    bad = deepcopy(cases[0])
    bad["input"]["native_expected"] = {"vectors": [[1.0]]}
    with pytest.raises(ValueError):
        native_request(bad)


def test_batch257_exposes_chunk_before_padding():
    cases = fastembed_cases(["test/model"])
    row = next(c for c in cases if c["id"].endswith(":batch257"))
    assert len(row["input"]["texts"]) == 257
    assert row["input"]["texts"][:256] == ["a"] * 256
    assert row["input"]["texts"][-1] == "alpha " * 513
    assert cases[0]["input"]["texts"] == cases[-1]["input"]["texts"] == []


def test_dimension_correction_is_narrow_and_vector_preserving():
    assert dimension_corrections(384, [1, 384], 384) == []
    assert dimension_corrections(384, [1, 512], 512) == ["reported_dimension"]
    assert dimension_corrections(384, [1, 1024], 1024) == ["reported_dimension"]
    for reported, shape, expected in [(42, [1, 512], 512), (384, [1, 513], 512),
                                      (True, [1, 384], 384), (384, [1, True], 384)]:
        with pytest.raises(ValueError):
            dimension_corrections(reported, shape, expected)


def original_record():
    return {"model": "test/model", "frozen_import": True,
            "cold_modules": {"fastembed": False, "onnxruntime": False},
            "implementation": "CLIPOnnxEmbedding", "notices": [],
            "sessions": [{"intra_op_num_threads": 0, "inter_op_num_threads": 0,
                          "optimization": "GraphOptimizationLevel.ORT_ENABLE_ALL",
                          "configured_providers": ["CPUExecutionProvider"],
                          "actual_providers": ["CPUExecutionProvider"]}],
            "results": [{"id": "test/model:one", "shape": [1, 2],
                         "vectors_f32le_hex": "0000803f00000040",
                         "before": {"model_loaded": False, "device": "unknown", "dim": 384},
                         "state": {"model_loaded": True, "device": "cpu", "dim": 384},
                         "batches": [{"inputs": {"input_ids": {"dtype": "int64", "shape": [1, 2], "values": [3, 4]}},
                                      "outputs": [{"dtype": "float32", "shape": [1, 2]}]}]}]}


@pytest.mark.parametrize("changed", ["provider", "state", "tokens", "dtype", "nonfinite", "advisory"])
def test_original_record_rejects_false_provider_state_or_missing_tokens(changed):
    from tools.rust_migration.fastembed_reference import validate_model_record

    definition = {"name": "test/model", "dimension": 2, "advisories": []}
    cases = [{"id": "test/model:one", "input": {"side": "passage", "texts": ["a"]}}]
    validate_model_record(original_record(), definition, cases)
    row = original_record()
    if changed == "provider":
        row["sessions"][0]["actual_providers"] = ["CUDAExecutionProvider"]
    elif changed == "state":
        row["results"][0]["state"]["model_loaded"] = False
    elif changed == "tokens":
        row["results"][0]["batches"][0]["inputs"]["input_ids"]["values"] = []
    elif changed == "dtype":
        row["results"][0]["batches"][0]["inputs"]["input_ids"]["dtype"] = "float32"
    elif changed == "nonfinite":
        row["results"][0]["vectors_f32le_hex"] = "0000807f00000040"
    else:
        row["notices"] = [{"message": "unregistered warning"}]
    with pytest.raises(ValueError):
        validate_model_record(row, definition, cases)


def failed_original_fixture():
    definition = {"name": "jinaai/jina-embeddings-v2-base-de", "graph": "onnx/model_fp16.onnx",
                  "assets": {"model_id": "jinaai/jina-embeddings-v2-base-de",
                             "revision": "3f9eede875721714945b6a99a3198299243cf2be",
                             "artifacts": {"onnx/model_fp16.onnx": {
                                 "sha256": "e039ce538df36cb7ecee6bb88aacf0699227277be769a8e9adb5da719d23c571"}}}}
    error = {"exception": "onnxruntime.capi.onnxruntime_pybind11_state.Fail",
             "message": "[ONNXRuntimeError] : 1 : FAIL : Exception during initialization: GetIndexFromName "
                        "Attempting to get index by a name which does not exist:"
                        "InsertedPrecisionFreeCast_/encoder/layer.11/attention/output/LayerNorm/Constant_output_0"
                        "for node: /embeddings/LayerNorm/Mul/SimplifiedLayerNormFusion/"}
    return definition, error


def test_original_failure_allowance_is_bound_to_actual_graph_and_runtime_error():
    from tools.rust_migration.fastembed_reference import known_original_failure

    definition, error = failed_original_fixture()
    assert known_original_failure(definition, error, "Darwin")
    assert known_original_failure(definition, error, "Linux")
    for changed in ("name", "revision", "sha256", "message", "exception", "platform"):
        bad, failure, system = deepcopy(definition), dict(error), "Darwin"
        if changed == "name":
            bad["name"] = "jinaai/jina-embeddings-v2-base-en"
        elif changed == "revision":
            bad["assets"]["revision"] = "1" * 40
        elif changed == "sha256":
            bad["assets"]["artifacts"]["onnx/model_fp16.onnx"]["sha256"] = "0" * 64
        elif changed in {"message", "exception"}:
            failure[changed] = "some other failure"
        else:
            system = "Windows"
        assert not known_original_failure(bad, failure, system)


def test_failed_original_requires_matching_failed_session_evidence():
    from tools.rust_migration.fastembed_reference import validate_model_record

    definition, error = failed_original_fixture()
    definition.update(dimension=768, advisories=[])
    record = original_record()
    record.update(model=definition["name"], platform="Darwin", implementation="PooledNormalizedEmbedding")
    state = {"model_loaded": False, "device": "unknown", "dim": 384}
    record["results"] = [{"id": "failed", "before": state, "state": dict(state), "error": error, "batches": []}]
    record["sessions"][0].update(actual_providers=[], error=dict(error))
    cases = [{"id": "failed", "input": {"side": "passage", "texts": ["a"]}}]
    validate_model_record(record, definition, cases)
    del record["sessions"][0]["error"]
    with pytest.raises(ValueError, match="attempt"):
        validate_model_record(record, definition, cases)
