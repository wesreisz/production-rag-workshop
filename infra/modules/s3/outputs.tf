output "bucket_name" {
  description = "The S3 bucket name"
  value       = aws_s3_bucket.this.bucket
}

output "bucket_arn" {
  description = "The S3 bucket ARN"
  value       = aws_s3_bucket.this.arn
}

output "bucket_id" {
  description = "The S3 bucket ID"
  value       = aws_s3_bucket.this.id
}
