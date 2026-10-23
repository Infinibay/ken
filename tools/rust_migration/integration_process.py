"""Actual factory process, reusing the bounded native process owner."""
from pathlib import Path
from .transformer_process import run_transformer


def run_factory(probe: Path, request: dict, out: Path, *, deadline_s: float) -> dict:
    return run_transformer(probe,request,out,deadline_s=deadline_s,audit=True,
        argument_prefix=('--factory',),trace_network=True,prepared_model_cache=True)
