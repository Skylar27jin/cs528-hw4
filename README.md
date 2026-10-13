# CS528 HW4

FastAPI file server, Pub/Sub reporter, VM startup scripts, and instructor-client tests.

## Deploy

Authenticate with `gcloud auth login`. The deployment user needs permission to enable APIs, create VMs/service accounts/IPs/firewalls/PubSub resources, attach service accounts, and set IAM bindings. Use a billing-enabled project, its default VPC, and the existing HW2 bucket.

```bash
./deploy.sh --project bu-cs528-cloud-computing --bucket zetian-ps2
./deploy-client-vm.sh --project bu-cs528-cloud-computing
```

`deploy.sh` creates both service VMs with `startup.sh`; the startup script installs code and dependencies and enables the corresponding systemd service. Existing named VMs are reused without updating their code. Optional `--zone` defaults to `us-central1-a`.

| Runtime account | Permissions |
|---|---|
| `hw4-server` | Bucket Object Viewer, topic Pub/Sub Publisher, project Logging Log Writer |
| `hw4-reporter` | Pub/Sub Subscriber on the reporter subscription |

Clients use VM metadata credentials without service account keys. The client VM has no attached service account. The Linux applications run as user `hw4`. Service VMs use Debian 12/f1-micro; the client uses Ubuntu 24.04/e2-micro for compatibility with the supplied executable.

## HTTP client

```bash
gcloud compute ssh hw4-client --zone=us-central1-a --project=bu-cs528-cloud-computing
cd ~/hw4-client
./http-client-linux --domain 136.80.209.59 --port 8080 --bucket none --webdir none --num_requests 100 --index 12000 --random 42 --timeout 30 --verbose > client-100.txt 2>&1
```

GET and POST examples:

```bash
curl -i http://136.80.209.59:8080/0.html
curl -i http://136.80.209.59:8080/ -H 'Content-Type: application/json' -d '{"file":"0.html"}'
```

Missing files produce 404/WARNING, unsupported methods 501/ERROR, and banned-country requests 400/CRITICAL plus a Pub/Sub event. `X-country` is the homework simulation; the HW2 bucket's pre-existing public-read policy is unchanged.

## Raw output

- `output/client-100.txt`: instructor-client output from the separate VM.
- `output/deploy.txt`: successful service deployment command/output transcript.
- `output/curl-404.txt` and `output/curl-501.txt`: actual curl responses.
- `output/deployment/`: manual creation history, client deployment, HTTP headers, Cloud Logging, and subscriber stdout. Files preserve their original timestamps; the 404/501 Cloud Logging capture was refreshed during the final repository check.
- `output/stress/round-1/` through `round-4/`: raw response records, client metrics, commands and run metadata.
- `output/stress/server-metrics.jsonl`: raw whole-server CPU, memory and RX/TX observations.
- `output/stress/console.txt`: stress-run console output.

Reports, charts, calculated summaries and cost estimates are not included.

## Reproduce stress runs

Upload `tools/run_stress_rounds.py` to `~/hw4-client` on the client VM, then:

```bash
cd ~/hw4-client
python3 run_stress_rounds.py --binary ./http-client-linux --server 136.80.209.59 --output NEW_OUTPUT_FOLDER
```

The runner executes sequential 180-second rounds with 1–4 clients, records raw output, and prevents overlapping runs. The server's `hw4-metrics.service` records samples at `/var/log/hw4/metrics.jsonl`. Keep concurrency at four or fewer. VMs, disks and external IPs can incur charges until stopped or removed as applicable.

## Local tests

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
