"""Original input corpus and independently checked compatibility corrections."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess
import tempfile
import time
import zlib

from .reference import Reference, reference_env, verify_reference

RAW_LIMIT = 16 * 1024 * 1024


def known_original_failure(definition: dict, error: dict, system: str) -> bool:
    """One observed upstream CPU failure; never a general missing-vector waiver."""
    assets = definition.get("assets", {})
    return (system in {"Darwin", "Linux"}
            and definition.get("name") == "jinaai/jina-embeddings-v2-base-de"
            and definition.get("graph") == "onnx/model_fp16.onnx"
            and assets.get("model_id") == "jinaai/jina-embeddings-v2-base-de"
            and assets.get("revision") == "3f9eede875721714945b6a99a3198299243cf2be"
            and assets.get("artifacts", {}).get("onnx/model_fp16.onnx", {}).get("sha256")
            == "e039ce538df36cb7ecee6bb88aacf0699227277be769a8e9adb5da719d23c571"
            and error.get("exception") == "onnxruntime.capi.onnxruntime_pybind11_state.Fail"
            and all(marker in error.get("message", "") for marker in (
                "[ONNXRuntimeError] : 1 : FAIL : Exception during initialization:",
                "GetIndexFromName", "Attempting to get index by a name which does not exist:",
                "InsertedPrecisionFreeCast_/encoder/layer.11/attention/output/LayerNorm/Constant_output_0",
                "for node: /embeddings/LayerNorm/Mul/SimplifiedLayerNormFusion/")))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def write_chunk(directory: Path, name: str, record: dict) -> dict:
    raw = _json_bytes(record)
    if len(raw) > RAW_LIMIT:
        raise ValueError("raw record exceeds bound")
    payload = gzip.compress(raw, mtime=0)
    path = name + ".json.gz"
    (directory / path).write_bytes(payload)
    return {"path": path, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "raw_bytes": len(raw), "raw_sha256": hashlib.sha256(raw).hexdigest()}


def read_chunk(directory: Path, receipt: dict) -> dict:
    name = receipt["path"]
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("invalid compressed chunk path")
    path = directory / name
    if path.stat().st_size != receipt["bytes"] or path.stat().st_size > RAW_LIMIT + 1024 * 1024:
        raise ValueError("compressed chunk size mismatch")
    payload = path.read_bytes()
    if len(payload) != receipt["bytes"] or hashlib.sha256(payload).hexdigest() != receipt["sha256"]:
        raise ValueError("compressed chunk authentication failed")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        raw = decoder.decompress(payload, RAW_LIMIT + 1)
    except zlib.error as error:
        raise ValueError("invalid compressed chunk") from error
    if len(raw) > RAW_LIMIT or decoder.unconsumed_tail:
        raise ValueError("decompressed chunk exceeds bound")
    if not decoder.eof or decoder.unused_data:
        raise ValueError("truncated or trailing compressed stream")
    if len(raw) != receipt["raw_bytes"] or hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]:
        raise ValueError("raw chunk authentication failed")
    return json.loads(raw)


def installed_provenance() -> dict:
    distribution = importlib.metadata.distribution("fastembed")
    files = {}
    for entry in distribution.files or []:
        if str(entry).startswith("fastembed/") and str(entry).endswith(".py"):
            path = Path(distribution.locate_file(entry))
            files[str(entry)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ValueError("complete installed FastEmbed source unavailable")
    versions = {name: importlib.metadata.version(name)
                for name in ("fastembed", "numpy", "onnxruntime", "tokenizers")}
    if versions != {"fastembed": "0.8.0", "numpy": "2.4.4", "onnxruntime": "1.25.1", "tokenizers": "0.22.2"}:
        raise ValueError(f"original package versions drifted: {versions}")
    if platform.python_version() != "3.12.9":
        raise ValueError("original Python3.12.9 required")
    return {"python": platform.python_version(), "versions": versions, "fastembed_sources": files}


def source_state(sources: Path, definition: dict) -> dict:
    assets = definition["assets"]
    snapshot = sources / assets["model_id"].replace("/", "--") / assets["revision"]
    actual = {}
    for name, expected in assets["artifacts"].items():
        path = snapshot / name
        if not path.is_file() or path.stat().st_size != expected["bytes"]:
            raise ValueError(f"source size mismatch: {path}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected["sha256"]:
            raise ValueError(f"source hash mismatch: {path}")
        actual[name] = {"bytes": path.stat().st_size, "sha256": digest}
    return {"snapshot": str(snapshot), "artifacts": actual}


def catalogue_snapshots(catalogue: dict) -> dict:
    snapshots = {}
    for model in catalogue["models"]:
        assets = model["assets"]
        snapshot = snapshots.setdefault(assets["model_id"], {"revision": assets["revision"], "artifacts": {}})
        if snapshot["revision"] != assets["revision"]:
            raise ValueError("shared repository has inconsistent revisions")
        for name, record in assets["artifacts"].items():
            if name in snapshot["artifacts"] and snapshot["artifacts"][name] != record:
                raise ValueError("shared repository has inconsistent artifact declarations")
            snapshot["artifacts"][name] = record
    return snapshots


def tokenizer_boundaries(tokenizer, context: int) -> list[dict]:
    from tokenizers import Tokenizer

    unbounded = Tokenizer.from_str(tokenizer.to_str())
    unbounded.no_truncation()
    unbounded.no_padding()
    for word in ("a ", "alpha ", "the ", "x "):
        overhead = len(unbounded.encode(word).ids) - 1
        if len(unbounded.encode(word * 2).ids) != overhead + 2:
            continue
        rows = [{"id": f"context{target}", "text": word * (target - overhead),
                 "untruncated_tokens": target} for target in (context - 1, context, context + 1)]
        if all(len(unbounded.encode(row["text"]).ids) == row["untruncated_tokens"] for row in rows):
            return rows
    raise ValueError("could not construct exact tokenizer boundaries")


def capture_tokenizers(sources: Path, catalogue: dict, out: Path) -> dict:
    from fastembed.common.preprocessor_utils import load_tokenizer

    rows = []
    for repo, assets in catalogue_snapshots(catalogue).items():
        snapshot = sources / repo.replace("/", "--") / assets["revision"]
        tokenizer, special = load_tokenizer(snapshot)
        context = tokenizer.truncation["max_length"]
        cases = tokenizer_boundaries(tokenizer, context)
        cases.append({"id": "mixed-and-literals", "texts": ["", " ", "café", "cafe\u0301", "🦀 日本語",
                                                              "[PAD] [UNK] [CLS] [SEP] <s> </s> <mask>"]})
        observations = []
        for case in cases:
            texts = case.get("texts", [case.get("text", "")])
            encodings = tokenizer.encode_batch(texts)
            observations.append({**case, "texts": texts,
                                 "encodings": [{"ids": e.ids, "attention_mask": e.attention_mask,
                                                "type_ids": e.type_ids, "special_tokens_mask": e.special_tokens_mask}
                                               for e in encodings]})
        record = {"repo": repo, "revision": assets["revision"], "context": context,
                  "truncation": tokenizer.truncation, "padding": tokenizer.padding,
                  "special_token_ids": special, "cases": observations}
        receipt = write_chunk(out, "tokens-" + repo.replace("/", "--"), record)
        rows.append({"repo": repo, "record": receipt})
    if len(rows) != 29:
        raise ValueError("all29 original tokenizer revisions required")
    return {"format": "ken-fastembed-original-tokens/1", "repositories": rows}


def capture_fastembed(reference: Reference, sources: Path, registry: Path, out: Path) -> dict:
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError("frozen original drift before capture")
    provenance = installed_provenance()
    tooling = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
               for name in ("fastembed_catalog.py", "fastembed_reference.py", "fastembed_reference_child.py")}
    catalogue = json.loads(registry.read_bytes())
    from .fastembed_catalog import build_catalogue, describe_catalogue
    descriptions = describe_catalogue()
    snapshots = catalogue_snapshots(catalogue)
    if build_catalogue(descriptions, snapshots) != catalogue or len(descriptions) != 30:
        raise ValueError("complete actual original catalogue required")
    cases = fastembed_cases([row["model"] for row in descriptions])
    sources = sources.absolute()
    out.mkdir(parents=True, exist_ok=False)
    (out / "cases.json").write_bytes(_json_bytes(cases))
    script = Path(__file__).with_name("fastembed_reference_child.py").read_text()
    rows = []
    for index, definition in enumerate(catalogue["models"]):
        before = source_state(sources, definition)
        model_cases = [c for c in cases if c["model"] == definition["name"]]
        started = time.monotonic_ns()
        with tempfile.TemporaryDirectory(prefix="ken-fastembed-original-") as directory:
            env = reference_env(reference, Path(directory))
            env.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
            child = subprocess.run([str(reference.python), "-c", script], cwd=directory, env=env,
                                   input=json.dumps({"reference": str(reference.root),
                                                     "definition": definition, "source": before,
                                                     "cases": model_cases}),
                                   capture_output=True, text=True, timeout=1800)
        stem = f"{index:02d}"
        (out / f"{stem}.stdout.log").write_text(child.stdout)
        (out / f"{stem}.stderr.log").write_text(child.stderr)
        if child.returncode:
            raise ValueError(f"original capture failed for {definition['name']}: {child.stderr}")
        result = json.loads(child.stdout)
        if result["provenance"] != provenance:
            raise ValueError("child original package provenance differs from parent")
        validate_model_record(result, definition, model_cases)
        if source_state(sources, definition) != before:
            raise ValueError("model source drift during original capture")
        corrections = sorted({correction for row in result["results"] if "error" not in row and row["shape"][0] > 0
                              for correction in dimension_corrections(row["state"]["dim"], row["shape"], definition["dimension"])})
        receipt = write_chunk(out, stem, {**result, "stderr": child.stderr, "corrections": corrections,
                                         "source": before, "process_wall_ns": time.monotonic_ns() - started})
        rows.append({"model": definition["name"], "record": receipt})
        (out / "partial-index.json").write_bytes(_json_bytes(rows))
        print(json.dumps({"captured": len(rows), "model": definition["name"]}), flush=True)
    if provenance != installed_provenance() or verify_reference(reference.root, reference.manifest_path):
        raise ValueError("original sources drifted during capture")
    if tooling != {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in tooling}:
        raise ValueError("capture tooling changed during capture")
    tokenizers = capture_tokenizers(sources, catalogue, out)
    result = {"format": "ken-fastembed-original/1", "platform": platform.system(),
              "architecture": platform.machine(), "provenance": provenance,
              "reference_fingerprint": reference.fingerprint, "tooling": tooling,
              "registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
              "cases_sha256": hashlib.sha256((out / "cases.json").read_bytes()).hexdigest(),
              "models": rows, "tokenizers": tokenizers, "cases": len(cases), "native_acceptance": False}
    (out / "index.json").write_bytes(_json_bytes(result))
    return result


def validate_model_record(record: dict, definition: dict, cases: list[dict]) -> None:
    if (record["model"] != definition["name"] or not record["frozen_import"]
            or record["cold_modules"] != {"fastembed": False, "onnxruntime": False}
            or record["implementation"] not in {"OnnxTextEmbedding", "CLIPOnnxEmbedding",
                                                "PooledNormalizedEmbedding", "PooledEmbedding", "JinaEmbeddingV3"}
            or [row["id"] for row in record["results"]] != [c["id"] for c in cases]):
        raise ValueError("original history/source mismatch")
    if [n["message"] for n in record["notices"]] != [n["message"] for n in definition["advisories"]]:
        raise ValueError("original advisories differ from registered notices")
    import numpy as np
    prior_state = {"model_loaded": False, "device": "unknown", "dim": 384}
    for result, case in zip(record["results"], cases, strict=True):
        count = len(case["input"]["texts"])
        if "error" in result:
            if (not count or not known_original_failure(definition, result["error"], record["platform"])
                    or result["before"] != prior_state or result["state"] != prior_state
                    or prior_state["model_loaded"] or result["batches"]
                    or "shape" in result or "vectors_f32le_hex" in result):
                raise ValueError("unexpected original error or false ready/vector state")
            continue
        expected_shape = [count, definition["dimension"]]
        if result["shape"] != expected_shape:
            raise ValueError("original result dimension mismatch")
        values = np.frombuffer(bytes.fromhex(result["vectors_f32le_hex"]), dtype="<f4")
        if values.size != count * definition["dimension"] or not np.isfinite(values).all():
            raise ValueError("nonfinite/incomplete original vectors")
        dimension_corrections(result["state"]["dim"], result["shape"], definition["dimension"])
        loaded = prior_state["model_loaded"] or count > 0
        expected_state = {"model_loaded": loaded, "device": "cpu" if loaded else "unknown", "dim": 384}
        if result["before"] != prior_state or result["state"] != expected_state:
            raise ValueError("original lazy state history mismatch")
        prior_state = result["state"]
        batch_rows = 0
        for batch in result["batches"]:
            if not batch["outputs"] or batch["outputs"][0]["dtype"] != "float32":
                raise ValueError("actual original graph output is not F32; resolve spec before native code")
            inputs = batch["inputs"]
            if "input_ids" not in inputs:
                raise ValueError("original input tokens missing")
            for tensor in inputs.values():
                if (tensor["dtype"] != "int64" or any(type(n) is not int or n < 0 for n in tensor["shape"])
                        or len(tensor["values"]) != math.prod(tensor["shape"])
                        or any(type(n) is not int or not -(2**63) <= n < 2**63 for n in tensor["values"])):
                    raise ValueError("original input tensor dtype/shape/values mismatch")
            shape = inputs["input_ids"]["shape"]
            if len(shape) != 2 or not 1 <= shape[0] <= 256:
                raise ValueError("original batch token shape mismatch")
            output_shape = batch["outputs"][0]["shape"]
            if len(output_shape) not in {2, 3} or output_shape[0] != shape[0] or output_shape[-1] != definition["dimension"]:
                raise ValueError("original graph batch shape mismatch")
            batch_rows += shape[0]
        if batch_rows != count:
            raise ValueError("original graph rows differ from requested rows")
    failures = [r for r in record["results"] if "error" in r]
    expected_sessions = len(failures) if failures else 1
    if len(record["sessions"]) != expected_sessions:
        raise ValueError("real original session attempts missing")
    for session in record["sessions"]:
        if failures and not known_original_failure(definition, session.get("error", {}), record["platform"]):
            raise ValueError("failed original session attempt evidence missing or mismatched")
        if not failures and "error" in session:
            raise ValueError("unexpected failed original session attempt")
        expected_providers = [] if failures else ["CPUExecutionProvider"]
        if session["configured_providers"] != ["CPUExecutionProvider"] or session["actual_providers"] != expected_providers:
            raise ValueError("original CPU provider mismatch")
        if (session["intra_op_num_threads"], session["inter_op_num_threads"], session["optimization"]) != (0, 0, "GraphOptimizationLevel.ORT_ENABLE_ALL"):
            raise ValueError("original session defaults changed")


def fastembed_cases(names: list[str]) -> list[dict]:
    mixed = ["", " ", "alpha beta", "¿Dónde está el código?", "cafe\u0301",
             "🦀 Rust 🚀", "日本語の検索", "[CLS] [SEP] <s> </s> [PAD]"]
    inputs = [("empty_cold_passages", "passage", []),
              ("mixed_queries", "query", mixed),
              ("mixed_passages", "passage", mixed),
              ("repeat_queries", "query", mixed),
              *[(f"length{n}", "passage", ["alpha " * n]) for n in (511, 512, 513)],
              ("batch256", "passage", ["a"] * 256),
              ("batch257", "passage", ["a"] * 256 + ["alpha " * 513]),
              ("empty_warm_queries", "query", [])]
    return [{"id": f"{name}:{case}", "model": name,
             "input": {"side": side, "texts": list(texts)}}
            for name in names for case, side, texts in inputs]


def native_request(case: dict) -> dict:
    if set(case) != {"id", "model", "input"} or set(case["input"]) != {"side", "texts"}:
        raise ValueError("only independently supplied text requests permitted")
    side, texts = case["input"]["side"], case["input"]["texts"]
    if (side not in {"query", "passage"} or type(texts) is not list
            or any(type(text) is not str for text in texts)):
        raise ValueError("typed text request required")
    return {"id": case["id"], "operation": "embed", "side": side, "texts": texts}


def dimension_corrections(reported: int, shape: list[int], registered: int) -> list[str]:
    if (type(reported) is not int or type(registered) is not int or registered <= 0
            or len(shape) != 2 or any(type(n) is not int or n < 0 for n in shape)
            or shape[1] != registered):
        raise ValueError("actual vector shape must match the registered dimension")
    if reported == registered:
        return []
    if reported == 384:
        return ["reported_dimension"]
    raise ValueError("only the observed original constant384 property is correctable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["capture"])
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--python", type=Path)
    args = parser.parse_args()
    reference = Reference.load(args.reference)
    if args.python:
        reference = Reference(reference.root, reference.manifest_path, reference.fingerprint, args.python.absolute())
    result = capture_fastembed(reference, args.sources, args.registry, args.out)
    print(json.dumps({"captured": len(result["models"]), "cases": result["cases"], "platform": result["platform"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
