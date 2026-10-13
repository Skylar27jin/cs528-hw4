#!/bin/bash
# Create a separate HTTP client VM, upload the instructor binary, check --help.
set -euo pipefail
PROJECT_ID=''
ZONE='us-central1-a'
CLIENT_VM='hw4-client'
cd "$(dirname "$0")"
CLIENT_FILE="$PWD/http-client-linux"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --project) PROJECT_ID="${2:?Missing project}"; shift 2 ;;
        --zone) ZONE="${2:?Missing zone}"; shift 2 ;;
        --client) CLIENT_FILE="${2:?Missing executable path}"; shift 2 ;;
        *) echo "Usage: $0 --project PROJECT [--zone ZONE] [--client FILE]" >&2; exit 2 ;;
    esac
done
[ -n "$PROJECT_ID" ] || { echo 'Provide --project.' >&2; exit 2; }
[ -f "$CLIENT_FILE" ] || { echo "Client not found: $CLIENT_FILE" >&2; exit 2; }
mkdir -p evidence/client-vm
exec > >(tee "evidence/client-vm/deploy-$(date -u +%Y%m%dT%H%M%SZ).log") 2>&1
set -x
GCLOUD=(gcloud --project="$PROJECT_ID" --quiet)
"${GCLOUD[@]}" services enable compute.googleapis.com
INSTANCES=$("${GCLOUD[@]}" compute instances list --format='value(name)')
if ! printf '%s\n' "$INSTANCES" | grep -Fxq "$CLIENT_VM"; then
    "${GCLOUD[@]}" compute instances create "$CLIENT_VM" \
        --zone="$ZONE" --machine-type=e2-micro --network=default \
        --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
        --boot-disk-size=10GB --boot-disk-type=pd-standard \
        --no-service-account --no-scopes --labels=course=cs528,homework=hw4
fi
# Retry initial SSH connection while the guest agent provisions the login user.
READY=0
for attempt in 1 2 3 4 5 6; do
    if "${GCLOUD[@]}" compute ssh "$CLIENT_VM" --zone="$ZONE" \
        --command='mkdir -p ~/hw4-client; uname -m'; then READY=1; break; fi
    sleep 5
done
[ "$READY" = 1 ] || { echo 'SSH is not ready; rerun this script.' >&2; exit 1; }
"${GCLOUD[@]}" compute scp "$CLIENT_FILE" "$CLIENT_VM:~/hw4-client/http-client-linux" --zone="$ZONE"
"${GCLOUD[@]}" compute ssh "$CLIENT_VM" --zone="$ZONE" \
    --command='cd ~/hw4-client && chmod u+x http-client-linux && ./http-client-linux --help'
set +x
printf '\nConnect with:\ngcloud compute ssh %s --zone=%s --project=%s\n' "$CLIENT_VM" "$ZONE" "$PROJECT_ID"
