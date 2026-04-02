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

module "pipeline" {
  source = "../../modules/step-functions"

  project_name       = var.project_name
  source_bucket_name = module.media_bucket.bucket_name
  object_key_prefix  = "uploads/"
  tags               = local.common_tags

  definition = jsonencode({
    StartAt = "ValidateInput"
    States = {
      ValidateInput = {
        Type = "Pass"
        End  = true
      }
    }
  })
}
