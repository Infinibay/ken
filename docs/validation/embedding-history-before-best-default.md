# Historical embedding and accelerator controls

Archived from README at dea7035816c59ba976e5d495542ede63c215a06e.
The text below describes earlier configurations and benchmarks. References to
"default" are historical; see the current README and the complete requested-piece
validation journal for current defaults and observed quality. These datasets do
not establish the quality of the present complete search pipeline.

## Embedding models & GPU

New projects use **`ken/static-qwen3-r512-v2`** (1024-dim), a fitted token table that ships inside the wheel. It is not a neural network. A text is tokenised, one vector per token is looked up and added up, and the sum goes through a single matrix:

```
ids  = tokenize(text)          # Qwen3's own tokenizer, bundled with the table
vec  = normalise( Σ table[ids] · projection )
```

That is ~1000 arithmetic operations per token instead of the 880 million a transformer spends, so it encodes about **10 000 texts a second on one CPU thread** — three orders of magnitude faster than running a model — with no GPU, no ONNX, no torch, and nothing to download on first use. The table is 23 MB and the arithmetic is `numpy`.

For scale: its teacher, `Qwen/Qwen3-Embedding-0.6B`, encoded 856 texts/s on the datacenter GPU it was fitted on. A Linux-kernel-sized index is upwards of 872 000 texts — about seventeen minutes of pure encoding there, on hardware most people do not have.

It is fitted, not designed: a ridge regression against `Qwen/Qwen3-Embedding-0.6B` over 964 475 texts of the exact shapes ken stores, parsed with ken's own parsers from [the-stack-smol](https://huggingface.co/datasets/bigcode/the-stack-smol) and balanced across sixteen languages.

**How good is it?** On 4 351 retrieval queries over code held out of its training — one thousand files per language, split off before a single training text was built — it reaches 97% of its teacher's recall@10:

| | recall@10 |
| --- | --- |
| `Qwen/Qwen3-Embedding-0.6B` (teacher, `[torch]`, ~1.2 GB) | 0.728 |
| **`ken/static-qwen3-r512-v2`** (default, 23 MB) | **0.708** |

Per language, table against teacher: typescript 0.92/0.93 · go 0.85/0.87 · rust 0.82/0.87 · csharp 0.79/0.79 · php 0.78/0.76 · java 0.78/0.82 · powershell 0.84/0.87 · python 0.74/0.80 · ruby 0.72/0.73 · bash 0.70/0.66 · c++ 0.66/0.65 · sql 0.25/0.31 · css 0.22/0.23 · html 0.20/0.14. CSS, HTML and SQL are low **for both** — those files carry few docstrings, so the task itself is hard there, not the table.

And on ranking, which is what ken actually does with it: over 637 real prompts from two projects ranking 2 627 files, asking whether each encoder surfaces the teacher's own top pick in its top ten —

| encoder | English prompts (n=373) | Spanish prompts (n=264) |
| --- | --- | --- |
| **`ken/static-qwen3-r512-v2`** | **0.603** | 0.216 |
| `multilingual-MiniLM` (previous default) | 0.086 | 0.239 |

+0.517 in English (95% CI [+0.461, +0.574]); in Spanish the difference is indistinguishable from zero ([−0.091, +0.046]). The table is fitted on code-shaped text, so that is where it is strongest — but it does not cost you anything on conversational prompts in other languages either.

`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim) remains available and is the automatic fallback if an install has no table.

A project's model is **pinned to its index**. Upgrading ken never re-encodes an existing project behind your back — cosine similarity across two models is meaningless, so switching always requires a deliberate re-encode:

```sh
# Re-encode every stored embedding with a new model (no re-index; uses the
# source text ken already keeps). Records the model so it stays pinned.
ken reembed --model ken/static-qwen3-r512-v2
```

Any [fastembed](https://github.com/qdrant/fastembed) model works out of the box too.

To choose the default for **future** projects (leaving existing ones untouched), set a user-level default:

```sh
ken default-model                     # show the current default for new projects
ken default-model BAAI/bge-m3         # every project installed from now on uses this
ken default-model --clear             # back to ken's built-in default
```

This only affects projects created afterwards; switch an existing one with `ken reembed --model <name>`.

### GPU acceleration

**The default needs none.** A table lookup and a sum have nothing to offload — the static table runs on the CPU at ~10 000 texts a second and there is no GPU path to want. This section is for the model backends.

The embedder auto-detects a GPU and uses it, falling back to CPU when none is usable — no configuration. What counts as a GPU depends on the backend:

| Backend | Accelerators | How to get it |
| --- | --- | --- |
| static table (default) | none — it is a lookup, not a model | built in |
| fastembed / ONNX | CUDA, ROCm — Linux/Windows only | `pip install 'ken-rank[gpu]'` |
| torch / sentence-transformers | CUDA, **Apple Silicon (MPS)** | `pip install 'ken-rank[torch]'` |

Override detection with `KEN_EMBED_DEVICE=auto|cpu|gpu|cuda|mps` (and `KEN_EMBED_DEVICE_ID=0` to pick a CUDA index). `auto` and `gpu` prefer CUDA, then MPS, then CPU; naming one accelerator restricts the choice to that one, so `cuda` on a Mac lands on the CPU rather than quietly substituting the other GPU.

**On Apple Silicon**, only the torch backend reaches the GPU — ONNX Runtime has no MPS provider, and `[gpu]` is not installable on macOS at all (onnxruntime-gpu ships no Mac wheels), so the default models stay on the CPU where they are already fast. `[torch]` alone is enough: the stock PyPI `torch` wheel for macOS arm64 carries MPS.

MPS is used more defensively than CUDA, because it fails in ways CUDA doesn't:

- **It can lie quietly.** A batch can come back as `NaN`, or as rows the GPU never filled in — which survive normalisation as all-zero vectors that are perfectly finite and score 0.0 against every query forever. ken checks that each batch is finite *and* unit-norm; if it isn't, or the GPU raises, it re-encodes on the CPU and stays there for the rest of the process. One reload, versus unusable vectors in `ken.db` that nobody notices until retrieval has quietly degraded.
- **It won't tell you it's out of memory.** torch's MPS allocator ceiling is set from a fraction of RAM and lands *above* the RAM that exists, so instead of an out-of-memory error macOS just swaps. ken caps it (`KEN_MPS_MEMORY_FRACTION`, default `0.7`) so an oversized batch raises and hits the fallback above.
- **torch 2.9+ is required** to use the GPU (macOS 14+). Below that, a PyTorch bug could return embeddings that are finite, unit-norm and *wrong* — the one failure no runtime check can catch — so ken refuses MPS on older torch and says so in the log rather than trusting an index it can't verify. The `[torch]` extra pins this for you on Apple Silicon.

**Is the GPU worth it?** For most people, not much — and that's fine. The device only affects how fast a *query* is embedded; the rest of a rank (the cosine sweep over the mapped vectors, the lexical/import channels) is CPU work either way. With the default table a query embeds in well under a millisecond, and with a fastembed model in ~30–40 ms on CPU, so the GPU barely moves the needle for inline ranking. Even with the heavy `Qwen/Qwen3-Embedding-0.6B` on a large repo, a full rank was ~1.1 s of which the query embed is ~250 ms on CPU vs ~50 ms on GPU (measured on CUDA — Apple Silicon is unmeasured) — the GPU saves ~200 ms of a second-plus that's dominated by device-independent work. So CPU-only is perfectly usable, including with Qwen3.

Where the GPU genuinely pays off: **bulk work** — a full `ken reembed` or the first index of a big repo re-encodes thousands of texts at once, and there the GPU is several times faster. And if you simply want to shave every last millisecond off inline ranking, turn it on. Otherwise, don't sweat it.

### Stronger models (torch backend)

Some of the best open-source embedding models are not shipped by fastembed. The optional `torch` extra adds a [sentence-transformers](https://www.sbert.net/) backend so you can use them — most notably **`Qwen/Qwen3-Embedding-0.6B`**, the top scorer in ken's own retrieval benchmark, and `BAAI/bge-m3`:

```sh
pip install 'ken-rank[torch]'
ken reembed --model Qwen/Qwen3-Embedding-0.6B
```

ken selects the backend automatically from the model name — just point `ken reembed --model` at it.

**How good is Qwen3?** On ken's benchmark (100 labeled prompt→file queries over a real project with Spanish prompts and English code), Qwen3-0.6B was clearly the strongest model tested:

| Model | Recall@5 | MRR | Spanish Recall@5 |
| --- | --- | --- | --- |
| Qwen3-Embedding-0.6B (`[torch]`) | **0.77** | **0.68** | **0.75** |
| multilingual-MiniLM (previous default) | 0.59 | 0.47 | 0.59 |
| all-MiniLM (old English-only default) | 0.54 | 0.36 | 0.33 |

Those numbers come from a different, older benchmark than the ones at the top of this section, so read them against each other and not across — what they establish is the ordering among *model* backends. The default table is distilled from the winner of this table and reaches 97% of it on held-out code, so `[torch]` is worth installing when you want the last few points of recall and can afford 1.2 GB and ~250 ms per query, and is otherwise unnecessary.

That is roughly **+40% Recall@5 and +87% MRR** over the old default, and it more than doubles retrieval quality on non-English prompts.

**The costs.** Qwen3 is not free to run:

- **Heavier install.** The `[torch]` extra pulls PyTorch + sentence-transformers — hundreds of MB, versus the small ONNX-only default. The model itself is ~1.2 GB.
- **Bigger index.** It is 1024-dimensional, so stored vectors are ~2.7× the size of the 384-dim default. Since 0.9.0 that lands in `.ken/vectors/` rather than in `ken.db`.
- **Slower on CPU.** It shines on a GPU — the torch backend picks up CUDA or Apple Silicon's MPS on its own (the `[gpu]` extra is for the fastembed path, not this one). On CPU the per-prompt embedding is noticeably slower than the fastembed default, which matters because the daemon embeds inline on every prompt. On a Mac, `[torch]` alone is enough: the stock PyPI `torch` wheel for macOS arm64 ships MPS support, no extra index or extra to install.

So it is worth it when you have a GPU (or don't mind the CPU latency) and want the best retrieval; otherwise the lightweight multilingual default is the better trade-off. The fastembed default always stays the no-torch path.
