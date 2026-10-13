#!/bin/bash
# Runs on the VM as root via Compute Engine startup-script metadata.
# Application archive and settings are supplied through instance metadata.
set -euo pipefail
metadata() {
    curl --fail --silent --show-error --retry 5 --retry-delay 2 \
        -H 'Metadata-Flavor: Google' \
        "http://metadata.google.internal/computeMetadata/v1/$1"
}
PROJECT_ID=$(metadata project/project-id)
BUCKET_NAME=$(metadata instance/attributes/hw4-bucket)
SERVICE_ROLE=$(metadata instance/attributes/hw4-role)
case "$SERVICE_ROLE" in
    server) APP_COMMAND='/opt/hw4/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8080 --workers 1 --timeout-graceful-shutdown 90' ;;
    reporter) APP_COMMAND='/opt/hw4/.venv/bin/python /opt/hw4/subscriber.py' ;;
    *) echo "Invalid hw4-role metadata" >&2; exit 1 ;;
esac
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv curl
id hw4 >/dev/null 2>&1 || useradd --system --home /opt/hw4 --shell /usr/sbin/nologin hw4
mkdir -p /opt/hw4 /var/log/hw4
metadata instance/attributes/hw4-source | base64 -d | tar xz -C /opt/hw4
python3 -m venv /opt/hw4/.venv
/opt/hw4/.venv/bin/pip install --disable-pip-version-check -r /opt/hw4/requirements.txt
INSTANCE_ID=$(metadata instance/id)
ZONE=$(metadata instance/zone)
cat > /opt/hw4/service.env <<EOF
GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
BUCKET_NAME=${BUCKET_NAME}
TOPIC_PATH=projects/${PROJECT_ID}/topics/hw4-forbidden
SUBSCRIPTION_PATH=projects/${PROJECT_ID}/subscriptions/hw4-forbidden-reporter
INSTANCE_ID=$INSTANCE_ID
ZONE=${ZONE##*/}
CLOUD_LOGGING=1
PYTHONUNBUFFERED=1
EOF
cat > /etc/systemd/system/hw4.service <<EOF
[Unit]
Description=CS528 HW4 ${SERVICE_ROLE}
Wants=network-online.target
After=network-online.target
[Service]
User=hw4
WorkingDirectory=/opt/hw4
EnvironmentFile=/opt/hw4/service.env
ExecStart=${APP_COMMAND}
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
if [ "${SERVICE_ROLE}" = "server" ]; then
    systemctl enable hw4-metrics
    systemctl restart hw4-metrics
fi
