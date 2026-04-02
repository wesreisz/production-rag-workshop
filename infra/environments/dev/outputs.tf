output "media_bucket_name" {
  description = "S3 media bucket name"
  value       = module.media_bucket.bucket_name
}

output "state_machine_arn" {
  description = "Step Functions state machine ARN"
  value       = module.pipeline.state_machine_arn
}
