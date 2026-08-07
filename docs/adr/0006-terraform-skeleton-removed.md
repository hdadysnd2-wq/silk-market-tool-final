# ADR 0006 — Remove the Terraform skeleton (Railway is the deploy target)

**Status:** Accepted · **Date:** 2026-08-07 · **Supersedes:** the skeleton described in `infra/terraform/README.md`

## Context

`infra/terraform/` held an intentionally-incomplete AWS (`me-south-1`) skeleton:
VPC / RDS / ElastiCache / S3 / ECS-Fargate module stubs, no state backend, never
applied. The 2026-08-06 and 2026-08-07 audits both flagged it as a hazard: a
skeleton that *looks* like real infrastructure is worse than none, because a
reader can mistake it for the deploy path and because it rots silently against
the code it claims to provision.

Meanwhile the product's real, exercised deploy target is **Railway** — four
services (`api`, `worker`, `beat`, `web`) on one Postgres + one Redis, wired by
`deploy-to-railway.sh` / `.ps1` and `apps/api/railway*.json`, documented in
`docs/DEPLOY_RAILWAY.md`. Object storage is any S3-compatible store (R2 / S3 /
MinIO), now required and fail-closed in the deploy script (audit C2). There is
no AWS account, no ECS, and no Terraform state anywhere in the loop.

## Decision

**Delete the Terraform skeleton.** It is not "trivially finishable" (a real IaC
effort would need a state backend, secrets management, an ALB, ECS task
definitions mirroring the Railway topology, and CI to plan/apply — days of work
for infrastructure we do not currently run), and keeping a non-applied skeleton
misrepresents the deploy story.

If a move off Railway to AWS is ever chosen, the intended topology is preserved
in this ADR and in git history (`infra/terraform/` at this commit's parent) as
the starting point — nothing is lost that a fresh, state-backed effort wouldn't
rewrite anyway.

## Intended AWS topology (recorded for a future effort)

`me-south-1` (AWS Bahrain, closest to KSA data-residency): VPC with public +
private subnets across 2 AZs · RDS PostgreSQL 16 with `pgvector` · ElastiCache
Redis (Celery broker + cache) · private S3 bucket for product images with
presigned uploads · ECS Fargate running `api` / `worker` / `beat` behind an ALB.
The engine's SQLite spend-cap/cache would need an EFS mount or a move to
Postgres/Redis (see audit) before a multi-task Fargate deploy.

## Consequences

- `infra/terraform/` is removed; `infra/docker-compose.dev.yml` remains (it is
  the real local stack and is exercised by `make dev`).
- The deploy story is now singular and honest: Railway, via the scripts and
  `docs/DEPLOY_RAILWAY.md`.
- No behavior change to the application.
