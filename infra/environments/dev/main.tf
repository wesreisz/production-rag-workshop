provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

module "media_bucket" {
  source = "../../modules/s3"

  bucket_name      = "${var.project_name}-media-${local.account_id}"
  enable_eventbridge = true
  tags             = local.common_tags
}

module "start_transcription" {
  source = "../../modules/lambda"

  function_name = "${var.project_name}-start-transcription"
  handler       = "src.handlers.start_transcription.handler"
  timeout       = 60
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
        Action   = ["s3:GetObject"]
        Resource = "${module.media_bucket.bucket_arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
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
  timeout       = 30
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

module "chunk_transcript" {
  source = "../../modules/lambda"

  function_name = "${var.project_name}-chunk-transcript"
  handler       = "src.handlers.chunk_transcript.handler"
  timeout       = 120
  source_dir    = "${path.module}/../../../modules/chunking-module"
  tags          = local.common_tags

  environment_variables = {
    MEDIA_BUCKET        = module.media_bucket.bucket_name
    EMBEDDING_QUEUE_URL = module.embedding_queue.queue_url
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
        Resource = module.embedding_queue.queue_arn
      }
    ]
  })
}

module "networking" {
  source       = "../../modules/networking"
  project_name = var.project_name
  aws_region   = var.aws_region
  tags         = local.common_tags
}

module "aurora_vectordb" {
  source            = "../../modules/aurora-vectordb"
  project_name      = var.project_name
  subnet_ids        = module.networking.subnet_ids
  security_group_id = module.networking.aurora_security_group_id
  master_password   = var.aurora_master_password
  tags              = local.common_tags
}

resource "aws_lambda_layer_version" "psycopg2" {
  layer_name          = "${var.project_name}-psycopg2"
  filename            = "${path.module}/../../../layers/psycopg2/psycopg2-layer.zip"
  compatible_runtimes = ["python3.11"]
  source_code_hash    = filebase64sha256("${path.module}/../../../layers/psycopg2/psycopg2-layer.zip")
}

module "embedding_queue" {
  source     = "../../modules/sqs"
  queue_name = "${var.project_name}-embedding-queue"
  tags       = local.common_tags
}

module "embed_chunk" {
  source = "../../modules/lambda-vpc"

  function_name = "${var.project_name}-embed-chunk"
  handler       = "src.handlers.process_embedding.handler"
  timeout       = 120
  source_dir    = "${path.module}/../../../modules/embedding-module"
  tags          = local.common_tags

  subnet_ids         = module.networking.subnet_ids
  security_group_ids = [module.networking.lambda_security_group_id]
  layers             = [aws_lambda_layer_version.psycopg2.arn]

  environment_variables = {
    SECRET_ARN           = module.aurora_vectordb.secret_arn
    DB_NAME              = module.aurora_vectordb.db_name
    EMBEDDING_DIMENSIONS = "256"
  }

  policy_statements = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${module.media_bucket.bucket_arn}/chunks/*"
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = module.aurora_vectordb.secret_arn
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = module.embedding_queue.queue_arn
      }
    ]
  })
}

resource "aws_lambda_event_source_mapping" "embedding" {
  event_source_arn = module.embedding_queue.queue_arn
  function_name    = module.embed_chunk.function_arn
  batch_size       = 1
  enabled          = true
}

resource "null_resource" "build_migration_deps" {
  triggers = {
    handler_hash  = filesha256("${path.module}/../../../modules/migration-module/src/handlers/run_migrations.py")
    versions_hash = sha256(join("", [for f in sort(fileset("${path.module}/../../../modules/migration-module/migrations/versions", "*.py")) : filesha256("${path.module}/../../../modules/migration-module/migrations/versions/${f}")]))
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/../../../scripts/build-migration-module.sh"
  }
}

module "run_migrations" {
  source = "../../modules/lambda-vpc"

  function_name = "${var.project_name}-run-migrations"
  handler       = "src.handlers.run_migrations.handler"
  timeout       = 30
  source_dir    = "${path.module}/../../../modules/migration-module"
  tags          = local.common_tags

  subnet_ids         = module.networking.subnet_ids
  security_group_ids = [module.networking.lambda_security_group_id]
  layers             = [aws_lambda_layer_version.psycopg2.arn]

  environment_variables = {
    SECRET_ARN = module.aurora_vectordb.secret_arn
    DB_NAME    = module.aurora_vectordb.db_name
  }

  policy_statements = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = module.aurora_vectordb.secret_arn
      }
    ]
  })

  depends_on = [null_resource.build_migration_deps]
}

resource "null_resource" "run_migrations" {
  depends_on = [module.run_migrations, module.aurora_vectordb]

  triggers = {
    handler_hash  = filesha256("${path.module}/../../../modules/migration-module/src/handlers/run_migrations.py")
    versions_hash = sha256(join("", [for f in sort(fileset("${path.module}/../../../modules/migration-module/migrations/versions", "*.py")) : filesha256("${path.module}/../../../modules/migration-module/migrations/versions/${f}")]))
  }

  provisioner "local-exec" {
    command = <<-EOT
      aws lambda invoke \
        --function-name ${module.run_migrations.function_name} \
        --payload '{}' \
        --region ${var.aws_region} \
        /tmp/migration-result.json && \
      cat /tmp/migration-result.json && \
      python3 -c "import json,sys; r=json.load(open('/tmp/migration-result.json')); sys.exit(1) if r.get('errorMessage') else sys.exit(0)"
    EOT
  }
}

module "pipeline" {
  source       = "../../modules/step-functions"
  project_name = var.project_name
  tags         = local.common_tags

  s3_bucket_name = module.media_bucket.bucket_name

  lambda_arns = [
    module.start_transcription.function_arn,
    module.check_transcription.function_arn,
    module.chunk_transcript.function_arn,
  ]

  state_machine_definition = jsonencode({
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
          Payload = {
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
          Payload = {
            "detail" = {
              "bucket_name.$"       = "$.transcription.detail.bucket_name"
              "transcript_s3_key.$" = "$.transcription.detail.transcript_s3_key"
              "video_id.$"          = "$.transcription.detail.video_id"
              "source_key.$"        = "$.transcription.detail.source_key"
              "speaker.$"           = "$.transcription.detail.speaker"
              "title.$"             = "$.transcription.detail.title"
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

resource "random_password" "embed_text_api_key" {
  length  = 32
  special = false
}

module "embed_text_endpoint" {
  source = "../../modules/lambda"

  function_name = "${var.project_name}-embed-text"
  handler       = "src.handlers.embed_text.handler"
  timeout       = 30
  source_dir    = "${path.module}/../../../modules/embedding-endpoint"
  tags          = local.common_tags

  environment_variables = {
    EMBEDDING_DIMENSIONS = "256"
    API_KEY              = random_password.embed_text_api_key.result
  }

  policy_statements = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
      }
    ]
  })
}

resource "aws_lambda_function_url" "embed_text" {
  function_name      = module.embed_text_endpoint.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "embed_text_public_url" {
  statement_id           = "FunctionURLAllowPublicAccess"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = module.embed_text_endpoint.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "embed_text_public_invoke" {
  statement_id  = "FunctionURLInvokeAllowPublicAccess"
  action        = "lambda:InvokeFunction"
  function_name = module.embed_text_endpoint.function_name
  principal     = "*"
}
