#!/bin/bash
exec > /var/log/user-data.log 2>&1
set -e

# ── Attendre que dpkg/apt soit libre (cloud-init / unattended-upgrades) ──
wait_for_apt_lock() {
  local max_wait=180
  local waited=0
  while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || \
        sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || \
        sudo fuser /var/cache/apt/archives/lock >/dev/null 2>&1; do
    if [ $waited -ge $max_wait ]; then
      echo "TIMEOUT: dpkg/apt lock still held after ${max_wait}s"
      break
    fi
    echo "dpkg/apt lock busy, waiting... (${waited}s)"
    sleep 5
    waited=$((waited + 5))
  done
}

wait_for_apt_lock
apt update -y
apt install -y apache2
systemctl start apache2
systemctl enable apache2
echo "Hello from Eya Auto Scaling EC2" > /var/www/html/index.html

# ── Installation du CloudWatch Agent ──────────────────────────────
wait_for_apt_lock
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
apt install -y ./amazon-cloudwatch-agent.deb

# ── Configuration du CloudWatch Agent ─────────────────────────────
# NB : /var/log/syslog est la cible des lignes "logger -t myapp ..."
# émises par les scripts de simulation de panne (stress-ng, arrêt
# service) — voir note en bas de fichier. Sans ces lignes, les logs
# Apache seuls (error/access) n'expliquent pas la cause racine des
# incidents CPUHigh / ServiceDown.
mkdir -p /opt/aws/amazon-cloudwatch-agent/etc
cat <<'CONFIG' > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/apache2/error.log",
            "log_group_name": "/aws/ec2/agent-devops/app",
            "log_stream_name": "{instance_id}/apache-error"
          },
          {
            "file_path": "/var/log/apache2/access.log",
            "log_group_name": "/aws/ec2/agent-devops/app",
            "log_stream_name": "{instance_id}/apache-access"
          },
          {
            "file_path": "/var/log/syslog",
            "log_group_name": "/aws/ec2/agent-devops/app",
            "log_stream_name": "{instance_id}/syslog"
          }
        ]
      }
    }
  }
}
CONFIG

# ── Démarrage du CloudWatch Agent ─────────────────────────────────
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json