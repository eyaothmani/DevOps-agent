# ─────────────────────────────────────────────────────────────────
# Security Group — instances EC2
# ─────────────────────────────────────────────────────────────────
resource "aws_security_group" "ec2_sg" {
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "eya-ec2-sg" }
}


# ─────────────────────────────────────────────────────────────────
# Launch Template
# ─────────────────────────────────────────────────────────────────
resource "aws_launch_template" "lt" {
  name_prefix            = "eya-lt"
  image_id                = "ami-0c1ac8a41498c1a9c"
  instance_type           = "t3.micro"
  vpc_security_group_ids  = [aws_security_group.ec2_sg.id]
  user_data               = base64encode(file("${path.module}/user_data.sh"))

  iam_instance_profile {
    name = aws_iam_instance_profile.ec2_profile.name
  }

  # Force IMDSv2 : bloque le vol de credentials via SSRF (ex. CVE Capital One 2019)
  metadata_options {
    http_tokens                 = "required"
    http_endpoint                = "enabled"
    http_put_response_hop_limit  = 1
  }

  # Chiffrement du volume root
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      encrypted   = true
      volume_size = 8
      volume_type = "gp3"
    }
  }

  depends_on = [aws_cloudwatch_log_group.ec2_app_logs]

  lifecycle {
    create_before_destroy = true
  }
}
# ─────────────────────────────────────────────────────────────────
# Auto Scaling Group
# ─────────────────────────────────────────────────────────────────
resource "aws_autoscaling_group" "asg" {
  name             = "eya-asg"
  desired_capacity = 2
  max_size         = 3
  min_size         = 2

  vpc_zone_identifier = [
    aws_subnet.public_subnet.id,
    aws_subnet.public_subnet_b.id
  ]

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 120
    }

  }

  target_group_arns = [aws_lb_target_group.ec2_tg.arn]

  launch_template {
    id      = aws_launch_template.lt.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "eya-asg-instance"
    propagate_at_launch = true
  }

  tag {
    key                 = "Project"
    value               = "agent-devops-autonome"
    propagate_at_launch = true
  }
}

resource "aws_iam_role" "ec2_role" {
  name = "ec2-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ec2_ssm_core" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ec2_cw_agent" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "eya-ec2-instance-profile"
  role = aws_iam_role.ec2_role.name
}