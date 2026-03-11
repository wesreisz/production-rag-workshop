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

output "cloudshell_subnet_id" {
  description = "Private subnet for CloudShell VPC environments"
  value       = module.networking.cloudshell_subnet_id
}

output "cloudshell_security_group_id" {
  description = "Security group for CloudShell VPC environments"
  value       = module.networking.cloudshell_security_group_id
}

output "embedding_function_name" {
  description = "Embedding Lambda function name"
  value       = module.embed_chunk.function_name
}

