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
   Watch it under the repo's **Actions** tab.

That's it — pushing a `v*` tag is the only trigger. A version already on PyPI
cannot be re-uploaded, so always bump before tagging.
