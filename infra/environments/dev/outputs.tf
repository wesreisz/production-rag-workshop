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

output "chunk_transcript_function_name" {
  value = module.chunk_transcript.function_name
}

output "embedding_queue_url" {
  value = aws_sqs_queue.embedding.url
}

output "embedding_queue_arn" {
  value = aws_sqs_queue.embedding.arn
}

output "aurora_cluster_endpoint" {
  value = module.aurora_vectordb.cluster_endpoint
}

output "aurora_secret_arn" {
  value = module.aurora_vectordb.secret_arn
}

output "aurora_db_name" {
  value = module.aurora_vectordb.db_name
}

output "vpc_id" {
  value = module.networking.vpc_id
}

output "lambda_security_group_id" {
  value = module.networking.lambda_security_group_id
}

output "embedding_function_name" {
  value = module.embed_chunk.function_name
}
