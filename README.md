# CS528 HW4 — VM services

FastAPI file server + Pub/Sub reporter, migrated from HW3. The server reads the HW2 bucket; forbidden-country events go to a separate subscription. The reporter prints each event and acknowledges it. Delivery is at least once, so stdout can contain duplicates. HW4 does not require rewriting a bucket audit file.

## Files

- `server.py`: FastAPI application served by Uvicorn; GET path, POST JSON/form `file`, or plain-text filename.
- `cloud_log.py`: structured Cloud Logging API entries using the attached VM identity.
- `subscriber.py`: reporting service, using the reporter VM identity.
- `deploy.py`: creates accounts, resource permissions, topic/subscription, server static IP, firewall, and selected VMs. Packages local code into startup metadata; no GitHub repository or service account key is needed.
- `metrics.py`: whole-VM CPU, memory, RX/TX sampled every second.
- `stress.py`: runs at most four instructor-client processes, for at most 180 seconds.
- `plot_metrics.py`: plots measured resource peaks for recorded stress windows.

## Prerequisites

Install Python 3 and the Google Cloud CLI on the deployment computer. Run `gcloud auth login`, select an account authorized to provision resources in a billing-enabled project, and use an existing VPC (default: `default`). The deployer needs permission to enable APIs, create VMs/static IPs/firewalls/service accounts, attach service accounts (`iam.serviceAccounts.actAs`), create Pub/Sub resources, and set the listed IAM bindings. Runtime accounts do not receive deployment permissions.

This project uses `bu-cs528-cloud-computing` and bucket `zetian-ps2` from HW2. VM defaults: `us-central1-a`, Debian 12, `f1-micro` (614 MB), 10 GB standard persistent disk. HTTP uses port 8080; the exercise endpoint does not configure HTTPS.

## Deploy in one command

From this directory:

```bash
python3 deploy.py --project=bu-cs528-cloud-computing --bucket=zetian-ps2 --apply
```

This creates **both service VMs**. To create just the server for initial verification:

```bash
python3 deploy.py --project=bu-cs528-cloud-computing --bucket=zetian-ps2 --only=server --apply
```

Omit `--apply` to preview the plan. Override `--zone`, `--network`, or `--machine-type` as needed. Existing named VMs are left unchanged: rerunning this command is NOT an application update. An existing topic/subscription/network must have the intended configuration; do not reuse these HW4 resource names for unrelated work.

### Runtime IAM

| Account | Role | Scope |
|---|---|---|
| `hw4-server` | Storage Object Viewer | HW2 bucket |
| `hw4-server` | Pub/Sub Publisher | `hw4-forbidden` topic |
| `hw4-server` | Logging Log Writer | project |
| `hw4-reporter` | Pub/Sub Subscriber | `hw4-forbidden-reporter` subscription |

Google client libraries obtain credentials from the VM metadata server. There are no downloaded keys and no user ADC login. The `cloud-platform` access scope allows API calls subject to these IAM permissions; it does not grant extra IAM roles. Applications run as the unprivileged Linux user `hw4`.

The startup script installs dependencies and enables `hw4.service`. systemd restarts a crashed service and starts it on reboot. On the server it also enables `hw4-metrics.service`. Source is in `/opt/hw4`; metric samples are in `/var/log/hw4/metrics.jsonl`. Startup installation takes a few minutes. Existing default-VPC SSH rules are not modified by the script.

## Inspect the VM

```bash
gcloud compute ssh hw4-server --project=bu-cs528-cloud-computing --zone=us-central1-a --command='sudo systemctl status hw4 --no-pager'
gcloud compute ssh hw4-server --project=bu-cs528-cloud-computing --zone=us-central1-a --command='sudo journalctl -u google-startup-scripts.service -n 60 --no-pager'
```

For the reporter, use `hw4-reporter` and `sudo journalctl -u hw4 -n 30 --no-pager`.

## HTTP verification

Set `URL` to `http://STATIC_IP:8080` (obtain the IP with `gcloud compute addresses describe hw4-server-ip --region=us-central1 --format='value(address)' --project=bu-cs528-cloud-computing`).

```bash
curl -i "$URL/0.html"
curl -i "$URL/" -H 'Content-Type: application/json' -d '{"file":"0.html"}'
curl -i "$URL/no-such-file.html"
curl -i -X PUT "$URL/0.html"
curl -I "$URL/0.html"
curl -i -X CONNECT "$URL/0.html"
curl -i -X TRACE "$URL/0.html"
curl -i -X OPTIONS "$URL/0.html"
curl -i -X DELETE "$URL/0.html"
curl -i -X PATCH "$URL/0.html"
curl -i -H 'X-country: Iran' "$URL/0.html"
```

Expected: GET/POST 200; missing file 404/WARNING; unsupported methods 501/ERROR; forbidden country 400/CRITICAL. Forbidden attempts are logged even if publication fails; a publication failure produces 503 rather than claiming notification succeeded. Cloud API failures are logged to the systemd journal if Cloud Logging itself is unavailable.

```bash
gcloud logging read 'resource.type="gce_instance" AND logName="projects/bu-cs528-cloud-computing/logs/hw4-errors"' --project=bu-cs528-cloud-computing --freshness=1h --limit=30 --format=json
```

Browser screenshots: navigate directly to a file or missing path with Chrome Network open. On that same origin, send POST/PUT/forbidden requests through DevTools `fetch`; inspect their Headers/Payload/Response. No artificial demo status codes are used.

`X-country` is a client-supplied simulation, not geographic authentication. The HW2 bucket's pre-existing public-read policy is unchanged and allows direct access outside this service.

## Client VM and stress testing (separate step)

Create a separate Linux client VM and obtain the instructor's Linux-compatible client. The HW3 macOS executable is not a Linux client. Run the instructor client there for 100 files and save its output. Do not substitute the local unit tests for this evidence.

Run four **sequential** rounds on the client VM, using `--clients 1`, then 2, 3, 4, and different output directories:

```bash
python3 stress.py --clients 1 --seconds 180 --output results/one -- ./http-client YOUR_CLIENT_ARGUMENTS
```

Replace `YOUR_CLIENT_ARGUMENTS` with arguments verified by that binary's `--help`; include verbose output to preserve statuses. Each worker repeats the client command if it finishes before the window ends. Do not start multiple stress.py runs at once. Client exit codes alone do not establish server overload: count timeouts, connection failures and unexpected server errors from raw logs, exclude country-denial 400s and deliberate shutdowns at the window boundary. If all four clients succeed, report the observed peaks over three minutes instead of claiming a saturation threshold.

Copy `/var/log/hw4/metrics.jsonl` from the server and all four `window.json` files from the client. Both VMs must have synchronized clocks. Then, on the analysis computer:

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python plot_metrics.py metrics.jsonl results/one/window.json results/two/window.json results/three/window.json results/four/window.json --output performance.png
```

Metrics include all VM processes, including logging and the collector. CPU is normalized across visible logical CPUs; memory is total minus available; bandwidth is non-loopback RX + TX in Mbit/s. One-second peaks depend on sample interval. This is not an HTTP-only bandwidth measurement. Check sample coverage and client-VM saturation before drawing conclusions. No performance results or cost figures are fabricated by these tools.

Record start/end times and inspect Cloud Billing for actual charges (VM, disk, external IP, traffic and API usage). Credits/free-tier eligibility may change net cost; if reporting estimates, label them. Stopping a VM does not remove disk or reserved-IP charges. Delete only HW4 resources when the assignment is finished.

## Local tests

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Local tests use fake Storage/Pub/Sub clients. Live evidence and deployment output are saved separately under `evidence/` and are excluded from Git by default. Review before publishing and explicitly include the evidence you cite in the PDF.

## References

- https://docs.cloud.google.com/compute/docs/instances/startup-scripts/linux
- https://docs.cloud.google.com/python/docs/reference/logging/latest/direct-lib-usage
- https://docs.cloud.google.com/compute/docs/general-purpose-machines

## Server framework

FastAPI handles HTTP requests; Uvicorn runs the app on port 8080. One process uses up to eight worker threads for synchronous Google SDK operations, so Storage/Pub/Sub/Logging calls do not block the async event loop. POST supports JSON, URL-encoded forms and plain text (64 KiB body limit). Unsupported methods are intercepted before routing and logged as 501/ERROR. Automatic API documentation routes are disabled to preserve bucket-path semantics.
