provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

module "media_bucket" {
  source = "../../modules/s3"

  bucket_name        = "${var.project_name}-media-${local.account_id}"
  enable_eventbridge = true
}

module "start_transcription" {
  source = "../../modules/lambda"

  function_name = "${var.project_name}-start-transcription"
  handler       = "src.handlers.start_transcription.handler"
  source_dir    = "${path.module}/../../../modules/transcribe-module"
  timeout       = 60
  memory_size   = 256

  environment_variables = {
    MEDIA_BUCKET = module.media_bucket.bucket_name
  }

  policy_statements = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "${module.media_bucket.bucket_arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = "${module.media_bucket.bucket_arn}/transcripts/*"
      },
      {
        Effect   = "Allow"
        Action   = "transcribe:StartTranscriptionJob"
        Resource = "*"
      }
    ]
  })
}

module "check_transcription" {
  source = "../../modules/lambda"

  function_name = "${var.project_name}-check-transcription"
  handler       = "src.handlers.check_transcription.handler"
  source_dir    = "${path.module}/../../../modules/transcribe-module"
  timeout       = 30
  memory_size   = 256

  environment_variables = {
    MEDIA_BUCKET = module.media_bucket.bucket_name
  }

  policy_statements = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "transcribe:GetTranscriptionJob"
        Resource = "*"
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/aws/stepfunctions/${var.project_name}-pipeline"
  retention_in_days = 14
}

resource "aws_iam_role" "step_functions" {
  name = "${var.project_name}-step-functions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "step_functions_logging" {
  name = "${var.project_name}-step-functions-logging"
  role = aws_iam_role.step_functions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.project_name}-pipeline"
  role_arn = aws_iam_role.step_functions.arn

  definition = jsonencode({
    StartAt        = "ValidateInput"
    TimeoutSeconds = 1800
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
        End  = true
      }
      TranscriptionFailed = {
        Type  = "Fail"
        Error = "TranscriptionFailed"
        Cause = "Transcription job failed or encountered an error"
      }
    }
  })

  logging_configuration {
    level                  = "ALL"
    include_execution_data = true
    log_destination        = "${aws_cloudwatch_log_group.pipeline.arn}:*"
  }
}

resource "aws_iam_role_policy" "step_functions_lambda" {
  name = "${var.project_name}-step-functions-lambda"
  role = aws_iam_role.step_functions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource = [
          module.start_transcription.function_arn,
          module.check_transcription.function_arn
        ]
      }
    ]
  })
}

resource "aws_iam_role" "eventbridge" {
  name = "${var.project_name}-eventbridge-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "eventbridge_sfn" {
  name = "${var.project_name}-eventbridge-sfn"
  role = aws_iam_role.eventbridge.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "states:StartExecution"
        Resource = aws_sfn_state_machine.pipeline.arn
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "s3_upload" {
  name = "${var.project_name}-s3-upload-trigger"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = {
        name = [module.media_bucket.bucket_name]
      }
      object = {
        key = [{
          prefix = "uploads/"
        }]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "start_pipeline" {
  rule      = aws_cloudwatch_event_rule.s3_upload.name
  target_id = "start-pipeline"
  arn       = aws_sfn_state_machine.pipeline.arn
  role_arn  = aws_iam_role.eventbridge.arn
}
