"""Create HW4 VMs and install the services through instance startup metadata."""
import argparse
import base64
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent

def startup(role, project, bucket):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        for name in ['server.py', 'subscriber.py', 'cloud_log.py', 'metrics.py', 'requirements.txt']:
            tar.add(ROOT / name, arcname=name)
    payload = base64.b64encode(archive.getvalue()).decode()
    command = ('/opt/hw4/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8080 '
               '--workers 1 --timeout-graceful-shutdown 90' if role == 'server'
               else '/opt/hw4/.venv/bin/python /opt/hw4/subscriber.py')
    return f'''#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv curl
id hw4 >/dev/null 2>&1 || useradd --system --home /opt/hw4 --shell /usr/sbin/nologin hw4
mkdir -p /opt/hw4 /var/log/hw4
printf '%s' '{payload}' | base64 -d | tar xz -C /opt/hw4
python3 -m venv /opt/hw4/.venv
/opt/hw4/.venv/bin/pip install --disable-pip-version-check -r /opt/hw4/requirements.txt
INSTANCE_ID=$(curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/id)
ZONE=$(curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/zone)
cat > /opt/hw4/service.env <<EOF
GOOGLE_CLOUD_PROJECT={project}
BUCKET_NAME={bucket}
TOPIC_PATH=projects/{project}/topics/hw4-forbidden
SUBSCRIPTION_PATH=projects/{project}/subscriptions/hw4-forbidden-reporter
INSTANCE_ID=$INSTANCE_ID
ZONE=${{ZONE##*/}}
CLOUD_LOGGING=1
PYTHONUNBUFFERED=1
EOF
cat > /etc/systemd/system/hw4.service <<'EOF'
[Unit]
Description=CS528 HW4 {role}
Wants=network-online.target
After=network-online.target
[Service]
User=hw4
WorkingDirectory=/opt/hw4
EnvironmentFile=/opt/hw4/service.env
ExecStart={command}
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
/var/log/hw4/metrics.jsonl {{
    daily
    rotate 3
    compress
    missingok
    copytruncate
    su hw4 hw4
}}
EOF
systemctl daemon-reload
systemctl enable hw4
systemctl restart hw4
''' + ("systemctl enable hw4-metrics\nsystemctl restart hw4-metrics\n" if role == 'server' else '')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--zone', default='us-central1-a')
    parser.add_argument('--network', default='default')
    parser.add_argument('--machine-type', default='f1-micro')
    parser.add_argument('--only', choices=['server', 'reporter', 'both'], default='both')
    parser.add_argument('--apply', action='store_true', help='Execute; otherwise show the plan only')
    args = parser.parse_args()
    for value in (args.project, args.bucket, args.zone, args.network, args.machine_type):
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', value):
            parser.error('Invalid resource name: ' + value)
    region = args.zone.rsplit('-', 1)[0]
    roles = ['server', 'reporter'] if args.only == 'both' else [args.only]
    if not args.apply:
        print(json.dumps({'project': args.project, 'zone': args.zone, 'roles': roles,
                          'machine_type': args.machine_type, 'bucket': args.bucket,
                          'static_ip': 'hw4-server-ip', 'port': 8080}, indent=2))
        print('Add --apply to provision resources. Existing HW4 VMs are not overwritten.')
        return
    def run(*parts):
        command = ['gcloud', *parts, '--project=' + args.project, '--quiet']
        print('+ ' + ' '.join(command), flush=True)
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise SystemExit(result.stderr or result.stdout or 'gcloud failed')
        return result.stdout
    def ensure(group, name, flags=(), create_flags=()):
        # List failure is fatal; permission errors must not be mistaken for absence.
        records = json.loads(run(*group, 'list', '--format=json', *flags))
        if not any(r.get('name', '').split('/')[-1] == name or r.get('email') == name for r in records):
            run(*group, 'create', name, *create_flags)
    run('services', 'enable', 'compute.googleapis.com', 'iam.googleapis.com',
        'pubsub.googleapis.com', 'logging.googleapis.com', 'storage.googleapis.com')
    accounts = {}
    for role in roles:
        account_id = 'hw4-' + role
        email = account_id + '@' + args.project + '.iam.gserviceaccount.com'
        existing = json.loads(run('iam', 'service-accounts', 'list', '--format=json'))
        if not any(a['email'] == email for a in existing):
            run('iam', 'service-accounts', 'create', account_id)
        accounts[role] = email
    ensure(['pubsub', 'topics'], 'hw4-forbidden')
    ensure(['pubsub', 'subscriptions'], 'hw4-forbidden-reporter',
           create_flags=('--topic=hw4-forbidden',))
    if 'server' in roles:
        member = 'serviceAccount:' + accounts['server']
        run('storage', 'buckets', 'add-iam-policy-binding', 'gs://' + args.bucket,
            '--member=' + member, '--role=roles/storage.objectViewer', '--condition=None')
        run('pubsub', 'topics', 'add-iam-policy-binding', 'hw4-forbidden',
            '--member=' + member, '--role=roles/pubsub.publisher')
        run('projects', 'add-iam-policy-binding', args.project,
            '--member=' + member, '--role=roles/logging.logWriter', '--condition=None')
        ensure(['compute', 'addresses'], 'hw4-server-ip', flags=('--regions=' + region,),
               create_flags=('--region=' + region,))
        ensure(['compute', 'firewall-rules'], 'hw4-http', create_flags=(
            '--network=' + args.network, '--allow=tcp:8080', '--source-ranges=0.0.0.0/0',
            '--target-tags=hw4-server'))
    if 'reporter' in roles:
        run('pubsub', 'subscriptions', 'add-iam-policy-binding', 'hw4-forbidden-reporter',
            '--member=serviceAccount:' + accounts['reporter'], '--role=roles/pubsub.subscriber')
    existing_vms = json.loads(run('compute', 'instances', 'list', '--format=json'))
    for role in roles:
        name = 'hw4-' + role
        if any(v['name'] == name for v in existing_vms):
            print('Exists; leaving VM unchanged: ' + name)
            continue
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'startup.sh'
            script.write_text(startup(role, args.project, args.bucket))
            extra = []
            if role == 'server':
                ip = run('compute', 'addresses', 'describe', 'hw4-server-ip',
                         '--region=' + region, '--format=value(address)').strip()
                extra = ['--address=' + ip, '--tags=hw4-server']
            result = run('compute', 'instances', 'create', name, '--zone=' + args.zone,
                '--machine-type=' + args.machine_type, '--network=' + args.network,
                '--image-family=debian-12', '--image-project=debian-cloud',
                '--boot-disk-size=10GB', '--boot-disk-type=pd-standard',
                '--service-account=' + accounts[role], '--scopes=cloud-platform',
                '--labels=course=cs528,homework=hw4',
                '--metadata-from-file=startup-script=' + str(script), '--format=json', *extra)
            print(result)
    print('Provisioned. Startup package installation may take several minutes.')

if __name__ == '__main__':
    main()
