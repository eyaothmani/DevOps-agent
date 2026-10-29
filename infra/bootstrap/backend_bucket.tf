# infra/bootstrap/backend_bucket.tf
# Bucket S3 qui stockera le state de infra/ (l'app détruite chaque nuit).
# Ce bucket, lui, N'EST JAMAIS DÉTRUIT.

resource "aws_s3_bucket" "tfstate" {
  bucket = "agent-devops-autonome-eya" # doit être globalement unique — adapte si déjà pris

  tags = {
    Project = "agent-devops-autonome"
    Purpose = "terraform-state"
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
