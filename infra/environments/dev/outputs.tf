output "media_bucket_name" {
  value = module.media_bucket.bucket_name
}

output "state_machine_arn" {
  value = module.pipeline.state_machine_arn
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
  value       = module.embedding_queue.queue_url
}

output "embedding_queue_arn" {
  description = "Embedding fan-out queue ARN"
  value       = module.embedding_queue.queue_arn
}

output "embedding_dlq_url" {
  description = "Embedding dead-letter queue URL"
  value       = module.embedding_queue.dlq_url
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
  description = "Lambda security group"
  value       = module.networking.lambda_security_group_id
}


output "embedding_function_name" {
  description = "Embedding Lambda function name"
  value       = module.embed_chunk.function_name
}

output "embed_text_endpoint_url" {
  description = "Public URL for generating embeddings"
  value       = aws_lambda_function_url.embed_text.function_url
}

output "embed_text_api_key" {
  description = "API key for the embed-text endpoint"
  value       = random_password.embed_text_api_key.result
  sensitive   = true
}

