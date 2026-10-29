# --- Security Group pour l'ALB ---
resource "aws_security_group" "alb_sg" {
  name        = "eya-alb-sg"
  description = "Security group for the Application Load Balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "eya-alb-sg" }
}

# --- Application Load Balancer ---
# NOTE SÉCURITÉ (US 4.6 — STRIDE) : écoute HTTP simple assumée pour le PoC.
# Pas de domaine/certificat ACM dans le périmètre budgétaire (contrainte
# "zéro coût AWS additionnel"). En production, ajout d'un listener HTTPS
# (443) avec redirection 80→443 et certificat ACM serait requis.
resource "aws_lb" "main" {
  name               = "eya-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]

  subnets = [
    aws_subnet.public_subnet.id,
    aws_subnet.public_subnet_b.id
  ]

  tags = { Name = "eya-alb" }
}

# --- Target Group (où l'ALB envoie le trafic) ---
resource "aws_lb_target_group" "ec2_tg" {
  name     = "eya-ec2-tg"
  port     = 80
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    path                = "/"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = { Name = "eya-ec2-tg" }
}

# --- Listener : écoute le port 80 et redirige vers le target group ---
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port               = 80
  protocol           = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ec2_tg.arn
  }
}