# infra/bootstrap/backend_lock_table.tf
resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "agent-devops-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST" # gratuit à cette échelle, dans le free tier permanent
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Project = "agent-devops-autonome"
    Purpose = "terraform-state-lock"
  }
}
