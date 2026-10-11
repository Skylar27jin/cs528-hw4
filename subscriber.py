"""Pub/Sub reporting service using the VM's attached service account."""
import json
import os
from concurrent.futures import CancelledError
from google.cloud import pubsub_v1

def handle_message(message):
    try:
        event = json.loads(message.data)
        if event.get("event") != "forbidden_country" or not event.get("event_id"):
            raise ValueError("Invalid forbidden-country event")
        print(json.dumps({**event, "message": f"Permission denied: {event['country']} requesting {event.get('file') or event['path']}",
                          "pubsub_message_id": message.message_id}), flush=True)
        message.ack()
    except Exception as error:
        print(json.dumps({"severity": "ERROR", "error_type": type(error).__name__}), flush=True)
        message.nack()

def main():
    with pubsub_v1.SubscriberClient() as client:
        future = client.subscribe(os.environ["SUBSCRIPTION_PATH"], callback=handle_message,
                                  flow_control=pubsub_v1.types.FlowControl(max_messages=10))
        print("Listening on " + os.environ["SUBSCRIPTION_PATH"], flush=True)
        try:
            future.result()
        except KeyboardInterrupt:
            future.cancel()
            try:
                future.result(timeout=30)
            except CancelledError:
                pass

if __name__ == "__main__":
    main()
