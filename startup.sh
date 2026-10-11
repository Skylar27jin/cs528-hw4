#!/bin/bash
# deploy.py fills the __PLACEHOLDERS__ before attaching this script to the VM.
# Do not run this template directly on your laptop.
set -euo pipefail
case "__ROLE__" in server|reporter) ;; *) echo "Run deploy.py to render this template." >&2; exit 1 ;; esac
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv curl
id hw4 >/dev/null 2>&1 || useradd --system --home /opt/hw4 --shell /usr/sbin/nologin hw4
mkdir -p /opt/hw4 /var/log/hw4
printf '%s' '__PAYLOAD__' | base64 -d | tar xz -C /opt/hw4
python3 -m venv /opt/hw4/.venv
/opt/hw4/.venv/bin/pip install --disable-pip-version-check -r /opt/hw4/requirements.txt
INSTANCE_ID=$(curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/id)
ZONE=$(curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/zone)
cat > /opt/hw4/service.env <<EOF
GOOGLE_CLOUD_PROJECT=__PROJECT__
BUCKET_NAME=__BUCKET__
TOPIC_PATH=projects/__PROJECT__/topics/hw4-forbidden
SUBSCRIPTION_PATH=projects/__PROJECT__/subscriptions/hw4-forbidden-reporter
INSTANCE_ID=$INSTANCE_ID
ZONE=${ZONE##*/}
CLOUD_LOGGING=1
PYTHONUNBUFFERED=1
EOF
cat > /etc/systemd/system/hw4.service <<'EOF'
[Unit]
Description=CS528 HW4 __ROLE__
Wants=network-online.target
After=network-online.target
[Service]
User=hw4
WorkingDirectory=/opt/hw4
EnvironmentFile=/opt/hw4/service.env
ExecStart=__COMMAND__
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
EOF
chown hw4:hw4 /var/log/hw4
cat > /etc/systemd/system/hw4-metrics.service <<'EOF'
[Unit]
Description=HW4 VM resource samples
[Service]
User=hw4
ExecStart=/opt/hw4/.venv/bin/python /opt/hw4/metrics.py
StandardOutput=append:/var/log/hw4/metrics.jsonl
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/logrotate.d/hw4 <<'EOF'
/var/log/hw4/metrics.jsonl {
    daily
    rotate 3
    compress
    missingok
    copytruncate
    su hw4 hw4
}
EOF
systemctl daemon-reload
systemctl enable hw4
systemctl restart hw4
if [ "__ROLE__" = "server" ]; then
    systemctl enable hw4-metrics
    systemctl restart hw4-metrics
fi
