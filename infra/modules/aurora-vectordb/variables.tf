variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for DB subnet group"
  type        = list(string)
}

variable "security_group_id" {
  description = "Aurora security group ID"
  type        = string
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "ragdb"
}

variable "master_username" {
  description = "Master username"
  type        = string
  default     = "ragadmin"
}

variable "master_password" {
  description = "Master password"
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}

variable "enable_deletion_protection" {
  description = "Set to true for production. Enables final snapshot on destroy and 30-day secret recovery window."
  type        = bool
  default     = false
}
