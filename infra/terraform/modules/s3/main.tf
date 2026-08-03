# S3 skeleton for product images (private, SSE, lifecycle rules).
# TODO: aws_s3_bucket, public-access block, encryption, CORS for presigned uploads.
variable "environment" { type = string }
variable "bucket_name" { type = string }

output "bucket_name" { value = var.bucket_name }
