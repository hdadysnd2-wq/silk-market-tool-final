# Provenance — how this monorepo was assembled (Phase 0)

Both source repositories were **snapshot-vendored** rather than history-merged.
The source clones were shallow (`--depth 1`), which makes `git subtree`/`git
filter-repo` history import impractical; the master prompt explicitly permits a
snapshot copy with the originals archived. The exact source commits are recorded
below so any file can be traced back.

## Source commits

| Repo | Role | Branch | Commit (HEAD at vendor time) |
|------|------|--------|------------------------------|
| `hdadysnd2-wq/Silk-market-intelligence` | brain (engine) | `main` | `e63293bf59b6ef6d31aeb36bf22aa3b15375b30f` |
| `hdadysnd2-wq/silk-market-tool-` | body (shell + UI) | `claude/saudi-export-intelligence-mvp-9bpu73` | `3bd73a00b4793a3c7cca4b39afca1e59fb7ace46` |

## What landed where

- Repo A repo-root (all `silk_*.py`, `api.py`, `correlation.py`, `fix_agent.py`,
  `silk_platform/`, `data/`, `config/`, `tools/`, `migrations/`, `samples/`,
  `evals/`, `web/`, engine `docs/`, `requirements*.txt`) →
  `packages/silk_intel/silk_intel/`. Its `tests/` →
  `packages/silk_intel/silk_intel/tests/` (byte-identical; see the deviation note
  in `architecture.md`). Excluded: `.git/`, `.github/` (Repo A's CI is superseded
  by the unified one), `.claude/`.
- Repo B `backend/` → `apps/api/`; `frontend/` → `apps/web/`; `infra/terraform/`
  → `infra/terraform/`; `docker-compose.yml` → adapted into
  `infra/docker-compose.dev.yml`; `.env.example` → root `.env.example`.

## Added at merge time (net-new)

- `packages/silk_intel/{pyproject.toml,conftest.py,README.md}` — package wrapper.
- `packages/contracts/` — unified data contract (decision #4).
- `etl/` — offline bulk-job skeletons (world_trade / hs_reference sync).
- `infra/docker-compose.dev.yml`, root `Makefile`, `.github/workflows/ci.yml`,
  `tools/check_no_pandas.py`, `.gitignore`, `README.md`, `docs/*`.

## Freeze & archive

Per Phase 0 step 4, both source repos are feature-frozen; archive them after the
monorepo's first green CI. Nothing further should be committed to the originals —
all work continues here.
