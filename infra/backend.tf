# Remote state S3 + verrouillage DynamoDB.
# Le bucket et la table sont créés une seule fois par infra/bootstrap/.

terraform {
  backend "s3" {
    bucket         = "agent-devops-autonome-eya"
    key            = "poc/terraform.tfstate"
    region         = "eu-north-1"
    dynamodb_table = "agent-devops-tfstate-lock"
    encrypt        = true
  }
}
