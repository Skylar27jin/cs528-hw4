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
    template = (ROOT / 'startup.sh').read_text()
    replacements = {'__PROJECT__': project, '__BUCKET__': bucket,
                    '__ROLE__': role, '__COMMAND__': command}
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template.replace('__PAYLOAD__', payload)


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
