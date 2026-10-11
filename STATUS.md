# Verification — 2026-10-11

## Running resource

- Project: `bu-cs528-cloud-computing`
- VM: `hw4-server`, zone `us-central1-a`
- Type: `f1-micro`, 614 MB configured memory, 10 GB standard disk
- Static IP: `136.119.167.105`
- URL: http://136.119.167.105:8080/0.html
- Runtime identity: `hw4-server@bu-cs528-cloud-computing.iam.gserviceaccount.com`
- `hw4.service` and `hw4-metrics.service`: active and enabled
- Initial creation startup completed successfully. Subsequently migrated to FastAPI + Uvicorn; persisted startup metadata and systemd ExecStart both use `uvicorn server:app`.

## Verified

- 27 local tests pass with mocked cloud clients (FastAPI version).
- 19 live HTTP checks pass on FastAPI + Uvicorn: GET/POST 200, missing 404, seven unsupported methods 501, nine forbidden countries 400.
- GET and POST return the same 97,586 bytes; SHA-256 matches `gs://zetian-ps2/0.html`.
- Cloud Logging contains matching request IDs for all 17 error responses: one WARNING, seven ERROR, nine CRITICAL.
- Live Pub/Sub pull returns forbidden-country messages. Diagnostic pull did not acknowledge them, so the future reporter can still receive them after the acknowledgement deadline.
- Whole-VM metric sampler produces CPU/memory/RX/TX JSONL every second.

Evidence is under `evidence/`: `deploy.txt`, `fastapi-update.txt`, `fastapi-http-check.json`, `fastapi-cloud-logs.json`, `fastapi-pubsub-pull.json`, and `bucket-0.html`. These local files are ignored by Git; deliberately attach reviewed evidence when preparing the report.

## Not yet performed

- Reporter deployment on its own VM; code and startup script are provided, callback tested locally.
- Client VM creation, instructor-client 100 requests, and 1..4-client stress runs.
- Final performance graph, billing review, browser screenshots, PDF, GitHub publication.

Only the server VM was created for this step. It remains running for browser testing. VM, disk, and external-IP resources may incur charges; no final cost figure has been calculated.

To stop compute while retaining the VM for later:

```bash
gcloud compute instances stop hw4-server --zone=us-central1-a --project=bu-cs528-cloud-computing
```

The disk and reserved external IP remain allocated when the VM is stopped. Restart with `gcloud compute instances start` using the same name/zone/project. Startup metadata reruns on boot.
