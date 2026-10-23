"""Fresh-process observation of the frozen original; no native expectations."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import sys
import time
import traceback
import warnings

import numpy as np

request = json.load(sys.stdin)
root = Path(request["reference"])
definition = request["definition"]
from ken.embedder.onnx_fastembed import OnnxEmbedder
import ken.embedder.onnx_fastembed as implementation

if not Path(implementation.__file__).resolve().is_relative_to(root / "src"):
    raise ValueError("original import escaped frozen tree")

encoder = OnnxEmbedder(definition["name"], device="cpu")
results, sessions, active_batches, notices = [], [], [], []


def state() -> dict:
    return {"model_loaded": encoder._model is not None, "device": encoder.device, "dim": encoder.dim}


def peak() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value * 1024 if platform.system() == "Linux" else value


def run_case(case: dict) -> None:
    active_batches.clear()
    before = state()
    started = time.monotonic_ns()
    call = encoder.embed_queries if case["input"]["side"] == "query" else encoder.embed_passages
    try:
        rows = call(case["input"]["texts"])
    except Exception as error:
        results.append({"id": case["id"], "before": before, "state": state(),
                        "error": {"exception": type(error).__module__ + "." + type(error).__name__,
                                  "message": str(error), "traceback": traceback.format_exc()},
                        "batches": list(active_batches), "elapsed_ns": time.monotonic_ns() - started,
                        "peak_rss_bytes": peak()})
        return
    elapsed = time.monotonic_ns() - started
    vectors = np.asarray(rows, dtype="<f4").reshape((len(rows), definition["dimension"]))
    results.append({"id": case["id"], "before": before, "state": state(),
                    "shape": list(vectors.shape), "vectors_f32le_hex": vectors.tobytes().hex(),
                    "batches": list(active_batches), "elapsed_ns": elapsed, "peak_rss_bytes": peak()})


# Observe cold empty use before importing either heavyweight package for hooks.
run_case(request["cases"][0])
cold_modules = {name: name in sys.modules for name in ("fastembed", "onnxruntime")}
if any(cold_modules.values()):
    raise ValueError("cold empty original unexpectedly imported inference packages")

import fastembed
import onnxruntime as ort

original_constructor = fastembed.TextEmbedding
original_init = ort.InferenceSession.__init__
original_run = ort.InferenceSession.run


def local_constructor(*args, **kwargs):
    if "specific_model_path" in kwargs or "local_files_only" in kwargs:
        raise ValueError("original unexpectedly supplied path adapter options")
    # These two options change only asset location/network access. Inference,
    # batching, threads and math remain the real unmodified implementation.
    return original_constructor(*args, **kwargs, specific_model_path=request["source"]["snapshot"],
                                local_files_only=True)


def observe_init(self, path_or_bytes, *args, **kwargs):
    options = kwargs["sess_options"]
    observation = {"graph": str(path_or_bytes), "configured_providers": kwargs.get("providers"),
                   "actual_providers": [], "intra_op_num_threads": options.intra_op_num_threads,
                   "inter_op_num_threads": options.inter_op_num_threads,
                   "optimization": str(options.graph_optimization_level)}
    sessions.append(observation)
    try:
        original_init(self, path_or_bytes, *args, **kwargs)
    except Exception as error:
        observation["error"] = {"exception": type(error).__module__ + "." + type(error).__name__, "message": str(error)}
        raise
    observation["actual_providers"] = self.get_providers()


def observe_run(self, output_names, input_feed, *args, **kwargs):
    inputs = {name: {"shape": list(value.shape), "dtype": str(value.dtype),
                     "values": value.reshape(-1).tolist()} for name, value in input_feed.items()}
    started = time.monotonic_ns()
    outputs = original_run(self, output_names, input_feed, *args, **kwargs)
    active_batches.append({"inputs": inputs,
                           "outputs": [{"shape": list(value.shape), "dtype": str(value.dtype)}
                                       for value in outputs],
                           "elapsed_ns": time.monotonic_ns() - started})
    return outputs


fastembed.TextEmbedding = local_constructor
ort.InferenceSession.__init__ = observe_init
ort.InferenceSession.run = observe_run
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    for case in request["cases"][1:]:
        run_case(case)
    notices = [{"category": warning.category.__name__, "message": str(warning.message),
                "filename": warning.filename, "lineno": warning.lineno} for warning in caught]
for notice in notices:
    # Preserve diagnostics in raw stderr as well as structured notices.
    sys.stderr.write(f"{notice['filename']}:{notice['lineno']}: {notice['category']}: {notice['message']}\n")
distribution = importlib.metadata.distribution("fastembed")
source_hashes = {str(entry): hashlib.sha256(Path(distribution.locate_file(entry)).read_bytes()).hexdigest()
                 for entry in distribution.files or []
                 if str(entry).startswith("fastembed/") and str(entry).endswith(".py")}
provenance = {"python": platform.python_version(),
              "versions": {p: importlib.metadata.version(p) for p in ("fastembed", "numpy", "onnxruntime", "tokenizers")},
              "fastembed_sources": source_hashes}
print(json.dumps({"model": definition["name"], "frozen_import": True,
                  "import_relative": str(Path(implementation.__file__).relative_to(root)),
                  "implementation_sha256": hashlib.sha256(Path(implementation.__file__).read_bytes()).hexdigest(),
                  "implementation": (type(encoder._model.model).__name__ if encoder._model is not None else
                                     next(c.__name__ for c in original_constructor.EMBEDDINGS_REGISTRY
                                          if any(m.model.lower() == definition["name"].lower() for m in c._list_supported_models()))),
                  "cold_modules": cold_modules, "sessions": sessions, "notices": notices,
                  "provenance": provenance,
                  "platform": platform.system(), "architecture": platform.machine(), "results": results},
                 allow_nan=False, separators=(",", ":")))
