# CV-CUE MCP — working notes for Claude

MCP server for Arista CV-CUE. It runs in two places from this one codebase:

- **Local**: Claude Desktop on this Mac runs `.venv312/bin/cv-cue-mcp` (stdio), using the key in `.env`.
- **Fly.io**: `https://cv-cue-mcp.fly.dev` (hosted sign-in app + `/mcp`). claude.ai's custom connector
  and the Claude Code `arista-cv-cue` entry use it.

## How changes ship (automatic once committed)

1. Make the change, then check it: `.venv312/bin/ruff check src tests scripts` and
   `.venv312/bin/python -m pytest -q`. Both must pass before committing.
2. If tools changed, regenerate the reference: `.venv312/bin/python scripts/gen_tool_docs.py`,
   and update the docs in `docs/src/content/docs/` (and the changelog) to match.
3. Commit on `main`. The `post-commit` hook (`.githooks/`, enabled with
   `git config core.hooksPath .githooks`) then:
   - pushes to GitHub, and
   - reinstalls the local copy into `.venv312` in the background (log: `.git/post-commit-install.log`).
4. GitHub Actions (`.github/workflows/ci.yml`) runs the tests on 3.10–3.12, then deploys to Fly
   **only if Fly is online** (at least one machine) and server files changed (`src/`, `Dockerfile`,
   `fly.toml`, `pyproject.toml`). Docs deploy to GitHub Pages via `docs.yml`.
5. Tell the user to quit and reopen Claude Desktop to load the new local version.

Commit when a change is complete and tested, not mid-way: every commit on `main` goes live.
Never commit `.env`, `*.db`, or anything from `../cv-cue-mcp-secrets/`.

## Fly on/off

- Off (saves cost): `fly scale count 0 --app cv-cue-mcp`. The volume `cvcue_data` keeps the data.
- On with the latest code: GitHub → Actions → CI → **Run workflow**, or `fly deploy` from this folder.
  (`fly scale count 1` also works but starts the previously deployed version.)

## Gotchas

- Editable installs don't work in this folder (macOS marks `.pth` files hidden under Desktop);
  use a regular `pip install ".[http,dev]"`.
- Writes are off server-wide on Fly (`CVCUE_ENABLE_WRITES="false"` in `fly.toml`).
- `CVCUE_MASTER_KEY` encrypts stored keys; Fly can't show it again. Don't rotate it casually.
- The GitHub secret `FLY_API_TOKEN` is an app-scoped deploy token (`fly tokens list --app cv-cue-mcp`),
  expiring 2027-11-05.
