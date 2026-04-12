output "media_bucket_name" {
  value = module.media_bucket.bucket_name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

output "start_transcription_function_name" {
  value = module.start_transcription.function_name
}

output "check_transcription_function_name" {
  value = module.check_transcription.function_name
}
