# ElastiCache (Redis) skeleton for Celery broker + cache.
# TODO: aws_elasticache_subnet_group, aws_elasticache_replication_group.
variable "environment" { type = string }
variable "subnet_ids" { type = list(string) }

output "endpoint" { value = null }
