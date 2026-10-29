variable "environment" {
  description = "Nom de l'environnement (tag Environment)"
  type        = string
  default     = "stage"
}

variable "owner" {
  description = "Proprietaire du projet (tag Owner)"
  type        = string
  default     = "eya-devops-stage"
}