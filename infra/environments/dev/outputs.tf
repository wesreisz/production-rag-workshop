output "media_bucket_name" {
  value = module.media_bucket.bucket_name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}
