# ECS Fargate skeleton: three services (api, worker, beat) behind an ALB.
# TODO: aws_ecs_cluster, task definitions, services, ALB, autoscaling.
variable "environment" { type = string }
variable "subnet_ids" { type = list(string) }

output "api_url" { value = null }
