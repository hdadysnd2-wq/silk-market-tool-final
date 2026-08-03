variable "region" {
  description = "AWS region. me-south-1 (Bahrain) is the closest region honoring Saudi data-residency preferences."
  type        = string
  default     = "me-south-1"
}

variable "environment" {
  description = "Deployment environment name (e.g. staging, production)."
  type        = string
  default     = "staging"
}

variable "vpc_cidr" {
  description = "CIDR block for the platform VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "db_instance_class" {
  description = "RDS PostgreSQL instance class."
  type        = string
  default     = "db.t4g.medium"
}
