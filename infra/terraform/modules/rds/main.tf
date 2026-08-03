# RDS PostgreSQL 16 skeleton (pgvector via CREATE EXTENSION vector).
# TODO: aws_db_subnet_group, aws_db_instance, security group, secrets.
variable "environment" { type = string }
variable "subnet_ids" { type = list(string) }
variable "instance_class" { type = string }
variable "engine_version" { type = string }

output "endpoint" { value = null }
