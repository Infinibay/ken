"""Resume a frozen development producer with an explicit free-buffer resource cap."""
from __future__ import annotations

import hashlib
import json
import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    import mlx.core as mx
    script, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    budget = 512 * 1024**2
    previous = mx.set_cache_limit(budget)
    if previous < budget:
        mx.set_cache_limit(previous)
    with (output / "resource-events.jsonl").open("a") as stream:
        stream.write(json.dumps({"time_utc": datetime.now(timezone.utc).isoformat(),
            "event": "resume_with_bounded_free_cache", "free_cache_bytes": min(previous, budget),
            "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "producer_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            "note": "same frozen math, model and source; report latency separately by resource episode"}) + "\n")
    sys.argv = [str(script), *sys.argv[3:]]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
