# Infrastructure (skeleton)

This directory is an **intentionally incomplete** Terraform skeleton. It is
never applied from this repository and has no configured state backend — it
exists to document the intended production topology and give a later
infrastructure effort a starting shape.

## Intended topology (AWS Bahrain, `me-south-1`)

`me-south-1` is the closest AWS region honoring Saudi data-residency
preferences; a KSA local zone can replace it when required.

- **VPC** (`modules/vpc`) — public + private subnets across two AZs.
- **RDS PostgreSQL 16** (`modules/rds`) — with `pgvector` enabled via
  `CREATE EXTENSION vector`.
- **ElastiCache Redis** (`modules/elasticache`) — Celery broker and cache.
- **S3** (`modules/s3`) — private bucket for product images, presigned uploads.
- **ECS Fargate** (`modules/ecs`) — three services: `api`, `worker`, `beat`,
  behind an ALB.

## Before applying

1. Implement the `TODO`s in each module.
2. Configure a remote state backend (`backend "s3"` block in `main.tf`).
3. Supply real values for the variables in `variables.tf`.
4. Store all secrets (DB password, vendor API keys) in AWS Secrets Manager,
   never in `.tf` files or state.
