# Releasing ken-rank

ken is published to PyPI as [`ken-rank`](https://pypi.org/project/ken-rank/) via
GitHub Actions using **Trusted Publishing** (OIDC). No API token or secret is
stored in the repo — PyPI verifies the release came from this repository's
workflow.

## One-time PyPI setup (do this once)

1. Sign in to PyPI and open the project:
   https://pypi.org/manage/project/ken-rank/settings/publishing/
2. Under **Add a new trusted publisher → GitHub**, enter:
   - **Owner:** `Infinibay`
   - **Repository name:** `ken`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`
3. Save. From now on the workflow can publish without a token.

Optionally, in the GitHub repo settings, create an **Environment** named `pypi`
(Settings → Environments) and add required reviewers if you want a manual
approval gate before each publish.

Once Trusted Publishing works, delete any remaining API tokens on PyPI —
they are no longer needed.

## Validate a release candidate

From a clean checkout, sync the locked development environment and run the same
checks as the standalone `CI` workflow:

```sh
uv sync --locked --dev
uv run pytest
uv run mypy
```

The mypy check uses the incremental baseline declared in `pyproject.toml`:
modules with existing annotation debt have explicit temporary overrides, while
the rest of `src/ken` must remain clean. Do not describe this as complete strict
typing until those overrides have been removed.

Also keep the required runtime dependency `mcp>=2.0,<3` in
`[project].dependencies`, not in an optional extra. The MCP startup regression
tests protect that packaging contract and the MCP 2.x API requirement.

## Dependency age policy

`[tool.uv].exclude-newer = "14 days"` applies a rolling minimum age to registry
distributions, including transitive dependencies and the development group.
Run `uv lock --check` and `uv sync --locked --dev` before validation. Do not
work around an ineligible pin by disabling the cutoff: select a compatible
eligible version and repeat the relevant checks.

uv records the resolved cutoff in the lockfile, so it does not become stale
merely as time passes. A fresh resolution refreshes the cutoff. This policy is
uv-specific; pip does not read it, and Git/local source dependencies are outside
its registry-upload-time rule. See the
[uv documentation](https://docs.astral.sh/uv/concepts/resolution/#dependency-cooldowns).

The development group obtains Torch from the explicit official CPU index. This
keeps tensor regression tests runnable without installing CUDA dependencies.
The published package's normal runtime dependencies do not include Torch.

## Cutting a release

1. Bump the version in **`src/ken/__init__.py`** (`__version__ = "X.Y.Z"`) — the
   only place it lives. `pyproject.toml` declares `dynamic = ["version"]` and
   hatchling reads it from there, so the published metadata and what
   `ken --version` prints are the same string by construction. (They were not
   always: 0.5.0 and 0.7.0 both shipped reporting the previous release, because
   the version used to be written in two files.)
2. Commit and push to `main`.
3. Tag and push the tag:

   ```sh
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

4. The `Publish to PyPI` workflow builds the sdist + wheel and publishes them.
   Watch it under the repo's **Actions** tab. Publication is intentionally
   separate from the `CI` workflow, so confirm the candidate passed the checks
   above before tagging.

That's it — pushing a `v*` tag is the only trigger. A version already on PyPI
cannot be re-uploaded, so always bump before tagging.
