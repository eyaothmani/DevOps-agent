resource "aws_db_subnet_group" "db_subnet" {
  name       = "eya-db-subnet-group"
  subnet_ids = [aws_subnet.private_subnet.id, aws_subnet.public_subnet.id]
  tags       = { Name = "eya-db-subnet-group" }
}

resource "aws_security_group" "rds_sg" {
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # Egress restreint au VPC : RDS n'a pas besoin de sortir vers Internet
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["10.0.0.0/16"]
  }

  tags = { Name = "eya-rds-sg" }
}

resource "aws_db_instance" "db" {
  identifier        = "eya-mydb"
  engine            = "mysql"
  engine_version    = "8.0"
  instance_class    = "db.t3.micro"
  allocated_storage = 20
  storage_encrypted = true   # clé KMS gérée par AWS par défaut, gratuit

  db_name  = "appdb"
  username = "eya_dbadmin"   # évite le username générique "admin"
  password = random_password.rds_master.result

  db_subnet_group_name   = aws_db_subnet_group.db_subnet.name
  vpc_security_group_ids = [aws_security_group.rds_sg.id]

  skip_final_snapshot = true
  publicly_accessible = false

  lifecycle {
    ignore_changes = [password]
  }
}