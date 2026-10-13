#!/bin/bash
# Create both HW4 service VMs; run from a computer with authenticated gcloud.
set -euo pipefail
PROJECT_ID=''
BUCKET_NAME=''
ZONE='us-central1-a'
while [ "$#" -gt 0 ]; do
    case "$1" in
        --project) PROJECT_ID="${2:?Missing project}"; shift 2 ;;
        --bucket) BUCKET_NAME="${2:?Missing bucket}"; shift 2 ;;
        --zone) ZONE="${2:?Missing zone}"; shift 2 ;;
        *) echo "Usage: $0 --project PROJECT --bucket BUCKET [--zone ZONE]" >&2; exit 2 ;;
    esac
done
[ -n "$PROJECT_ID" ] && [ -n "$BUCKET_NAME" ] || { echo 'Provide --project and --bucket.' >&2; exit 2; }
cd "$(dirname "$0")"
REGION="${ZONE%-*}"
mkdir -p evidence/script-deployment
exec > >(tee "evidence/script-deployment/deploy-$(date -u +%Y%m%dT%H%M%SZ).log") 2>&1
# Prints actual commands and their output; no credential tokens are printed.
set -x
GCLOUD=(gcloud --project="$PROJECT_ID" --quiet)
"${GCLOUD[@]}" services enable compute.googleapis.com iam.googleapis.com pubsub.googleapis.com logging.googleapis.com storage.googleapis.com
ACCOUNTS=$("${GCLOUD[@]}" iam service-accounts list --format='value(email)')
for role in server reporter; do
    EMAIL="hw4-${role}@${PROJECT_ID}.iam.gserviceaccount.com"
    if ! printf '%s\n' "$ACCOUNTS" | grep -Fxq "$EMAIL"; then
        "${GCLOUD[@]}" iam service-accounts create "hw4-${role}" --display-name="HW4 ${role}"
    fi
done
TOPICS=$("${GCLOUD[@]}" pubsub topics list --format='value(name)')
if ! printf '%s\n' "$TOPICS" | grep -Fxq "projects/$PROJECT_ID/topics/hw4-forbidden"; then
    "${GCLOUD[@]}" pubsub topics create hw4-forbidden
fi
SUBSCRIPTIONS=$("${GCLOUD[@]}" pubsub subscriptions list --format='value(name)')
if ! printf '%s\n' "$SUBSCRIPTIONS" | grep -Fxq "projects/$PROJECT_ID/subscriptions/hw4-forbidden-reporter"; then
    "${GCLOUD[@]}" pubsub subscriptions create hw4-forbidden-reporter --topic=hw4-forbidden
fi
SERVER_MEMBER="serviceAccount:hw4-server@${PROJECT_ID}.iam.gserviceaccount.com"
"${GCLOUD[@]}" storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" --member="$SERVER_MEMBER" --role=roles/storage.objectViewer --condition=None --format='value(etag)'
"${GCLOUD[@]}" pubsub topics add-iam-policy-binding hw4-forbidden --member="$SERVER_MEMBER" --role=roles/pubsub.publisher
"${GCLOUD[@]}" projects add-iam-policy-binding "$PROJECT_ID" --member="$SERVER_MEMBER" --role=roles/logging.logWriter --condition=None --format='value(etag)'
"${GCLOUD[@]}" pubsub subscriptions add-iam-policy-binding hw4-forbidden-reporter --member="serviceAccount:hw4-reporter@${PROJECT_ID}.iam.gserviceaccount.com" --role=roles/pubsub.subscriber
ADDRESSES=$("${GCLOUD[@]}" compute addresses list --regions="$REGION" --format='value(name)')
if ! printf '%s\n' "$ADDRESSES" | grep -Fxq hw4-server-ip; then
    "${GCLOUD[@]}" compute addresses create hw4-server-ip --region="$REGION"
fi
STATIC_IP=$("${GCLOUD[@]}" compute addresses describe hw4-server-ip --region="$REGION" --format='value(address)')
FIREWALLS=$("${GCLOUD[@]}" compute firewall-rules list --format='value(name)')
if ! printf '%s\n' "$FIREWALLS" | grep -Fxq hw4-http; then
    "${GCLOUD[@]}" compute firewall-rules create hw4-http --network=default --allow=tcp:8080 --source-ranges=0.0.0.0/0 --target-tags=hw4-server
fi
COPYFILE_DISABLE=1 tar -czf evidence/script-deployment/source.tar.gz server.py subscriber.py cloud_log.py metrics.py requirements.txt
base64 < evidence/script-deployment/source.tar.gz > evidence/script-deployment/source.b64
bash -n startup.sh
INSTANCES=$("${GCLOUD[@]}" compute instances list --format='value(name)')
for role in server reporter; do
    if printf '%s\n' "$INSTANCES" | grep -Fxq "hw4-$role"; then
        printf 'VM hw4-%s already exists; no recreation or code update.\n' "$role"
        continue
    fi
    EXTRA=(--tags=hw4-reporter)
    if [ "$role" = server ]; then EXTRA=(--address="$STATIC_IP" --tags=hw4-server); fi
    "${GCLOUD[@]}" compute instances create "hw4-$role" \
        --zone="$ZONE" --machine-type=f1-micro --network=default \
        --image-family=debian-12 --image-project=debian-cloud \
        --boot-disk-size=10GB --boot-disk-type=pd-standard \
        --service-account="hw4-${role}@${PROJECT_ID}.iam.gserviceaccount.com" \
        --scopes=cloud-platform --labels=course=cs528,homework=hw4 \
        --metadata="hw4-role=$role,hw4-bucket=$BUCKET_NAME" \
        --metadata-from-file=startup-script=startup.sh,hw4-source=evidence/script-deployment/source.b64 \
        "${EXTRA[@]}"
done
set +x
printf 'Web endpoint: http://%s:8080/0.html\nStartup installation may take several minutes.\n' "$STATIC_IP"
