output "media_bucket_name" {
  description = "S3 media bucket name"
  value       = module.media_bucket.bucket_name
}

output "state_machine_arn" {
  description = "Step Functions state machine ARN"
  value       = module.pipeline.state_machine_arn
}

output "start_transcription_function_name" {
  description = "Start transcription Lambda"
  value       = module.start_transcription.function_name
}

output "check_transcription_function_name" {
  description = "Check transcription Lambda"
  value       = module.check_transcription.function_name
}
