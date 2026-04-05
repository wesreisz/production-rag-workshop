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

output "chunk_transcript_function_name" {
  description = "Chunk transcript Lambda"
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

output "aurora_cluster_endpoint" {
  description = "Aurora writer endpoint"
  value       = module.aurora_vectordb.cluster_endpoint
}

output "aurora_secret_arn" {
  description = "Secrets Manager secret ARN"
  value       = module.aurora_vectordb.secret_arn
}

output "aurora_db_name" {
  description = "Database name"
  value       = module.aurora_vectordb.db_name
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.networking.vpc_id
}

output "lambda_security_group_id" {
  description = "Lambda security group ID"
  value       = module.networking.lambda_security_group_id
}

output "embedding_function_name" {
  description = "Embedding Lambda function name"
  value       = module.embed_chunk.function_name
}

output "embedding_dlq_url" {
  description = "Embedding dead-letter queue URL"
  value       = aws_sqs_queue.embedding_dlq.url
}

output "embed_text_endpoint_url" {
  description = "Public URL for generating embeddings"
  value       = aws_lambda_function_url.embed_text.function_url
}

output "embed_text_api_key" {
  description = "API key for the embedding endpoint"
  value       = random_password.embed_text_api_key.result
  sensitive   = true
}
