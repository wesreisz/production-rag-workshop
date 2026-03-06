output "media_bucket_name" {
  value = module.media_bucket.bucket_name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

output "start_transcription_function_name" {
  description = "Start transcription Lambda function name"
  value       = module.start_transcription.function_name
}

output "check_transcription_function_name" {
  description = "Check transcription Lambda function name"
  value       = module.check_transcription.function_name
}

output "chunk_transcript_function_name" {
  description = "Chunk transcript Lambda function name"
  value       = module.chunk_transcript.function_name
}

output "embedding_queue_url" {
  description = "Embedding fan-out queue URL"
  value       = aws_sqs_queue.embedding.url
}

output "embedding_queue_arn" {
  description = "Embedding fan-out queue ARN"
  value       = aws_sqs_queue.embedding.arn
}
