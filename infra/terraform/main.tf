# Infrastructure skeleton for the Silk Export Intelligence Platform.
#
# This is a SKELETON only — it is never applied in this repository and has no
# state backend configured. It documents the intended AWS Bahrain (me-south-1)
# topology so a KSA-data-residency deployment can be filled in later. Fill in
# module inputs and add a remote backend before any real `terraform apply`.

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # backend "s3" { ... }  # configure remote state before applying
}

provider "aws" {
  # AWS Bahrain — closest region honoring Saudi data-residency preferences.
  region = var.region
  default_tags {
    tags = {
      Project     = "silk-export-intelligence"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

module "network" {
  source      = "./modules/vpc"
  environment = var.environment
  cidr_block  = var.vpc_cidr
}

module "database" {
  source            = "./modules/rds"
  environment       = var.environment
  subnet_ids        = module.network.private_subnet_ids
  instance_class    = var.db_instance_class
  engine_version    = "16"
  # pgvector is available on RDS PostgreSQL 16 via CREATE EXTENSION vector.
}

module "cache" {
  source      = "./modules/elasticache"
  environment = var.environment
  subnet_ids  = module.network.private_subnet_ids
}

module "storage" {
  source      = "./modules/s3"
  environment = var.environment
  bucket_name = "silk-products-${var.environment}"
}

module "app" {
  source          = "./modules/ecs"
  environment     = var.environment
  subnet_ids      = module.network.private_subnet_ids
  # API, Celery worker, and Celery beat run as separate ECS services.
}
