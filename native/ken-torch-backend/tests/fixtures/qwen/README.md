# Two-layer Qwen3 original fixture

`capture.py` uses the isolated original Torch2.9.0 / Transformers4.57.6 Qwen3Model to create two distinguishable layers and actual CPU/MPS F32/F16/BF16 hidden states. The fixed parameter formula needs no random seed. Both explicitly unprefixed and model.-prefixed safetensors contain the same tensors. These tiny files test the native architecture and corruption boundaries; they do not certify the full registered models or application migration. Product execution uses no Python.
