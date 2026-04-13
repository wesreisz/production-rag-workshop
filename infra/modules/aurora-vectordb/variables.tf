variable "project_name" {
  type        = string
  description = "Prefix for resource names"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for Aurora subnet group"
}

variable "security_group_id" {
  type        = string
  description = "Security group ID for Aurora cluster"
}

variable "db_name" {
  type        = string
  default     = "ragdb"
  description = "Database name"
}

variable "master_username" {
  type        = string
  default     = "ragadmin"
  description = "Master username"
}

variable "master_password" {
  type        = string
  sensitive   = true
  description = "Master password"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Resource tags"
}
