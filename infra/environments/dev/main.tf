provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

module "media_bucket" {
  source = "../../modules/s3"

  bucket_name        = "production-rag-media-${local.account_id}"
  enable_eventbridge = true
  tags               = local.common_tags
}

module "start_transcription" {
  source = "../../modules/lambda"

  function_name = "${var.project_name}-start-transcription"
  handler       = "src.handlers.start_transcription.handler"
  runtime       = "python3.11"
  timeout       = 60
  memory_size   = 256
  source_dir    = "${path.module}/../../../modules/transcribe-module"
  tags          = local.common_tags

  environment_variables = {
    MEDIA_BUCKET = module.media_bucket.bucket_name
  }

  policy_statements = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject"]
        Resource = "${module.media_bucket.bucket_arn}/*"
      },
      {
        Effect = "Allow"
        Action = ["s3:PutObject"]
        Resource = "${module.media_bucket.bucket_arn}/transcripts/*"
      },
      {
        Effect   = "Allow"
        Action   = ["transcribe:StartTranscriptionJob"]
        Resource = "*"
      }
    ]
  })
}

module "check_transcription" {
  source = "../../modules/lambda"

  function_name = "${var.project_name}-check-transcription"
  handler       = "src.handlers.check_transcription.handler"
  runtime       = "python3.11"
  timeout       = 30
  memory_size   = 256
  source_dir    = "${path.module}/../../../modules/transcribe-module"
  tags          = local.common_tags

  environment_variables = {
    MEDIA_BUCKET = module.media_bucket.bucket_name
  }

  policy_statements = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["transcribe:GetTranscriptionJob"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_sqs_queue" "embedding_dlq" {
  name                      = "${var.project_name}-embedding-dlq"
  message_retention_seconds = 86400
  tags                      = local.common_tags
}

resource "aws_sqs_queue" "embedding" {
  name                       = "${var.project_name}-embedding-queue"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 86400
  tags                       = local.common_tags
}

resource "aws_sqs_queue_redrive_policy" "embedding" {
  queue_url = aws_sqs_queue.embedding.id
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.embedding_dlq.arn
    maxReceiveCount     = 3
  })
}

module "chunk_transcript" {
  source = "../../modules/lambda"

  function_name = "${var.project_name}-chunk-transcript"
  handler       = "src.handlers.chunk_transcript.handler"
  runtime       = "python3.11"
  timeout       = 120
  memory_size   = 256
  source_dir    = "${path.module}/../../../modules/chunking-module"
  tags          = local.common_tags

  environment_variables = {
    MEDIA_BUCKET        = module.media_bucket.bucket_name
    EMBEDDING_QUEUE_URL = aws_sqs_queue.embedding.url
  }

  policy_statements = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${module.media_bucket.bucket_arn}/transcripts/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${module.media_bucket.bucket_arn}/chunks/*"
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.embedding.arn
      }
    ]
  })
}

module "pipeline" {
  source = "../../modules/step-functions"

  project_name       = var.project_name
  source_bucket_name = module.media_bucket.bucket_name
  object_key_prefix  = "uploads/"
  tags               = local.common_tags

  enable_additional_policy = true
  additional_policy_json   = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["lambda:InvokeFunction"]
        Resource = [
          module.start_transcription.function_arn,
          module.check_transcription.function_arn,
          module.chunk_transcript.function_arn
        ]
      }
    ]
  })

  definition = jsonencode({
    StartAt = "ValidateInput"
    States = {
      ValidateInput = {
        Type = "Pass"
        Next = "StartTranscription"
      }
      StartTranscription = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = module.start_transcription.function_arn
          "Payload.$"  = "$"
        }
        ResultPath = "$.transcription"
        ResultSelector = {
          "detail.$"     = "$.Payload.detail"
          "statusCode.$" = "$.Payload.statusCode"
        }
        Next = "WaitForTranscription"
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
            IntervalSeconds = 5
            MaxAttempts     = 2
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "TranscriptionFailed"
            ResultPath  = "$.error"
          }
        ]
      }
      WaitForTranscription = {
        Type    = "Wait"
        Seconds = 30
        Next    = "CheckTranscriptionStatus"
      }
      CheckTranscriptionStatus = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = module.check_transcription.function_arn
          "Payload" = {
            "detail.$" = "$.transcription.detail"
          }
        }
        ResultPath = "$.transcription"
        ResultSelector = {
          "detail.$"     = "$.Payload.detail"
          "statusCode.$" = "$.Payload.statusCode"
        }
        Next = "IsTranscriptionComplete"
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
            IntervalSeconds = 5
            MaxAttempts     = 2
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "TranscriptionFailed"
            ResultPath  = "$.error"
          }
        ]
      }
      IsTranscriptionComplete = {
        Type = "Choice"
        Choices = [
          {
            Variable     = "$.transcription.detail.status"
            StringEquals = "COMPLETED"
            Next         = "TranscriptionSucceeded"
          },
          {
            Variable     = "$.transcription.detail.status"
            StringEquals = "FAILED"
            Next         = "TranscriptionFailed"
          }
        ]
        Default = "WaitForTranscription"
      }
      TranscriptionSucceeded = {
        Type = "Pass"
        Next = "ChunkTranscript"
      }
      ChunkTranscript = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = module.chunk_transcript.function_arn
          "Payload" = {
            "detail" = {
              "bucket_name.$"        = "$.transcription.detail.bucket_name"
              "transcript_s3_key.$"  = "$.transcription.detail.transcript_s3_key"
              "video_id.$"           = "$.transcription.detail.video_id"
              "source_key.$"         = "$.transcription.detail.source_key"
              "speaker.$"            = "$.transcription.detail.speaker"
              "title.$"              = "$.transcription.detail.title"
            }
          }
        }
        ResultPath = "$.chunking"
        ResultSelector = {
          "detail.$"     = "$.Payload.detail"
          "statusCode.$" = "$.Payload.statusCode"
        }
        Next = "ChunkingSucceeded"
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
            IntervalSeconds = 5
            MaxAttempts     = 2
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "ChunkingFailed"
            ResultPath  = "$.error"
          }
        ]
      }
      ChunkingSucceeded = {
        Type = "Pass"
        End  = true
      }
      ChunkingFailed = {
        Type  = "Fail"
        Error = "ChunkingFailed"
        Cause = "Chunking failed or encountered an error"
      }
      TranscriptionFailed = {
        Type  = "Fail"
        Error = "TranscriptionFailed"
        Cause = "Transcription job failed or encountered an error"
      }
    }
  })
}
