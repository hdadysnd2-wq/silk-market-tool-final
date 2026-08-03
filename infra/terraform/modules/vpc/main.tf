# VPC skeleton: public + private subnets across two AZs, NAT for egress.
# TODO: implement aws_vpc, aws_subnet, aws_nat_gateway, route tables.
variable "environment" { type = string }
variable "cidr_block" { type = string }

output "vpc_id" { value = null }
output "private_subnet_ids" { value = [] }
output "public_subnet_ids" { value = [] }
