output "region" {
  description = "The region the platform is deployed in."
  value       = var.region
}

output "database_endpoint" {
  description = "RDS PostgreSQL connection endpoint."
  value       = module.database.endpoint
}

output "cache_endpoint" {
  description = "ElastiCache (Redis) primary endpoint."
  value       = module.cache.endpoint
}

output "product_bucket" {
  description = "S3 bucket for product images."
  value       = module.storage.bucket_name
}
