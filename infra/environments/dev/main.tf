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
    StartAt = "ValidateInput"
    States = {
      ValidateInput = {
        Type = "Pass"
        End  = true
      }
    }
  })

  logging_configuration {
    level                  = "ALL"
    include_execution_data = true
    log_destination        = "${aws_cloudwatch_log_group.pipeline.arn}:*"
  }
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
